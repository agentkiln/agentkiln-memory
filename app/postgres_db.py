from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone

from psycopg_pool import ConnectionPool

from .db import MemoryRow, memory_id_for
from .postgres_schema import SCHEMA_SQL, cjk_terms, to_tsquery
from .schemas import AddRequest
from .text import lexical_terms


class PostgresMemoryDatabase:
    backend_name = "postgres"

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=int(os.getenv("DB_POOL_MIN", "0")),
            max_size=int(os.getenv("DB_POOL_MAX", "5")),
            timeout=float(os.getenv("DB_POOL_TIMEOUT", "15")),
            max_idle=float(os.getenv("DB_POOL_MAX_IDLE", "60")),
            max_lifetime=float(os.getenv("DB_POOL_MAX_LIFETIME", "900")),
            reconnect_timeout=float(os.getenv("DB_RECONNECT_TIMEOUT", "30")),
            check=ConnectionPool.check_connection,
            kwargs={"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "10"))},
            open=True,
        )

    def _connect(self):
        return self.pool.connection()

    def close(self) -> None:
        self.pool.close()

    def initialize(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(SCHEMA_SQL)

    def request_status(self, request: AddRequest) -> str:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT session_id, payload_hash FROM requests "
                    "WHERE user_id = %s AND request_id = %s",
                    (request.user_id, request.request_id),
                )
                existing = cursor.fetchone()
        if existing is None:
            return "new"
        if existing[0] != request.session_id or existing[1] != request.payload_hash():
            return "conflict"
        return "existing"

    def add(
        self,
        request: AddRequest,
        annotations: list[str],
        embeddings: list[list[float]],
        embedding_model: str,
    ) -> None:
        if len(annotations) != len(request.messages) or len(embeddings) != len(request.messages):
            raise ValueError("annotations and embeddings must match message count")
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO requests (user_id, request_id, session_id, payload_hash, created_at) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, request_id) DO NOTHING",
                    (
                        request.user_id,
                        request.request_id,
                        request.session_id,
                        request.payload_hash(),
                        created_at,
                    ),
                )
                if cursor.rowcount == 0:
                    cursor.execute(
                        "SELECT session_id, payload_hash FROM requests "
                        "WHERE user_id = %s AND request_id = %s",
                        (request.user_id, request.request_id),
                    )
                    existing = cursor.fetchone()
                    if existing is None:
                        raise RuntimeError("request row disappeared during concurrent add")
                    if (
                        existing[0] != request.session_id
                        or existing[1] != request.payload_hash()
                    ):
                        raise ValueError("request_id was already used with a different payload")
                    return
                for ordinal, message in enumerate(request.messages):
                    vector = embeddings[ordinal]
                    if not vector or not all(math.isfinite(value) for value in vector):
                        raise ValueError("embedding vectors must be finite and non-empty")
                    memory_id = memory_id_for(request.user_id, request.request_id, ordinal)
                    search_text = " ".join(
                        lexical_terms(
                            f"{message.content}\n{annotations[ordinal]}",
                            limit=384,
                            index_cjk_characters=True,
                        )
                    )
                    cursor.execute(
                        """
                        INSERT INTO memories (
                            id, user_id, session_id, request_id, ordinal, role, content,
                            occurred_at, created_at, search_text
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            memory_id,
                            request.user_id,
                            request.session_id,
                            request.request_id,
                            ordinal,
                            message.role,
                            message.content,
                            message.timestamp,
                            created_at,
                            search_text,
                        ),
                    )
                    cursor.execute(
                        "INSERT INTO embeddings (memory_id, user_id, model, dimensions, vector_json) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (
                            memory_id,
                            request.user_id,
                            embedding_model,
                            len(vector),
                            json.dumps(vector, separators=(",", ":")),
                        ),
                    )
                cursor.execute(
                    "INSERT INTO user_revisions (user_id, revision) VALUES (%s, 1) "
                    "ON CONFLICT (user_id) DO UPDATE "
                    "SET revision = user_revisions.revision + 1",
                    (request.user_id,),
                )

    def lexical_search(self, user_id: str, query: str, limit: int) -> list[MemoryRow]:
        tsquery = to_tsquery(query)
        cjk = cjk_terms(query)
        if not tsquery and not cjk:
            return []
        conditions: list[str] = []
        params: list[object] = []
        if tsquery:
            conditions.append(
                "to_tsvector('simple', coalesce(m.content, '') || ' ' || "
                "coalesce(m.search_text, '')) @@ to_tsquery('simple', %s)"
            )
            params.append(tsquery)
        if cjk:
            cjk_clauses = " OR ".join("m.content LIKE %s" for _ in cjk)
            conditions.append(f"({cjk_clauses})")
            params.extend(f"%{term}%" for term in cjk)
        rank_expression = (
            "ts_rank("
            "to_tsvector('simple', coalesce(m.content, '') || ' ' || coalesce(m.search_text, '')), "
            "to_tsquery('simple', %s))"
            if tsquery
            else "0.0"
        )
        rank_params = [tsquery] if tsquery else []
        sql = f"""
            SELECT m.id, m.user_id, m.session_id, m.request_id, m.ordinal,
                   m.role, m.content, m.occurred_at, m.created_at, m.search_text,
                   {rank_expression} AS rank
            FROM memories AS m
            WHERE m.user_id = %s AND ({' OR '.join(conditions)})
            ORDER BY rank DESC
            LIMIT %s
        """
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (*rank_params, user_id, *params, limit))
                rows = cursor.fetchall()
        return [
            MemoryRow(
                id=row[0],
                row_id=0,
                user_id=row[1],
                session_id=row[2],
                request_id=row[3],
                ordinal=int(row[4]),
                role=row[5],
                content=row[6],
                occurred_at=row[7],
                created_at=row[8],
                search_text=row[9],
                fts_rank=float(row[10]) if row[10] is not None else 1_000.0,
            )
            for row in rows
        ]

    def vector_search(
        self,
        user_id: str,
        query_vector: list[float],
        limit: int,
        model: str,
        minimum_similarity: float = 0.0,
    ) -> list[MemoryRow]:
        if not query_vector:
            return []
        query_norm = math.sqrt(sum(value * value for value in query_vector))
        if query_norm == 0:
            return []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.id, m.user_id, m.session_id, m.request_id, m.ordinal,
                           m.role, m.content, m.occurred_at, m.created_at, m.search_text,
                           e.vector_json
                    FROM embeddings AS e
                    JOIN memories AS m ON m.id = e.memory_id
                    WHERE e.user_id = %s AND e.model = %s AND e.dimensions = %s
                    """,
                    (user_id, model, len(query_vector)),
                )
                rows = cursor.fetchall()
        scored: list[tuple[float, MemoryRow]] = []
        for row in rows:
            vector = json.loads(row[10])
            denominator = query_norm * math.sqrt(sum(value * value for value in vector))
            if denominator == 0:
                continue
            similarity = sum(left * right for left, right in zip(query_vector, vector)) / denominator
            if similarity < minimum_similarity:
                continue
            memory = MemoryRow(
                id=row[0],
                row_id=0,
                user_id=row[1],
                session_id=row[2],
                request_id=row[3],
                ordinal=int(row[4]),
                role=row[5],
                content=row[6],
                occurred_at=row[7],
                created_at=row[8],
                search_text=row[9],
                fts_rank=1_000.0,
            )
            scored.append((similarity, memory))
        scored.sort(key=lambda item: (item[0], item[1].occurred_at or 0), reverse=True)
        return [row for _score, row in scored[:limit]]

    def neighbors(self, user_id: str, seed_ids: list[str], radius: int = 1) -> list[tuple[MemoryRow, int, int]]:
        if not seed_ids or radius < 1:
            return []
        by_session, positions = self._session_rows(user_id, seed_ids)
        output: dict[str, tuple[MemoryRow, int, int]] = {}
        for seed_rank, seed_id in enumerate(seed_ids):
            location = positions.get(seed_id)
            if not location:
                continue
            session_id, seed_index = location
            session_rows = by_session[session_id]
            start = max(0, seed_index - radius)
            stop = min(len(session_rows), seed_index + radius + 1)
            for index in range(start, stop):
                distance = abs(index - seed_index)
                row = session_rows[index]
                current = output.get(row.id)
                candidate = (row, distance, seed_rank)
                if current is None or (distance, seed_rank) < (current[1], current[2]):
                    output[row.id] = candidate
        return list(output.values())

    def neighbor_windows(self, user_id: str, seed_ids: list[str], radius: int = 1) -> dict[str, list[MemoryRow]]:
        if not seed_ids or radius < 1:
            return {}
        by_session, positions = self._session_rows(user_id, seed_ids)
        windows: dict[str, list[MemoryRow]] = {}
        for seed_id in seed_ids:
            location = positions.get(seed_id)
            if not location:
                continue
            session_id, seed_index = location
            session_rows = by_session[session_id]
            windows[seed_id] = session_rows[
                max(0, seed_index - radius) : min(len(session_rows), seed_index + radius + 1)
            ]
        return windows

    def _session_rows(
        self, user_id: str, seed_ids: list[str]
    ) -> tuple[dict[str, list[MemoryRow]], dict[str, tuple[str, int]]]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT DISTINCT session_id FROM memories WHERE user_id = %s AND id = ANY(%s)",
                    (user_id, list(seed_ids)),
                )
                session_ids = sorted(row[0] for row in cursor.fetchall())
                if not session_ids:
                    return {}, {}
                cursor.execute(
                    """
                    SELECT id, user_id, session_id, request_id, ordinal, role,
                           content, occurred_at, created_at, search_text
                    FROM memories
                    WHERE user_id = %s AND session_id = ANY(%s)
                    ORDER BY session_id, occurred_at NULLS FIRST, created_at, ordinal, id
                    """,
                    (user_id, session_ids),
                )
                rows = cursor.fetchall()
        by_session: dict[str, list[MemoryRow]] = {}
        for row in rows:
            memory = MemoryRow(
                id=row[0],
                row_id=0,
                user_id=row[1],
                session_id=row[2],
                request_id=row[3],
                ordinal=int(row[4]),
                role=row[5],
                content=row[6],
                occurred_at=row[7],
                created_at=row[8],
                search_text=row[9],
                fts_rank=1_000.0,
            )
            by_session.setdefault(memory.session_id, []).append(memory)
        for session_rows in by_session.values():
            session_rows.sort(
                key=lambda row: (*row.source_order()[:2], row.created_at, row.ordinal, row.id)
            )
        positions = {
            row.id: (session_id, index)
            for session_id, session_rows in by_session.items()
            for index, row in enumerate(session_rows)
        }
        return by_session, positions

    def revision(self, user_id: str) -> int:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT revision FROM user_revisions WHERE user_id = %s",
                    (user_id,),
                )
                row = cursor.fetchone()
        return int(row[0]) if row else 0
