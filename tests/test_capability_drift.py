from pathlib import Path

import pytest

from lore import store
from lore.capabilities.drift import core
from lore.schemas import FileChange, Freshness, LoreError


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))
    return root


def _freshness(indexed_sha: str | None = "abc123", head_sha: str | None = "def456") -> Freshness:
    return Freshness(
        repo="owner/repo",
        indexed_sha=indexed_sha,
        head_sha=head_sha,
        verdict="stale",
        summary="stale",
        measured_at="2024-01-01T00:00:00+00:00",
    )


WIKI_TEXT = (
    "# Page: Session Store\n"
    "createSessionStore lives in [packages/mcp/src/lib/sessionStore.ts:1-10]().\n"
    "# Page: Overview\n"
    "Nothing changed here.\n"
)


def test_drift_reports_broken_for_a_page_whose_cited_file_was_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    store.write_wiki("owner/repo", WIKI_TEXT, _freshness())
    removed = FileChange(filename="packages/mcp/src/lib/sessionStore.ts", status="removed", changes=12)
    monkeypatch.setattr(core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([removed], True))

    result = core.drift("owner/repo")

    assert result.verdict == "broken"
    assert result.comparison_complete is True
    assert result.changed_file_count == 1
    session_page = next(page for page in result.pages if page.title == "Session Store")
    overview_page = next(page for page in result.pages if page.title == "Overview")
    assert session_page.verdict == "broken"
    assert overview_page.verdict == "intact"


def test_drift_restricted_to_one_page_measures_only_that_page(monkeypatch: pytest.MonkeyPatch) -> None:
    store.write_wiki("owner/repo", WIKI_TEXT, _freshness())
    monkeypatch.setattr(core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([], True))

    result = core.drift("owner/repo", page=2)

    assert len(result.pages) == 1
    assert result.pages[0].title == "Overview"


def test_drift_never_calls_github_when_the_indexed_commit_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    store.write_wiki("owner/repo", WIKI_TEXT, _freshness(indexed_sha=None))

    def _must_not_be_called(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("changed_files must not be called when the indexed commit is unknown")

    monkeypatch.setattr(core.github, "changed_files", _must_not_be_called)

    result = core.drift("owner/repo")

    assert result.comparison_complete is False
    assert result.verdict == "unknown"


def test_drift_marks_the_whole_report_unknown_when_the_compare_call_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.write_wiki("owner/repo", WIKI_TEXT, _freshness())
    monkeypatch.setattr(core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([], False))

    result = core.drift("owner/repo")

    assert result.comparison_complete is False
    assert result.verdict == "unknown"
    # "Session Store" cites a file absent from the (incomplete) changed set, so it cannot be
    # trusted as intact; "Overview" cites nothing at all, so it is trivially intact either way.
    session_page = next(page for page in result.pages if page.title == "Session Store")
    assert session_page.verdict == "unknown"


def test_drift_raises_a_named_command_when_nothing_is_cached() -> None:
    with pytest.raises(LoreError, match=r"lore fetch owner/repo"):
        core.drift("owner/repo")
