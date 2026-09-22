"""Drift: whether a cached wiki's pages still match the repository, page by page.

Loads the cached index `fetch` already wrote, reads the commits `freshness` would compare,
walks GitHub's compare API for every file changed since indexing, and intersects that against
each page's own citations through `lore.drift`. No model is consulted.
"""

from lore import store
from lore.capabilities.freshness import core as freshness_core
from lore.drift import page_drift, report
from lore.schemas import DriftReport, FileChange
from lore.sources import github

# One read per page, deliberately far larger than any real wiki page: `store.read_page` caps
# and truncates by construction, and drift must see every citation on the page, not a slice.
_FULL_PAGE_LIMIT = 100_000_000


def drift(repo: str, page: int | str | None = None, timeout_seconds: float = 60.0) -> DriftReport:
    """Measure whether a cached wiki's pages still match the repository, page by page.

    Args:
        repo: The repository slug `fetch` cached, e.g. `owner/name`.
        page: Restrict the measurement to one page, by number or a case-insensitive title
            substring; `None` measures every cached page.
        timeout_seconds: Per-request timeout for the GitHub compare call.

    Returns:
        A `DriftReport` whose verdict is the worst page verdict present. `comparison_complete`
        is `False`, and every page whose citations could not be ruled out is `unknown` rather
        than `intact`, when GitHub's changed-file list could not be enumerated in full or the
        indexed or head commit is itself unknown.

    Raises:
        LoreError: No wiki is cached for `repo`, or `page` matches no cached page or more than one.
    """
    index = store.load_index(repo)
    ref = freshness_core.parse_repo(repo)
    numbers: list[int | str] = [page] if page is not None else [entry.number for entry in index.pages]

    indexed_sha = index.freshness.indexed_sha
    head_sha = index.freshness.head_sha
    changed_by_path: dict[str, FileChange] = {}
    changed_file_count = 0
    complete = False
    if indexed_sha is not None and head_sha is not None:
        changes, complete = github.changed_files(ref, indexed_sha, head_sha, timeout_seconds=timeout_seconds)
        changed_by_path = {change.filename: change for change in changes}
        changed_file_count = len(changes)

    page_drifts = []
    for number in numbers:
        read_result = store.read_page(repo, number, limit=_FULL_PAGE_LIMIT)
        page_drifts.append(
            page_drift(read_result.page_number, read_result.page_title, read_result.text, changed_by_path, complete)
        )

    return report(repo, indexed_sha, head_sha, page_drifts, changed_file_count, complete)
