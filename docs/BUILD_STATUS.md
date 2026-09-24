# Build Status

Updated: 2026-09-24.

## Public timeline check

The linked competition page states:

- Evaluation access opened on 2026-09-20 at 00:00 UTC+8.
- Materials close on 2026-10-31 at 23:59 UTC+8.
- Evaluation stops on 2026-11-04 at 23:59 UTC+8.
- The official leaderboard is planned for mid-November 2026.

## Build progress

| Area | Status | Notes |
|---|---|---|
| Repository | Complete | AgentKiln Memory project sources and deployment files. |
| Database backends | Complete | SQLite for local development; PostgreSQL for PandaStack production. |
| PostgreSQL schema | Complete | `scripts/init_postgres.py` creates tables with GIN full-text indexes. |
| PostgreSQL CJK search | Complete | Untokenized CJK text falls back to substring matching; ASCII keeps tsquery. |
| PostgreSQL verification | Complete | `scripts/verify_postgres.py` ran Add/Search and CJK retrieval against PandaStack PostgreSQL. |
| PandaStack deployment | Prepared | App start command uses `$PORT`; see `deploy/PandaStack.md`. |
| Add/Search API | Complete | Synchronous contracts, aliases, validation, idempotency, and conflict handling. |
| Request validation | Complete | Required fields, field types, nonempty messages and query, roles, timestamps, and `top_k` are validated; indexed `request_id` and `user_id` are capped at 512 characters. Query and options lengths and Add message count have no application-level maximum. |
| Long-query handling | Complete | Search accepts long queries; lexical retrieval selects terms across the full query and chunked `text-embedding-v4` processes every chunk, while chat analysis and reranking use a configurable beginning-and-end excerpt. |
| User isolation | Complete | Exact `user_id` filtering for lexical, vector, and neighbor retrieval. |
| Persistence | Complete | SQLite WAL storage with request deduplication and restart tests. |
| Retry efficiency | Complete | Identical Add retries return before model or embedding calls. |
| Add atomicity | Covered | Failed writes leave no partial message rows searchable. |
| Lexical retrieval | Complete | FTS5 with English stemming, CJK n-grams, and phrase scoring. |
| Option handling | Complete | Options influence ranking but do not contaminate candidate retrieval. |
| CJK candidate filtering | Complete | Two-character CJK terms participate in cross-modal candidate checks. |
| Vector retrieval | Complete | Local mock and runtime-provider modes; RRF fusion with lexical candidates. |
| Vector indexing | Complete | Embedding filters use a user, model, and dimension index. |
| Vector abstention | Complete | Stricter similarity threshold when lexical retrieval has no matches. |
| Provider resilience | Complete | Bounded retries honor Retry-After for transient model/network failures. |
| Embedding validation | Complete | Provider responses with mixed or empty vector dimensions fail closed. |
| Load control | Complete | Add and Search concurrency are bounded in process and configurable for capacity. |
| Evidence output | Complete | Token-bounded, source-deduplicated conversation windows with timestamps. |
| Score contract | Covered | Returned scores are bounded to 0-1 and sorted descending. |
| Long-source packing | Complete | A single oversized source is truncated within budget instead of dropped. |
| CJK packing | Covered | Oversized CJK evidence is truncated within its budget. |
| Output robustness | Complete | Unknown packed source IDs are skipped instead of failing the request. |
| Anchor integrity | Complete | Packed windows never return an anchor ID that is absent from their content. |
| Neighbor retention | Complete | Unique neighbor evidence is kept even when its anchor was already returned. |
| Token budgeting | Complete | CJK characters are counted separately to avoid under-budgeting Chinese evidence. |
| Concurrent chunk order | Complete | Source windows use chunk index, timestamp, and ordinal together. |
| Chunk ordering | Complete | Chunk index sorts before timestamps so concurrent chunks keep source order. |
| Multi-hop evidence | Covered | Relation-end tests verify complementary evidence survives packing. |
| Cache integrity | Complete | Search cache keys include the full retrieval configuration. |
| Temporal intent | Complete | Latest/earliest scoring and correction-aware selection. |
| Marker matching | Complete | English temporal and update markers require word boundaries, avoiding substring false positives. |
| Offline evaluation | Complete | JSONL retrieval panel reports hit rate and latency. |
| Evidence matching | Complete | Offline evaluation accepts evidence IDs or evidence text. |
| Docker deployment | Complete | Dockerfile, Compose file, persistent volume, health check, and non-root user. |
| Production guard | Complete | Production startup requires competition mode, strong API-key auth, model credentials, and an HTTPS model endpoint. |
| HTTPS edge | Complete | Caddy example for a public TLS endpoint. |
| Contract verification | Complete | Public smoke and operational contract checks. |
| Release verification | Complete | Checks deadlines, clean commit, public HTTPS URLs, and required submission material. |
| URL safety | Complete | Release checks reject credentials, loopback, link-local, and private IPv4 endpoints. |
| Recovery verification | Complete | Restart script verifies committed evidence is searchable again. |
| Privacy scan | Complete | CI blocks tracked databases, keys, tokens, credentials, and logs. |
| Formal model verification | Prior deployment | Chat and embedding calls were verified on PandaStack before the current code changes; the updated rerank integration still needs remote verification. |
| Public deployment | Prior deployment | PandaStack Apps with Managed PostgreSQL and public HTTPS endpoints were verified before the current code changes. |
| Platform Smoke | Not run | Requires an evaluation API key. |
| Full evaluation | Not run | Requires an accepted deployed endpoint and available quota. |
| Official score | Not available | No official result exists yet. |

## What remains

The remaining work is deployment and official evaluation:

1. Publish this repository to a public GitHub repository.
2. Deploy the updated image to a public HTTPS host with a persistent volume.
3. Configure `AML_API_KEY`, model credentials, and embedding/rerank endpoints.
4. Run the contract, smoke, concurrency, and recovery checks against the deployed endpoint.
5. Submit the live Add/Search URLs and repository commit for review.
6. Run the platform Smoke, then reserve the Full attempt for the frozen version.

Do not publish benchmark claims until a real evaluation result exists.
