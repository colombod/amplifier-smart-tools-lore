import subprocess
from typing import Any

import pytest

from lore.schemas import LoreError
from lore.sources import github


def test_get_via_gh_raises_a_lore_error_on_malformed_json_instead_of_json_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], returncode=0, stdout="not json", stderr="")

    monkeypatch.setattr(github.subprocess, "run", _fake_run)

    with pytest.raises(LoreError, match="could not be parsed as JSON"):
        github._get_via_gh("repos/owner/repo", 5.0)


def test_status_from_gh_stderr_reads_the_parenthesized_http_code() -> None:
    assert github.status_from_gh_stderr("gh: Not Found (HTTP 404)") == 404


def test_status_from_gh_stderr_reads_a_rate_limit_code() -> None:
    assert github.status_from_gh_stderr("gh: API rate limit exceeded (HTTP 403)") == 403


def test_status_from_gh_stderr_returns_zero_when_no_code_is_present() -> None:
    assert github.status_from_gh_stderr("gh: could not resolve host") == 0


def test_head_commit_from_json_reads_sha_and_committer_date() -> None:
    body = {"sha": "abc123", "commit": {"committer": {"date": "2026-07-20T00:00:00Z"}}}

    assert github._head_commit_from_json(body) == ("abc123", "2026-07-20T00:00:00Z")


def test_head_commit_from_json_tolerates_a_missing_commit_section() -> None:
    assert github._head_commit_from_json({"sha": "abc123"}) == ("abc123", None)


def test_head_commit_from_json_tolerates_a_completely_empty_payload() -> None:
    assert github._head_commit_from_json({}) == (None, None)


def test_error_detail_prefers_the_bodys_message() -> None:
    assert github._error_detail(404, {"message": "Not Found"}) == "HTTP 404: Not Found"


def test_error_detail_falls_back_to_the_raw_body_when_there_is_no_message() -> None:
    assert github._error_detail(500, "internal error") == "HTTP 500: internal error"
