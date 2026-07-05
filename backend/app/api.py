"""CovenantOps Agent API — CovenantOps web layer.

Endpoints:
  POST /api/covenant/run              run the agent (query: learning, attack, fail_after)
  POST /api/covenant/resume/{task}    resume an interrupted run from checkpoint
  GET  /api/traces/{trace_id}/receipt signed execution receipt
  GET  /api/receipts/public-key       Ed25519 public key (offline verification)
  GET  /api/health                    liveness + AIRG reachability + guard path
"""
from __future__ import annotations

from typing import Dict, Optional, Any

from fastapi import APIRouter, HTTPException, Query, UploadFile, File

from app.agent.runner import CovenantAgent
from app.agent.learning import SelfImprovement, LessonStore
from app.trust.governance import Governance
from app.trust.receipt import ReceiptService
from app.trust.recovery import CheckpointStore, RecoveryContext, RunInterrupted
from app.trust.vultr_inference import VultrInference
from app.trust.trace_memory import TraceMemory

router = APIRouter()

# Process-lifetime singletons (persisted via Postgres in production).
_governance = Governance()
_receipts = ReceiptService()
_improver = SelfImprovement(LessonStore())
_checkpoints = CheckpointStore()
_inference = VultrInference()
_memory = TraceMemory()
_traces: Dict[str, object] = {}


def _trace_summary(trace) -> dict:
    return {
        "trace_id": trace.id,
        "task_id": trace.task_id,
        "borrower": trace.metadata.get("borrower"),
        "facility": trace.metadata.get("facility"),
        "severity": trace.metadata.get("severity"),
        "confidence": trace.metadata.get("confidence"),
        "guard_path": trace.guard_path.value,
        "lessons_promoted": trace.metadata.get("lessons_promoted", 0),
        "memo": trace.final_output,
        "citations": trace.metadata.get("citations", []),
        "findings": trace.metadata.get("findings", []),
        "tool_calls": [
            {"tool": tc.tool, "args": tc.args, "guard": tc.guard.decision.value,
             "guard_findings": tc.guard.findings}
            for tc in trace.tool_calls
        ],
    }


@router.post("/api/covenant/run")
def covenant_run(
    learning: bool = Query(True, description="enable cross-run self-improvement"),
    attack: bool = Query(False, description="inject a malicious instruction to demo the guard"),
    fail_after: Optional[int] = Query(None, description="inject a failure after covenant index N (demo)"),
):
    improver = _improver if learning else None
    recovery = None
    task_id = None
    if fail_after is not None:
        recovery = RecoveryContext(_checkpoints, task_id="task_" + _new(), fail_after=fail_after)
        task_id = recovery.task_id
    agent = CovenantAgent(guard=_governance.guard, inject_attack=attack,
                          improver=improver, recovery=recovery, inference=_inference)
    try:
        trace = agent.run(task_id=task_id)
    except RunInterrupted as e:
        return {"interrupted": True, "checkpoint_id": e.checkpoint_id,
                "completed": e.completed, "task_id": recovery.task_id,
                "message": "Run interrupted; call /api/covenant/resume to continue."}
    _traces[trace.id] = trace
    _memory.save_run(trace)
    return _trace_summary(trace)


@router.get("/api/covenant/run/stream")
def covenant_run_stream(
    learning: bool = Query(True),
    attack: bool = Query(False),
):
    """Run the agent while streaming REAL per-step progress as Server-Sent Events.

    Events (JSON in each `data:` frame):
      {"type":"progress","step":"plan|retrieve_clauses|pull_filings|calculate|
                                  apply_waiver|cross_check|memo"}
      {"type":"result","run": <trace summary>}
      {"type":"error","message": ...}
    Each progress event fires when that phase actually completes in the runner,
    so the UI timeline reflects the true execution (including slow LLM/guard calls).
    """
    import json as _json
    import queue as _queue
    import threading as _threading

    events: "_queue.Queue" = _queue.Queue()
    improver = _improver if learning else None
    agent = CovenantAgent(guard=_governance.guard, inject_attack=attack,
                          improver=improver, inference=_inference,
                          progress=lambda step: events.put({"type": "progress", "step": step}))
    outcome: Dict[str, Any] = {}

    def _worker():
        try:
            trace = agent.run()
            _traces[trace.id] = trace
            _memory.save_run(trace)
            outcome["trace"] = trace
        except Exception as e:  # pragma: no cover - defensive
            outcome["error"] = f"{type(e).__name__}: {e}"
        finally:
            events.put({"type": "__done__"})

    def _gen():
        worker = _threading.Thread(target=_worker, daemon=True)
        worker.start()
        while True:
            ev = events.get()
            if ev.get("type") == "__done__":
                break
            yield f"data: {_json.dumps(ev)}\n\n"
        worker.join()
        if "trace" in outcome:
            yield f"data: {_json.dumps({'type': 'result', 'run': _trace_summary(outcome['trace'])})}\n\n"
        else:
            yield f"data: {_json.dumps({'type': 'error', 'message': outcome.get('error', 'run failed')})}\n\n"

    from fastapi.responses import StreamingResponse
    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no",
                                      "Connection": "keep-alive"})


@router.post("/api/covenant/resume/{task_id}")
def covenant_resume(task_id: str, learning: bool = Query(True)):
    cp = _checkpoints.load(task_id)
    if not cp:
        raise HTTPException(status_code=404, detail="No checkpoint for this task.")
    ctx = RecoveryContext(_checkpoints, task_id,
                          resume_state={**cp["state"], "checkpoint_id": cp["checkpoint_id"]})
    improver = _improver if learning else None
    trace = CovenantAgent(guard=_governance.guard, improver=improver, recovery=ctx).run(task_id=task_id)
    _traces[trace.id] = trace
    out = _trace_summary(trace)
    out["resumed"] = True
    return out


@router.get("/api/traces/{trace_id}/receipt")
def get_receipt(trace_id: str):
    trace = _traces.get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return _receipts.build(trace)




@router.get("/api/traces/{trace_id}/receipt/verify")
def verify_stored_receipt(trace_id: str):
    trace = _traces.get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    receipt = _receipts.build(trace)
    return _verify_receipt_payload(receipt)


@router.post("/api/receipts/verify")
def verify_receipt_payload(payload: Dict[str, Any]):
    return _verify_receipt_payload(payload)


@router.get("/api/traces/{trace_id}/replay")
def replay_trace(trace_id: str):
    trace = _traces.get(trace_id)
    if trace is None:
        saved = _memory.get_run(trace_id)
        if saved is None:
            raise HTTPException(status_code=404, detail="Trace not found.")
        return {"trace_id": trace_id, "source": "TraceMemory", "events": saved.get("tool_calls", []), "final_output": saved.get("final_output")}
    return {
        "trace_id": trace.id,
        "task_id": trace.task_id,
        "source": "live_trace",
        "events": [
            {
                "index": i + 1,
                "tool": tc.tool,
                "args": tc.args,
                "guard_decision": tc.guard.decision.value,
                "guard_path": tc.guard.guard_path.value,
                "findings": tc.guard.findings,
            }
            for i, tc in enumerate(trace.tool_calls)
        ],
        "final_output": trace.final_output,
    }


@router.get("/api/trace-events")
def list_trace_events():
    return {"events": _memory.list_events()}


@router.post("/api/evidence/upload")
async def upload_evidence(file: UploadFile = File(...)):
    import os, shutil
    from pathlib import Path
    from app.tools.ingestion import ingest_document
    upload_dir = Path(os.environ.get("COVENANTOPS_UPLOAD_DIR", "data/evidence"))
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload.bin").name
    dest = upload_dir / safe_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty file rejected.")
    try:
        doc = ingest_document(str(dest))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not ingest file: {e}")
    _memory.save_event({"event_type": "document_uploaded", "filename": doc.filename, "source_type": doc.source_type, "trust_level": doc.trust_level.value})
    return {
        "filename": doc.filename,
        "source_type": doc.source_type,
        "trust_level": doc.trust_level.value,
        "chunks": len(doc.chunks),
        "sha256": doc.sha256,
        "injection_findings": doc.injection_findings,
    }


@router.get("/api/receipts/public-key")
def public_key():
    return {"algorithm": "Ed25519", "public_key_ed25519_b64": _receipts.public_key_b64()}


@router.get("/api/traces/{trace_id}/evaluation")
def get_evaluation(trace_id: str):
    trace = _traces.get(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return {"trace_id": trace_id, "evaluation": trace.metadata.get("evaluation"),
            "evidence_map": trace.metadata.get("evidence_map"),
            "context_health": trace.metadata.get("context_health")}


@router.get("/api/runs")
def list_runs():
    return {"runs": _memory.list_runs(), "persistent": _memory.persistent}


@router.get("/api/integrations/vultr/status")
def vultr_status():
    """Surface whether Vultr Serverless Inference is configured (judge-visible)."""
    return {
        "serverless_inference_configured": _inference.enabled,
        "base_url": _inference.base_url,
        "chat_model": _inference.chat_model,
        "last_used": _inference.last_used,
    }


@router.get("/api/evidence")
def list_evidence():
    """Ingest and list the evidence pack: multi-format, trust-tagged, injection-scanned."""
    from app.tools.ingestion import ingest_directory
    import os
    docs = ingest_directory(os.environ.get("COVENANTOPS_EVIDENCE_DIR", "data/evidence"))
    return {
        "count": len(docs),
        "documents": [
            {"filename": d.filename, "source_type": d.source_type,
             "trust_level": d.trust_level.value, "chunks": len(d.chunks),
             "injection_findings": d.injection_findings, "sha256": d.sha256[:16]}
            for d in docs
        ],
    }


@router.get("/api/health")
def health():
    return {
        "status": "ok",
        "airg_enabled": _governance.enabled,
        "airg_url": _governance.airg_url or None,
        "last_guard_path": _governance.last_path.value,
        "vultr_inference_enabled": _inference.enabled,
        "vultr_last_used": _inference.last_used,
    }


def _verify_receipt_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import base64
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from app.trust.receipt import canonical
        body = payload.get("receipt")
        sig = payload.get("signature_ed25519_b64")
        pub_b64 = payload.get("public_key_ed25519_b64") or _receipts.public_key_b64()
        if not body or not sig:
            return {"valid": False, "reason": "receipt body or signature missing"}
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64))
        pub.verify(base64.b64decode(sig), canonical(body))
        return {"valid": True, "algorithm": "Ed25519", "reason": "signature verified"}
    except Exception as e:
        return {"valid": False, "algorithm": "Ed25519", "reason": str(e)}


def _new() -> str:
    import uuid
    return uuid.uuid4().hex[:12]
