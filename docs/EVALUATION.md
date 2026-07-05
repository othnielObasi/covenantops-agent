# CovenantOps Agent Evaluation Framework

CovenantOps Agent is evaluated against the hackathon judging criteria and enterprise-agent quality gates. The goal is to prove CovenantOps Agent is not a single retrieve-then-answer RAG call, but a real document-grounded workflow agent whose every decision is verifiable.

## Hackathon judging alignment

| Category | Weight | CovenantOps Agent evidence |
|---|---:|---|
| Impact | 25% | Finance covenant monitoring matches Statement Two directly and is useful to banks, private-credit funds, and portfolio-monitoring teams. |
| Demo | 50% | Browser flow shows multi-format ingestion, planning, repeated retrieval, tool calls, context-integrity checks, memo generation, self-improvement, and offline receipt verification. |
| Creativity | 15% | Signed offline-verifiable receipts + AIRG governance + poisoning-gated self-improvement make every memo auditable, tamper-evident, and improving. |
| Pitch | 10% | Demo-led one-minute flow: ingest → investigate → decide → verify. |

## Self-evaluation dashboard

Every `/api/covenant/run` returns an `evaluation` object (also at `/api/traces/{id}/evaluation`) with quality-gate scores derived from the actual run — not hard-coded:

| Score | Measures | Target |
|---|---|---:|
| Agentic workflow | Planning, repeated retrieval, tool calls, enterprise outcome | >= 90 |
| Document grounding | Citation count, source diversity, source trust | >= 85 |
| Calculation correctness | Deterministic covenant calculation | 100 |
| Transaction cause matching | Explained vs unexplained transaction causes | >= 75 |
| Context health | Freshness, injection, poisoning, domain validation | >= 80 |
| TraceMemory reliability | Steps, tool calls, checkpoints, learning-gate events | >= 90 |
| Verifiability | Receipt creation, signing, offline verification, tamper detection | 100 |
| Enterprise usefulness | Risk level, recommendation, memo completeness | >= 90 |
| Security hardening | Injection blocked, guard path, governance | >= 85 |
| Demo readiness | Docker path, ingestion, run, memo, receipt verify | >= 90 |

The weighted `hackathon_readiness_score` maps these to the judging weights above.

## Evidence map

Each run returns an `evidence_map` linking the final decision to: the governing covenant clause, latest financial values, deterministic calculation, historical trend, transaction-cause matching, waiver/amendment status, the context-integrity guard, and the signed receipt.

## What makes CovenantOps Agent stand out (beyond a strong RAG agent)

- **Multi-format grounding** across PDF, DOCX, XLSX, CSV, and scanned images (OCR), each weighted by source trust.
- **Offline-verifiable receipts** — verify a memo on your own laptop, no server, no blockchain.
- **AIRG governance** at the tool↔agent boundary, with a fail-safe local guard.
- **Poisoning-gated self-improvement** — the agent learns across runs, but a blocked/low-confidence run cannot teach; an ablation proves the gain is real.
- **Recovery** — an interrupted run resumes without duplicate work.

## Verifiability

```bash
python3 backend/tools/verify_receipt.py sample-receipts/valid-receipt.json
python3 backend/tools/verify_receipt.py sample-receipts/tampered-receipt.json
```

The valid receipt passes; the tampered receipt fails.
