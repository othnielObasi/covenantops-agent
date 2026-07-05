# CovenantOps Agent

A verifiable, document-grounded agent for loan-covenant monitoring. React-free
Vite frontend + FastAPI backend + SQLite (dev) / PostgreSQL (prod).

## Cursor Cloud specific instructions

The update script (run automatically on startup) already installs deps: it creates
the backend virtualenv at `backend/.venv`, installs `backend/requirements.txt`, and
runs `npm install` in `frontend/`. You normally only need to start the services.

### Services
| Service | Dir | Start (dev) | Port |
| --- | --- | --- | --- |
| Backend API (FastAPI) | `backend` | `.venv/bin/uvicorn app.main:app --reload --port 8000` | 8000 |
| Frontend (Vite) | `frontend` | `npm run dev` | 3000 |

- Always run the backend via the venv interpreter: `backend/.venv/bin/uvicorn` /
  `backend/.venv/bin/python` / `backend/.venv/bin/pytest`. The system Python is
  externally managed and has none of the deps.
- The frontend proxies `/api` → `http://localhost:8000` (override with
  `VITE_API_TARGET`). Start the backend before exercising the UI.
- Lint/test/build: backend tests `cd backend && .venv/bin/python -m pytest tests -q`
  (26 tests); frontend production build `cd frontend && npm run build`. There is no
  separate lint step configured.

### Non-obvious notes
- **No secrets required.** Everything external (AIRG governance, Vultr Serverless
  Inference) is optional and fails safe to a deterministic local path. With no env
  vars, `/api/health` reports `local_fallback` / `vultr_inference_enabled:false` —
  that is the expected dev state, not an error.
- **DB is SQLite by default** at `backend/data/covenantops.db` (auto-created, zero
  setup). Only `docker compose` switches it to PostgreSQL.
- **OCR is optional.** `pytesseract` needs the `tesseract` system binary, which is
  not installed; scanned-image evidence (e.g. `Scanned Waiver Note.png`) is skipped
  silently. All other formats and all tests work without it.
- **Frontend is vanilla JS**, not React. The whole UI lives in
  `frontend/index.html` (styles + shell) and `frontend/src/main.js` (rendering +
  the `api` fetch layer). There is no JSX/Tailwind toolchain.
- **Receipt verification gotcha:** the honest "Verify this receipt" path must use
  the server-side endpoint `GET /api/traces/{id}/receipt/verify`. Round-tripping a
  signed receipt through the browser's `JSON.stringify` reserializes whole-number
  floats (`8000000.0 → 8000000`) and breaks the canonical Ed25519 hash, giving a
  false "invalid". The tamper demo intentionally mutates-and-POSTs to `/api/receipts/verify`.
- Signing key is per-instance unless `COVENANTOPS_SIGNING_KEY_B64` is set, so
  receipts do not verify across backend restarts. Verify within the same run of the
  server.

### Deployment (Docker Compose → Vultr)
- `docker compose up --build` runs the deployable stack: `web` (Vite preview,
  proxies `/api` → `api`), `api` (FastAPI), `db` (Postgres 16, named volume). This
  is the exact Vultr Compute deployment; see `docs/DEPLOY_VULTR.md`.
- Docker is **not** installed by the update script. To test compose in a Cloud VM,
  install Docker first (docker-in-docker: `fuse-overlayfs` storage driver +
  `iptables-legacy`; for Docker 29 also set `features.containerd-snapshotter:false`
  in `/etc/docker/daemon.json`).
- The `web` container serves via `vite preview` (not a bare static server) **so
  that `/api` is proxied**; a plain static `serve` would 404 on `/api`.
- Postgres persistence needs `psycopg2-binary` (in `backend/requirements.txt`);
  without it TraceMemory silently falls back to in-memory and `/api/runs` reports
  `persistent:false`.
- The compose stack binds host ports 3000/8000; stop the local dev servers first
  to avoid port conflicts.

### External integrations (AIRG + Vultr) — keys go in `.env` (untracked)
- `AIRG_URL` + `AIRG_API_KEY` enable the hosted governance path (`guard_path:airg`);
  without both, the deterministic local guard is used. Note the AIRG account may
  default-allow, so the injection demo only blocks under the local guard.
- Vultr Serverless Inference needs the **inference** key (authenticates at
  `api.vultrinference.com`), which is different from the Vultr **account** API key
  (`api.vultr.com`, IP-allowlisted). Set `VULTR_INFERENCE_API_KEY` +
  `VULTR_CHAT_MODEL`. Pick a **non-reasoning** model (e.g.
  `deepseek-ai/DeepSeek-V4-Flash`) — reasoning models (Kimi/Qwen/MiniMax) put output
  in a `reasoning` field and return empty `content` under small `max_tokens`, so the
  memo's "Analyst note (Vultr inference)" comes back blank. List models via
  `GET https://api.vultrinference.com/v1/models`.
