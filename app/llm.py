from __future__ import annotations

import hashlib
import http.client
import json
import logging
import math
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from dataclasses import dataclass

from .config import Settings
from .schemas import MemoryMessage


class LLMUnavailable(RuntimeError):
    pass


logger = logging.getLogger("uvicorn.error")
EMBEDDING_BATCH_SIZE = 10
EMBEDDING_CHUNK_MAX_BYTES = 4096
EMBEDDING_BEIJING_BATCH_MAX_BYTES = 32000
EMBEDDING_OTHER_BATCH_MAX_BYTES = 8000
ANNOTATION_FRAGMENT_MAX_BYTES = 2048
ANNOTATION_BATCH_MAX_BYTES = 32 * 1024
ANNOTATION_BATCH_MAX_ITEMS = 16
QUERY_ANALYSIS_OPTIONS_MAX_CHARS = 4_000
QUERY_ANALYSIS_OPTIONS_MAX_ITEMS = 128


@dataclass(frozen=True)
class QueryPlan:
    terms: list[str]
    facets: list[str]
    intent: str


class MemoryLLM:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def ready(self) -> bool:
        return self.settings.llm_mode in {"off", "dev_mock"} or bool(
            self.settings.openai_api_key and self.settings.embedding_api_key
        )

    def _require_competition_key(self) -> None:
        if self.settings.llm_mode == "competition" and not self.settings.openai_api_key:
            logger.error("llm unavailable reason=missing_api_key mode=competition")
            raise LLMUnavailable("OPENAI_API_KEY is required in competition mode")

    def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """Return relevance scores aligned with documents, or None when rerank is unavailable."""
        if (
            self.settings.llm_mode != "competition"
            or not self.settings.rerank_model
            or not self.settings.rerank_api_key
        ):
            return None
        if not documents:
            return []
        native_dashscope = self.settings.rerank_model == "qwen3.7-text-rerank"
        if native_dashscope:
            parsed = urlparse(self.settings.rerank_base_url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            path = "/api/v1/services/rerank/text-rerank/text-rerank"
            payload = {
                "model": self.settings.rerank_model,
                "input": {"query": query, "documents": documents},
            }
        else:
            base_url = self.settings.rerank_base_url
            path = "/rerank"
            payload = {"model": self.settings.rerank_model, "query": query, "documents": documents}
        try:
            body = self._post(
                path,
                payload,
                base_url=base_url,
                api_key=self.settings.rerank_api_key,
            )
        except LLMUnavailable:
            return None
        source = body.get("output") if native_dashscope else body
        results = source.get("results") if isinstance(source, dict) else None
        if not isinstance(results, list):
            return None
        scores: list[float | None] = [None] * len(documents)
        for item in results:
            if not isinstance(item, dict):
                continue
            index = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if not isinstance(index, int) or not (0 <= index < len(documents)):
                continue
            if type(score) in {int, float} and math.isfinite(score):
                scores[index] = float(score)
        if any(value is None for value in scores):
            return None
        return [float(value) for value in scores]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._require_competition_key()
        if self.settings.llm_mode != "competition":
            return [self._mock_embedding(text) for text in texts]
        if not self.settings.embedding_api_key:
            raise LLMUnavailable("OPENAI_EMBEDDING_API_KEY is required in competition mode")
        def input_items():
            for owner, original in enumerate(texts):
                chunks = (
                    self._embedding_chunks(original)
                    if self.settings.embedding_model == "text-embedding-v4"
                    else (original,)
                )
                for chunk in chunks:
                    yield owner, chunk

        if self.settings.embedding_model == "text-embedding-v4":
            host = urlparse(self.settings.embedding_base_url).hostname or ""
            max_batch_bytes = (
                EMBEDDING_BEIJING_BATCH_MAX_BYTES
                if host == "dashscope.aliyuncs.com"
                or host.endswith(".cn-beijing.maas.aliyuncs.com")
                else EMBEDDING_OTHER_BATCH_MAX_BYTES
            )
        else:
            max_batch_bytes = None

        def batches():
            batch: list[tuple[int, str]] = []
            batch_bytes = 0
            for owner, chunk in input_items():
                size = len(chunk.encode("utf-8"))
                if batch and max_batch_bytes is not None and batch_bytes + size > max_batch_bytes:
                    yield batch
                    batch = []
                    batch_bytes = 0
                batch.append((owner, chunk))
                batch_bytes += size
                if len(batch) == EMBEDDING_BATCH_SIZE:
                    yield batch
                    batch = []
                    batch_bytes = 0
            if batch:
                yield batch

        first_vectors: list[list[float] | None] = [None] * len(texts)
        weighted_sums: list[list[float] | None] = [None] * len(texts)
        byte_totals = [0] * len(texts)
        chunk_counts = [0] * len(texts)
        dimension: int | None = None
        for batch_items in batches():
            batch = [chunk for _owner, chunk in batch_items]
            body = self._post(
                "/embeddings",
                {"model": self.settings.embedding_model, "input": batch},
                base_url=self.settings.embedding_base_url,
                api_key=self.settings.embedding_api_key,
            )
            data = body.get("data")
            if not isinstance(data, list) or len(data) != len(batch):
                raise LLMUnavailable("embedding response count mismatch")
            if (
                any(not isinstance(row, dict) or type(row.get("index")) is not int for row in data)
                or {row["index"] for row in data} != set(range(len(batch)))
            ):
                raise LLMUnavailable("embedding response index mismatch")
            rows = sorted(data, key=lambda row: row["index"])
            for (owner, chunk), row in zip(batch_items, rows):
                embedding = row.get("embedding")
                if not isinstance(embedding, list) or not embedding or any(
                    type(value) not in {int, float} or not math.isfinite(value)
                    for value in embedding
                ):
                    raise LLMUnavailable("embedding response contains invalid vector")
                vector = [float(value) for value in embedding]
                if dimension is None:
                    dimension = len(vector)
                elif len(vector) != dimension:
                    raise LLMUnavailable("embedding dimensions are inconsistent")
                if first_vectors[owner] is None:
                    first_vectors[owner] = vector
                    weighted_sums[owner] = [0.0] * len(vector)
                weight = len(chunk.encode("utf-8"))
                sums = weighted_sums[owner]
                if sums is not None:
                    for axis, value in enumerate(vector):
                        sums[axis] += value * weight
                byte_totals[owner] += weight
                chunk_counts[owner] += 1
        output: list[list[float]] = []
        for first, sums, total, count in zip(
            first_vectors, weighted_sums, byte_totals, chunk_counts
        ):
            if first is None:
                raise LLMUnavailable("embedding response count mismatch")
            if count == 1:
                output.append(first)
            elif sums is not None and total:
                output.append([value / total for value in sums])
            else:
                raise LLMUnavailable("embedding response contains invalid vector")
        return output

    @staticmethod
    def _embedding_chunks(text: str):
        if len(text) <= EMBEDDING_CHUNK_MAX_BYTES and len(text.encode("utf-8")) <= EMBEDDING_CHUNK_MAX_BYTES:
            yield text
            return
        current: list[str] = []
        current_bytes = 0
        for character in text:
            size = len(character.encode("utf-8"))
            if current_bytes + size > EMBEDDING_CHUNK_MAX_BYTES:
                yield "".join(current)
                current = []
                current_bytes = 0
            current.append(character)
            current_bytes += size
        if current:
            yield "".join(current)

    def annotate_messages(self, messages: list[MemoryMessage]) -> list[str]:
        self._require_competition_key()
        if self.settings.llm_mode != "competition" or not self.settings.openai_api_key:
            return ["" for _message in messages]

        def payload_for(batch: list[tuple[int, str, str]]) -> dict:
            transcript = [
                {"index": index, "role": role, "content": content}
                for index, (_source_index, role, content) in enumerate(batch)
            ]
            return {
                "model": self.settings.openai_model,
                "temperature": 0,
                "max_tokens": min(2048, max(256, len(batch) * 96)),
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Extract retrieval-only cues from memory messages. Return JSON with an items array. "
                            "Each item has index and terms. Use names, dates, places, preferences, corrections, "
                            "relationships, rules, and distinctive phrases from the same message. Do not answer questions."
                        ),
                    },
                    {"role": "user", "content": json.dumps({"messages": transcript}, ensure_ascii=False)},
                ],
            }

        terms_by_message: list[list[str]] = [[] for _message in messages]

        def send(batch: list[tuple[int, str, str]]) -> None:
            body = self._post("/chat/completions", payload_for(batch))
            parsed = self._json_content(body)
            items = parsed.get("items") if isinstance(parsed, dict) else None
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict) or type(item.get("index")) is not int:
                    continue
                local_index = item["index"]
                if 0 <= local_index < len(batch) and isinstance(item.get("terms"), list):
                    source_index = batch[local_index][0]
                    terms_by_message[source_index].extend(str(term) for term in item["terms"])

        batch: list[tuple[int, str, str]] = []
        for source_index, message in enumerate(messages):
            for fragment in self._annotation_fragments(message.content):
                entry = (source_index, message.role, fragment)
                candidate = [*batch, entry]
                if batch and (
                    len(candidate) > ANNOTATION_BATCH_MAX_ITEMS
                    or len(json.dumps(payload_for(candidate)).encode("utf-8")) > ANNOTATION_BATCH_MAX_BYTES
                ):
                    send(batch)
                    batch = []
                batch.append(entry)
                if len(json.dumps(payload_for(batch)).encode("utf-8")) > ANNOTATION_BATCH_MAX_BYTES:
                    raise LLMUnavailable("annotation request exceeds size limit")
        if batch:
            send(batch)
        return [" ".join(dict.fromkeys(terms)) for terms in terms_by_message]

    @staticmethod
    def _annotation_fragments(text: str):
        if len(text) <= ANNOTATION_FRAGMENT_MAX_BYTES and len(text.encode("utf-8")) <= ANNOTATION_FRAGMENT_MAX_BYTES:
            yield text
            return
        current: list[str] = []
        current_bytes = 0
        for character in text:
            size = len(character.encode("utf-8"))
            if current_bytes + size > ANNOTATION_FRAGMENT_MAX_BYTES:
                yield "".join(current)
                current = []
                current_bytes = 0
            current.append(character)
            current_bytes += size
        if current:
            yield "".join(current)

    def analyze_query(self, query: str, options: list[str] | None) -> QueryPlan:
        self._require_competition_key()
        if self.settings.llm_mode != "competition" or not self.settings.openai_api_key:
            return QueryPlan(terms=[], facets=[], intent="none")
        body = self._post(
            "/chat/completions",
            {
                "model": self.settings.openai_model,
                "temperature": 0,
                "max_tokens": 256,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Analyze a memory retrieval query without answering it. Return JSON with terms, facets, "
                            "and temporal_intent. temporal_intent is one of none, latest, earliest. Do not choose options."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"query": query, "options": self._analysis_options(options)},
                            ensure_ascii=False,
                        ),
                    },
                ],
            },
        )
        parsed = self._json_content(body)
        intent = parsed.get("temporal_intent", "none") if isinstance(parsed, dict) else "none"
        if not isinstance(intent, str) or intent not in {"none", "latest", "earliest"}:
            intent = "none"
        return QueryPlan(
            terms=self._string_list(parsed.get("terms", []) if isinstance(parsed, dict) else [], 48),
            facets=self._string_list(parsed.get("facets", []) if isinstance(parsed, dict) else [], 12),
            intent=intent,
        )

    @staticmethod
    def _analysis_options(options: list[str] | None) -> list[str] | None:
        if options is None:
            return None
        if len(options) <= QUERY_ANALYSIS_OPTIONS_MAX_ITEMS and sum(map(len, options)) <= QUERY_ANALYSIS_OPTIONS_MAX_CHARS:
            return options
        if len(options) > QUERY_ANALYSIS_OPTIONS_MAX_ITEMS:
            last = len(options) - 1
            slots = QUERY_ANALYSIS_OPTIONS_MAX_ITEMS - 1
            options = [options[index * last // slots] for index in range(QUERY_ANALYSIS_OPTIONS_MAX_ITEMS)]
        per_option = QUERY_ANALYSIS_OPTIONS_MAX_CHARS // len(options)
        return [
            option if len(option) <= per_option else (
                option[:per_option // 2] + option[-(per_option - per_option // 2):]
            )
            for option in options
        ]

    def _post(
        self,
        path: str,
        payload: dict,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        resolved_base_url = base_url or self.settings.openai_base_url
        resolved_api_key = api_key or self.settings.openai_api_key
        model = payload.get("model") if isinstance(payload, dict) else None
        endpoint = self._endpoint_label(resolved_base_url)
        attempts = 3
        last_error: Exception | None = None
        for attempt in range(attempts):
            started = time.perf_counter()
            logger.info(
                "llm call start endpoint=%s path=%s model=%s attempt=%d/%d timeout_s=%.1f",
                endpoint,
                path,
                model,
                attempt + 1,
                attempts,
                self.settings.timeout_seconds,
            )
            request = urllib.request.Request(
                f"{resolved_base_url}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            request.add_unredirected_header("Authorization", f"Bearer {resolved_api_key}")
            try:
                with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                    decoded = self._decode_response(response.read())
                    logger.info(
                        "llm call success endpoint=%s path=%s model=%s attempt=%d/%d "
                        "duration_ms=%.1f",
                        endpoint,
                        path,
                        model,
                        attempt + 1,
                        attempts,
                        (time.perf_counter() - started) * 1000,
                    )
                    return decoded
            except urllib.error.HTTPError as exc:
                last_error = exc
                body = self._error_body(exc)
                error_code, request_id = self._error_identifiers(body)
                status = exc.code
                if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                    logger.error(
                        "llm call failed endpoint=%s path=%s model=%s attempt=%d/%d "
                        "status=%s duration_ms=%.1f error_code=%s request_id=%s",
                        endpoint,
                        path,
                        model,
                        attempt + 1,
                        attempts,
                        status,
                        (time.perf_counter() - started) * 1000,
                        error_code,
                        request_id,
                    )
                    raise LLMUnavailable(
                        f"model request failed: HTTP {exc.code} "
                        f"code={error_code} request_id={request_id}"
                    ) from exc
                delay = self._retry_delay(exc, attempt)
                logger.warning(
                    "llm call retry endpoint=%s path=%s model=%s attempt=%d/%d "
                    "status=%s retry_in_s=%.1f error_code=%s request_id=%s",
                    endpoint,
                    path,
                    model,
                    attempt + 1,
                    attempts,
                    status,
                    delay,
                    error_code,
                    request_id,
                )
            except (
                http.client.IncompleteRead,
                urllib.error.URLError,
                TimeoutError,
                OSError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt == attempts - 1:
                    logger.error(
                        "llm call failed endpoint=%s path=%s model=%s attempt=%d/%d "
                        "duration_ms=%.1f error_type=%s",
                        endpoint,
                        path,
                        model,
                        attempt + 1,
                        attempts,
                        (time.perf_counter() - started) * 1000,
                        type(exc).__name__,
                    )
                    raise LLMUnavailable(
                        f"model request failed: {type(exc).__name__}"
                    ) from exc
                delay = 0.2 * (2**attempt)
                logger.warning(
                    "llm call retry endpoint=%s path=%s model=%s attempt=%d/%d "
                    "retry_in_s=%.1f error_type=%s",
                    endpoint,
                    path,
                    model,
                    attempt + 1,
                    attempts,
                    delay,
                    type(exc).__name__,
                )
            time.sleep(delay)
        logger.error(
            "llm call failed endpoint=%s path=%s model=%s attempts=%d error_type=%s",
            endpoint,
            path,
            model,
            attempts,
            type(last_error).__name__,
        )
        raise LLMUnavailable(f"model request failed: {type(last_error).__name__}")

    @staticmethod
    def _retry_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return max(0.0, min(60.0, float(retry_after)))
            except ValueError:
                pass
        return 0.2 * (2**attempt)

    @staticmethod
    def _error_body(exc: urllib.error.HTTPError, limit: int = 400) -> str:
        try:
            body = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return ""
        return body[:limit]

    @staticmethod
    def _error_identifiers(body: str) -> tuple[str, str]:
        try:
            parsed = json.loads(body)
        except (TypeError, ValueError):
            return "unknown", "unknown"
        if not isinstance(parsed, dict):
            return "unknown", "unknown"
        error = parsed.get("error")
        nested = error if isinstance(error, dict) else {}

        def safe(value: object) -> str:
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value):
                return value
            return "unknown"

        code = safe(parsed.get("code"))
        if code == "unknown":
            code = safe(nested.get("code"))
        if code == "unknown":
            code = safe(nested.get("type"))
        return code, safe(parsed.get("request_id"))

    @staticmethod
    def _endpoint_label(base_url: str) -> str:
        parsed = urlparse(base_url)
        if parsed.hostname:
            return parsed.netloc.split("@")[-1]
        return "<invalid-url>"

    @staticmethod
    def _decode_response(raw: bytes | str) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("model response must be a JSON object")
        return value

    @staticmethod
    def _json_content(body: dict) -> dict:
        try:
            content = body["choices"][0]["message"]["content"]
            return json.loads(content)
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _string_list(value: object, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if isinstance(item, (str, int, float))][:limit]

    @staticmethod
    def _mock_embedding(text: str, dimensions: int = 64) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [(digest[i % len(digest)] / 255.0) * 2.0 - 1.0 for i in range(dimensions)]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]
