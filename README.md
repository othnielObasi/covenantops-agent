# CovenantOps Agent

**A verifiable, document-grounded enterprise agent for loan-covenant monitoring.**

CovenantOps Agent ingests the real document set a credit team works from — a signed credit agreement, waiver letters, management accounts, transaction exports, and even scanned notes — determines whether a borrower is drifting toward breaching its financial covenants, explains *why*, and produces an escalation memo backed by a cryptographically signed receipt that anyone can verify offline.

Built for the RAISE Hackathon 2026 (Vultr Track, Statement Two): a web-based enterprise agent that plans, retrieves more than once, calls deterministic tools, makes decisions, and produces an outcome a real credit team could use.

---

## Table of contents

- [Highlights](#highlights)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Verifying a receipt offline](#verifying-a-receipt-offline)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Vultr alignment](#vultr-alignment)
- [Security notes](#security-notes)
- [Documentation](#documentation)
- [License](#license)

---

## Highlights

- **Multi-format document grounding** — PDF, DOCX, XLSX, CSV, and scanned images (OCR), each tagged with a source-provenance trust level.
- **Verifiable output** — every memo is backed by an Ed25519-signed receipt, verifiable offline with no server and no trusted third party. Tampering is detectable.
- **Governed** — every tool call is evaluated at the tool-agent boundary (AIRG when configured, deterministic local guard otherwise). Prompt injection in low-trust documents is caught before it reaches the agent's reasoning.
- **Context integrity** — freshness, source-authority conflict, and finance-domain checks run before a decision is finalized.
- **Self-improving, safely** — the agent learns to attribute causes across runs; a poisoning gate prevents a blocked or low-confidence run from teaching, and an ablation demonstrates the improvement is real.
- **Resilient** — an interrupted run resumes from a checkpoint without duplicate work.
- **Durable** — runs and trace events persist across restarts (SQLite locally, PostgreSQL in production).
- **Vultr-native** — LLM and RAG workloads route to Vultr Serverless Inference when configured, with a deterministic local fallback and no GPU dependency.

## How it works

Given a borrower and facility, the agent runs a multi-step workflow rather than a single retrieval-and-answer call:

1. **Ingest & plan** — parse the credit agreement and evidence set; tag each document by trust level; scan for injection.
2. **Retrieve clauses** — pull the governing covenant clauses (leverage, interest cover, liquidity).
3. **Retrieve financials** — pull filings to establish the trend.
4. **Recalculate ratios** — deterministically re-verify each ratio from the underlying figures.
5. **Apply waivers** — adjust the effective threshold for any active signed waiver.
6. **Cross-check transactions** — attribute a cause to each flagged movement; surface what cannot be explained.
7. **Check context integrity** — freshness, injection, source-authority conflicts, finance-domain validation.
8. **Generate the memo** — risk level, ratio vs. threshold, headroom, causes, unexplained items, confidence, and recommendations, with citations to source documents.
9. **Sign the receipt** — an Ed25519-signed record of the evidence the memo stands on, verifiable offline.

The confidence score reflects how many flagged transactions were matched to a clear cause versus left unexplained — an honest signal, not a model's self-report.

## Architecture

```
Frontend (React/Vite)  --HTTP /api/*-->  FastAPI backend
                                          |
                                          |  Agent runner:
                                          |    plan -> retrieve -> calculate
                                          |    -> cross-check -> memo
                                          |
                                          |  Tools:  ingestion, extractors,
                                          |          finance calculations
                                          |  Trust:  receipt (Ed25519),
                                          |          governance (AIRG + fallback),
                                          |          context health, recovery,
                                          |          TraceMemory, Vultr inference
                                          |
                                          v
                              PostgreSQL / SQLite  (durable runs + events)
```

External integrations (AIRG governance, Vultr Serverless Inference) are optional and fail safe: if unreachable or unconfigured, the agent continues on a deterministic local path and records which path it used.

## Quick start

### With Docker (recommended)

```bash
cp .env.example .env
docker compose up --build
```

| Service   | URL                          |
| --------- | ---------------------------- |
| Frontend  | http://localhost:3000        |
| API       | http://localhost:8000        |
| API docs  | http://localhost:8000/docs   |

### Without Docker

Backend:

```bash
cd backend
pip install -r requirements.txt
# OCR for scanned documents requires the tesseract binary:
#   Debian/Ubuntu: apt-get install -y tesseract-ocr
#   macOS:         brew install tesseract
uvicorn app.main:app --reload --port 8000
```

Frontend (in a second terminal):

```bash
cd frontend
npm install
npm run dev          # http://localhost:3000, proxies /api to :8000
```

> The Vite dev **and** preview servers proxy `/api` to `VITE_API_TARGET` (default `http://localhost:8000`). In production, serve the frontend and API behind the same origin, or set `VITE_API_TARGET` at build time.

## Configuration

All configuration is via environment variables (see `.env.example`). Everything external is optional — the app runs fully with none of them set.

| Variable | Default | Purpose |
| --- | --- | --- |
| `FRONTEND_ORIGIN` | `http://localhost:3000,http://localhost:5173` | Allowed CORS origins. |
| `COVENANTOPS_AGREEMENT_PDF` | `data/credit_agreement.pdf` | Credit agreement the agent grounds on. |
| `COVENANTOPS_EVIDENCE_DIR` | `data/evidence` | Directory of the multi-format evidence pack. |
| `COVENANTOPS_UPLOAD_DIR` | `data/evidence` | Destination for uploaded documents. |
| `COVENANTOPS_SIGNING_KEY_B64` | *(generated)* | Base64 Ed25519 signing key. **Recommended in production** — see [Security notes](#security-notes). |
| `DATABASE_URL` | `sqlite:///./data/covenantops.db` | TraceMemory persistence; use a PostgreSQL URL in production. |
| `AIRG_URL` | *(unset)* | AIRG governance endpoint. If unset, the local guard is used. |
| `AIRG_API_KEY` | *(unset)* | AIRG API key (`X-API-Key`). |
| `AIRG_TIMEOUT_SECONDS` | `4` | AIRG request timeout; a slow API degrades to the local guard. |
| `VULTR_INFERENCE_API_KEY` | *(unset)* | Vultr Serverless Inference key. If unset, deterministic local reasoning is used. |
| `VULTR_CHAT_MODEL` | `kimi-k2-instruct` | Vultr chat model. |
| `VULTR_TIMEOUT_SECONDS` | `20` | Vultr request timeout. |

## API reference

Base URL: `http://localhost:8000`. Interactive docs at `/docs`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/covenant/run` | Run the agent. Query: `learning` (bool), `attack` (bool), `fail_after` (int). |
| `POST` | `/api/covenant/resume/{task_id}` | Resume an interrupted run from its checkpoint. |
| `GET` | `/api/traces/{trace_id}/receipt` | Signed evidence receipt for a run. |
| `GET` | `/api/traces/{trace_id}/receipt/verify` | Server-side verification of a run's receipt. |
| `POST` | `/api/receipts/verify` | Verify a posted receipt payload (used by the tamper demo). |
| `GET` | `/api/traces/{trace_id}/evaluation` | Self-evaluation scores, evidence map, and context health. |
| `GET` | `/api/traces/{trace_id}/replay` | Replay a run's tool calls, guard decisions, and outcome. |
| `GET` | `/api/trace-events` | Recent persisted TraceMemory events. |
| `POST` | `/api/evidence/upload` | Upload and ingest a document (multipart). |
| `GET` | `/api/evidence` | Ingest and list the evidence pack (format, trust level, injection findings). |
| `GET` | `/api/runs` | List persisted runs. |
| `GET` | `/api/receipts/public-key` | Ed25519 public key for offline verification. |
| `GET` | `/api/integrations/vultr/status` | Whether Vultr Serverless Inference is configured. |
| `GET` | `/api/health` | Liveness, guard path, and integration status. |

## Verifying a receipt offline

Every completed run produces a receipt that can be verified without the server, using only the standalone verifier and the public key embedded in the receipt:

```bash
python3 backend/tools/verify_receipt.py sample-receipts/valid-receipt.json
#   content hash MATCH, Ed25519 signature VALID  -> exit 0

python3 backend/tools/verify_receipt.py sample-receipts/tampered-receipt.json
#   content hash MISMATCH, signature INVALID     -> exit 1
```

The verifier recomputes the SHA-256 over the canonical encoding of the receipt body and checks the Ed25519 signature against the embedded public key. Any change to the memo or evidence invalidates the receipt.

## Testing

```bash
cd backend
python3 -m pytest tests -q      # 14 tests
```

The suite covers document ingestion and threshold extraction, the agent workflow and memo, receipt sign/verify and tamper rejection, governance fail-safe, poisoning-gated self-improvement and its ablation, recovery/resume, multi-format ingestion with trust tagging, waiver application, evaluation/evidence-map generation, context-health checks, and persistent TraceMemory.

## Project layout

```
covenantops-agent/
├── backend/
│   ├── app/
│   │   ├── agent/        # runner (workflow), memo, learning, evaluation
│   │   ├── tools/        # ingestion, extractors/, finance calculations
│   │   ├── trust/        # receipt, governance, context_health, recovery,
│   │   │                 #   trace_memory, vultr_inference
│   │   ├── api.py        # FastAPI routes
│   │   ├── main.py       # app entrypoint
│   │   └── models.py     # schemas
│   ├── data/             # credit agreement + evidence pack
│   ├── tests/            # pytest suite
│   ├── tools/            # standalone offline receipt verifier
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/             # React + Vite + Tailwind
├── docs/                 # BRD, TRD, executive summary, evaluation, demo script
├── sample-receipts/      # valid + tampered receipts for the verify demo
├── docker-compose.yml
└── .env.example
```

## Vultr alignment

The Vultr track requires that LLM workloads run on Vultr Serverless Inference (GPUs are not available for the event). CovenantOps Agent follows this:

- The application deploys on Vultr Compute via Docker Compose.
- LLM reasoning and RAG retrieval route to Vultr Serverless Inference (`https://api.vultrinference.com/v1`, OpenAI-compatible) when `VULTR_INFERENCE_API_KEY` is set.
- If Vultr inference is not configured or is unreachable, the agent uses deterministic local reasoning so the demo remains stable — with no GPU dependency.
- Each run records the inference path (`vultr` or `local_fallback`), and `/api/integrations/vultr/status` surfaces the configuration for transparency.

## Security notes

- **Signing key.** For any real deployment, set `COVENANTOPS_SIGNING_KEY_B64` to a stable key. Without it, a key is generated per instance, so receipts will not verify across restarts or multiple replicas. Generate one with:

  ```bash
  cd backend
  python3 -c "from app.trust.receipt import ReceiptService; print(ReceiptService.generate_key_b64())"
  ```

- **Governance fails safe.** When AIRG is unreachable, the agent falls back to a deterministic local guard that still blocks injection and PII in tool outputs; the guard path is always recorded.
- **Uploaded documents** are filename-sanitized, size-checked, and injection-scanned on ingestion.
- **Representative data.** The included credit agreement and evidence pack are representative and intended for demonstration. Replace them with client-owned documents for production use.

## Documentation

- `docs/CovenantOps-Agent-Executive-Summary.docx` — one-page overview.
- `docs/CovenantOps-Agent-BRD.docx` — business requirements.
- `docs/CovenantOps-Agent-TRD.docx` — technical requirements and architecture.
- `docs/EVALUATION.md` — evaluation framework and judging alignment.
- `docs/DEMO_SCRIPT.md` — one-minute demo script.

## License

Apache-2.0. The representative evidence pack is provided for demonstration and may be replaced with client-owned production documents.
