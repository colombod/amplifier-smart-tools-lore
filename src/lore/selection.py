"""Selection: which of a wiki's pages actually ground one question, without a model.

A `DriftReport`'s verdict is the worst page in the whole cached wiki, which is the right read
for `lore drift` reporting on the wiki as a whole, but the wrong scope for a gate about one
question: a wiki with hundreds of pages and one broken page must not refuse every question,
including ones that have nothing to do with that page. This module picks the pages that
plausibly ground a question, by term overlap between the question and each page's title and
body. It is a relevance heuristic for scoping a gate, not a search engine, and no model call is
involved.
"""

import re

from lore import store
from lore.schemas import PageEntry, WikiIndex

# One read per page, deliberately far larger than any real wiki page: `store.read_page` caps
# and truncates by construction, and scoring must see the whole page, not a slice. Matches
# `lore.capabilities.drift.core._FULL_PAGE_LIMIT` and `lore.capabilities.explain.core._FULL_PAGE_LIMIT`.
_FULL_PAGE_LIMIT = 100_000_000

# A page titled for the exact thing being asked about is almost always the right page, even
# when a distant, unrelated page happens to mention the same words once in passing. Title
# matches are weighted this many times a body match, rather than folded into one flat count.
_TITLE_WEIGHT = 5

_TERM_PATTERN = re.compile(r"[a-z0-9]+")

# A short, general-purpose English stopword list, not a domain one: "server", "config", "api"
# and the like are exactly the kind of word that should count toward a page's score.
_STOPWORDS = frozenset(
    [
        "a",
        "about",
        "after",
        "again",
        "all",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "could",
        "did",
        "do",
        "does",
        "doing",
        "done",
        "each",
        "for",
        "from",
        "had",
        "has",
        "have",
        "having",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "may",
        "might",
        "must",
        "my",
        "of",
        "off",
        "on",
        "once",
        "only",
        "or",
        "our",
        "out",
        "over",
        "shall",
        "should",
        "so",
        "some",
        "such",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "through",
        "to",
        "under",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)


def select_pages(index: WikiIndex, question: str, limit: int = 5) -> list[PageEntry]:
    """The pages of `index` most likely to ground `question`, ranked without a model call.

    Extracts terms from `question` (case-folded, common stopwords dropped, terms under three
    characters dropped), then scores each page by how many distinct terms appear in its title
    (weighted `_TITLE_WEIGHT` times) plus how many distinct terms appear in its body. A page
    that shares no term with `question` scores zero and is dropped: sharing nothing is not
    evidence a page grounds the question, so it must never be selected by default.

    Args:
        index: The wiki index to select pages from.
        question: The question to score every page against.
        limit: Maximum number of pages to return.

    Returns:
        The highest scoring pages, ordered by descending score and then ascending page number
        for a stable order, capped at `limit`. Empty when no page shares any term with
        `question`, or when `question` carries no terms once stopwords are dropped.
    """
    terms = _question_terms(question)
    if not terms:
        return []

    scored: list[tuple[int, PageEntry]] = []
    for entry in index.pages:
        read_result = store.read_page(index.repo, entry.number, limit=_FULL_PAGE_LIMIT)
        score = _score_page(terms, entry.title, read_result.text)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda scored_entry: (-scored_entry[0], scored_entry[1].number))
    return [entry for _, entry in scored[:limit]]


def _question_terms(question: str) -> list[str]:
    """The distinct, meaningful terms in `question`: case-folded, short words and stopwords dropped."""
    seen: list[str] = []
    for token in _TERM_PATTERN.findall(question.lower()):
        if len(token) < 3 or token in _STOPWORDS:
            continue
        if token not in seen:
            seen.append(token)
    return seen


def _score_page(terms: list[str], title: str, body: str) -> int:
    """How well `title`/`body` match `terms`: a title hit counts `_TITLE_WEIGHT` times a body hit."""
    title_lower = title.lower()
    body_lower = body.lower()
    title_hits = sum(1 for term in terms if _contains_term(title_lower, term))
    body_hits = sum(1 for term in terms if _contains_term(body_lower, term))
    return title_hits * _TITLE_WEIGHT + body_hits


def _contains_term(text: str, term: str) -> bool:
    """Whether `term` appears in `text` as a whole word, not merely as a substring of a longer one."""
    return re.search(rf"\b{re.escape(term)}\b", text) is not None
