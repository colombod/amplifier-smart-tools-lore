"""Freshness: how far DeepWiki's index for a repository trails its live default branch.

Measured against two sources, never estimated: the commit DeepWiki states it indexed, read
off the page it renders for the repository, and the repository's live default branch, read
through the GitHub API. No model is consulted, so the result is a measurement and not an
opinion.
"""

from datetime import UTC, datetime
import re

from lore.schemas import Freshness, LoreError, RepoRef, StalenessVerdict
from lore.sources import deepwiki, github

# At or below both, DeepWiki's index is close enough to trust without a warning; past either,
# treat what it says as dated. Chosen to match the worked example in the tool's own vision doc.
AGING_COMMITS_LIMIT = 25
AGING_DAYS_LIMIT = 30

_PLAIN_REPO = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)$")
_GITHUB_URL = re.compile(r"^https?://(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)")


def parse_repo(value: str) -> RepoRef:
    """`value` as a `RepoRef`: `owner/name`, or a full `https://github.com/owner/name` URL.

    Args:
        value: The repository, as `owner/name` or a `github.com` URL. A URL's trailing
            `.git` and any path past the repository name are ignored.

    Returns:
        The parsed owner and repository name.

    Raises:
        LoreError: `value` matches neither accepted form.
    """
    text = value.strip()
    match = _GITHUB_URL.match(text) if text.startswith(("http://", "https://")) else _PLAIN_REPO.match(text)
    if match is None:
        raise LoreError(
            f"'{value}' is not a repository lore understands. "
            "Use 'owner/name' or a full 'https://github.com/owner/name' URL."
        )
    return RepoRef(owner=match.group("owner"), repo=match.group("repo").removesuffix(".git"))


def measure(repo: str, timeout_seconds: float = 30.0) -> Freshness:
    """How far DeepWiki's index for `repo` trails its live default branch, measured now.

    Args:
        repo: The repository, as `owner/name` or a full `https://github.com/owner/name` URL.
        timeout_seconds: Per-request timeout for each of the sources this consults.

    Returns:
        The indexed and head commits, the gap between them, a verdict, and a one-line
        summary safe to show a person verbatim. `commits_behind` and `days_behind` are
        `None`, and the verdict is `"unknown"`, when a required signal could not be read;
        `unmeasured` names each one and why.

    Raises:
        LoreError: `repo` does not parse, or GitHub reports no such repository.
    """
    ref = parse_repo(repo)
    if not github.repository_exists(ref, timeout_seconds):
        raise LoreError(
            f"GitHub reports no repository at '{ref.slug}'. It may not exist, be private, "
            "or be misspelled. DeepWiki covers public repositories only."
        )

    unmeasured: list[str] = []

    indexed_sha, indexed_date = deepwiki.indexed_commit(ref, timeout_seconds)
    if indexed_sha is None:
        # A repository DeepWiki has never indexed renders a shell page with no "Last indexed"
        # marker, and its MCP endpoint answers "Repository not found. Visit ... to index it."
        # Both were observed together, so name the state and the fix rather than reporting a
        # parse failure the caller can do nothing with.
        unmeasured.append(
            f"DeepWiki has no indexed wiki for {ref.slug}, so there is nothing to date. "
            f"Visit https://deepwiki.com/{ref.slug} to have it indexed, then measure again."
        )

    default_branch: str | None = None
    head_sha: str | None = None
    head_date: str | None = None
    try:
        default_branch = github.default_branch(ref, timeout_seconds)
        head_sha, head_date = github.head_commit(ref, default_branch, timeout_seconds)
    except LoreError as error:
        unmeasured.append(f"Could not read the repository's live head commit: {error}")

    commits_behind: int | None = None
    if indexed_sha is not None and default_branch is not None:
        commits_behind = github.commits_between(ref, indexed_sha, default_branch, timeout_seconds)
        if commits_behind is None:
            unmeasured.append(f"GitHub could not compare commit {indexed_sha} against '{default_branch}'.")

    days_behind = _days_behind(indexed_date, head_date)

    if indexed_sha is None or commits_behind is None or head_sha is None:
        verdict: StalenessVerdict = "unknown"
        summary = _summary_unknown(ref, unmeasured)
    else:
        verdict = _verdict(commits_behind, days_behind)
        summary = _summary_measured(ref, indexed_sha, indexed_date, head_sha, commits_behind, days_behind)

    return Freshness(
        repo=ref.slug,
        indexed_sha=indexed_sha,
        indexed_date=indexed_date,
        head_sha=head_sha,
        head_date=head_date,
        default_branch=default_branch,
        commits_behind=commits_behind,
        days_behind=days_behind,
        verdict=verdict,
        summary=summary,
        measured_at=datetime.now(UTC).isoformat(),
        unmeasured=unmeasured,
    )


def _verdict(commits_behind: int | None, days_behind: int | None) -> StalenessVerdict:
    """The verdict for one measurement.

    `commits_behind` is `None` only when the signal that would set it could not be read; by
    construction in `measure`, that always coincides with `indexed_sha` being unreadable too,
    so checking it alone is enough to decide `"unknown"`.
    """
    if commits_behind is None:
        return "unknown"
    if commits_behind == 0:
        return "current"
    if commits_behind <= AGING_COMMITS_LIMIT and days_behind is not None and days_behind <= AGING_DAYS_LIMIT:
        return "aging"
    return "stale"


def _days_behind(indexed_date: str | None, head_date: str | None) -> int | None:
    """Whole days from `indexed_date` to `head_date`, floored, never negative.

    `None` when either date cannot be read, which is a reported unknown rather than a guess.
    """
    indexed_moment = parse_moment(indexed_date)
    head_moment = parse_moment(head_date)
    if indexed_moment is None or head_moment is None:
        return None
    return max((head_moment - indexed_moment).days, 0)


def parse_moment(value: str | None) -> datetime | None:
    """`value` as a timezone-aware `datetime`, or `None` when it is not a date lore recognizes.

    Covers both shapes this module receives: DeepWiki's normalized `YYYY-MM-DD`, and GitHub's
    full `YYYY-MM-DDTHH:MM:SSZ` commit timestamps. Public: `lore.capabilities.howto.core` also
    uses it, to compare Context7's `last_update_date` against a repository's live head date.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _summary_unknown(ref: RepoRef, unmeasured: list[str]) -> str:
    """One line naming which signal could not be read, for the `"unknown"` verdict."""
    reason = " ".join(unmeasured) if unmeasured else "A required signal could not be read."
    return f"Freshness for {ref.slug} is unknown. {reason}"


def _summary_measured(
    ref: RepoRef,
    indexed_sha: str,
    indexed_date: str | None,
    head_sha: str,
    commits_behind: int,
    days_behind: int | None,
) -> str:
    """One line a caller can show a person verbatim, naming the real numbers."""
    if commits_behind == 0:
        return f"DeepWiki's index for {ref.slug} is current, at {indexed_sha} ({indexed_date})."
    commit_word = "commit" if commits_behind == 1 else "commits"
    days_clause = ""
    if days_behind is not None:
        day_word = "day" if days_behind == 1 else "days"
        days_clause = f" and {days_behind} {day_word}"
    return (
        f"DeepWiki indexed {ref.slug} at {indexed_sha} ({indexed_date}). The repository is "
        f"{commits_behind} {commit_word}{days_clause} further on, at {head_sha}. "
        f"Treat API details as {commits_behind} {commit_word} old."
    )
