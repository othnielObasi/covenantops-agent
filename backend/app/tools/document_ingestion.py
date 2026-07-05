"""Real PDF ingestion for CovenantOps Agent.

Parses an actual credit-agreement PDF into structured covenant clauses, rather
than reading a hand-authored dict. This is the difference between *modelling*
document grounding and *doing* it: the agent grounds on clauses extracted from a
real document, with page-level provenance for the citation trail.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


# Section headings we treat as covenant/anchor clauses, mapped to covenant types.
_SECTION_TYPES = {
    "6.1": "leverage",
    "6.2": "interest_cover",
    "6.3": "liquidity",
    "7.4": "cure",
    "9.1": "default",
}

# Threshold extraction: ratios like "3.50:1.00" and money like "USD 8,000,000".
_RATIO_RE = re.compile(r"(\d+\.\d+)\s*:\s*\d+\.\d+")
_MONEY_RE = re.compile(r"USD\s*([\d,]+)")
_SECTION_RE = re.compile(r"Section\s+(\d+\.\d+)\s+([^.]+)\.")


def _direction_for(section: str, text: str) -> Optional[str]:
    t = text.lower()
    if "not exceed" in t or "shall not exceed" in t:
        return "max"
    if "not be less than" in t or "not less than" in t or "maintain" in t:
        return "min"
    return None


def _threshold_for(covenant_type: str, text: str):
    if covenant_type in ("leverage", "interest_cover"):
        m = _RATIO_RE.search(text)
        return float(m.group(1)) if m else None
    if covenant_type == "liquidity":
        m = _MONEY_RE.search(text)
        return float(m.group(1).replace(",", "")) if m else None
    return None


def _metric_for(covenant_type: str) -> Optional[str]:
    return {
        "leverage": "Total Net Debt / EBITDA",
        "interest_cover": "EBITDA / Net Finance Charges",
        "liquidity": "Available Liquidity (USD)",
    }.get(covenant_type)


def ingest_credit_agreement(pdf_path: str) -> Dict:
    """Parse a credit-agreement PDF into borrower/facility + covenant clauses.
    Each clause carries page-level provenance for citation."""
    if pdfplumber is None:
        raise RuntimeError("pdfplumber is required for PDF ingestion")
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(pdf_path)

    pages_text: List[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")
    full = "\n".join(pages_text)

    # Borrower / facility from the cover text.
    borrower_m = re.search(r"among\s+(.+?),\s*as Borrower", full, re.IGNORECASE | re.DOTALL)
    borrower = re.sub(r"\s+", " ", borrower_m.group(1)).strip() if borrower_m else "Unknown Borrower"
    facility_m = re.search(r"(USD[\s\d,]+Senior Secured Term Loan[^\n]*)", full)
    facility = facility_m.group(1).strip() if facility_m else "Senior Secured Term Loan"

    # Which page each section sits on (for provenance).
    def page_of(section_no: str) -> int:
        for i, pt in enumerate(pages_text):
            if re.search(rf"Section\s+{re.escape(section_no)}\b", pt):
                return i + 1
        return 1

    clauses: List[Dict] = []
    # A real clause heading looks like "Section 6.1 Leverage Ratio." followed by a
    # capitalised title, NOT an inline cross-reference like "...of Section 7.4)".
    # Require the section number to be followed by a Title Case heading and a period.
    heading_re = re.compile(r"Section\s+(\d+\.\d+)\s+([A-Z][A-Za-z ]+?)\.\s")
    matches = list(heading_re.finditer(full))
    seen_sections = set()
    for idx, m in enumerate(matches):
        section_no = m.group(1)
        covenant_type = _SECTION_TYPES.get(section_no)
        if covenant_type is None or section_no in seen_sections:
            continue
        title = m.group(2).strip()
        # A real heading title is short (a name), not a run-on sentence fragment.
        if len(title.split()) > 6:
            continue
        seen_sections.add(section_no)
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full)
        body = re.sub(r"\s+", " ", full[start:end]).strip()
        clause = {
            "id": f"sec-{section_no}",
            "section": section_no,
            "title": title,
            "text": body,
            "covenant_type": covenant_type,
            "threshold": _threshold_for(covenant_type, body),
            "direction": _direction_for(section_no, body),
            "metric": _metric_for(covenant_type),
            "source_page": page_of(section_no),
            "source_document": path.name,
        }
        clauses.append(clause)

    return {
        "borrower": borrower,
        "facility": facility,
        "source_document": path.name,
        "page_count": len(pages_text),
        "clauses": clauses,
    }
