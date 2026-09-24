# Security and Data Handling

- Never commit `.env`, API keys, or system credentials.
- Health is public. Add and Search can require Bearer, Token, or `X-Api-Key` authentication.
- Retrieval is scoped to the exact `user_id` supplied in each request.
- The service does not log request bodies or model credentials.
- Production requires HTTPS chat, embedding, and rerank endpoints. Model Authorization headers do not follow redirects.
- Production requires a PostgreSQL `DATABASE_URL`; a missing URL cannot silently select local SQLite.
- Upstream error bodies are excluded from service error responses; only HTTP status and bounded error identifiers are returned.
- Delete the configured SQLite database or Docker volume after evaluation or testing runs complete.
- Revoke any accidentally exposed credential before opening a sanitized private report.
