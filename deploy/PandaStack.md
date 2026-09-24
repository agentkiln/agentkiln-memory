# PandaStack Deployment

PandaStack Apps with Managed PostgreSQL is the deployment target for this branch.

## Why Apps + PostgreSQL

Apps provide a stable public HTTPS URL, and Managed PostgreSQL keeps the database across sleep, wake, and redeploys. Sandboxes are for testing only because their URLs and local files are temporary.

## Database

Create a PostgreSQL 16 database, copy its connection URL, and add `?sslmode=require`.

```env
DATABASE_URL=postgresql://user:password@host:5432/database?sslmode=require
```

The service creates its tables on startup. Keep the database awake settings at auto-suspend to stay within the free credit.

To create the schema manually before first boot:

```powershell
pip install "psycopg[binary]"
$env:DATABASE_URL="postgresql://...?...sslmode=require"
py scripts/init_postgres.py
```

## App

Create an App from the private GitHub repository and select the `master` branch. The deploy workflow below also listens to `master`, so the App and workflow must use the same branch.

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Do not hard-code port 8000; PandaStack injects `$PORT`.

Environment variables:

```env
DATABASE_URL=postgresql://...?...sslmode=require
AML_API_KEY=<long random value>
OPENAI_API_KEY=<runtime credential>
AML_PRODUCTION=1
AML_LLM_MODE=competition
OPENAI_BASE_URL=https://<chat-provider>/v1
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-v4
OPENAI_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_EMBEDDING_API_KEY=<embedding credential>
RERANK_MODEL=qwen3.7-text-rerank
RERANK_BASE_URL=https://<rerank-host>/api/v1/services/rerank/text-rerank/text-rerank
RERANK_API_KEY=<reranker credential>
```

The embedding endpoint reuses `OPENAI_BASE_URL` and `OPENAI_API_KEY` unless you set `OPENAI_EMBEDDING_BASE_URL` and `OPENAI_EMBEDDING_API_KEY`, so chat and embeddings can come from different OpenAI-compatible providers.
Set `OPENAI_BASE_URL` to the actual chat provider used by `OPENAI_API_KEY`. For `RERANK_MODEL=qwen3.7-text-rerank`, set `RERANK_BASE_URL` to the full native endpoint ending in `/api/v1/services/rerank/text-rerank/text-rerank`, including any provider-specific host. The `/compatible-mode/v1` URL is for the embedding service in this example. Set `RERANK_API_KEY` to the credential for the native endpoint.
PandaStack logs include timestamps, model-call start and completion, retries, HTTP status, and safe upstream error identifiers. Request content and upstream error bodies are not written to these logs.
Long Add requests are split across bounded chat annotation and `text-embedding-v4` calls. The original messages are stored whole; larger requests may take longer because they require more upstream calls.
With `AML_PRODUCTION=1`, chat, embedding, and rerank base URLs must all use HTTPS. `DATABASE_URL` must point to Managed PostgreSQL; the app fails startup if it is missing. SQLite remains the local development backend.

## Auto Deploy

This repository has `.github/workflows/deploy-pandastack.yml`, which calls the PandaStack deploy API on every push to `master`. Add a repository secret:

```text
PANDASTACK_API_KEY = pds_...
```

Create that token under PandaStack API Tokens. After that, `git push origin master` triggers a redeploy automatically.

## Verify

```bash
python scripts/ops_contract.py --base-url https://<app-id>.pandastack.ai --api-key "$MEMORY_SYSTEM_KEY"
```

Submit these endpoints:

- `POST https://<app-id>.pandastack.ai/add`
- `POST https://<app-id>.pandastack.ai/search`
- `GET https://<app-id>.pandastack.ai/health`

Keep App auto-hibernate and database auto-suspend enabled on the free tier. Always-on usage can exhaust the monthly credit and pause the service.
