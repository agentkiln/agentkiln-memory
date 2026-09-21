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
    {"live", "lives", "living", "home", "city", "country", "move", "moved", "relocated", "\u4f4f", "\u4f4f\u5728", "\u4f4f\u54ea", "\u5728\u4f4f", "\u642c\u5bb6", "\u642c\u5230", "\u5317\u4eac"},
    {"work", "job", "career", "profession", "occupation", "company", "role", "\u5de5\u4f5c", "\u4e0a\u73ed", "\u516c\u53f8", "\u804c\u4e1a", "\u516c\u53f8\u4e0a\u73ed"},
    {"school", "study", "studied", "education", "university", "college", "degree", "\u5b66\u6821", "\u5b66\u4e60", "\u8bfb\u4e66", "\u5927\u5b66", "\u5b66\u6821\u8bfb\u4e66"},
    {"book", "read", "reading", "author", "novel", "\u4e66", "\u770b\u4e66", "\u4f5c\u8005", "\u5c0f\u8bf4", "\u9605\u8bfb", "\u770b\u4ec0\u4e48", "\u770b\u4ec0\u4e48\u4e66", "\u4ec0\u4e48\u4e66"},
    {"music", "song", "artist", "band", "listen", "\u6b4c", "\u97f3\u4e50", "\u6b4c\u624b", "\u4e50\u961f", "\u542c", "\u542c\u4ec0\u4e48", "\u542c\u4ec0\u4e48\u6b4c", "\u4ec0\u4e48\u6b4c"},
    {"food", "meal", "eat", "restaurant", "drink", "tea", "coffee", "\u5403", "\u559d", "\u996d", "\u83dc", "\u9910", "\u8336", "\u5496\u5561", "\u559c\u6b22\u559d", "\u559c\u6b22\u5403"},
    {"health", "doctor", "medicine", "medical", "treatment", "\u5065\u5eb7", "\u533b\u751f", "\u533b\u7597", "\u8eab\u4f53", "\u6cbb\u7597"},
    {"family", "friend", "partner", "spouse", "child", "children", "parent", "\u5bb6\u4eba", "\u670b\u53cb", "\u5bb6\u5ead", "\u5b69\u5b50", "\u7236\u6bcd", "\u8c01"},
    {"travel", "trip", "vacation", "holiday", "visit", "camping", "hiking", "\u65c5\u6e38", "\u51fa\u53bb\u73a9", "\u5ea6\u5047", "\u53c2\u89c2", "\u65c5\u884c", "\u53bb\u4e86\u54ea\u91cc"},
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
