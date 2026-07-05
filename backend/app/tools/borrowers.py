"""Multi-borrower portfolio for CovenantOps Agent.

Real covenant monitoring is a portfolio activity: a credit team watches many
borrowers, each with its own signed agreement, reported financials, and
transaction ledger. This module provides the per-borrower datasets the agent
runs its workflow against.

The lead borrower (`meridian`) is grounded in the ingested credit-agreement PDF
(see finance_tools). The additional borrowers below carry representative
agreement terms, filings, and transactions so the *same* agent workflow —
retrieve clauses -> pull filings -> re-verify each ratio -> apply waivers ->
cross-check transactions -> memo — produces a genuine, distinct investigation
for each one.
"""
from __future__ import annotations

from typing import Dict, List


def _clauses(doc: str, lev: float, ic: float, liq: float) -> List[Dict]:
    return [
        {"id": "sec-6.1", "covenant_type": "leverage", "threshold": lev, "direction": "max",
         "metric": "Total Net Debt / EBITDA", "title": "Leverage Ratio",
         "text": f"The Borrower shall ensure that Total Net Debt to EBITDA does not exceed {lev}:1.",
         "source_page": 2, "source_document": doc},
        {"id": "sec-6.2", "covenant_type": "interest_cover", "threshold": ic, "direction": "min",
         "metric": "EBITDA / Net Finance Charges", "title": "Interest Cover Ratio",
         "text": f"The ratio of EBITDA to Net Finance Charges shall not be less than {ic}:1.",
         "source_page": 2, "source_document": doc},
        {"id": "sec-6.3", "covenant_type": "liquidity", "threshold": liq, "direction": "min",
         "metric": "Available Liquidity (USD)", "title": "Minimum Liquidity",
         "text": f"Available Liquidity shall at all times be not less than USD {int(liq):,}.",
         "source_page": 2, "source_document": doc},
        {"id": "sec-7.4", "covenant_type": "equity_cure", "threshold": None, "direction": None,
         "metric": "Equity Cure", "title": "Equity Cure",
         "text": "The Borrower may cure a breach by injecting equity within the cure period.",
         "source_page": 2, "source_document": doc},
    ]


def _filings(tnd: float, ebitda: float, nfc: float, liq: int) -> List[Dict]:
    """Four quarters trending toward the latest reported figures (the latest
    period drives the covenant calculation; the earlier ones establish trend)."""
    return [
        {"period": "2024-Q4", "total_net_debt": round(tnd * 0.94, 1), "ebitda": round(ebitda * 1.03, 1),
         "net_finance_charges": round(nfc * 0.90, 2), "available_liquidity": int(liq * 1.45)},
        {"period": "2025-Q1", "total_net_debt": round(tnd * 0.96, 1), "ebitda": round(ebitda * 1.02, 1),
         "net_finance_charges": round(nfc * 0.94, 2), "available_liquidity": int(liq * 1.28)},
        {"period": "2025-Q2", "total_net_debt": round(tnd * 0.98, 1), "ebitda": round(ebitda * 1.01, 1),
         "net_finance_charges": round(nfc * 0.97, 2), "available_liquidity": int(liq * 1.12)},
        {"period": "2025-Q3", "total_net_debt": tnd, "ebitda": ebitda,
         "net_finance_charges": nfc, "available_liquidity": int(liq)},
    ]


# Additional borrowers (beyond the PDF-grounded lead borrower "meridian").
# EBITDA is normalised to 100 so the target ratios are exact:
#   leverage = total_net_debt / ebitda ; interest_cover = ebitda / net_finance_charges.
BORROWERS: Dict[str, Dict] = {
    "alderbrook": {
        "borrower": "ALDERBROOK RETAIL HOLDINGS LTD",
        "facility": "USD 45,000,000 Revolving Credit Facility",
        "clauses": _clauses("alderbrook_credit_agreement.pdf", 3.75, 4.0, 9_000_000),
        "filings": _filings(362.0, 100.0, 22.99, 9_800_000),   # lev 3.62, ic 4.35, liq 9.8M -> watch
        "transactions": [
            {"id": "txn-2201", "date": "2025-08-11", "type": "debt_drawdown", "amount": 4_200_000, "note": "Seasonal inventory financing drawdown"},
            {"id": "txn-2210", "date": "2025-09-02", "type": "capex", "amount": 1_400_000, "note": "Store refurbishment capex"},
            {"id": "txn-2214", "date": "2025-09-20", "type": "unclassified", "amount": 650_000, "note": "Unattributed vendor payment"},
        ],
        "waivers": [],
    },
    "kestrel": {
        "borrower": "KESTREL MANUFACTURING GROUP",
        "facility": "GBP 28,000,000 Term Loan Facility",
        "clauses": _clauses("kestrel_credit_agreement.pdf", 4.0, 3.5, 6_000_000),
        "filings": _filings(428.0, 100.0, 31.75, 6_100_000),   # lev 4.28, ic 3.15, liq 6.1M -> breach
        "transactions": [
            {"id": "txn-3301", "date": "2025-07-22", "type": "debt_drawdown", "amount": 8_500_000, "note": "Emergency working-capital drawdown"},
            {"id": "txn-3305", "date": "2025-08-30", "type": "one_off_cost", "amount": 3_100_000, "note": "Machinery breakdown remediation"},
            {"id": "txn-3308", "date": "2025-09-05", "type": "capex", "amount": 2_100_000, "note": "Replacement press-line capex"},
            {"id": "txn-3312", "date": "2025-09-18", "type": "unclassified", "amount": 1_200_000, "note": "Related-party settlement"},
        ],
        "waivers": [],
    },
    "solent": {
        "borrower": "SOLENT MARINE LOGISTICS PLC",
        "facility": "USD 62,000,000 Senior Secured Facility",
        "clauses": _clauses("solent_credit_agreement.pdf", 4.25, 3.75, 10_000_000),
        "filings": _filings(285.0, 100.0, 18.52, 14_200_000),  # lev 2.85, ic 5.4, liq 14.2M -> within
        "transactions": [
            {"id": "txn-5501", "date": "2025-09-12", "type": "receipt", "amount": 2_600_000, "note": "Charter revenue settlement received"},
        ],
        "waivers": [],
    },
    "northwind": {
        "borrower": "NORTHWIND UTILITIES PLC",
        "facility": "EUR 90,000,000 Term & Revolving Facilities",
        "clauses": _clauses("northwind_credit_agreement.pdf", 4.5, 3.5, 10_000_000),
        "filings": _filings(460.0, 100.0, 25.64, 11_000_000),  # lev 4.6, ic 3.9, liq 11M -> breach (leverage)
        "transactions": [
            {"id": "txn-6601", "date": "2025-08-05", "type": "debt_drawdown", "amount": 12_000_000, "note": "Grid-upgrade capital programme drawdown"},
            {"id": "txn-6605", "date": "2025-09-08", "type": "dividend", "amount": 6_500_000, "note": "Interim dividend to shareholders"},
            {"id": "txn-6612", "date": "2025-09-25", "type": "unclassified", "amount": 1_800_000, "note": "Unreconciled cross-entity transfer"},
        ],
        "waivers": [],
    },
}


def borrower_ids() -> List[str]:
    return list(BORROWERS.keys())


def get_dataset(borrower_id: str) -> Dict:
    return BORROWERS[borrower_id]
