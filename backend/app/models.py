"""CovenantOps Agent core schemas. Self-contained — no external platform dependency."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class GuardDecision(str, Enum):
    allow = "allow"
    review = "review"
    block = "block"


class GuardPath(str, Enum):
    airg = "airg"
    local_fallback = "local_fallback"
    none = "none"


class GuardResult(BaseModel):
    decision: GuardDecision = GuardDecision.allow
    risk_score: int = 0
    reason: str = ""
    guard_path: GuardPath = GuardPath.none
    findings: List[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    tool_call_id: str = Field(default_factory=lambda: new_id("tc"))
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    output: Optional[Dict[str, Any]] = None
    guard: GuardResult = Field(default_factory=GuardResult)
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class TraceStatus(str, Enum):
    success = "success"
    failed = "failed"
    recovered = "recovered"


class TrustLevel(str, Enum):
    """Source-provenance trust: how much the agent should weight evidence by origin."""
    very_high = "very_high"   # signed credit agreement, signed waiver
    high = "high"             # bank/transaction export
    medium = "medium"         # management accounts (borrower-prepared)
    low = "low"               # borrower note / commentary
    untrusted = "untrusted"   # unknown / unverified source


TRUST_WEIGHT = {
    TrustLevel.very_high: 1.0,
    TrustLevel.high: 0.8,
    TrustLevel.medium: 0.55,
    TrustLevel.low: 0.25,
    TrustLevel.untrusted: 0.0,
}


class IngestedDocument(BaseModel):
    id: str = Field(default_factory=lambda: new_id("doc"))
    filename: str
    source_type: str
    trust_level: TrustLevel = TrustLevel.untrusted
    chunks: List[Dict[str, Any]] = Field(default_factory=list)
    sha256: Optional[str] = None
    injection_findings: List[str] = Field(default_factory=list)
    # Freshness/supersession metadata, derived at ingestion (best-effort from filename
    # today; a real deployment would source these from document metadata/upload form).
    reporting_period: Optional[str] = None   # e.g. "2025-Q3" — which period this document speaks to
    version: Optional[int] = None            # e.g. 2 for "...v2.docx"
    signed_status: str = "unknown"           # "signed" | "draft" | "unknown"
    superseded_by: Optional[str] = None      # filename of a newer document of the same source_type


class ExecutionTrace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("trace"), alias="_id")
    task_id: str
    agent_id: str
    task_description: str
    status: TraceStatus = TraceStatus.success
    tool_calls: List[ToolCall] = Field(default_factory=list)
    final_output: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    guard_path: GuardPath = GuardPath.none
    created_at: datetime = Field(default_factory=utc_now)

    model_config = ConfigDict(populate_by_name=True)


class Lesson(BaseModel):
    id: str = Field(default_factory=lambda: new_id("lesson"))
    source_trace_id: str
    borrower: Optional[str] = None           # revalidation scope: don't cross-apply across borrowers
    covenant_type: str
    transaction_type: str
    cause: str
    confidence: float
    valid_for_period: Optional[str] = None   # staleness scope
    provenance: str = "reflection"
    created_at: datetime = Field(default_factory=utc_now)
