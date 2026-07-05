"""Tools the covenant agent calls. Clauses come from the ingested real PDF;
filings and transactions from representative data. Each tool is a real function,
so the agent's workflow is genuine multi-step tool use."""
from __future__ import annotations

from typing import Dict, List, Optional

import os
from app.tools.documents import FILINGS, TRANSACTIONS
from app.tools.document_ingestion import ingest_credit_agreement

# The credit agreement is ingested lazily on first use (not at import), so a
# missing/unreadable PDF surfaces a clear error at call time rather than crashing
# the entire app during import.
_PDF = os.environ.get("COVENANTOPS_AGREEMENT_PDF", "data/credit_agreement.pdf")
_AGREEMENT = None


def _agreement() -> Dict:
    global _AGREEMENT
    if _AGREEMENT is None:
        try:
            _AGREEMENT = ingest_credit_agreement(_PDF)
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"Credit-agreement PDF not found at '{_PDF}'. Set COVENANTOPS_AGREEMENT_PDF "
                f"or place the file at data/credit_agreement.pdf."
            ) from e
    return _AGREEMENT


def _clauses() -> List[Dict]:
    return _agreement()["clauses"]


def get_borrower() -> str:
    return _agreement()["borrower"]


def get_facility() -> str:
    return _agreement()["facility"]


# Backwards-compatible module attributes (resolved lazily via __getattr__ below).
def __getattr__(name):
    if name == "CLAUSES":
        return _clauses()
    if name == "BORROWER":
        return _agreement()["borrower"]
    if name == "FACILITY":
        return _agreement()["facility"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_active_waivers() -> List[Dict]:
    """Signed waivers/amendments that temporarily adjust a covenant threshold.
    In production these are parsed from the ingested signed_waiver documents; here
    a representative Q2 leverage waiver stands in (very_high trust source)."""
    return [
        {
            "id": "waiver-q2",
            "covenant_type": "leverage",
            "adjusted_threshold": 3.75,   # temporarily relaxed from 3.50
            "valid_periods": ["2025-Q2", "2025-Q3"],
            "source": "Q2 Waiver Letter.docx",
            "trust": "very_high",
        }
    ]


def _effective_threshold(covenant_type: str, base_threshold: float, period: str) -> Dict:
    """Apply any active, in-period waiver to the base covenant threshold.

    If a waiver exists for this covenant type but its valid_periods does not cover
    the requested period, that is surfaced explicitly as `waiver_expired` rather
    than silently reverting to the base threshold with no explanation — a stale
    waiver that no longer applies is a freshness finding, not a non-event."""
    candidates = [w for w in get_active_waivers() if w["covenant_type"] == covenant_type]
    for w in candidates:
        if period in w["valid_periods"]:
            return {"threshold": w["adjusted_threshold"], "waiver_applied": w["id"],
                    "base_threshold": base_threshold, "waiver_source": w["source"],
                    "waiver_expired": None}
    if candidates:
        w = candidates[-1]
        periods = ", ".join(w["valid_periods"])
        expired_note = (f"{w['id']} ({w['source']}) is valid for {periods} and does not cover "
                        f"{period}; the base threshold applies and this period requires review.")
        return {"threshold": base_threshold, "waiver_applied": None,
                "base_threshold": base_threshold, "waiver_source": None,
                "waiver_expired": expired_note}
    return {"threshold": base_threshold, "waiver_applied": None,
            "base_threshold": base_threshold, "waiver_source": None, "waiver_expired": None}


def retrieve_covenant_clauses(query: str, top_k: int = 3) -> List[Dict]:
    """Keyword-scored retrieval over the clauses parsed from the real PDF."""
    q = query.lower()
    scored = []
    for clause in _clauses():
        hay = (clause["title"] + " " + clause["text"] + " " + (clause.get("covenant_type") or "")).lower()
        score = sum(1 for w in q.split() if len(w) > 3 and w in hay)
        if score:
            scored.append((score, clause))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [c for _, c in scored[:top_k]] or _clauses()[:1]


def get_filings(periods: Optional[int] = None) -> List[Dict]:
    return FILINGS[-periods:] if periods else list(FILINGS)


def calculate_ratio(covenant_type: str, period: Optional[str] = None) -> Dict:
    filing = None
    if period:
        filing = next((f for f in FILINGS if f["period"] == period), None)
    filing = filing or FILINGS[-1]

    clause = next((c for c in _clauses() if c.get("covenant_type") == covenant_type), None)
    if clause is None:
        raise ValueError(f"No covenant of type {covenant_type}")

    threshold = clause["threshold"]
    direction = clause["direction"]

    # apply any active signed waiver that adjusts this covenant's threshold for the period
    eff = _effective_threshold(covenant_type, threshold, filing["period"])
    threshold = eff["threshold"]

    if covenant_type == "leverage":
        value = round(filing["total_net_debt"] / filing["ebitda"], 3)
    elif covenant_type == "interest_cover":
        value = round(filing["ebitda"] / filing["net_finance_charges"], 3)
    elif covenant_type == "liquidity":
        value = float(filing["available_liquidity"])
    else:
        raise ValueError(f"No calculation defined for {covenant_type}")

    if direction == "max":
        breached = value > threshold
        headroom = round(threshold - value, 3)
    else:
        breached = value < threshold
        headroom = round(value - threshold, 3)

    near = threshold * 0.10
    drifting = (not breached) and (abs(headroom) <= near if covenant_type != "liquidity" else abs(headroom) <= threshold * 0.15)

    return {
        "covenant_id": clause["id"],
        "covenant_type": covenant_type,
        "period": filing["period"],
        "value": value,
        "threshold": threshold,
        "direction": direction,
        "headroom": headroom,
        "breached": breached,
        "drifting_toward_breach": bool(drifting),
        "metric": clause["metric"],
        "source_page": clause.get("source_page"),
        "source_document": clause.get("source_document"),
        "waiver_applied": eff["waiver_applied"],
        "base_threshold": eff["base_threshold"],
        "waiver_source": eff["waiver_source"],
        "waiver_expired": eff["waiver_expired"],
    }


def cross_check_transactions(covenant_type: str) -> Dict:
    affects = {
        "leverage": {"debt_drawdown": "increases Total Net Debt", "one_off_cost": "reduces EBITDA", "capex": "may increase debt/reduce headroom"},
        "interest_cover": {"debt_drawdown": "raises Net Finance Charges", "one_off_cost": "reduces EBITDA"},
        "liquidity": {"dividend": "reduces Available Liquidity", "capex": "reduces Available Liquidity", "receipt": "increases Available Liquidity"},
    }
    rules = affects.get(covenant_type, {})
    matched, unexplained = [], []
    for txn in TRANSACTIONS:
        cause = rules.get(txn["type"])
        if cause:
            matched.append({**txn, "cause": cause})
        elif txn["type"] == "unclassified":
            unexplained.append({**txn, "cause": None})
    total_relevant = len(matched) + len(unexplained)
    confidence = round(len(matched) / total_relevant, 2) if total_relevant else 1.0
    return {
        "covenant_type": covenant_type,
        "matched": matched,
        "unexplained": unexplained,
        "confidence": confidence,
        "explanation_count": len(matched),
        "unexplained_count": len(unexplained),
    }
