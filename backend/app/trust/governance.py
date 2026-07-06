"""Governance layer for CovenantOps Agent.

Sits at the tool<->agent boundary. Every tool call is evaluated; tool outputs that
carry free text sourced from documents/transactions are scanned for injection and
PII before the agent trusts them.

Primary path: AIRG hosted API (POST /actions/evaluate, POST /actions/scan-output).
Fallback path: a deterministic local guard — not a stub, a real standalone
governance layer with graduated risk scoring, so the agent is fully governed even
with zero external configuration.

TR-S1: governance is OPTIONAL and MUST fail safe. If AIRG is unreachable, times out,
or errors, the agent continues on the local fallback rather than failing the run.
TR-S2: each result records which guard path produced it (airg | local_fallback).
TR-S3: a short timeout ensures a slow API degrades to fallback quickly.
"""
from __future__ import annotations

import os
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.models import GuardDecision, GuardPath, GuardResult

# Tools whose output carries free text sourced from documents or transactions,
# and so must be scanned for injection/PII before the agent trusts it. The
# clarifying Q&A is included: the user's question and the model's answer are both
# free text and must pass the same governance boundary as any other tool.
_DOC_TOOLS = {"retrieve_covenant_clauses", "get_filings", "cross_check_transactions", "covenant_qa"}

# Risk contributed by a matched pattern, before capping at 100.
_CRITICAL = 90   # a single match is decisive on its own -> block
_HIGH = 55       # a single match alone -> review; two -> block
_MEDIUM = 30     # weak/ambiguous manipulation signal -> review only in combination

# (pattern, weight, label) — label is what shows up in findings for audit/replay.
_INJECTION_RULES: List[Tuple[re.Pattern, int, str]] = [
    # Direct instruction override — clearly adversarial, block outright.
    (re.compile(r"ignore (all |any |prior |previous |the )*(instructions|rules|context|policy)", re.I), _CRITICAL, "instruction_override"),
    (re.compile(r"disregard (the |all |prior )?(above|instructions|policy)", re.I), _CRITICAL, "instruction_override"),
    (re.compile(r"you are now\b|new instructions\s*:|system\s*(prompt|override)", re.I), _CRITICAL, "role_override"),
    (re.compile(r"bypass (the )?(guard|governance|policy|check)", re.I), _CRITICAL, "governance_bypass"),
    # Content-manipulation asks — strongly adversarial, but stated as a request
    # rather than a hard override; review-tier alone, block if paired with anything else.
    (re.compile(r"report all covenants (as )?(compliant|passing|ok)", re.I), _HIGH, "outcome_manipulation"),
    (re.compile(r"mark (the )?borrower (as )?compliant", re.I), _HIGH, "outcome_manipulation"),
    (re.compile(r"do not (flag|report|escalate|mention)", re.I), _HIGH, "suppression_request"),
    (re.compile(r"act as\b.{0,20}\b(administrator|system|developer)", re.I), _HIGH, "role_override"),
    (re.compile(r"pretend (you are|to be)", re.I), _HIGH, "role_override"),
    (re.compile(r"jailbreak", re.I), _HIGH, "jailbreak_reference"),
    # Softer, ambiguous social-engineering phrasing — worth a human look, not a block.
    (re.compile(r"for (debugging|testing) purposes,?\s*ignore", re.I), _MEDIUM, "soft_override"),
    (re.compile(r"this is (a|an) (test|drill)\b", re.I), _MEDIUM, "pretext"),
    (re.compile(r"reveal (your )?(system prompt|instructions)", re.I), _MEDIUM, "prompt_probe"),
    (re.compile(r"print (your )?(system prompt|instructions)", re.I), _MEDIUM, "prompt_probe"),
]

_PII_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn"),
    (re.compile(r"\b(?:\d[ -]*?){13,16}\b"), "card_number"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private_key"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.I), "email"),
    (re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"), "phone_number"),
]


def _text_of(output: Any) -> str:
    if isinstance(output, dict):
        return " ".join(str(v) for v in output.values())
    return str(output)


def local_guard(tool: str, args: Dict[str, Any], output: Any) -> GuardResult:
    """Deterministic offline guard — the standalone governance layer used whenever
    AIRG is unset or unreachable. Scans tool outputs carrying document/transaction
    text for injection (graduated by severity) and PII (always decisive), and
    allows other calls with a clean pass-through."""
    if tool not in _DOC_TOOLS:
        return GuardResult(
            decision=GuardDecision.allow, risk_score=0, reason="clean",
            guard_path=GuardPath.local_fallback, findings=[],
        )

    text = _text_of(output)
    findings: List[str] = []
    risk_score = 0
    for pattern, weight, label in _INJECTION_RULES:
        if pattern.search(text):
            findings.append(f"prompt_injection:{label}")
            risk_score += weight
    pii_found = False
    for pattern, label in _PII_RULES:
        if pattern.search(text):
            findings.append(f"pii_detected:{label}")
            pii_found = True

    risk_score = min(risk_score, 100)

    if pii_found or risk_score >= _CRITICAL:
        return GuardResult(
            decision=GuardDecision.block,
            risk_score=max(risk_score, 90),
            reason="Injection/PII detected in tool output; content withheld from agent reasoning.",
            guard_path=GuardPath.local_fallback,
            findings=findings,
        )
    if risk_score >= _MEDIUM:
        return GuardResult(
            decision=GuardDecision.review,
            risk_score=risk_score,
            reason="Ambiguous manipulation signal in tool output; flagged for human review.",
            guard_path=GuardPath.local_fallback,
            findings=findings,
        )
    return GuardResult(
        decision=GuardDecision.allow, risk_score=0, reason="clean",
        guard_path=GuardPath.local_fallback, findings=[],
    )


class Governance:
    """Guard callable factory. Use .guard as the agent's guard function.
    Tries AIRG first (if configured), falls back to local guard on any failure."""

    def __init__(self,
                 airg_url: Optional[str] = None,
                 airg_key: Optional[str] = None,
                 timeout: float = 4.0,
                 agent_id: str = "covenantops-covenant"):
        self.airg_url = (airg_url or os.environ.get("AIRG_URL") or "").rstrip("/")
        self.airg_key = airg_key or os.environ.get("AIRG_API_KEY")
        self.timeout = float(os.environ.get("AIRG_TIMEOUT_SECONDS", timeout))
        self.agent_id = os.environ.get("AIRG_AGENT_ID", agent_id)
        self.session_id = os.environ.get("AIRG_SESSION_ID", "covenantops")
        self.org_id = os.environ.get("AIRG_ORG_ID", "")
        self.workspace_id = os.environ.get("AIRG_WORKSPACE_ID", "")
        self.app_id = os.environ.get("AIRG_APP_ID", "covenantops-agent")
        self.environment = os.environ.get("AIRG_ENVIRONMENT", "production")
        self.user_id = os.environ.get("AIRG_USER_ID", "covenantops-system")
        self.workflow_id = os.environ.get("AIRG_WORKFLOW_ID", "loan-covenant-monitoring")
        self.trace_id: Optional[str] = None
        self.parent_span_id: Optional[str] = None
        self.enabled = bool(self.airg_url and self.airg_key)
        self.last_path = GuardPath.none

    def set_trace_context(self, trace_id: str, parent_span_id: Optional[str] = None) -> None:
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id

    def _headers(self, request_id: str) -> Dict[str, str]:
        headers = {
            "X-API-Key": self.airg_key or "",
            "Content-Type": "application/json",
            "X-AIRG-Agent-Id": self.agent_id,
            "X-AIRG-Session-Id": self.session_id,
            "X-AIRG-App-Id": self.app_id,
            "X-AIRG-Environment": self.environment,
            "X-AIRG-User-Id": self.user_id,
            "X-AIRG-Workflow-Id": self.workflow_id,
            "X-Request-Id": request_id,
        }
        if self.org_id:
            headers["X-AIRG-Org-Id"] = self.org_id
        if self.workspace_id:
            headers["X-AIRG-Workspace-Id"] = self.workspace_id
        if self.trace_id:
            headers["X-AIRG-Trace-Id"] = self.trace_id
        if self.parent_span_id:
            headers["X-AIRG-Span-Id"] = self.parent_span_id
        return headers

    def _context(self, tool: str, request_id: str) -> Dict[str, Any]:
        context = {
            "tool_type": "read",
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "app_id": self.app_id,
            "environment": self.environment,
            "user_id": self.user_id,
            "workflow_id": self.workflow_id,
            "request_id": request_id,
            "agent_type": "credit-risk-monitor",
            "channel": "covenantops",
            "domain": "finance",
            "risk_domain": "finance",
            "tool_family": "covenant-monitoring",
        }
        if self.org_id:
            context["org_id"] = self.org_id
        if self.workspace_id:
            context["workspace_id"] = self.workspace_id
        if self.trace_id:
            context["trace_id"] = self.trace_id
        if self.parent_span_id:
            context["span_id"] = self.parent_span_id
        return context

    def guard(self, tool: str, args: Dict[str, Any], output: Any) -> GuardResult:
        if self.enabled:
            res = self._airg_guard(tool, args, output)
            if res is not None:
                self.last_path = GuardPath.airg
                return res
            # AIRG failed -> fail safe to local
        res = local_guard(tool, args, output)
        self.last_path = res.guard_path
        return res

    def _airg_guard(self, tool: str, args: Dict[str, Any], output: Any) -> Optional[GuardResult]:
        """Call AIRG /actions/evaluate and, for document tools, /actions/scan-output.
        Returns None on ANY failure so the caller falls back to local (TR-S1)."""
        request_id = str(uuid.uuid4())
        headers = self._headers(request_id)
        context = self._context(tool, request_id)
        try:
            with httpx.Client(timeout=self.timeout) as client:
                ev = client.post(f"{self.airg_url}/actions/evaluate", headers=headers, json={
                    "tool": tool, "args": args, "agent_id": self.agent_id,
                    "session_id": self.session_id, "context": context,
                })
                ev.raise_for_status()
                ed = ev.json()
                decision = str(ed.get("decision", "allow")).lower()
                risk = int(ed.get("risk_score", 0))
                findings = []

                if tool in _DOC_TOOLS:
                    sc = client.post(f"{self.airg_url}/actions/scan-output", headers=headers, json={
                        "text": _text_of(output), "agent_id": self.agent_id,
                        "session_id": self.session_id,
                    })
                    sc.raise_for_status()
                    sd = sc.json()
                    if sd.get("findings") or sd.get("blocked"):
                        decision = "block"
                        findings = sd.get("findings", ["scan_output_flag"])
                        risk = max(risk, int(sd.get("risk_score", 90)))

                dec = {"allow": GuardDecision.allow, "review": GuardDecision.review,
                       "block": GuardDecision.block}.get(decision, GuardDecision.allow)
                return GuardResult(decision=dec, risk_score=risk,
                                   reason=ed.get("reason", "airg evaluated"),
                                   guard_path=GuardPath.airg, findings=findings)
        except Exception:
            return None  # fail safe -> local
