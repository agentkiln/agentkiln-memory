from __future__ import annotations

import re
import unicodedata


WORD_RE = re.compile(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)*")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "did", "do", "does",
    "for", "from", "had", "has", "have", "how", "i", "in", "is", "it", "me",
    "my", "of", "on", "or", "that", "the", "their", "them", "they", "this",
    "to", "was", "were", "what", "when", "where", "which", "who", "why",
    "with", "would", "you", "your", "什么", "哪个", "哪些", "怎么", "如何",
    "是否", "我的", "他的", "她的", "他们", "这个", "那个", "我们", "你们",
    "多少", "为何", "为什么",
}

LATEST_MARKERS = (
    "latest", "current", "currently", "now", "newest", "recent", "last", "最近",
    "最新", "当前", "现在", "最后",
)
EARLIEST_MARKERS = (
    "earliest", "first", "initial", "originally", "最早", "最初", "第一次", "起初",
)
UPDATE_MARKERS = (
    "actually", "instead", "changed", "updated", "correction", "corrected", "now",
    "其实", "改成", "改为", "更正", "更新", "现在", "后来",
)
CONCEPTS = (
    {"prefer", "preference", "favorite", "favourite", "like", "love", "enjoy"},
    {"live", "lives", "living", "home", "city", "country", "move", "moved", "relocated"},
    {"work", "job", "career", "profession", "occupation", "company", "role"},
    {"school", "study", "studied", "education", "university", "college", "degree"},
    {"book", "read", "reading", "author", "novel"},
    {"music", "song", "artist", "band", "listen"},
    {"food", "meal", "eat", "restaurant", "drink", "tea", "coffee"},
    {"health", "doctor", "medicine", "medical", "treatment"},
    {"family", "friend", "partner", "spouse", "child", "children", "parent"},
    {"travel", "trip", "vacation", "holiday", "visit", "camping", "hiking"},
    {"plan", "planning", "intend", "goal", "will", "going", "打算", "计划", "准备"},
    {"change", "update", "correction", "instead", "current", "latest", "改成", "更正"},
    {"before", "after", "earlier", "later", "first", "last", "之前", "之后", "后来"},
)


def normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _stem(word: str) -> set[str]:
    variants = {word}
    if len(word) > 5 and word.endswith("ing"):
        variants.add(word[:-3])
    if len(word) > 4 and word.endswith("ed"):
        variants.add(word[:-2])
    if len(word) > 4 and word.endswith("es"):
        variants.add(word[:-2])
    if len(word) > 3 and word.endswith("s"):
        variants.add(word[:-1])
    return {item for item in variants if len(item) > 1}


def lexical_terms(value: str, limit: int = 256) -> list[str]:
    normalized = normalize_text(value)
    ordered: dict[str, None] = {}
    for match in WORD_RE.finditer(normalized):
        word = match.group(0)
        if len(word) > 1 and word not in STOPWORDS:
            for variant in sorted(_stem(word)):
                ordered.setdefault(variant, None)
    for match in CJK_RE.finditer(normalized):
        run = match.group(0)
        if len(run) == 1:
            ordered.setdefault(run, None)
            continue
        for size in (2, 3):
            for index in range(max(0, len(run) - size + 1)):
                term = run[index : index + size]
                if term not in STOPWORDS:
                    ordered.setdefault(term, None)
    return list(ordered)[:limit]


def semantic_terms(value: str, limit: int = 128) -> list[str]:
    base = lexical_terms(value, limit=limit)
    present = set(base)
    ordered: dict[str, None] = {term: None for term in base}
    for group in CONCEPTS:
        if present & group:
            for term in sorted(group):
                ordered.setdefault(term, None)
    return list(ordered)[:limit]


def fts_query(terms: list[str]) -> str:
    safe: list[str] = []
    for term in terms:
        cleaned = term.replace('"', '""').strip()
        if cleaned:
            safe.append(f'"{cleaned}"')
    return " OR ".join(safe)


def phrase_bonus(query: str, content: str) -> float:
    normalized_query = normalize_text(query)
    normalized_content = normalize_text(content)
    if len(normalized_query) < 4:
        return 0.0
    return 1.0 if normalized_query in normalized_content else 0.0


def coverage(terms: set[str], values: list[str]) -> float:
    if not terms:
        return 0.0
    content_terms: set[str] = set()
    for value in values:
        content_terms.update(lexical_terms(value, limit=512))
    return len(terms & content_terms) / len(terms)


def lexical_overlap(terms: list[str], content: str, search_text: str = "") -> bool:
    query_terms = {
        term
        for term in terms
        if (CJK_RE.fullmatch(term) and len(term) >= 2) or len(term) > 2
    }
    if not query_terms:
        return False
    content_terms = set(lexical_terms(f"{content}\n{search_text}", limit=1024))
    return bool(query_terms & content_terms)


def temporal_intent(query: str) -> str:
    normalized = normalize_text(query)
    if _contains_marker(normalized, EARLIEST_MARKERS):
        return "earliest"
    if _contains_marker(normalized, LATEST_MARKERS):
        return "latest"
    return "none"


def has_update_marker(value: str) -> bool:
    normalized = normalize_text(value)
    return _contains_marker(normalized, UPDATE_MARKERS)


def _contains_marker(normalized: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if any(character.isascii() and character.isalpha() for character in marker):
            pattern = r"(?<![a-z0-9_])" + re.escape(marker) + r"(?![a-z0-9_])"
            if re.search(pattern, normalized):
                return True
        elif marker in normalized:
            return True
    return False


def estimate_tokens(value: str) -> int:
    if not value:
        return 0
    cjk_count = sum(1 for character in value if CJK_RE.fullmatch(character))
    other_count = len(value) - cjk_count
    return cjk_count + (other_count + 3) // 4
