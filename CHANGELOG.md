# Changelog

## Unreleased

- Fixed cross-user memory ID collisions for identifier values containing separators in both storage backends.
- Rejected invalid timestamps and malformed or non-finite embedding vectors before storage.
- Kept untimed corrections searchable and restored single-character CJK retrieval, including older SQLite indexes.
- Required HTTPS for all production model endpoints, stopped forwarding model credentials on redirects, and removed upstream error bodies from API errors.
- Required a PostgreSQL `DATABASE_URL` in production so a missing setting cannot select local SQLite.
- Split embedding calls into batches of at most 10 and validate response indexes and dimensions.
- Use the native `qwen3.7-text-rerank` API and cap each request at 500 rule-ranked candidates.
- Apply rerank scores to Search evidence order, retry failed reranks, and keep temporal queries on time-aware ranking.
- Add model-call timestamps and diagnostic logs without writing upstream response bodies into persistent logs.
- Keep packed evidence IDs tied to a source in the returned window.
- Rebalanced ranking weights toward temporal signals and added correction-based suppression of superseded memories.
- Included the rerank configuration in the Search cache key.
- Added the optional reranker with `RERANK_MODEL`, `RERANK_BASE_URL`, and `RERANK_API_KEY`; rerank failures fall back to rule-based ranking.
- Added the PostgreSQL backend with GIN full-text indexes and CJK substring search.
- Added the PandaStack deployment guide with Managed PostgreSQL.
- Added the technical report, centered logo, English and Chinese README, CI and deployment badges.
- Removed the invalid job-level `secrets` condition from the deploy workflow.

## 1.0.0 - initial release

- Added the FastAPI Add/Search service.
- Added SQLite persistence, FTS5 retrieval, vector storage, RRF fusion, and source-window packing.
- Added strict user isolation, request idempotency, payload conflict detection, and API-key auth.
- Added Docker, Compose, Caddy, contract-check, smoke, and recovery deployment assets.
- Added public submission, disclosure, and security documents.
