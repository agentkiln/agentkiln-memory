# AgentKiln Memory Technical Report

## 1. Overview

AgentKiln Memory is an evidence-only long-term memory service for AI agents. It stores agent conversation turns under strict per-user isolation, indexes them with a hybrid lexical and vector pipeline, and returns verbatim source evidence ranked by relevance. The system never generates final answers; the downstream agent sees exactly what the memory layer retrieved.

The system follows a public synchronous Add/Search contract. The same guarantees apply in production: idempotent writes, conflict detection, token-bounded output, and fail-closed behavior when required model credentials are absent.

## 2. Design Decisions

### 2.1 Evidence-only retrieval

Most memory systems conflate retrieval with generation: they return synthesized answers. This makes it impossible to audit what the agent actually remembered and hides retrieval failures behind fluent text. AgentKiln Memory separates the two concerns completely. Search returns source messages wrapped in session-window headers, so the retrieval layer is independently auditable, testable, and composable with any downstream generation model.

### 2.2 Hybrid lexical and vector retrieval

Vector-only retrieval misses exact terms, names, dates, and code identifiers. Lexical-only retrieval misses paraphrases and semantic matches. Neither channel is sufficient alone. The system runs both in parallel and fuses candidates with reciprocal rank fusion, then applies a lexical-overlap filter to suppress weak vector matches.

### 2.3 Session-window expansion

A single message rarely carries enough context. When a candidate matches, the system expands to include adjacent turns in the same session, ordered by a source-order key that combines chunk index, timestamp, and ordinal. This restores multi-message conversation windows without requiring the evaluator to send full conversations in a single Add call.

### 2.4 CJK-native tokenization

Unicode normalization (NFKC), Porter stemming for English, and character n-gram tokenization for Chinese work out of the box. Chinese text is tokenized into overlapping 2-grams and 3-grams; English text uses word-boundary regex with suffix stripping. Stopword lists cover both languages. Token estimation counts CJK characters individually to avoid under-budgeting Chinese evidence.

### 2.5 Deterministic ranking with optional rerank

The default ranking model combines six weighted signals: term coverage, RRF order, expanded-term coverage, option matches, phrase bonuses, and temporal intent. All signals are deterministic and testable. For queries without temporal intent, a configured external reranker orders the final evidence; when it is unavailable, Search uses rule-based ranking and retries the reranker on the next request. Earliest and latest queries keep time-aware rule ranking so historical evidence is retained.

## 3. Architecture

```
                    +---------------------+
                    |   FastAPI Service   |
                    |  /add  /search /v1  |
                    +----------+----------+
                               |
                 +-------------+-------------+
                 |                           |
           +-----v------+             +------v------+
           | MemoryLLM  |             | MemoryService|
           | embeddings |             |  isolation   |
           | annotation |             |  caching     |
           | query plan |             +------+------+
           |  rerank    |                    |
           +-----+------+                    |
                 |                           |
       +---------v----------+     +----------v-----------+
       | Embedding Provider |     |    MemoryDatabase    |
       |   Rerank Provider  |     | PostgreSQL / SQLite  |
       +--------------------+     +----------+-----------+
                                                |
                                    +----------v-----------+
                                    |   Retrieval Layer    |
                                    |  FTS5 lexical search |
                                    |  Vector similarity   |
                                    |  RRF fusion          |
                                    |  Window expansion    |
                                    |  Temporal ranking    |
                                    +----------------------+
```

### 3.1 Components

| Component | Responsibility |
|-----------|----------------|
| `app/main.py` | FastAPI entry point, authentication, route registration |
| `app/config.py` | Environment-driven settings with fail-closed production validation |
| `app/service.py` | Retrieval pipeline orchestration, user isolation, caching |
| `app/llm.py` | Embedding, annotation, query planning, and rerank calls with bounded retries |
| `app/text.py` | Tokenization, normalization, concept expansion, temporal markers, token estimation |
| `app/db.py` | SQLite storage, FTS5 indexing, schema migration |
| `app/postgres_db.py` | PostgreSQL storage backend with GIN full-text indexes |
| `app/pack.py` | Token-bounded evidence window packing |
| `app/schemas.py` | Pydantic request and response models |

### 3.2 Storage backends

The SQLite backend uses WAL journaling, a 60-second busy timeout, and FTS5 with `porter unicode61 remove_diacritics 2` tokenization. The PostgreSQL backend uses GIN full-text indexes with substring fallback for untokenized CJK text. Both backends implement identical interfaces; the database URL selects the backend at startup.

## 4. Retrieval Pipeline

### 4.1 Add path

1. Validate required fields, a nonempty message list, supported roles, and Unix-millisecond timestamps within years 1-9999. `request_id` and `user_id` are capped at 512 characters to limit PostgreSQL index key size; `session_id` and message count have no application-level maximum.
2. Check `request_id` status: new, existing (skip model calls), or conflict (HTTP 409).
3. Annotate messages with an LLM call that extracts retrieval cues from the transcript.
4. Embed message contents through the configured embedding provider in batches of at most 10, then check each batch's indexes, vector finiteness, and the combined dimensions.
5. Persist messages, annotations, vectors, and FTS index entries in a single transaction. A failed write leaves no partial rows searchable.

### 4.2 Search path

1. **Query analysis**: long queries are accepted. Chat analysis and reranking use a beginning-and-end excerpt of 16,000 characters by default; `AML_QUERY_MODEL_MAX_CHARS` can raise this without a code-level ceiling. An LLM call extracts retrieval cues, facets, and temporal intent. In `off` or `dev_mock` modes, lexical features alone drive retrieval.
2. **Lexical search**: up to 160 selected terms from across the full query drive FTS5 or PostgreSQL full-text search, retrieving up to `AML_CANDIDATE_LIMIT` candidates using BM25 ranking. This bound limits database query size while prioritizing the final question and distinctive terms from other positions. Single-character CJK queries remain searchable; SQLite also checks older source text within the same user when its previous index lacks the character.
3. **Vector search**: the full query is embedded in chunks for `text-embedding-v4` and compared against stored vectors using cosine similarity. Vectors are filtered by exact user, embedding model, and dimension.
4. **Event-day lookup and fusion**: only a query that clearly asks about events on one unambiguous calendar day adds a lookup against source `timestamp` metadata. Both backends use their existing `(user_id, occurred_at, ordinal)` index and a half-open UTC day range. Dates in project or ticket names, due dates, and deadlines do not trigger this lookup. Date candidates join lexical and vector candidates in `1 / (60 + rank)` fusion; a lexical-overlap filter still suppresses weak vector-only candidates. A same-day timestamp boosts ranking rather than excluding all other evidence. If no timestamped source falls on that day, Search keeps ordinary reranking available.
5. **Window expansion**: matched candidates expand to adjacent turns in the same session using source-order keys. The service fetches output windows for at most `min(top_k, AML_MAX_OUTPUT_ITEMS)` anchors, so a request for one result does not load windows for one hundred.
6. **Ranking and selection**: a weighted combination of term coverage (0.40), fused-rank order (0.16), expanded coverage (0.12), option matches (0.10), phrase bonus (0.06), and temporal intent (up to 0.16) produces the rule order. For non-temporal queries without matching event-day timestamp evidence, a successful reranker call supplies the final ordering scores. The `qwen3.7-text-rerank` call takes at most 500 top rule-ranked candidates; any remainder stays after them in rule order. A later correction may suppress a related older single fact, but an independent clause in the older source remains eligible when relevant to the query. For explicit global summaries, selection retains the top result and favors distinct sessions only among candidates close to the original relevance cutoff, then preserves their score order. Ordinary fact, multi-hop, earliest, and latest queries keep their existing selection order.
7. **Packing**: evidence windows are packed into a token budget with source deduplication. A returned source ID identifies a source included in its evidence window; unknown packed source IDs are skipped rather than failing the request.

### 4.3 Token budgeting

The output budget defaults to approximately 32,000 tokens with a maximum of 100 windows, also bounded by the requested `top_k`. This is a character-based estimate: CJK characters count as one token each and other characters as one quarter token. A single oversized source is truncated within budget rather than dropped, preserving partial evidence for the downstream agent.

## 5. Integrity Guarantees

### 5.1 User isolation

Every memory, FTS index entry, vector, cache key, and neighbor query is scoped to the exact `user_id`. Cross-user access returns an empty result, never an error, so isolation failures do not leak information.

### 5.2 Idempotent Add

The same `request_id` with the same payload is safe to retry. The system detects duplicate requests by payload hash and returns the original response without calling model endpoints. A different payload with the same `request_id` returns HTTP 409. Memory IDs hash an unambiguous tuple of user, request, and message position.

### 5.3 Fail-closed production

Production mode requires `AML_LLM_MODE=competition`, a strong `AML_API_KEY` (minimum 16 characters), an `OPENAI_API_KEY`, HTTPS for all chat, embedding, and rerank endpoints, and a PostgreSQL `DATABASE_URL`. Missing embedding credentials do not silently degrade to mock vectors. Model Authorization headers do not follow redirects.

### 5.4 Provider resilience

Upstream model calls use bounded retries with exponential backoff and `Retry-After` header respect. HTTP errors expose status and safe diagnostic identifiers without returning the upstream response body. Rerank failures degrade to rule-based ranking rather than failing the Search request.

### 5.5 No benchmark hard-coding

The system contains no benchmark answers, dataset-specific mappings, prompt injection, or human-in-the-loop answering path. All retrieval is data-driven.

## 6. Concurrency Model

Add and Search concurrency are bounded by in-process semaphores, configurable through `AML_ADD_CONCURRENCY` and `AML_SEARCH_CONCURRENCY`. Search results are cached by a key that includes the full retrieval configuration, so identical queries within the same revision hit the cache without repeating model calls. Cache entries are invalidated by user revision, which increments on every successful Add.

## 7. Evaluation

### 7.1 Test coverage

Unit and integration tests cover API contract validation, user isolation, idempotent Add, payload conflict detection, persistence across restarts, concurrent operations, temporal retrieval, CJK tokenization, provider resilience, rerank ordering, and packing robustness.

### 7.2 Offline evaluation

The `eval/retrieval.py` module evaluates retrieval quality against JSONL panels containing memories, questions, and optional evidence annotations. Metrics include hit rate at K and measured Search latency. This enables parameter tuning before committing to a formal evaluation run.

### 7.3 Measured performance

Local end-to-end verification with 24 concurrent synchronous Add calls completed in approximately 0.35 seconds, with a measured Search latency of approximately 0.110 seconds in `dev_mock` mode. Production Search latency with live embedding and rerank calls was approximately 4-6 seconds in an earlier deployment; the current code has not been tested remotely.

## 8. Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `AML_DATABASE_PATH` | `data/memory.db` | SQLite database path |
| `DATABASE_URL` | empty | PostgreSQL URL; when set, PostgreSQL backend is used |
| `AML_PRODUCTION` | empty | Set to `1` to require competition mode and API-key auth |
| `AML_LLM_MODE` | `off` | `off`, `dev_mock`, or `competition` |
| `AML_API_KEY` | empty | Optional Add/Search authentication |
| `OPENAI_API_KEY` | empty | Runtime model credential |
| `OPENAI_MODEL` | `gpt-4o-mini` | Add/Search LLM model |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-v4` | Embedding model |
| `OPENAI_EMBEDDING_BASE_URL` | falls back to `OPENAI_BASE_URL` | Optional separate embedding endpoint |
| `OPENAI_EMBEDDING_API_KEY` | falls back to `OPENAI_API_KEY` | Optional separate embedding credential |
| `RERANK_MODEL` | empty | Optional reranker model name; empty disables reranking |
| `RERANK_BASE_URL` | falls back to embedding base URL | Optional separate reranker endpoint |
| `RERANK_API_KEY` | falls back to embedding key | Optional separate reranker credential |
| `AML_TIMEOUT_SECONDS` | `90` | Upstream timeout |
| `AML_CANDIDATE_LIMIT` | `300` | Candidate cap before ranking |
| `AML_QUERY_MODEL_MAX_CHARS` | `16000` | Chat analysis and rerank query excerpt length; configurable without a code-level ceiling |
| `AML_MAX_OUTPUT_TOKENS` | `32000` | Approximate evidence token budget |
| `AML_MAX_OUTPUT_ITEMS` | `100` | Maximum returned evidence windows, also bounded by `top_k` |
| `AML_VECTOR_MIN_SIMILARITY` | `0.35` | Minimum vector similarity for vector-only candidates |
| `AML_VECTOR_ONLY_MIN_SIMILARITY` | `0.65` | Stricter threshold when lexical retrieval has no candidates |
| `AML_SEARCH_CONCURRENCY` | `32` | Maximum in-process Search operations |
| `AML_ADD_CONCURRENCY` | `16` | Maximum in-process Add operations |

## 9. Limitations

1. **Memory governance**: the system has no structured fact-version graph. Its heuristic correction suppression compares related candidates and keeps an older source when the query needs an independent fact in it; this does not resolve every possible conflict.
2. **Ranking weights**: the six-signal weighted combination has not been tuned against an external evaluation benchmark. The weights are reasonable defaults based on retrieval-system best practice, not empirically optimized values.
3. **Vector index**: the current implementation uses exact cosine similarity over stored vectors rather than an approximate nearest neighbor index. This is acceptable at the candidate limit of 300 but would need an ANN index for much larger corpora.
4. **Rerank latency**: for non-temporal queries without matching event-day timestamp evidence, the optional reranker adds one upstream call per uncached Search. This increases latency and must be measured against retrieval quality on a representative local panel before changing its use or ranking weights.
5. **No semantic deduplication**: source deduplication is by memory ID. Semantically identical memories from different sessions are not merged.

## 10. AI-Assisted Development

OpenAI Codex was used as a software-engineering assistant to research the public interface contract, implement the repository, write tests, and prepare deployment documentation. Codex was not invoked during evaluation as a hidden participant.
