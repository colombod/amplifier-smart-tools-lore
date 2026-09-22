import pytest

from lore.capabilities.freshness import core
from lore.schemas import LoreError, RepoRef


def test_parse_repo_accepts_the_plain_owner_name_form() -> None:
    assert core.parse_repo("upstash/context7") == RepoRef(owner="upstash", repo="context7")


def test_parse_repo_strips_surrounding_whitespace() -> None:
    assert core.parse_repo("  upstash/context7  ") == RepoRef(owner="upstash", repo="context7")


def test_parse_repo_accepts_a_full_github_url() -> None:
    assert core.parse_repo("https://github.com/upstash/context7") == RepoRef(owner="upstash", repo="context7")


def test_parse_repo_accepts_a_github_url_with_a_trailing_git_suffix() -> None:
    assert core.parse_repo("https://github.com/upstash/context7.git") == RepoRef(owner="upstash", repo="context7")


def test_parse_repo_accepts_a_github_url_with_a_path_past_the_repo() -> None:
    assert core.parse_repo("https://github.com/upstash/context7/tree/main") == RepoRef(owner="upstash", repo="context7")


def test_parse_repo_accepts_a_www_github_url() -> None:
    assert core.parse_repo("https://www.github.com/upstash/context7") == RepoRef(owner="upstash", repo="context7")


def test_parse_repo_rejects_a_non_github_url() -> None:
    with pytest.raises(LoreError, match="owner/name"):
        core.parse_repo("https://gitlab.com/upstash/context7")


def test_parse_repo_rejects_a_bare_string_with_no_slash() -> None:
    with pytest.raises(LoreError, match="owner/name"):
        core.parse_repo("upstash")


def test_parse_repo_rejects_more_than_one_slash_in_plain_form() -> None:
    with pytest.raises(LoreError, match="owner/name"):
        core.parse_repo("upstash/context7/extra")


def test_parse_repo_rejects_an_empty_string() -> None:
    with pytest.raises(LoreError, match="owner/name"):
        core.parse_repo("")


@pytest.mark.parametrize(
    ("commits_behind", "days_behind", "expected"),
    [
        (None, None, "unknown"),
        (None, 5, "unknown"),
        (0, 0, "current"),
        (0, 100, "current"),
        (25, 30, "aging"),
        (1, 0, "aging"),
        (26, 0, "stale"),
        (25, 31, "stale"),
        (25, None, "stale"),
        (100, 100, "stale"),
    ],
)
def test_verdict_boundaries(commits_behind: int | None, days_behind: int | None, expected: str) -> None:
    assert core._verdict(commits_behind, days_behind) == expected


def test_days_behind_floors_to_whole_days() -> None:
    assert core._days_behind("2026-07-20", "2026-07-20T23:59:59Z") == 0
    assert core._days_behind("2026-07-20", "2026-07-21T00:00:01Z") == 1


def test_days_behind_never_goes_negative_when_head_precedes_indexed() -> None:
    assert core._days_behind("2026-07-20", "2026-07-01T00:00:00Z") == 0


def test_days_behind_is_none_when_either_date_is_unreadable() -> None:
    assert core._days_behind(None, "2026-07-20T00:00:00Z") is None
    assert core._days_behind("2026-07-20", None) is None
    assert core._days_behind("not a date", "2026-07-20T00:00:00Z") is None


def test_parse_moment_reads_a_date_only_string_and_a_full_timestamp() -> None:
    assert core._parse_moment("2026-07-20") is not None
    assert core._parse_moment("2026-07-20T12:00:00Z") is not None
    assert core._parse_moment(None) is None
    assert core._parse_moment("") is None
    assert core._parse_moment("not a date") is None


def test_summary_unknown_names_the_unmeasured_reason() -> None:
    ref = RepoRef(owner="owner", repo="repo")

    summary = core._summary_unknown(ref, ["DeepWiki's page did not carry an indexed commit."])

    assert "owner/repo" in summary
    assert "DeepWiki's page did not carry an indexed commit." in summary


def test_summary_unknown_has_a_fallback_reason_when_nothing_was_recorded() -> None:
    ref = RepoRef(owner="owner", repo="repo")

    summary = core._summary_unknown(ref, [])

    assert "owner/repo" in summary


def test_summary_measured_says_current_plainly() -> None:
    ref = RepoRef(owner="owner", repo="repo")

    summary = core._summary_measured(ref, "abc123", "2026-07-20", "abc123", 0, 0)

    assert summary == "DeepWiki's index for owner/repo is current, at abc123 (2026-07-20)."


def test_summary_measured_names_the_real_numbers_when_behind() -> None:
    ref = RepoRef(owner="upstash", repo="context7")

    summary = core._summary_measured(ref, "23843e9c", "2026-07-20", "eb27b949", 82, 63)

    assert "upstash/context7" in summary
    assert "23843e9c" in summary
    assert "eb27b949" in summary
    assert "82 commits" in summary
    assert "63 days" in summary


def test_summary_measured_omits_the_days_clause_when_days_behind_is_unknown() -> None:
    ref = RepoRef(owner="owner", repo="repo")

    summary = core._summary_measured(ref, "abc123", "2026-07-20", "def456", 5, None)

    assert "5 commits" in summary
    assert "days" not in summary


def test_summary_measured_singularizes_one_commit_and_one_day() -> None:
    ref = RepoRef(owner="owner", repo="repo")

    summary = core._summary_measured(ref, "abc123", "2026-07-20", "def456", 1, 1)

    assert "1 commit " in summary or summary.endswith("1 commit old.")
    assert "1 day" in summary
    assert "1 commits" not in summary
    assert "1 days" not in summary
