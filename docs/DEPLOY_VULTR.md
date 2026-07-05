# Deploying CovenantOps Agent to Vultr

CovenantOps Agent is a web-based enterprise agent that deploys on **Vultr Cloud
Compute** via Docker Compose. LLM/RAG workloads route to **Vultr Serverless
Inference** (no GPU required — GPUs are not used for this event). If inference is
not configured, the agent runs a deterministic local fallback so the demo never
breaks.

The composed stack is three services:

| Service | Image / build | Port | Purpose |
| --- | --- | --- | --- |
| `web` | `./frontend` (Vite build, served by `vite preview`) | 3000 | UI; proxies `/api` to `api` (same-origin, no CORS) |
| `api` | `./backend` (FastAPI + Uvicorn) | 8000 | Agent workflow, tools, receipts |
| `db`  | `postgres:16` | 5432 | Durable TraceMemory (runs + events) |

> The `web` container runs the Vite **preview** server, which applies the
> `/api → VITE_API_TARGET` proxy from `frontend/vite.config.js`. This keeps the
> browser same-origin with the frontend, so no backend host is baked into the
> build and there is no CORS to configure.

---

## 1. Prerequisites

- A **Vultr** account.
- A **Vultr Serverless Inference** API key (Products → Serverless Inference →
  API Keys). See https://docs.vultr.com/products/compute/serverless-inference .
- (Optional) A stable Ed25519 signing key so receipts verify across restarts /
  replicas.

## 2. Provision a Vultr Compute instance

1. In the Vultr portal, deploy a **Cloud Compute** instance:
   - OS: **Ubuntu 24.04 LTS**
   - Plan: any 2 vCPU / 4 GB (or larger) — **no GPU needed**.
2. Open firewall ports **3000** (UI) and, if you want the API reachable directly,
   **8000**. For a single-origin deployment only **3000** is required.
3. SSH into the instance and install Docker + the Compose plugin:

   ```bash
   curl -fsSL https://get.docker.com | sh
   ```

## 3. Get the code and configure

```bash
git clone <your-fork-url> covenantops-agent
cd covenantops-agent
cp .env.example .env
```

Edit `.env`:

```dotenv
# Route ALL LLM/RAG workloads to Vultr Serverless Inference (Vultr track requirement)
VULTR_INFERENCE_API_KEY=<your-vultr-serverless-inference-key>
# Reasoning model served by Vultr Serverless Inference
VULTR_CHAT_MODEL=kimi-k2-instruct
# For document grounding / retrieval, use a VultronRetriever model via Serverless
# Inference: https://huggingface.co/collections/vultr/vultronretriever

# Stable receipt signing key (so receipts verify across restarts/replicas).
# Generate one with:
#   docker compose run --rm api python -c \
#     "from app.trust.receipt import ReceiptService; print(ReceiptService.generate_key_b64())"
COVENANTOPS_SIGNING_KEY_B64=<base64-ed25519-key>

# Allow the browser origin (public IP or domain) for CORS if you expose the API directly
FRONTEND_ORIGIN=http://<instance-ip>:3000
```

> Everything under Vultr Serverless Inference and AIRG governance is **optional and
> fail-safe** — with no keys the agent still runs, on a deterministic local path,
> and each run records which path it used (`/api/integrations/vultr/status`).

## 4. Launch

```bash
docker compose up --build -d
```

| URL | What |
| --- | --- |
| `http://<instance-ip>:3000` | CovenantOps Agent console |
| `http://<instance-ip>:8000/docs` | API docs (if port 8000 is open) |

Verify:

```bash
curl http://<instance-ip>:3000/api/health
# -> {"status":"ok", ... , "vultr_inference_enabled": true, ...}  when a key is set
docker compose ps        # db should be "healthy", api + web "Up"
```

## 5. Vultr Serverless Inference

- Reasoning (drift judgement, cause-attribution narration) →
  `POST /v1/chat/completions` (OpenAI-compatible), model `VULTR_CHAT_MODEL`.
- Document grounding / RAG → Vultr vector store + `POST /v1/chat/completions/RAG`.
  Use a **VultronRetriever** model
  (https://huggingface.co/collections/vultr/vultronretriever) for retrieval.
- Implementation: `backend/app/trust/vultr_inference.py`. Base URL
  `https://api.vultrinference.com/v1`, auth `Authorization: Bearer <key>`.
- Transparency: `GET /api/integrations/vultr/status` reports whether inference is
  configured and which path (`vultr` vs `local_fallback`) was last used.

## 6. Persistence & durability

- The `db` service uses a named volume (`covenantops_pgdata`); runs and trace
  events survive container/instance restarts. `GET /api/runs` reports
  `"persistent": true` when Postgres is reachable (the `api` service waits for the
  db healthcheck before starting).
- With a fixed `COVENANTOPS_SIGNING_KEY_B64`, signed receipts remain verifiable
  across restarts and multiple replicas.

## 7. Updating a running deployment

```bash
git pull
docker compose up --build -d
```

## Notes

- No GPU is required or used; all LLM workloads go through Vultr Serverless
  Inference.
- To put the whole app behind a single port / TLS, place a reverse proxy (nginx,
  Caddy) in front of `web:3000` and terminate HTTPS there.
