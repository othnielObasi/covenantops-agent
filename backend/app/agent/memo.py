"""Escalation-memo formatter."""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple


def build_memo(borrower: str, facility: str, findings: List[Dict[str, Any]],
              staleness_penalty: float = 0.0, staleness_notes: Optional[List[str]] = None
              ) -> Tuple[str, str, float, float]:
    """Returns (memo_text, severity, confidence, raw_confidence).

    `raw_confidence` reflects transaction cause-matching only. `confidence` is
    that figure discounted by `staleness_penalty` (draft accounts, expired
    waivers, stale learned lessons) — the number a reviewer should actually rely
    on, with the discount and its cause shown in the memo rather than hidden."""
    staleness_notes = staleness_notes or []
    flagged = [f for f in findings if f["ratio"]["drifting_toward_breach"] or f["ratio"]["breached"]]
    confidences = [f["cross_check"]["confidence"] for f in flagged if f["cross_check"]]
    raw_confidence = min(confidences) if confidences else 1.0
    staleness_penalty = max(0.0, min(1.0, staleness_penalty))
    confidence = round(raw_confidence * (1 - staleness_penalty), 2)
    severity = "none"
    if any(f["ratio"]["breached"] for f in flagged):
        severity = "breach"
    elif flagged:
        severity = "watch"

    lines = [
        "COVENANT MONITORING \u2014 ESCALATION MEMO",
        f"Borrower: {borrower}",
        f"Facility: {facility}",
        "",
    ]
    if not flagged:
        lines.append("All tested covenants are within their thresholds with adequate headroom. No escalation required.")
    else:
        lines.append(f"STATUS: {severity.upper()} \u2014 {len(flagged)} covenant(s) require attention.")
        lines.append("")
        for f in flagged:
            r = f["ratio"]
            comp = "breached" if r["breached"] else "drifting toward breach"
            src = f" [source: {r.get('source_document','agreement')} p{r.get('source_page','?')}]"
            lines.append(f"\u2022 {r['covenant_id']} ({r['metric']}): {r['value']} vs limit {r['threshold']} \u2014 {comp} (headroom {r['headroom']}).{src}")
            if f["cross_check"]:
                cc = f["cross_check"]
                for m in cc["matched"]:
                    lines.append(f"    - cause: {m['id']} {m['note']} \u2192 {m['cause']}")
                for u in cc["unexplained"]:
                    lines.append(f"    - UNEXPLAINED: {u['id']} {u['note']} (no clear cause \u2014 requires review)")
                lines.append(f"    - cause-attribution confidence: {cc['confidence']} "
                             f"({cc['explanation_count']} explained / {cc['unexplained_count']} unexplained)")
        lines.append("")
        lines.append("Recommended action: request a compliance certificate and, if the leverage trend persists, "
                     "evaluate the Equity Cure right under Section 7.4 before the next test date.")
    if staleness_notes:
        lines.append("")
        lines.append("FRESHNESS WARNINGS:")
        for note in staleness_notes:
            lines.append(f"  ⚠ {note}")

    lines.append("")
    if staleness_penalty > 0:
        lines.append(f"Overall cause-attribution confidence: {confidence} "
                     f"(raw {raw_confidence}, discounted {round(staleness_penalty * 100)}% for staleness)")
    else:
        lines.append(f"Overall cause-attribution confidence: {confidence}")
    return ("\n".join(lines), severity, confidence, raw_confidence)
