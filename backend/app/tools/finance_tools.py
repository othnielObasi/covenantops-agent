"""Tools the covenant agent calls, now portfolio-aware.

The lead borrower ("meridian") is grounded in the ingested credit-agreement PDF;
additional borrowers come from app.tools.borrowers with representative agreement
terms, filings, and transactions. Every tool takes an optional `borrower_id` so
the *same* multi-step workflow runs a genuine, distinct investigation per borrower.
Each tool is a real function — the agent's workflow is genuine multi-step tool use.
"""
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

DEFAULT_BORROWER = "meridian"

# Meridian's signed Q2 leverage waiver (very_high trust source). Kept here so the
# lead borrower's behaviour is unchanged.
_MERIDIAN_WAIVERS = [
    {
        "id": "waiver-q2",
        "covenant_type": "leverage",
        "adjusted_threshold": 3.75,   # temporarily relaxed from 3.50
        "valid_periods": ["2025-Q2", "2025-Q3"],
        "source": "Q2 Waiver Letter.docx",
        "trust": "very_high",
    }
]


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


def _is_default(borrower_id: Optional[str]) -> bool:
    return borrower_id in (None, "", DEFAULT_BORROWER)


def _dataset(borrower_id: Optional[str] = None) -> Dict:
    """Resolve the per-borrower dataset (borrower, facility, clauses, filings,
    transactions, waivers). The default borrower is grounded in the real PDF."""
    if _is_default(borrower_id):
        ag = _agreement()
        return {
            "borrower": ag["borrower"],
            "facility": ag["facility"],
            "clauses": ag["clauses"],
            "filings": list(FILINGS),
            "transactions": list(TRANSACTIONS),
            "waivers": _MERIDIAN_WAIVERS,
        }
    from app.tools.borrowers import get_dataset
    return get_dataset(borrower_id)


def list_borrowers() -> List[Dict]:
    """The monitored portfolio: id, borrower name, and facility for each borrower."""
    from app.tools.borrowers import BORROWERS
    out = [{"id": DEFAULT_BORROWER, "borrower": get_borrower(), "facility": get_facility()}]
    for bid, ds in BORROWERS.items():
        out.append({"id": bid, "borrower": ds["borrower"], "facility": ds["facility"]})
    return out


def get_borrower(borrower_id: Optional[str] = None) -> str:
    return _dataset(borrower_id)["borrower"]


def get_facility(borrower_id: Optional[str] = None) -> str:
    return _dataset(borrower_id)["facility"]


def _clauses(borrower_id: Optional[str] = None) -> List[Dict]:
    return _dataset(borrower_id)["clauses"]


# Backwards-compatible module attributes (resolved lazily via __getattr__ below).
def __getattr__(name):
    if name == "CLAUSES":
        return _clauses()
    if name == "BORROWER":
        return get_borrower()
    if name == "FACILITY":
        return get_facility()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_active_waivers(borrower_id: Optional[str] = None) -> List[Dict]:
    """Signed waivers/amendments that temporarily adjust a covenant threshold.
    In production these are parsed from the ingested signed_waiver documents."""
    return list(_dataset(borrower_id)["waivers"])


def _effective_threshold(covenant_type: str, base_threshold: float, period: str,
                         borrower_id: Optional[str] = None) -> Dict:
    """Apply any active, in-period waiver to the base covenant threshold.

    If a waiver exists for this covenant type but its valid_periods does not cover
    the requested period, that is surfaced explicitly as `waiver_expired` rather
    than silently reverting to the base threshold with no explanation."""
    candidates = [w for w in get_active_waivers(borrower_id) if w["covenant_type"] == covenant_type]
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


def retrieve_covenant_clauses(query: str, top_k: int = 3, borrower_id: Optional[str] = None) -> List[Dict]:
    """Keyword-scored retrieval over the borrower's covenant clauses."""
    q = query.lower()
    clauses = _clauses(borrower_id)
    scored = []
    for clause in clauses:
        hay = (clause["title"] + " " + clause["text"] + " " + (clause.get("covenant_type") or "")).lower()
        score = sum(1 for w in q.split() if len(w) > 3 and w in hay)
        if score:
            scored.append((score, clause))
    scored.sort(key=lambda s: s[0], reverse=True)
    return [c for _, c in scored[:top_k]] or clauses[:1]


def get_filings(periods: Optional[int] = None, borrower_id: Optional[str] = None) -> List[Dict]:
    filings = _dataset(borrower_id)["filings"]
    return filings[-periods:] if periods else list(filings)


def calculate_ratio(covenant_type: str, period: Optional[str] = None,
                    borrower_id: Optional[str] = None) -> Dict:
    filings = _dataset(borrower_id)["filings"]
    filing = None
    if period:
        filing = next((f for f in filings if f["period"] == period), None)
    filing = filing or filings[-1]

    clause = next((c for c in _clauses(borrower_id) if c.get("covenant_type") == covenant_type), None)
    if clause is None:
        raise ValueError(f"No covenant of type {covenant_type}")

    threshold = clause["threshold"]
    direction = clause["direction"]

    # apply any active signed waiver that adjusts this covenant's threshold for the period
    eff = _effective_threshold(covenant_type, threshold, filing["period"], borrower_id)
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


def cross_check_transactions(covenant_type: str, borrower_id: Optional[str] = None) -> Dict:
    affects = {
        "leverage": {"debt_drawdown": "increases Total Net Debt", "one_off_cost": "reduces EBITDA", "capex": "may increase debt/reduce headroom"},
        "interest_cover": {"debt_drawdown": "raises Net Finance Charges", "one_off_cost": "reduces EBITDA"},
        "liquidity": {"dividend": "reduces Available Liquidity", "capex": "reduces Available Liquidity", "receipt": "increases Available Liquidity"},
    }
    rules = affects.get(covenant_type, {})
    matched, unexplained = [], []
    for txn in _dataset(borrower_id)["transactions"]:
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


# Covenant types tested for the portfolio-status summary (kept local to avoid a
# circular import with the runner).
_COVENANTS = ["leverage", "interest_cover", "liquidity"]


def portfolio_status(borrower_id: Optional[str] = None) -> Dict:
    """Fast, deterministic severity + cause-attribution confidence for a borrower,
    computed from the ratios and transactions only (no LLM / no governance calls).
    Used to populate the portfolio table quickly; the full agent run adds the
    Vultr analyst note, governance, receipt, and staleness-adjusted confidence."""
    severity = "none"
    confs: List[float] = []
    for cov in _COVENANTS:
        try:
            r = calculate_ratio(cov, borrower_id=borrower_id)
        except ValueError:
            continue
        if r["breached"]:
            severity = "breach"
        elif r["drifting_toward_breach"] and severity != "breach":
            severity = "watch"
        if r["breached"] or r["drifting_toward_breach"]:
            confs.append(cross_check_transactions(cov, borrower_id=borrower_id)["confidence"])
    confidence = round(sum(confs) / len(confs), 2) if confs else 1.0
    return {"severity": severity, "confidence": confidence}
