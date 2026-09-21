# Build Status

Updated: 2026-09-21.

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
| Add/Search API | Complete | Synchronous contracts, aliases, validation, idempotency, and conflict handling. |
| Input bounds | Complete | Identifier fields reject values longer than 512 characters. |
| Batch bounds | Complete | Add rejects batches larger than 200 messages. |
| User isolation | Complete | Exact `user_id` filtering for lexical, vector, and neighbor retrieval. |
| Persistence | Complete | SQLite WAL storage with request deduplication and restart tests. |
| Retry efficiency | Complete | Identical Add retries return before model or embedding calls. |
| Add atomicity | Covered | Failed writes leave no partial message rows searchable. |
| Lexical retrieval | Complete | FTS5 with English stemming, CJK n-grams, and phrase scoring. |
| CJK candidate filtering | Complete | Two-character CJK terms participate in cross-modal candidate checks. |
| Vector retrieval | Complete | Local mock and runtime-provider modes; RRF fusion with lexical candidates. |
| Vector abstention | Complete | Stricter similarity threshold when lexical retrieval has no matches. |
| Provider resilience | Complete | Bounded retries honor Retry-After for transient model/network failures. |
| Load control | Complete | Add and Search concurrency are bounded in process and configurable for capacity. |
| Evidence output | Complete | Token-bounded, source-deduplicated conversation windows with timestamps. |
| Long-source packing | Complete | A single oversized source is truncated within budget instead of dropped. |
| Output robustness | Complete | Unknown packed source IDs are skipped instead of failing the request. |
| Token budgeting | Complete | CJK characters are counted separately to avoid under-budgeting Chinese evidence. |
| Concurrent chunk order | Complete | Source windows use chunk index, timestamp, and ordinal together. |
| Multi-hop evidence | Covered | Relation-end tests verify complementary evidence survives packing. |
| Cache integrity | Complete | Search cache keys include the full retrieval configuration. |
| Temporal intent | Complete | Latest/earliest scoring and correction-aware selection. |
| Offline evaluation | Complete | JSONL retrieval panel reports hit rate and latency. |
| Docker deployment | Complete | Dockerfile, Compose file, persistent volume, health check, and non-root user. |
| Production guard | Complete | Production startup requires competition mode, strong API-key auth, model credentials, and an HTTPS model endpoint. |
| HTTPS edge | Complete | Caddy example for a public TLS endpoint. |
| Contract verification | Complete | Public smoke and operational contract checks. |
| Release verification | Complete | Checks deadlines, clean commit, public HTTPS URLs, and required submission material. |
| URL safety | Complete | Release checks reject credentials, loopback, link-local, and private IPv4 endpoints. |
| Recovery verification | Complete | Restart script verifies committed evidence is searchable again. |
| Privacy scan | Complete | CI blocks tracked databases, keys, tokens, credentials, and logs. |
| Formal model verification | Not run | Requires a runtime credential and paid model access. |
| Public deployment | Not run | Requires a public host and DNS. |
| Platform Smoke | Not run | Requires a evaluation API key. |
| Full evaluation | Not run | Requires an accepted deployed endpoint and available quota. |
| Official score | Not available | No official result exists yet. |

## What remains

The remaining work is operational rather than architectural:

1. Publish this repository to a public GitHub repository.
2. Deploy the `1.0.0` image to a public HTTPS host with a persistent volume.
3. Configure `AML_API_KEY`, `OPENAI_API_KEY`, `gpt-4o-mini`, and `text-embedding-v4`.
4. Run the contract, smoke, concurrency, and recovery checks against the deployed endpoint.
5. Submit the live Add/Search URLs and repository commit for organizer review.
6. Run the platform Smoke, then reserve the Full attempt for the frozen version.

Do not enter an official score until the organizer publishes a real evaluation result.
