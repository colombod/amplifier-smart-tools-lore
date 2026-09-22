from lore import drift
from lore.schemas import DriftVerdict, FileChange, FileStatus, PageDrift

# Verified shape: DeepWiki's "Relevant source files" block, one bullet per file, the path as
# both the link label and its href, plus prose above the list that carries no links itself.
SOURCE_FILES_BLOCK = """
<details>
<summary>Relevant source files</summary>

The following files were used as context for generating this wiki page:

- [.env.example](.env.example)
- [packages/mcp/src/index.ts](packages/mcp/src/index.ts)
- [packages/mcp/src/lib/sessionStore.ts](packages/mcp/src/lib/sessionStore.ts)
- [packages/mcp/src/lib/redis.ts](packages/mcp/src/lib/redis.ts)
</details>
"""


def test_cited_files_reads_every_path_from_the_relevant_source_files_block() -> None:
    files = drift.cited_files(SOURCE_FILES_BLOCK)

    assert files == [
        ".env.example",
        "packages/mcp/src/index.ts",
        "packages/mcp/src/lib/redis.ts",
        "packages/mcp/src/lib/sessionStore.ts",
    ]


def test_cited_files_returns_empty_when_there_is_no_block_and_no_inline_citation() -> None:
    assert drift.cited_files("Just prose about the architecture, no citations at all.") == []


def test_cited_files_tolerates_a_block_that_lists_nothing() -> None:
    text = """
<details>
<summary>Relevant source files</summary>

Nothing was retrieved for this page.
</details>
"""
    assert drift.cited_files(text) == []


def test_cited_files_reads_inline_citations_and_strips_the_line_range() -> None:
    text = "createSessionStore is defined in [packages/mcp/src/lib/sessionStore.ts:12-40]()."

    assert drift.cited_files(text) == ["packages/mcp/src/lib/sessionStore.ts"]


def test_cited_files_reads_an_inline_citation_with_a_single_line_number() -> None:
    text = "See [packages/mcp/src/index.ts:7]() for the entry point."

    assert drift.cited_files(text) == ["packages/mcp/src/index.ts"]


def test_cited_files_deduplicates_across_the_block_and_inline_citations() -> None:
    text = SOURCE_FILES_BLOCK + "\n\nSee [packages/mcp/src/index.ts:1-5]() again.\n"

    assert drift.cited_files(text).count("packages/mcp/src/index.ts") == 1


def test_cited_files_combines_the_block_and_inline_citations_into_one_sorted_set() -> None:
    text = SOURCE_FILES_BLOCK + "\n\nAlso see [packages/other.ts:1-2]().\n"

    files = drift.cited_files(text)

    assert "packages/other.ts" in files
    assert files == sorted(files)


def _change(filename: str, status: FileStatus, previous_filename: str | None = None) -> FileChange:
    return FileChange(filename=filename, status=status, changes=1, previous_filename=previous_filename)


def test_page_drift_is_intact_when_no_cited_file_appears_in_the_changed_set() -> None:
    result = drift.page_drift(1, "Overview", "[a.py:1]()", {}, complete=True)

    assert result.verdict == "intact"
    assert result.intact == ["a.py"]
    assert result.changed == []
    assert result.removed == []


def test_page_drift_is_drifted_when_a_cited_file_was_modified() -> None:
    changed = {"a.py": _change("a.py", "modified")}

    result = drift.page_drift(1, "Overview", "[a.py:1]()", changed, complete=True)

    assert result.verdict == "drifted"
    assert result.changed == [changed["a.py"]]
    assert result.removed == []


def test_page_drift_is_drifted_when_a_cited_file_was_added() -> None:
    changed = {"a.py": _change("a.py", "added")}

    result = drift.page_drift(1, "Overview", "[a.py:1]()", changed, complete=True)

    assert result.verdict == "drifted"


def test_page_drift_is_broken_when_a_cited_file_was_removed() -> None:
    changed = {"a.py": _change("a.py", "removed")}

    result = drift.page_drift(1, "Overview", "[a.py:1]()", changed, complete=True)

    assert result.verdict == "broken"
    assert result.removed == [changed["a.py"]]


def test_page_drift_is_broken_when_a_cited_file_was_renamed() -> None:
    changed = {"old.py": _change("new.py", "renamed", previous_filename="old.py")}

    result = drift.page_drift(1, "Overview", "[old.py:1]()", changed, complete=True)

    assert result.verdict == "broken"
    assert result.removed[0].previous_filename == "old.py"


def test_page_drift_broken_wins_over_drifted_on_the_same_page() -> None:
    changed = {
        "a.py": _change("a.py", "modified"),
        "b.py": _change("b.py", "removed"),
    }

    result = drift.page_drift(1, "Overview", "[a.py:1]() [b.py:2]()", changed, complete=True)

    assert result.verdict == "broken"
    assert len(result.changed) == 2
    assert len(result.removed) == 1


def test_page_drift_with_no_citations_is_intact() -> None:
    result = drift.page_drift(1, "Overview", "no citations here", {}, complete=True)

    assert result.verdict == "intact"
    assert result.cited_files == []


def test_page_drift_false_negative_rule_an_incomplete_comparison_reports_unknown_not_intact() -> None:
    """The load-bearing rule: absence from a truncated changed-file list is not evidence of anything."""
    result = drift.page_drift(1, "Overview", "[a.py:1]()", {}, complete=False)

    assert result.verdict == "unknown"
    assert result.verdict != "intact"


def test_page_drift_incomplete_comparison_still_reports_broken_for_a_file_actually_found_changed() -> None:
    """A file GitHub did report on, even from a truncated walk, is real evidence, not a guess."""
    changed = {"a.py": _change("a.py", "removed")}

    result = drift.page_drift(1, "Overview", "[a.py:1]()", changed, complete=False)

    assert result.verdict == "broken"


def test_page_drift_incomplete_comparison_still_reports_drifted_when_nothing_is_unresolved() -> None:
    changed = {"a.py": _change("a.py", "modified")}

    result = drift.page_drift(1, "Overview", "[a.py:1]()", changed, complete=False)

    assert result.verdict == "drifted"


def _page(number: int, verdict: DriftVerdict) -> PageDrift:
    return PageDrift(
        page_number=number,
        title=f"Page {number}",
        cited_files=[],
        changed=[],
        removed=[],
        intact=[],
        verdict=verdict,
        summary="test",
    )


def test_report_verdict_is_the_worst_page_verdict_not_an_average() -> None:
    pages = [_page(1, "intact"), _page(2, "intact"), _page(3, "broken"), _page(4, "drifted")]

    result = drift.report("owner/repo", "abc", "def", pages, changed_file_count=3, complete=True)

    assert result.verdict == "broken"


def test_report_verdict_prefers_unknown_over_drifted() -> None:
    pages = [_page(1, "drifted"), _page(2, "unknown")]

    result = drift.report("owner/repo", "abc", "def", pages, changed_file_count=1, complete=False)

    assert result.verdict == "unknown"


def test_report_verdict_is_intact_when_every_page_is_intact() -> None:
    pages = [_page(1, "intact"), _page(2, "intact")]

    result = drift.report("owner/repo", "abc", "def", pages, changed_file_count=0, complete=True)

    assert result.verdict == "intact"


def test_report_verdict_is_unknown_when_there_are_no_pages() -> None:
    result = drift.report("owner/repo", "abc", "def", [], changed_file_count=0, complete=True)

    assert result.verdict == "unknown"


def test_report_summary_names_the_repo_and_the_real_counts() -> None:
    pages = [_page(1, "broken"), _page(2, "drifted"), _page(3, "unknown"), _page(4, "intact")]

    result = drift.report("owner/repo", "abc", "def", pages, changed_file_count=5, complete=False)

    assert "owner/repo" in result.summary
    assert "1 broken" in result.summary
    assert "1 drifted" in result.summary
    assert "1 unknown" in result.summary
    assert "5 file(s) changed" in result.summary
    assert "incomplete" in result.summary.lower()
