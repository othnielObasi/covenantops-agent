"""Representative financial data (filings + transactions) for CovenantOps Agent.

The credit agreement itself is ingested from a real PDF (see document_ingestion.py);
filings and transactions are representative and stand in for core-banking feeds.
"""
from __future__ import annotations

# --- Borrower filings: the reported financials per quarter (the 'prior filings' to trend) ---
FILINGS = [
    {"period": "2024-Q4", "total_net_debt": 402.0, "ebitda": 124.0, "net_finance_charges": 27.5, "available_liquidity": 14_200_000},
    {"period": "2025-Q1", "total_net_debt": 411.0, "ebitda": 121.0, "net_finance_charges": 28.9, "available_liquidity": 12_600_000},
    {"period": "2025-Q2", "total_net_debt": 418.0, "ebitda": 118.5, "net_finance_charges": 30.1, "available_liquidity": 10_050_000},
    # Latest period: leverage now close to the 3.50x limit, liquidity approaching the floor.
    {"period": "2025-Q3", "total_net_debt": 423.0, "ebitda": 122.4, "net_finance_charges": 31.8, "available_liquidity": 8_900_000},
]

# --- Transaction ledger: recent transactions the agent cross-checks to explain drift ---
TRANSACTIONS = [
    {"id": "txn-4401", "date": "2025-08-04", "type": "debt_drawdown", "amount": 15_000_000, "note": "Drawdown under revolving facility for fleet expansion"},
    {"id": "txn-4402", "date": "2025-08-19", "type": "capex", "amount": 9_500_000, "note": "Acquisition of 40 heavy vehicles"},
    {"id": "txn-4407", "date": "2025-09-02", "type": "one_off_cost", "amount": 6_200_000, "note": "Restructuring charge — depot closure (reduces EBITDA)"},
    {"id": "txn-4411", "date": "2025-09-15", "type": "dividend", "amount": 5_000_000, "note": "Dividend distribution to holdco (reduces liquidity)"},
    {"id": "txn-4415", "date": "2025-09-21", "type": "receipt", "amount": 3_100_000, "note": "Customer settlement received"},
    {"id": "txn-4420", "date": "2025-09-28", "type": "unclassified", "amount": 2_400_000, "note": "Intercompany transfer — purpose not documented"},
]
