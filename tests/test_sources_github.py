import subprocess
from typing import Any

import httpx
import pytest

from lore.schemas import LoreError, RepoRef
from lore.sources import github

REPO = RepoRef(owner="upstash", repo="context7")


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


def _files_page(count: int, status: str = "modified", start: int = 0) -> dict[str, Any]:
    return {
        "files": [
            {"filename": f"file{index}.py", "status": status, "changes": 1} for index in range(start, start + count)
        ]
    }


def test_changed_files_returns_a_single_short_page_as_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "_get", lambda path, timeout_seconds: (httpx.codes.OK, _files_page(2)))

    changes, complete = github.changed_files(REPO, "base", "head")

    assert complete is True
    assert [change.filename for change in changes] == ["file0.py", "file1.py"]


def test_changed_files_walks_every_page_until_a_short_page_ends_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A full 300-row page is not proof of the last page; the walk must keep going."""
    calls: list[str] = []

    def _fake_get(path: str, timeout_seconds: float) -> tuple[int, Any]:
        calls.append(path)
        if "page=1" in path:
            return httpx.codes.OK, _files_page(github.COMPARE_FILES_PAGE_SIZE, start=0)
        if "page=2" in path:
            return httpx.codes.OK, _files_page(5, start=github.COMPARE_FILES_PAGE_SIZE)
        raise AssertionError(f"unexpected path requested: {path}")

    monkeypatch.setattr(github, "_get", _fake_get)

    changes, complete = github.changed_files(REPO, "base", "head")

    assert complete is True
    assert len(calls) == 2
    assert len(changes) == github.COMPARE_FILES_PAGE_SIZE + 5


def test_changed_files_reports_incomplete_when_a_page_request_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """The load-bearing rule: a failure mid-walk must never be reported as a complete, empty result."""

    def _fake_get(path: str, timeout_seconds: float) -> tuple[int, Any]:
        if "page=1" in path:
            return httpx.codes.OK, _files_page(github.COMPARE_FILES_PAGE_SIZE, start=0)
        return httpx.codes.FORBIDDEN, {"message": "rate limited"}

    monkeypatch.setattr(github, "_get", _fake_get)

    changes, complete = github.changed_files(REPO, "base", "head")

    assert complete is False
    assert len(changes) == github.COMPARE_FILES_PAGE_SIZE


def test_changed_files_reports_incomplete_when_the_response_carries_no_files_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(github, "_get", lambda path, timeout_seconds: (httpx.codes.OK, {"ahead_by": 3}))

    changes, complete = github.changed_files(REPO, "base", "head")

    assert complete is False
    assert changes == []


def test_changed_files_normalizes_an_unrecognized_status_and_keeps_it_off_the_removed_paths() -> None:
    entry = github._file_change({"filename": "a.py", "status": "copied", "changes": 1})

    assert entry.status == "unknown"


def test_changed_files_carries_previous_filename_for_a_rename() -> None:
    entry = github._file_change(
        {"filename": "new.py", "status": "renamed", "changes": 1, "previous_filename": "old.py"}
    )

    assert entry.status == "renamed"
    assert entry.previous_filename == "old.py"


def test_file_at_ref_decodes_base64_content(monkeypatch: pytest.MonkeyPatch) -> None:
    import base64

    encoded = base64.b64encode(b"hello world").decode("ascii")
    monkeypatch.setattr(
        github, "_get", lambda path, timeout_seconds: (httpx.codes.OK, {"content": encoded, "encoding": "base64"})
    )

    assert github.file_at_ref(REPO, "a.py", "main") == "hello world"


def test_file_at_ref_raises_a_named_error_when_the_path_is_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "_get", lambda path, timeout_seconds: (httpx.codes.NOT_FOUND, {"message": "Not Found"}))

    with pytest.raises(LoreError, match="does not exist"):
        github.file_at_ref(REPO, "gone.py", "main")


def test_file_at_ref_raises_when_the_response_carries_no_base64_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        github, "_get", lambda path, timeout_seconds: (httpx.codes.OK, {"content": "not-base64-flagged"})
    )

    with pytest.raises(LoreError, match="did not carry base64 content"):
        github.file_at_ref(REPO, "a.py", "main")
