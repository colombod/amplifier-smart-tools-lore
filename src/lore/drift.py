"""Drift: whether a cached wiki page's own citations still match the repository.

A repository-level freshness measurement ("N commits behind") can hide a page whose entire
cited files were deleted while every other page was untouched. This module intersects one
page's citations, both its "Relevant source files" block and its inline `[path:line-range]()`
citations, against the files GitHub reports changed since the wiki was indexed, so staleness
becomes a property of the page rather than an average over the repository. Pure: no network,
no disk. `lore.capabilities.drift.core` supplies the changed-file map this reads against.
"""

import re

from lore.schemas import DriftReport, DriftVerdict, FileChange, PageDrift

# Verified against a real DeepWiki page: the block that names every file the page was
# generated from, one bullet per file, the path as both the link label and its href.
_SOURCE_FILES_BLOCK = re.compile(
    r"<details>\s*<summary>\s*Relevant source files\s*</summary>(.*?)</details>", re.DOTALL | re.IGNORECASE
)
_MARKDOWN_LINK = re.compile(r"\[([^\[\]]+)\]\(([^()]*)\)")
# An inline citation carries the path and a line or line range in its link text, and an
# empty href: `[packages/mcp/src/index.ts:12-40]()`. The path is captured without the range.
_INLINE_CITATION = re.compile(r"\[([^\[\]]+):\d+(?:-\d+)?\]\(\)")

# Worse outcomes rank higher. `broken` is the exact failure this module exists to catch, so it
# ranks worst. `unknown` ranks above `drifted`: an incomplete comparison cannot rule out a page
# actually being broken, so treating it as merely `drifted` would understate the risk.
_VERDICT_SEVERITY: dict[DriftVerdict, int] = {"intact": 0, "drifted": 1, "unknown": 2, "broken": 3}


def cited_files(page_text: str) -> list[str]:
    """Every file `page_text` cites: its "Relevant source files" block and its inline citations.

    Tolerates a page with no such block, a block that lists nothing, and citations with a
    trailing `:line` or `:start-end` range, which is stripped before the path is returned.

    Args:
        page_text: The full text of one cached wiki page.

    Returns:
        The sorted, deduplicated set of paths the page cites.
    """
    paths: set[str] = set()

    block_match = _SOURCE_FILES_BLOCK.search(page_text)
    if block_match:
        for label, _href in _MARKDOWN_LINK.findall(block_match.group(1)):
            stripped = label.strip()
            if stripped:
                paths.add(stripped)

    for label in _INLINE_CITATION.findall(page_text):
        stripped = label.strip()
        if stripped:
            paths.add(stripped)

    return sorted(paths)


def page_drift(
    page_number: int, title: str, page_text: str, changed: dict[str, FileChange], complete: bool
) -> PageDrift:
    """Whether one page's citations still match the repository.

    Args:
        page_number: The page's number, as `WikiIndex.pages` numbers it.
        title: The page's title.
        page_text: The page's full text, to extract citations from.
        changed: Every file GitHub reports changed, keyed by filename.
        complete: Whether `changed` is the full set, or a walk that stopped partway through.
            A cited file absent from an incomplete `changed` is reported `unknown`, never
            `intact`: absence from a truncated comparison is not evidence of anything.

    Returns:
        A `PageDrift` for this page alone.
    """
    files = cited_files(page_text)
    changed_here: list[FileChange] = []
    removed_here: list[FileChange] = []
    intact_here: list[str] = []

    for filename in files:
        entry = changed.get(filename)
        if entry is None:
            intact_here.append(filename)
            continue
        changed_here.append(entry)
        if entry.status in ("removed", "renamed"):
            removed_here.append(entry)

    if removed_here:
        verdict: DriftVerdict = "broken"
    elif changed_here:
        verdict = "drifted"
    elif not complete and intact_here:
        verdict = "unknown"
    else:
        verdict = "intact"

    return PageDrift(
        page_number=page_number,
        title=title,
        cited_files=files,
        changed=changed_here,
        removed=removed_here,
        intact=intact_here,
        verdict=verdict,
        summary=_page_summary(page_number, title, verdict, changed_here, removed_here, complete),
    )


def report(
    repo: str,
    indexed_sha: str | None,
    head_sha: str | None,
    pages: list[PageDrift],
    changed_file_count: int,
    complete: bool,
) -> DriftReport:
    """Roll per-page drift into one report, whose verdict is the worst page verdict, never an average.

    Args:
        repo: The repository slug this report is for.
        indexed_sha: The commit DeepWiki states it indexed, or None when unmeasured.
        head_sha: The repository's live head commit, or None when unmeasured.
        pages: One `PageDrift` per page measured.
        changed_file_count: How many files GitHub reported changed, across whatever of the
            comparison was walked.
        complete: Whether that walk covered the full changed-file list.

    Returns:
        A `DriftReport` naming the worst page verdict present and a one-line summary.
    """
    verdict: DriftVerdict = (
        "unknown" if not pages else max(pages, key=lambda page: _VERDICT_SEVERITY[page.verdict]).verdict
    )
    return DriftReport(
        repo=repo,
        indexed_sha=indexed_sha,
        head_sha=head_sha,
        pages=pages,
        verdict=verdict,
        changed_file_count=changed_file_count,
        comparison_complete=complete,
        summary=_report_summary(repo, verdict, pages, changed_file_count, complete),
    )


def _page_summary(
    page_number: int,
    title: str,
    verdict: DriftVerdict,
    changed_here: list[FileChange],
    removed_here: list[FileChange],
    complete: bool,
) -> str:
    """One line a caller can show a person verbatim, naming the real counts for this page."""
    where = f"Page {page_number} ('{title}')"
    if verdict == "broken":
        names = ", ".join(f"{change.filename} ({change.status})" for change in removed_here)
        return f"{where} is broken: {len(removed_here)} of its cited file(s) no longer resolve: {names}."
    if verdict == "drifted":
        return f"{where} is drifted: {len(changed_here)} of its cited file(s) changed since indexing."
    if verdict == "unknown":
        reason = "the changed-file comparison was incomplete" if not complete else "the comparison could not be made"
        return f"{where} is unknown: {reason}, so its citations cannot be trusted."
    return f"{where} is intact: none of its cited files changed."


def _report_summary(
    repo: str, verdict: DriftVerdict, pages: list[PageDrift], changed_file_count: int, complete: bool
) -> str:
    """One line a caller can show a person verbatim, naming the real counts across the report."""
    if not pages:
        return f"{repo}: unknown, no pages were measured."
    broken = sum(1 for page in pages if page.verdict == "broken")
    drifted = sum(1 for page in pages if page.verdict == "drifted")
    unknown = sum(1 for page in pages if page.verdict == "unknown")
    incomplete_clause = " The changed-file comparison was incomplete." if not complete else ""
    return (
        f"{repo}: {verdict} across {len(pages)} page(s) measured ({broken} broken, {drifted} drifted, "
        f"{unknown} unknown), {changed_file_count} file(s) changed since indexing.{incomplete_clause}"
    )
