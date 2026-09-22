from pathlib import Path

import pytest

from lore import selection, store
from lore.schemas import Freshness


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
