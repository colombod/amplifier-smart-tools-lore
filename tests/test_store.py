from pathlib import Path

import pytest

from lore import store
from lore.schemas import Freshness, LoreError


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))
    return root


def _freshness(repo: str, indexed_sha: str = "abc123") -> Freshness:
    return Freshness(
        repo=repo,
        indexed_sha=indexed_sha,
        verdict="current",
        summary="up to date",
        measured_at="2024-01-01T00:00:00+00:00",
    )


def test_cache_root_uses_the_env_override_and_creates_it(cache_dir) -> None:
    root = store.cache_root()

    assert root == cache_dir
    assert root.is_dir()


def test_cache_root_resolves_a_relative_env_override_to_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative LORE_CACHE_DIR must not leave the reported cache root cwd-dependent."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LORE_CACHE_DIR", "relative-cache-dir")

    root = store.cache_root()

    assert root.is_absolute()
    assert root == tmp_path / "relative-cache-dir"
    assert root.is_dir()


def test_entry_root_keys_on_repo_and_indexed_sha() -> None:
    root = store.entry_root("owner/repo", "deadbeef")

    assert root == store.cache_root() / "wiki" / "owner__repo" / "deadbeef"


def test_entry_root_falls_back_to_unknown_when_no_sha_given() -> None:
    root = store.entry_root("owner/repo", None)

    assert root.name == "unknown"


def test_split_pages_handles_markers_preamble_and_no_markers() -> None:
    with_preamble = "intro text\n# Page: Foo\nfoo body\n# Page: Bar\nbar body\n"
    only_markers = "# Page: Foo\nfoo body\n# Page: Bar\nbar body\n"
    no_markers = "just plain text with no markers at all"

    assert store._split_pages(with_preamble) == [
        ("Overview", "intro text\n"),
        ("Foo", "foo body\n"),
        ("Bar", "bar body\n"),
    ]
    assert store._split_pages(only_markers) == [("Foo", "foo body\n"), ("Bar", "bar body\n")]
    assert store._split_pages(no_markers) == [("Contents", no_markers)]


def test_write_wiki_names_the_incomplete_cache_path_on_a_disk_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """The index is written after every page, so a failure there leaves pages with no index.

    Simulated by letting the first `_atomic_write` (a page) succeed for real and failing the
    second (the index), reproducing exactly the interrupted-write state the error must name.
    """
    original_atomic_write = store._atomic_write
    calls = {"count": 0}

    def _flaky(path: Path, text: str) -> None:
        calls["count"] += 1
        if calls["count"] == 1:
            original_atomic_write(path, text)
            return
        raise OSError("disk full")

    monkeypatch.setattr(store, "_atomic_write", _flaky)
    freshness = _freshness("owner/repo")

    with pytest.raises(LoreError) as failure:
        store.write_wiki("owner/repo", "# Page: One\nbody\n", freshness)

    message = str(failure.value)
    assert str(store.entry_root("owner/repo", freshness.indexed_sha)) in message
    assert "lore fetch owner/repo --refresh" in message


def test_write_wiki_then_load_index_round_trips() -> None:
    contents = "# Page: First\nfirst body\n# Page: Second\nsecond body\n"
    freshness = _freshness("owner/repo")

    written = store.write_wiki("owner/repo", contents, freshness)
    loaded = store.load_index("owner/repo")

    assert loaded == written
    assert [page.title for page in loaded.pages] == ["First", "Second"]
    assert loaded.total_characters == len("first body\n") + len("second body\n")


def test_load_index_without_sha_picks_the_most_recently_written_entry() -> None:
    store.write_wiki("owner/repo", "# Page: Old\nold\n", _freshness("owner/repo", "old-sha"))
    store.write_wiki("owner/repo", "# Page: New\nnew\n", _freshness("owner/repo", "new-sha"))

    loaded = store.load_index("owner/repo")

    assert loaded.freshness.indexed_sha == "new-sha"


def test_load_index_raises_a_named_command_when_nothing_cached() -> None:
    with pytest.raises(LoreError, match=r"lore fetch owner/repo"):
        store.load_index("owner/repo")


def test_load_index_with_a_corrupt_index_file_raises_a_lore_error_not_a_validation_error() -> None:
    written = store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness("owner/repo"))
    index_path = Path(written.root) / "index.json"
    index_path.write_text("{ not valid json or a valid WikiIndex", encoding="utf-8")

    with pytest.raises(LoreError, match=r"corrupt") as failure:
        store.load_index("owner/repo")

    assert "lore fetch owner/repo --refresh" in str(failure.value)


def test_read_page_with_a_missing_page_file_raises_a_named_lore_error() -> None:
    written = store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness("owner/repo"))
    (Path(written.root) / written.pages[0].path).unlink()

    with pytest.raises(LoreError, match=r"corrupt or unreadable") as failure:
        store.read_page("owner/repo", 1)

    assert "lore fetch owner/repo --refresh" in str(failure.value)


def test_search_pages_with_a_missing_page_file_raises_a_named_lore_error() -> None:
    written = store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness("owner/repo"))
    (Path(written.root) / written.pages[0].path).unlink()

    with pytest.raises(LoreError, match=r"corrupt or unreadable"):
        store.search_pages("owner/repo", "body")


def test_read_page_by_number_and_by_title_substring() -> None:
    store.write_wiki(
        "owner/repo",
        "# Page: Getting Started\nhello\n# Page: Advanced Usage\nworld\n",
        _freshness("owner/repo"),
    )

    by_number = store.read_page("owner/repo", 2)
    by_title = store.read_page("owner/repo", "advanced")

    assert by_number.page_title == "Advanced Usage"
    assert by_number.text == "world\n"
    assert by_title == by_number


def test_read_page_by_int_and_by_the_matching_numeric_string_are_equivalent() -> None:
    """`page` is `int | str` at every surface, and every CLI argument arrives as a string.

    Resolving whether a string means a page number or a title substring is the library's job
    (`store._resolve_page`/`_normalize_page`), not a wrapper's: a Python caller passing the
    string "7" must get exactly what a shell caller passing the argument `7` gets.
    """
    store.write_wiki(
        "owner/repo",
        "# Page: First\nfirst\n# Page: Second\nsecond\n",
        _freshness("owner/repo"),
    )

    by_int = store.read_page("owner/repo", 2)
    by_numeric_string = store.read_page("owner/repo", "2")

    assert by_numeric_string == by_int


def test_read_page_ambiguous_title_names_the_candidates() -> None:
    store.write_wiki(
        "owner/repo",
        "# Page: Setup Guide\na\n# Page: Setup Advanced\nb\n",
        _freshness("owner/repo"),
    )

    with pytest.raises(LoreError, match=r"Setup Guide, Setup Advanced"):
        store.read_page("owner/repo", "setup")


def test_read_page_out_of_range_number_is_a_lore_error() -> None:
    store.write_wiki("owner/repo", "# Page: Only\nbody\n", _freshness("owner/repo"))

    with pytest.raises(LoreError, match=r"range from 1 to 1"):
        store.read_page("owner/repo", 5)


def test_read_page_unknown_title_lists_the_titles_that_exist() -> None:
    store.write_wiki("owner/repo", "# Page: Alpha\na\n# Page: Beta\nb\n", _freshness("owner/repo"))

    with pytest.raises(LoreError, match=r"Alpha, Beta"):
        store.read_page("owner/repo", "gamma")


def test_the_cap_actually_holds_across_the_full_page() -> None:
    body = "".join(f"line {i:05d}\n" for i in range(5000))
    store.write_wiki("owner/repo", f"# Page: Big\n{body}", _freshness("owner/repo"))
    limit = 1000

    result = store.read_page("owner/repo", 1, start=0, limit=limit)
    slices = [result.text]

    assert len(result.text) == limit
    assert result.truncated is True
    assert result.next_start == limit

    while result.truncated:
        assert result.next_start is not None
        result = store.read_page("owner/repo", 1, start=result.next_start, limit=limit)
        slices.append(result.text)

    assert result.truncated is False
    assert result.next_start is None
    assert "".join(slices) == body


def test_read_page_rejects_nonpositive_limit_and_negative_start() -> None:
    store.write_wiki("owner/repo", "# Page: Only\nbody\n", _freshness("owner/repo"))

    with pytest.raises(LoreError, match=r"limit"):
        store.read_page("owner/repo", 1, limit=0)
    with pytest.raises(LoreError, match=r"start"):
        store.read_page("owner/repo", 1, start=-1)


def test_read_page_clamps_a_start_past_the_end_to_an_empty_honest_result() -> None:
    store.write_wiki("owner/repo", "# Page: Only\nshort\n", _freshness("owner/repo"))

    result = store.read_page("owner/repo", 1, start=10_000)

    assert result.text == ""
    assert result.truncated is False
    assert result.next_start is None


def test_search_pages_counts_and_truncates_hits() -> None:
    body = "\n".join(f"needle {i}" for i in range(10))
    store.write_wiki("owner/repo", f"# Page: Haystack\n{body}\n", _freshness("owner/repo"))

    result = store.search_pages("owner/repo", "needle", max_hits=3)

    assert result.total_hits == 10
    assert len(result.hits) == 3
    assert result.truncated is True


def test_search_pages_invalid_regex_raises_lore_error() -> None:
    store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness("owner/repo"))

    with pytest.raises(LoreError, match=r"not a valid regular expression"):
        store.search_pages("owner/repo", "[unclosed")


def test_write_document_refuses_a_dotdot_segment() -> None:
    with pytest.raises(LoreError):
        store.write_document("../escape", "text")
    with pytest.raises(LoreError):
        store.write_document("a/../../escape", "text")


def test_write_document_flattens_a_context7_library_id(cache_dir) -> None:
    """Every real caller passes a library id like `/upstash/context7`, so separators are the
    normal input and must not be refused. They flatten; they never escape the docs directory."""
    path = store.write_document("/upstash/context7", "# Docs\n")

    assert path == cache_dir / "docs" / "upstash__context7.md"
    assert path.read_text(encoding="utf-8") == "# Docs\n"


def test_write_document_writes_under_the_docs_directory(cache_dir) -> None:
    path = store.write_document("some-library", "# Docs\n")

    assert path == cache_dir / "docs" / "some-library.md"
    assert path.read_text(encoding="utf-8") == "# Docs\n"


def test_clear_removes_one_repo_without_touching_another() -> None:
    store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness("owner/repo"))
    store.write_wiki("other/repo", "# Page: One\nbody\n", _freshness("other/repo"))

    removed = store.clear("owner/repo")

    assert removed >= 1
    assert not store.entry_root("owner/repo", "abc123").exists()
    assert store.entry_root("other/repo", "abc123").exists()


def test_clear_with_no_repo_removes_everything(cache_dir) -> None:
    store.write_wiki("owner/repo", "# Page: One\nbody\n", _freshness("owner/repo"))
    store.write_document("some-library", "docs")

    removed = store.clear()

    assert removed >= 2
    assert not cache_dir.exists()
