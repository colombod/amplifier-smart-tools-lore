from pathlib import Path

import pytest

from lore import store
from lore.capabilities.fetch import core
from lore.schemas import Freshness, RepoRef


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))
    return root


def _freshness(indexed_sha: str = "abc123") -> Freshness:
    return Freshness(
        repo="owner/repo",
        indexed_sha=indexed_sha,
        verdict="current",
        summary="up to date",
        measured_at="2024-01-01T00:00:00+00:00",
    )


def test_fetch_returns_the_cached_index_visibly_marked_when_not_refreshing() -> None:
    freshness = _freshness()
    written = store.write_wiki("owner/repo", "# Page: One\nbody\n", freshness)
    ref = RepoRef(owner="owner", repo="repo")

    result = core.fetch("owner/repo", ref, freshness, refresh=False)

    assert result.from_cache is True
    assert result.pages == written.pages
    assert result.freshness == written.freshness


def test_write_wiki_itself_never_marks_the_index_as_a_cache_hit() -> None:
    written = store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness())

    assert written.from_cache is False
