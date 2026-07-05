"""Signed execution receipt — CovenantOps Agent's verifiable citation trail.

Assembles a portable record of a covenant run (agreement source, clauses,
ratios, transactions matched, memo hash), canonicalizes it deterministically,
hashes with SHA-256, and signs with Ed25519. Verifiable offline, without the
server, via tools/verify_receipt.py.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from app.models import ExecutionTrace

RECEIPT_VERSION = "covenantops.receipt/v1"


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class ReceiptService:
    def __init__(self, key_path: str = "data/covenantops_ed25519.key"):
        self._key_path = Path(key_path)
        self._key = self._load_or_create()

    def _load_or_create(self) -> Ed25519PrivateKey:
        # Preferred: a stable key from the environment (survives restarts/replicas).
        env = os.environ.get("COVENANTOPS_SIGNING_KEY_B64")
        if env:
            return Ed25519PrivateKey.from_private_bytes(base64.b64decode(env))
        # Next: a key persisted to disk (stable if the volume persists).
        if self._key_path.exists():
            return Ed25519PrivateKey.from_private_bytes(self._key_path.read_bytes())
        # Fallback: generate and try to persist. If the key cannot be persisted,
        # receipts signed now will NOT verify after a restart — warn loudly.
        import logging
        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        try:
            self._key_path.parent.mkdir(parents=True, exist_ok=True)
            self._key_path.write_bytes(raw)
            logging.getLogger("covenantops.receipt").info(
                "Generated a new signing key at %s. Set COVENANTOPS_SIGNING_KEY_B64 "
                "for a stable key across restarts/replicas.", self._key_path)
        except OSError:
            logging.getLogger("covenantops.receipt").warning(
                "Using an EPHEMERAL in-memory signing key (could not persist to %s). "
                "Receipts signed now will not verify after a restart. Set "
                "COVENANTOPS_SIGNING_KEY_B64 for a stable key.", self._key_path)
        return key

    @staticmethod
    def generate_key_b64() -> str:
        """Helper to mint a stable signing key for COVENANTOPS_SIGNING_KEY_B64."""
        k = Ed25519PrivateKey.generate()
        raw = k.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return base64.b64encode(raw).decode("ascii")

    def public_key_b64(self) -> str:
        pub = self._key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        return base64.b64encode(pub).decode("ascii")

    def build(self, trace: ExecutionTrace) -> Dict[str, Any]:
        md = trace.metadata
        doc_freshness = md.get("document_freshness", [])
        expired_waivers = [
            f["ratio"]["waiver_expired"] for f in md.get("findings", [])
            if f.get("ratio", {}).get("waiver_expired")
        ]
        body = {
            "receipt_version": RECEIPT_VERSION,
            "task_id": trace.task_id,
            "trace_id": trace.id,
            "agent_id": trace.agent_id,
            "borrower": md.get("borrower"),
            "facility": md.get("facility"),
            "severity": md.get("severity"),
            "confidence": md.get("confidence"),
            "guard_path": trace.guard_path.value,
            "evidence": {
                "clauses": [c for c in md.get("citations", []) if c.get("clause_id")],
                "transactions": [c for c in md.get("citations", []) if c.get("txn_id")],
                "tool_calls": [{"tool": tc.tool, "guard": tc.guard.decision.value} for tc in trace.tool_calls],
            },
            # So a reviewer can verify not just what was concluded, but whether the
            # underlying evidence was confirmed current at decision time.
            "freshness_checks": {
                "document_versions_used": [
                    {"filename": d["filename"], "reporting_period": d["reporting_period"], "version": d["version"]}
                    for d in doc_freshness
                ],
                "draft_documents_detected": [d["filename"] for d in doc_freshness if d["signed_status"] == "draft"],
                "superseding_documents_checked": [
                    {"superseded": d["filename"], "superseded_by": d["superseded_by"]}
                    for d in doc_freshness if d["superseded_by"]
                ],
                "expired_documents_detected": expired_waivers,
                "confidence_adjustments": {
                    "raw_confidence": md.get("raw_confidence"),
                    "staleness_penalty": md.get("staleness_penalty"),
                    "notes": md.get("staleness_notes", []),
                },
            },
            "memo_sha256": hashlib.sha256(trace.final_output.encode("utf-8")).hexdigest(),
        }
        encoded = canonical(body)
        content_hash = hashlib.sha256(encoded).hexdigest()
        signature = self._key.sign(encoded)
        return {
            "receipt": body,
            "content_sha256": content_hash,
            "signature_ed25519_b64": base64.b64encode(signature).decode("ascii"),
            "public_key_ed25519_b64": self.public_key_b64(),
            "verification": {
                "algorithm": "Ed25519",
                "canonicalization": "JSON sort_keys=true, separators=(',',':'), UTF-8",
                "instructions": "Recompute SHA-256 over the canonical encoding of 'receipt'; verify 'signature_ed25519_b64' with 'public_key_ed25519_b64'.",
            },
        }
