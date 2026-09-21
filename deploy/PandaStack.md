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

Create an App from the private GitHub repository and select the `PandaStack` branch.

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
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-v4
```

The embedding endpoint reuses `OPENAI_BASE_URL` and `OPENAI_API_KEY` unless you set `OPENAI_EMBEDDING_BASE_URL` and `OPENAI_EMBEDDING_API_KEY`, so chat and embeddings can come from different OpenAI-compatible providers.

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
