"""Drift: whether a cached wiki's pages still match the repository, page by page.

Loads the cached index `fetch` already wrote, reads the commits `freshness` would compare,
walks GitHub's compare API for every file changed since indexing, and intersects that against
each page's own citations through `lore.drift`. No model is consulted.
"""

from lore import store
from lore.capabilities.freshness import core as freshness_core
from lore.drift import page_drift, report
from lore.schemas import DriftReport, FileChange, RepoRef
from lore.sources import github

# One read per page, deliberately far larger than any real wiki page: `store.read_page` caps
# and truncates by construction, and drift must see every citation on the page, not a slice.
_FULL_PAGE_LIMIT = 100_000_000


def changed_file_map(
    ref: RepoRef, indexed_sha: str | None, head_sha: str | None, timeout_seconds: float = 60.0
) -> tuple[dict[str, FileChange], bool]:
    """Every file GitHub reports changed between `indexed_sha` and `head_sha`, keyed by filename.

    The raw signal `drift()` intersects against each page's own citations. Factored out so any
    other caller needing the same changed-file map (`explain --at-head`'s file ranking, for
    instance) gets it through the one path that walks GitHub's compare API, rather than a second
    copy of that walk.

    Args:
        ref: The repository to compare.
        indexed_sha: The commit DeepWiki states it indexed, or None when unmeasured.
        head_sha: The repository's live head commit, or None when unmeasured.
        timeout_seconds: Per-request timeout for the GitHub compare call.

    Returns:
        `(changed_by_path, complete)`. Empty and `complete=False` when either commit is unknown:
        an unmeasured commit means no comparison could be walked at all, not that nothing changed.
    """
    if indexed_sha is None or head_sha is None:
        return {}, False
    changes, complete = github.changed_files(ref, indexed_sha, head_sha, timeout_seconds=timeout_seconds)
    return {change.filename: change for change in changes}, complete


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
    changed_by_path, complete = changed_file_map(ref, indexed_sha, head_sha, timeout_seconds=timeout_seconds)
    changed_file_count = len(changed_by_path)

    page_drifts = []
    for number in numbers:
        read_result = store.read_page(repo, number, limit=_FULL_PAGE_LIMIT)
        page_drifts.append(
            page_drift(read_result.page_number, read_result.page_title, read_result.text, changed_by_path, complete)
        )

    return report(repo, indexed_sha, head_sha, page_drifts, changed_file_count, complete)
