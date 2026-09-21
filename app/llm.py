from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import Settings
from .schemas import MemoryMessage


class LLMUnavailable(RuntimeError):
    pass


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
        return self.settings.llm_mode in {"off", "dev_mock"} or bool(self.settings.openai_api_key)

    def _require_competition_key(self) -> None:
        if self.settings.llm_mode == "competition" and not self.settings.openai_api_key:
            raise LLMUnavailable("OPENAI_API_KEY is required in competition mode")

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._require_competition_key()
        if self.settings.llm_mode != "competition" or not self.settings.openai_api_key:
            return [self._mock_embedding(text) for text in texts]
        payload = {"model": self.settings.embedding_model, "input": texts}
        body = self._post("/embeddings", payload)
        rows = sorted(body.get("data", []), key=lambda row: row.get("index", 0))
        vectors = [[float(value) for value in row["embedding"]] for row in rows]
        if len(vectors) != len(texts):
            raise LLMUnavailable("embedding response count mismatch")
        dimensions = {len(vector) for vector in vectors}
        if len(dimensions) > 1 or (vectors and len(vectors[0]) == 0):
            raise LLMUnavailable("embedding dimensions are inconsistent")
        return vectors

    def annotate_messages(self, messages: list[MemoryMessage]) -> list[str]:
        self._require_competition_key()
        if self.settings.llm_mode != "competition" or not self.settings.openai_api_key:
            return ["" for _message in messages]
        transcript = [
            {"index": index, "role": message.role, "content": message.content}
            for index, message in enumerate(messages)
        ]
        body = self._post(
            "/chat/completions",
            {
                "model": self.settings.openai_model,
                "temperature": 0,
                "max_tokens": min(1024, max(128, len(messages) * 48)),
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
            },
        )
        output = ["" for _message in messages]
        parsed = self._json_content(body)
        for item in parsed.get("items", []) if isinstance(parsed, dict) else []:
            if not isinstance(item, dict) or not isinstance(item.get("index"), int):
                continue
            index = item["index"]
            if 0 <= index < len(output) and isinstance(item.get("terms"), list):
                output[index] = " ".join(str(term) for term in item["terms"])
        return output

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
                    {"role": "user", "content": json.dumps({"query": query, "options": options}, ensure_ascii=False)},
                ],
            },
        )
        parsed = self._json_content(body)
        intent = parsed.get("temporal_intent", "none") if isinstance(parsed, dict) else "none"
        if intent not in {"none", "latest", "earliest"}:
            intent = "none"
        return QueryPlan(
            terms=self._string_list(parsed.get("terms", []) if isinstance(parsed, dict) else [], 48),
            facets=self._string_list(parsed.get("facets", []) if isinstance(parsed, dict) else [], 12),
            intent=intent,
        )

    def _post(self, path: str, payload: dict) -> dict:
        attempts = 3
        last_error: Exception | None = None
        for attempt in range(attempts):
            request = urllib.request.Request(
                f"{self.settings.openai_base_url}{path}",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                    return self._decode_response(response.read())
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                    raise LLMUnavailable(f"model request failed: HTTP {exc.code}") from exc
                delay = self._retry_delay(exc, attempt)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise LLMUnavailable(f"model request failed: {exc}") from exc
                delay = 0.2 * (2**attempt)
            time.sleep(delay)
        raise LLMUnavailable(f"model request failed: {last_error}")

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
