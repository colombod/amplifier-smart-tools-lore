from pathlib import Path

import pytest

from lore import selection, store
from lore.schemas import FileChange, Freshness


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))
    return root


def _freshness(indexed_sha: str | None = "abc123") -> Freshness:
    return Freshness(
        repo="owner/repo",
        indexed_sha=indexed_sha,
        head_sha="def456",
        verdict="stale",
        summary="stale",
        measured_at="2024-01-01T00:00:00+00:00",
    )


WIKI_TEXT = (
    "# Page: Enterprise Offering\n"
    "The Enterprise offering includes SSO and audit logs.\n"
    "# Page: Getting Started\n"
    "Install the package and read the enterprise docs for advanced setup.\n"
    "# Page: Overview\n"
    "General project overview, nothing specific here.\n"
)


def test_select_pages_ranks_a_title_match_over_a_body_only_match() -> None:
    index = store.write_wiki("owner/repo", WIKI_TEXT, _freshness())

    selected = selection.select_pages(index, "What does the Enterprise offering include?")

    assert next(entry.title for entry in selected) == "Enterprise Offering"


def test_select_pages_excludes_a_page_sharing_no_term_with_the_question() -> None:
    index = store.write_wiki("owner/repo", WIKI_TEXT, _freshness())

    selected = selection.select_pages(index, "What does the Enterprise offering include?")

    assert "Overview" not in [entry.title for entry in selected]


def test_select_pages_orders_descending_by_score_then_ascending_by_page_number() -> None:
    # Score counts DISTINCT query terms present, not raw term frequency: Alpha and Gamma each
    # match all three terms once, so they tie, while Beta matches only one term and trails.
    text = "# Page: Alpha\nwidget gadget sprocket\n# Page: Beta\nwidget\n# Page: Gamma\nwidget gadget sprocket\n"
    index = store.write_wiki("owner/repo", text, _freshness())

    selected = selection.select_pages(index, "Tell me about the widget gadget sprocket")

    # Alpha (page 1) and Gamma (page 3) tie on score; page number breaks the tie. Beta (page
    # 2), with fewer distinct term hits, must sort after both regardless of its page number.
    assert [entry.title for entry in selected] == ["Alpha", "Gamma", "Beta"]


def test_select_pages_respects_the_limit() -> None:
    text = "".join(f"# Page: Widget {i}\nwidget widget\n" for i in range(10))
    index = store.write_wiki("owner/repo", text, _freshness())

    selected = selection.select_pages(index, "widget", limit=3)

    assert len(selected) == 3


def test_select_pages_returns_nothing_for_a_question_of_pure_stopwords() -> None:
    index = store.write_wiki("owner/repo", WIKI_TEXT, _freshness())

    selected = selection.select_pages(index, "What is the and of it")

    assert selected == []


def test_select_pages_returns_nothing_when_no_page_shares_any_term() -> None:
    index = store.write_wiki("owner/repo", WIKI_TEXT, _freshness())

    selected = selection.select_pages(index, "xyzzy plugh wobble")

    assert selected == []


# `rank_cited_files`: ORDER ONLY, NEVER FILTER. The permutation property below is the
# load-bearing safety test -- a heuristic that could drop a file could hide the one piece of
# evidence that mattered, which is exactly why an earlier proposal to classify files as
# important/unimportant was rejected in favor of reordering under a downstream budget.

_TRANSPORT_QUESTION = "How does the MCP server transport layer work and how is session state tracked?"
_SOME_CITED_PATHS = [
    "packages/mcp/src/index.ts",
    ".env.example",
    "packages/mcp/src/lib/api.ts",
    "auth-prompt.ts",
]
_SOME_PAGE_TEXTS = [
    (
        "Some prose about [packages/mcp/src/index.ts:1-10]() transport handling and "
        "[.env.example:1-2]() local configuration, plus [auth-prompt.ts:1-5]() and "
        "[packages/mcp/src/lib/api.ts:1-5]()."
    )
]


@pytest.mark.parametrize(
    "question",
    [
        _TRANSPORT_QUESTION,
        "xyzzy plugh wobble",  # matches no page text and no path segment
        "What is the and of it",  # pure stopwords: no terms survive extraction
        "",  # no terms at all
    ],
)
def test_rank_cited_files_is_always_a_permutation_of_cited(question: str) -> None:
    ranked = selection.rank_cited_files(question, _SOME_CITED_PATHS, _SOME_PAGE_TEXTS, {})

    assert sorted(ranked) == sorted(_SOME_CITED_PATHS)
    assert len(ranked) == len(_SOME_CITED_PATHS)


def test_rank_cited_files_permutation_property_holds_for_an_empty_cited_list() -> None:
    assert selection.rank_cited_files(_TRANSPORT_QUESTION, [], _SOME_PAGE_TEXTS, {}) == []


# Padding longer than `selection._PROXIMITY_WINDOW_CHARS` (300), so each citation's proximity
# window never bleeds into the paragraph discussing a different file.
_ISOLATING_PAD = "z" * 400


def test_rank_cited_files_ranks_source_files_cited_near_matching_prose_above_an_unrelated_file() -> None:
    """The measured defect: DeepWiki lists citations alphabetically, so `.env.example` used to
    win the budget over the files a transport/session question is actually about.
    """
    page_text = (
        f"discussion of transport handling near [packages/mcp/src/index.ts:1-10]().\n{_ISOLATING_PAD}\n"
        f"discussion of session tracking near [packages/mcp/src/lib/sessionStore.ts:1-10]().\n{_ISOLATING_PAD}\n"
        f"unrelated configuration notes near [.env.example:1-2]().\n"
    )
    cited = [".env.example", "packages/mcp/src/index.ts", "packages/mcp/src/lib/sessionStore.ts"]

    ranked = selection.rank_cited_files(_TRANSPORT_QUESTION, cited, [page_text], {})

    assert ranked.index("packages/mcp/src/index.ts") < ranked.index(".env.example")
    assert ranked.index("packages/mcp/src/lib/sessionStore.ts") < ranked.index(".env.example")


def test_rank_cited_files_proximity_outranks_a_bare_path_match() -> None:
    """A path segment matching a question term is a real signal, but text right next to the
    citation actually discussing it is stronger evidence, and must win.
    """
    question = "How does the cache invalidation work?"
    path_only_match = "src/cache/manager.py"  # never mentioned in page_texts: proximity is 0
    proximity_match = "src/utils/helpers.py"  # path shares no term, but cited near matching prose
    page_text = (
        "Understanding cache invalidation and how work gets scheduled requires reading "
        "[src/utils/helpers.py:1-5]() carefully, since it handles the retry loop."
    )

    ranked = selection.rank_cited_files(question, [path_only_match, proximity_match], [page_text], {})

    assert ranked == [proximity_match, path_only_match]


def test_rank_cited_files_path_match_outranks_change_size_alone() -> None:
    """Change size is the LOWEST-priority signal: it must never outrank a real relevance match."""
    question = "How does the session store work?"
    relevant_path = "src/lib/sessionStore.ts"  # segments "session", "store" match question terms
    unrelated_path = "src/lib/unrelated.ts"  # no term match, but a much larger recorded change
    changes = {
        unrelated_path: FileChange(filename=unrelated_path, status="modified", changes=500),
        relevant_path: FileChange(filename=relevant_path, status="modified", changes=1),
    }

    # Cited in the "wrong" order on purpose, so a passing test proves reordering happened.
    ranked = selection.rank_cited_files(question, [unrelated_path, relevant_path], [], changes)

    assert ranked == [relevant_path, unrelated_path]


def test_rank_cited_files_change_size_only_breaks_a_tie_between_equal_relevance() -> None:
    """With no proximity and no path-term signal for either file, the larger change wins."""
    question = "How does authentication work?"
    small_change = "src/lib/foo.ts"
    large_change = "src/lib/bar.ts"
    changes = {
        small_change: FileChange(filename=small_change, status="modified", changes=10),
        large_change: FileChange(filename=large_change, status="modified", changes=100),
    }

    ranked = selection.rank_cited_files(question, [small_change, large_change], [], changes)

    assert ranked == [large_change, small_change]


def test_rank_cited_files_is_deterministic_across_repeated_calls() -> None:
    first = selection.rank_cited_files(_TRANSPORT_QUESTION, _SOME_CITED_PATHS, _SOME_PAGE_TEXTS, {})
    second = selection.rank_cited_files(_TRANSPORT_QUESTION, _SOME_CITED_PATHS, _SOME_PAGE_TEXTS, {})

    assert first == second


def test_rank_cited_files_keeps_cited_order_when_every_path_scores_equally() -> None:
    """A full tie (no terms, no changes) falls all the way through to the original cited order."""
    cited = ["c/three.py", "a/one.py", "b/two.py"]

    ranked = selection.rank_cited_files("xyzzy plugh wobble", cited, [], {})

    assert ranked == cited
