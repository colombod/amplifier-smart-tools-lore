"""Selection: which of a wiki's pages actually ground one question, without a model.

A `DriftReport`'s verdict is the worst page in the whole cached wiki, which is the right read
for `lore drift` reporting on the wiki as a whole, but the wrong scope for a gate about one
question: a wiki with hundreds of pages and one broken page must not refuse every question,
including ones that have nothing to do with that page. `select_pages` picks the pages that
plausibly ground a question, by term overlap between the question and each page's title and
body. `rank_cited_files` scores, but never drops, the files those pages cite, so a fixed fetch
budget (`explain --at-head`) is spent on the files most likely to matter first rather than on
whichever files happen to sort first alphabetically. Both are relevance heuristics for scoping
or ordering, not a search engine, and no model call is involved in either.
"""

import re

from lore import store
from lore.schemas import FileChange, PageEntry, WikiIndex

# One read per page, deliberately far larger than any real wiki page: `store.read_page` caps
# and truncates by construction, and scoring must see the whole page, not a slice. Matches
# `lore.capabilities.drift.core._FULL_PAGE_LIMIT` and `lore.capabilities.explain.core._FULL_PAGE_LIMIT`.
_FULL_PAGE_LIMIT = 100_000_000

# A page titled for the exact thing being asked about is almost always the right page, even
# when a distant, unrelated page happens to mention the same words once in passing. Title
# matches are weighted this many times a body match, rather than folded into one flat count.
_TITLE_WEIGHT = 5

_TERM_PATTERN = re.compile(r"[a-z0-9]+")

# Characters of page text taken on each side of an occurrence of a cited path, when scoring how
# closely question terms sit to that citation. Wide enough to catch the sentence (or the couple
# of sentences) actually discussing the file, narrow enough that one occurrence's score cannot
# leak into an unrelated paragraph describing a different file entirely.
_PROXIMITY_WINDOW_CHARS = 300

# Splits a path into its meaningful segments: runs between path separators (`/`, `_`, `-`, `.`),
# further split on camelCase boundaries, so "packages/mcp/src/lib/sessionStore.ts" yields
# "packages", "mcp", "src", "lib", "session", "Store", "ts" rather than one opaque token.
_PATH_SEGMENT_PATTERN = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")

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


def rank_cited_files(
    question: str, cited: list[str], page_texts: list[str], changes: dict[str, FileChange]
) -> list[str]:
    """`cited`, reordered by relevance to `question`: a permutation, never a filter.

    `explain --at-head` fetches cited files under a fixed character budget; DeepWiki emits a
    page's "Relevant source files" block alphabetically, so fetching in cited order spends that
    budget on whichever files happen to sort first, not on the ones the question is actually
    about. This reorders the same list so the budget is spent well. It can only ever change the
    ORDER: a file this heuristic scores low can still be the one piece of evidence that matters,
    so nothing here may ever drop a path from the return value. The only thing permitted to
    remove a cited path from what actually gets fetched is the budget itself, downstream of this
    function -- never a relevance judgment made here.

    Scores each path by three signals, in this priority order:

    1. How many distinct question terms appear near an occurrence of the path in `page_texts`.
       Inline citations (`[path:12-40]()`) and "Relevant source files" bullets sit next to the
       prose discussing that file, so text close to a citation is the strongest signal available
       without fetching the file itself.
    2. How many distinct question terms match one of the path's own segments, splitting on path
       separators and camelCase (`sessionStore.ts` -> "session", "store", "ts"). This is what
       lets a question about "sessions" favor `sessionStore.ts` even when the wiki page happens
       to discuss it far from the citation itself.
    3. The size of the change recorded for that path in `changes`, used only to break a tie left
       by the two signals above: a heavily changed file is somewhat likelier to be what moved,
       but this must never outrank an actual relevance signal.

    Any tie remaining after all three keeps `cited`'s own order, so the result is deterministic
    across repeated calls.

    Args:
        question: The question being answered; scored the same way `select_pages` scores it.
        cited: The paths to rank, in their original cited order.
        page_texts: Full text of the pages that cite them, searched for proximity to occurrences.
        changes: Every file GitHub reports changed, keyed by filename; used only for the
            change-size tiebreak. A path absent from `changes` scores 0 for that signal.

    Returns:
        `cited` reordered by descending relevance. Always a permutation of `cited`: same paths,
        same count, in a new order -- never filtered, however irrelevant a path scores.
    """
    terms = _question_terms(question)
    if not terms:
        return list(cited)

    def _rank_key(indexed: tuple[int, str]) -> tuple[int, int, int, int]:
        index, path = indexed
        proximity = _proximity_score(terms, path, page_texts)
        path_score = _path_term_score(terms, path)
        change_size = changes[path].changes if path in changes else 0
        return (-proximity, -path_score, -change_size, index)

    ranked = sorted(enumerate(cited), key=_rank_key)
    return [path for _, path in ranked]


def _proximity_score(terms: list[str], path: str, page_texts: list[str]) -> int:
    """Sum, across every occurrence of `path` in `page_texts`, of distinct `terms` found nearby."""
    pattern = re.compile(re.escape(path))
    total = 0
    for text in page_texts:
        for match in pattern.finditer(text):
            start = max(0, match.start() - _PROXIMITY_WINDOW_CHARS)
            end = min(len(text), match.end() + _PROXIMITY_WINDOW_CHARS)
            window = text[start:end].lower()
            total += sum(1 for term in terms if _contains_term(window, term))
    return total


def _path_term_score(terms: list[str], path: str) -> int:
    """How many distinct `terms` match one of `path`'s own segments (path separators, camelCase)."""
    segments = {segment.lower() for segment in _PATH_SEGMENT_PATTERN.findall(path)}
    return sum(1 for term in terms if term in segments)
