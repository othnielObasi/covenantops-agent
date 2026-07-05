# Deploying CovenantOps Agent to Vultr

CovenantOps Agent is a web-based enterprise agent that deploys on **Vultr Cloud
Compute** via Docker Compose. LLM/RAG workloads route to **Vultr Serverless
Inference** (no GPU required — GPUs are not used for this event). If inference is
not configured, the agent runs a deterministic local fallback so the demo never
breaks.

The composed stack is three services:

| Service | Image / build | Port | Purpose |
| --- | --- | --- | --- |
| `web` | `./frontend` (Vite build served by **nginx**) | **80** (public) | Serves the SPA and reverse-proxies `/api` → `api` |
| `api` | `./backend` (FastAPI + Uvicorn) | 8000 (internal only) | Agent workflow, tools, receipts |
| `db`  | `postgres:16` | 5432 (internal only) | Durable TraceMemory (runs + events) |

> **Single public entry point.** Only the `web` service publishes a host port (80).
> nginx serves the built SPA and reverse-proxies `/api` (and `/docs`) to the `api`
> service inside the compose network. The browser is same-origin (no CORS, no
> backend host baked into the build), and the API and database are **not** exposed
> to the internet. All services use `restart: unless-stopped`.
>
> **Single worker by design.** The API runs one Uvicorn worker: signed receipts are
> held in-process between a run and its verification, so multiple workers would not
> share that state. Runs/events are durable in Postgres regardless.
>
> **TLS.** Let's Encrypt needs a domain (not a bare IP). Point a domain at the
> instance and put Caddy or nginx + certbot in front of `web` to terminate HTTPS.

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
2. Open firewall port **80** (HTTP). That is the only public port — the API (8000)
   and database (5432) stay internal to the compose network.
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

# Same-origin via the nginx proxy, so CORS is not needed; set this only if you
# also expose the API on its own origin.
FRONTEND_ORIGIN=http://<instance-ip>
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
| `http://<instance-ip>/` | CovenantOps Agent console |
| `http://<instance-ip>/api/...` | API (reverse-proxied by nginx) |
| `http://<instance-ip>/docs` | API docs |

Verify:

```bash
curl http://<instance-ip>/api/health
# -> {"status":"ok", ... , "vultr_inference_enabled": true, ...}  when a key is set
docker compose ps        # db should be "healthy", api + web "Up"
```

## 5. Vultr Serverless Inference

- **Use the Serverless Inference API key**, created in the portal under Serverless
  Inference — this authenticates at `https://api.vultrinference.com/v1`. It is
  **not** the same as your Vultr **account** API key (`https://api.vultr.com`,
  used to provision resources and often IP-allowlisted).
- Reasoning (drift judgement, cause-attribution narration) →
  `POST /v1/chat/completions` (OpenAI-compatible), model `VULTR_CHAT_MODEL`.
- **Choosing a model:** list your account's catalog with
  `curl -H "Authorization: Bearer <key>" https://api.vultrinference.com/v1/models`.
  Prefer a non-reasoning chat model (e.g. `deepseek-ai/DeepSeek-V4-Flash`,
  `zai-org/GLM-5.2-FP8`) so completions return `content` directly. Reasoning models
  (e.g. Kimi/Qwen/MiniMax) emit `reasoning` tokens and can return empty `content`
  under a small `max_tokens`.
- Document retrieval (real) → the covenant clauses are reranked against the
  investigation query by a **VultronRetriever** model via `POST /v1/rerank`
  (`VULTR_RERANK_MODEL`, default `vultr/VultronRetrieverPrime-Qwen3.5-8B`). These
  are **ReRank** models on the catalog
  (https://huggingface.co/collections/vultr/vultronretriever); a local keyword
  scorer is the fallback. Each run records `retrieval_path` (`vultr` | `local`).
- Clarifying Q&A → `POST /api/covenant/qa` answers a question about a run using the
  chat model, grounded strictly in that run's investigation, and governed on both
  the question and the answer (same guard boundary as every tool call).
- Implementation: `backend/app/trust/vultr_inference.py`. Base URL
  `https://api.vultrinference.com/v1`, auth `Authorization: Bearer <key>`.
- Transparency: `GET /api/integrations/vultr/status` reports whether inference is
  configured and the last path used; each run's memo includes an "Analyst note
  (Vultr inference)" and the Diagnostics audit trail names the retrieval path.

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
  Caddy) in front of `web` (port 80) and terminate HTTPS there.
