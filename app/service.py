from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import defaultdict

from .config import Settings
from .db import MemoryDatabase, MemoryRow
from .llm import MemoryLLM
from .pack import pack_windows
from .postgres_db import PostgresMemoryDatabase
from .schemas import AddRequest, SearchItem, SearchRequest
from .text import (
    coverage,
    fts_query,
    has_update_marker,
    lexical_overlap,
    lexical_terms,
    phrase_bonus,
    semantic_terms,
    temporal_intent,
)


QWEN37_RERANK_MAX_DOCUMENTS = 500
SEARCH_QUERY_PRIORITY_CHARS = 512
SEARCH_QUERY_LEXICAL_TERMS = 160
SEARCH_QUERY_PRIORITY_TERMS = 80
logger = logging.getLogger("uvicorn.error")


def _bounded_search_query(query: str, max_chars: int) -> str:
    if len(query) <= max_chars:
        return query
    head_length = (max_chars - 1) // 4
    tail_length = max_chars - head_length - 1
    return f"{query[:head_length]}\n{query[-tail_length:]}"


def _long_query_terms(query: str, excerpt: str, terms: list[str], facets: list[str]) -> list[str]:
    priority_text = " ".join(
        terms + facets + [excerpt[-SEARCH_QUERY_PRIORITY_CHARS:]]
        + semantic_terms(excerpt[-SEARCH_QUERY_PRIORITY_CHARS:], limit=32)
    )
    priority = lexical_terms(priority_text, limit=SEARCH_QUERY_PRIORITY_TERMS)
    seen = set(priority)
    remaining = [term for term in lexical_terms(query, limit=None) if term not in seen]
    # Prefer descriptive terms to numbered transcript noise, while retaining tail/question cues.
    remaining.sort(key=lambda term: (any(character.isdigit() for character in term), -len(term)))
    return (priority + remaining)[:SEARCH_QUERY_LEXICAL_TERMS]


class MemoryService:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.database_url:
            self.database = PostgresMemoryDatabase(settings.database_url)
        else:
            self.database = MemoryDatabase(settings.database_path)
        self.llm = MemoryLLM(settings)
        self._cache: dict[tuple[object, ...], list[SearchItem]] = {}
        self._cache_lock = threading.Lock()
        self._search_slots = threading.BoundedSemaphore(value=settings.search_concurrency)
        self._add_slots = threading.BoundedSemaphore(value=settings.add_concurrency)

    def initialize(self) -> None:
        self.database.initialize()

    def close(self) -> None:
        if isinstance(self.database, PostgresMemoryDatabase):
            self.database.close()

    def add(self, request: AddRequest) -> None:
        with self._add_slots:
            self._add_unlocked(request)

    def _add_unlocked(self, request: AddRequest) -> None:
        status = self.database.request_status(request)
        if status == "existing":
            return
        if status == "conflict":
            raise ValueError("request_id was already used with a different payload")
        annotations = self.llm.annotate_messages(request.messages)
        embeddings = self.llm.embed_texts([message.content for message in request.messages])
        self.database.add(request, annotations, embeddings, self.settings.embedding_model)

    def search(self, request: SearchRequest) -> list[SearchItem]:
        with self._search_slots:
            return self._search_unlocked(request)

    def _search_unlocked(self, request: SearchRequest) -> list[SearchItem]:
        revision = self.database.revision(request.user_id)
        input_digest = hashlib.sha256(
            json.dumps(
                [request.query, request.options], ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        ).digest()
        cache_key = (
            "v1",
            request.user_id,
            input_digest,
            request.top_k,
            revision,
            self.settings.llm_mode,
            self.settings.openai_model,
            self.settings.embedding_model,
            self.settings.candidate_limit,
            self.settings.max_output_tokens,
            self.settings.max_output_items,
            self.settings.vector_min_similarity,
            self.settings.vector_only_min_similarity,
            self.settings.rerank_model,
            self.settings.search_concurrency,
            self.settings.add_concurrency,
            self.settings.query_model_max_chars,
        )
        with self._cache_lock:
            cached = self._cache.get(cache_key)
        if cached is not None:
            return [item.model_copy() for item in cached]

        search_query = _bounded_search_query(request.query, self.settings.query_model_max_chars)
        if len(search_query) < len(request.query):
            logger.info(
                "search query model context compacted query_chars=%d model_chars=%d",
                len(request.query),
                len(search_query),
            )
        plan = self.llm.analyze_query(search_query, request.options)
        if (
            len(request.query) > self.settings.query_model_max_chars
            or len(lexical_terms(request.query, limit=SEARCH_QUERY_LEXICAL_TERMS + 1))
            > SEARCH_QUERY_LEXICAL_TERMS
        ):
            query_terms = _long_query_terms(
                request.query, search_query, plan.terms, plan.facets
            )
        else:
            query_parts = [search_query] + plan.terms + plan.facets + semantic_terms(search_query, limit=96)
            query_terms = lexical_terms(" ".join(query_parts), limit=SEARCH_QUERY_LEXICAL_TERMS)
        query = fts_query(query_terms)
        lexical_rows = self.database.lexical_search(
            request.user_id,
            query,
            self.settings.candidate_limit,
        )
        query_vector = self.llm.embed_texts([request.query])[0]
        vector_rows = self.database.vector_search(
            request.user_id,
            query_vector,
            self.settings.candidate_limit,
            self.settings.embedding_model,
            minimum_similarity=(
                self.settings.vector_min_similarity
                if lexical_rows
                else self.settings.vector_only_min_similarity
            ),
        )
        candidates = self._fuse(lexical_rows, vector_rows)
        if lexical_rows:
            allowed = {row.id for row in lexical_rows}
            allowed.update(
                row.id
                for row in vector_rows
                if lexical_overlap(query_terms, row.content, row.search_text)
            )
            candidates = [row for row in candidates if row.id in allowed]
        elif not vector_rows:
            return []
        candidates = self._expand_neighbors(request.user_id, candidates)
        if not candidates:
            return []
        intent = plan.intent if plan.intent != "none" else temporal_intent(request.query)
        if intent != "earliest":
            candidates = self._suppress_superseded(candidates)
        ordered = self._rank(
            search_query,
            request.options or [],
            candidates,
            intent,
            query_terms,
            plan.terms + plan.facets,
        )
        rerank_enabled = self.settings.llm_mode == "competition" and intent == "none" and bool(
            self.settings.rerank_model and self.settings.rerank_api_key
        )
        rerank_pool = (
            ordered[:QWEN37_RERANK_MAX_DOCUMENTS]
            if self.settings.rerank_model == "qwen3.7-text-rerank"
            else ordered
        )
        rerank_scores = (
            self.llm.rerank(search_query, [row.content for _score, row in rerank_pool])
            if intent == "none"
            else None
        )
        if rerank_scores is not None and len(rerank_scores) == len(rerank_pool):
            reranked = sorted(
                ((score, row) for score, (_rule_score, row) in zip(rerank_scores, rerank_pool)),
                key=lambda item: item[0],
                reverse=True,
            )
            ordered = reranked + [
                (0.0, row) for _score, row in ordered[len(rerank_pool) :]
            ]
        else:
            rerank_scores = None
        windows = self._windows(
            request.user_id, ordered[: min(request.top_k, self.settings.max_output_items)]
        )
        packed = pack_windows(
            windows,
            top_k=request.top_k,
            max_tokens=self.settings.max_output_tokens,
            max_items=self.settings.max_output_items,
        )
        rows_by_id = {row.id: row for _score, _anchor, context in windows for row in context}
        output = [
            SearchItem(
                id=window.source_id,
                content=window.content,
                score=round(max(0.0, min(1.0, window.score)), 6),
                created_at=rows_by_id[window.source_id].created_at,
            )
            for window in packed
            if window.source_id in rows_by_id
        ]
        if rerank_scores is not None or not rerank_enabled:
            with self._cache_lock:
                self._store_cache(cache_key, output)
        return [item.model_copy() for item in output]

    def _store_cache(self, cache_key: tuple[object, ...], output: list[SearchItem]) -> None:
        self._cache[cache_key] = [item.model_copy() for item in output]
        if len(self._cache) > 512:
            self._cache.pop(next(iter(self._cache)))

    @staticmethod
    def _suppress_superseded(candidates: list[MemoryRow]) -> list[MemoryRow]:
        """Demote older memories that a later correction in the same concept clearly supersedes."""
        corrections = [row for row in candidates if has_update_marker(row.content)]
        if not corrections:
            return candidates
        superseded_ids: set[str] = set()
        for newer in corrections:
            newer_terms = set(lexical_terms(newer.content, limit=96))
            if not newer_terms:
                continue
            for older in candidates:
                if older.id == newer.id:
                    continue
                if not MemoryService._is_later(newer, older):
                    continue
                older_terms = set(lexical_terms(older.content, limit=96))
                if older_terms and len(newer_terms & older_terms) / len(newer_terms) >= 0.6:
                    superseded_ids.add(older.id)
        if not superseded_ids:
            return candidates
        return [row for row in candidates if row.id not in superseded_ids]

    @staticmethod
    def _is_later(newer: MemoryRow, older: MemoryRow) -> bool:
        if newer.occurred_at is not None and older.occurred_at is not None:
            if newer.occurred_at != older.occurred_at:
                return newer.occurred_at > older.occurred_at
        if newer.created_at != older.created_at:
            return newer.created_at > older.created_at
        if newer.request_id == older.request_id and newer.ordinal != older.ordinal:
            return newer.ordinal > older.ordinal
        if newer.row_id and older.row_id and newer.row_id != older.row_id:
            return newer.row_id > older.row_id
        return False

    @staticmethod
    def _fuse(lexical: list[MemoryRow], vector: list[MemoryRow]) -> list[MemoryRow]:
        scores: dict[str, float] = defaultdict(float)
        rows: dict[str, MemoryRow] = {}
        for ranked in (lexical, vector):
            for index, row in enumerate(ranked):
                rows.setdefault(row.id, row)
                scores[row.id] += 1.0 / (60 + index + 1)
        return [rows[row_id] for row_id, _score in sorted(scores.items(), key=lambda item: item[1], reverse=True)]

    def _expand_neighbors(self, user_id: str, candidates: list[MemoryRow]) -> list[MemoryRow]:
        if not candidates:
            return []
        seen = {row.id for row in candidates}
        output = list(candidates)
        for row, _distance, seed_rank in self.database.neighbors(user_id, [item.id for item in candidates[:24]], radius=1):
            if row.id not in seen:
                output.append(row)
                seen.add(row.id)
        return output

    def _rank(
        self,
        query: str,
        options: list[str],
        candidates: list[MemoryRow],
        intent: str,
        query_terms: list[str],
        expanded_terms: list[str],
    ) -> list[tuple[float, MemoryRow]]:
        terms = set(query_terms)
        expansion = set(lexical_terms(" ".join(expanded_terms), limit=128)) - terms
        option_terms = set(lexical_terms(" ".join(options), limit=64))
        timestamps = [row.occurred_at for row in candidates if row.occurred_at is not None]
        minimum = min(timestamps) if timestamps else 0
        maximum = max(timestamps) if timestamps else 0
        ranked: list[tuple[float, MemoryRow]] = []
        for index, row in enumerate(candidates):
            values = [row.content, row.search_text]
            time_score = 0.0
            if row.occurred_at is not None and maximum > minimum:
                ratio = (row.occurred_at - minimum) / (maximum - minimum)
                if intent == "latest":
                    time_score = 0.16 * ratio
                elif intent == "earliest":
                    time_score = 0.16 * (1.0 - ratio)
            if intent == "latest" and has_update_marker(row.content):
                time_score += 0.05
            score = (
                0.40 * coverage(terms, values)
                + 0.16 * (1.0 / (1.0 + index))
                + 0.12 * coverage(expansion, values)
                + 0.10 * coverage(option_terms, values)
                + 0.06 * phrase_bonus(query, row.content)
                + time_score
            )
            ranked.append((score, row))
        ranked.sort(key=lambda item: (item[0], item[1].occurred_at or 0), reverse=True)
        return ranked

    def _windows(
        self,
        user_id: str,
        ranked: list[tuple[float, MemoryRow]],
    ) -> list[tuple[float, MemoryRow, list[MemoryRow]]]:
        selected = ranked[: self.settings.max_output_items]
        if isinstance(self.database, PostgresMemoryDatabase):
            window_map = self.database.neighbor_windows(
                user_id, [row.id for _score, row in selected], radius=1
            )
        else:
            window_map: dict[str, list[MemoryRow]] = {}
            for _score, row in selected:
                for context_row, _distance, _seed_rank in self.database.neighbors(user_id, [row.id], radius=1):
                    window_map.setdefault(row.id, [])
                    if all(existing.id != context_row.id for existing in window_map[row.id]):
                        window_map[row.id].append(context_row)
        return [
            (
                score,
                row,
                sorted(
                    window_map.get(row.id) or [row],
                    key=MemoryRow.source_order,
                ),
            )
            for score, row in selected
        ]
