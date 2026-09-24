from __future__ import annotations

import re

from .db import MemoryRow
from .text import temporal_intent


_SUMMARY_ACTION = re.compile(r"\b(?:summari[sz]e|summary\s+of|overview\s+of)\b", re.IGNORECASE)
_GLOBAL_SCOPE = re.compile(
    r"\b(?:history|timeline|conversation|sessions?|stages?|journey|evolution|progress|"
    r"experiences?)\b|\bover\s+time\b",
    re.IGNORECASE,
)
_CHINESE_GLOBAL_SUMMARY = re.compile(
    r"(?:总结|概述|综述).{0,80}(?:各阶段|整个|全部|所有|历程|变化|历史|进展)"
    r"|(?:各阶段|整个|全部|所有|历程|变化|历史|进展).{0,80}(?:总结|概述|综述)",
    re.IGNORECASE,
)


def select_diverse_evidence(
    query: str,
    ranked: list[tuple[float, MemoryRow]],
    limit: int,
    *,
    intent: str = "none",
) -> list[tuple[float, MemoryRow]]:
    """Prefer distinct sessions for explicit summaries without changing source rank order."""
    if limit <= 0 or not ranked:
        return []
    global_summary = (
        bool(_SUMMARY_ACTION.search(query) and _GLOBAL_SCOPE.search(query))
        or bool(_CHINESE_GLOBAL_SUMMARY.search(query))
    )
    if (
        limit == 1
        or len(ranked) <= limit
        or intent != "none"
        or temporal_intent(query) != "none"
        or not global_summary
    ):
        return ranked[:limit]

    selected_indices = [0]
    seen_sessions = {ranked[0][1].session_id}
    boundary_score = ranked[limit - 1][0]
    minimum_score = max(boundary_score * 0.75, boundary_score - 0.15)
    for index, (score, row) in enumerate(ranked[1:], start=1):
        if score < minimum_score:
            continue
        if row.session_id in seen_sessions:
            continue
        selected_indices.append(index)
        seen_sessions.add(row.session_id)
        if len(selected_indices) == limit:
            break

    if len(selected_indices) < limit:
        selected = set(selected_indices)
        for index in range(1, len(ranked)):
            if index not in selected:
                selected_indices.append(index)
                if len(selected_indices) == limit:
                    break

    return [ranked[index] for index in sorted(selected_indices)]
