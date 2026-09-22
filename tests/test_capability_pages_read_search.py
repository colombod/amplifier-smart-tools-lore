from pathlib import Path

import pytest

from lore import store
from lore.capabilities.pages import core as pages_core
from lore.capabilities.read import core as read_core
from lore.capabilities.search import core as search_core
from lore.schemas import Freshness, LoreError


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))
    return root


def _freshness() -> Freshness:
    return Freshness(
        repo="owner/repo",
        indexed_sha="abc123",
        verdict="current",
        summary="ok",
        measured_at="2024-01-01T00:00:00+00:00",
    )


def test_pages_returns_the_cached_index() -> None:
    written = store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness())

    assert pages_core.pages("owner/repo") == written


def test_pages_raises_a_named_command_when_nothing_is_cached() -> None:
    with pytest.raises(LoreError, match=r"lore fetch owner/repo"):
        pages_core.pages("owner/repo")


def test_read_returns_a_bounded_slice() -> None:
    store.write_wiki("owner/repo", "# Page: One\nhello world\n", _freshness())

    result = read_core.read("owner/repo", 1, limit=5)

    assert result.text == "hello"
    assert result.truncated is True


def test_search_finds_and_caps_hits() -> None:
    store.write_wiki("owner/repo", "# Page: One\nneedle\nneedle\nneedle\n", _freshness())

    result = search_core.search("owner/repo", "needle", max_hits=2)

    assert result.total_hits == 3
    assert len(result.hits) == 2
    assert result.truncated is True
