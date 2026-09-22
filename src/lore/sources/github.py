"""GitHub's REST API: the live side of a freshness measurement, working with no credentials."""

import base64
import binascii
import json
import os
import re
import shutil
import subprocess
from typing import Any
from urllib.parse import quote

import httpx

from lore.schemas import FileAbsentAtRefError, FileChange, FileNotTextAtRefError, FileStatus, LoreError, RepoRef

API_BASE = "https://api.github.com"
TOKEN_ENV = "GITHUB_TOKEN"

_GH_STATUS = re.compile(r"\(HTTP (\d+)\)")

# GitHub hard-caps the compare endpoint's `files` array at 300 entries per page and moves
# through more with `?page=N`; there is no `per_page` to raise that cap. A page shorter than
# this is the last one, by construction: continuing past it would ask for a page that does
# not exist rather than reveal more files.
COMPARE_FILES_PAGE_SIZE = 300
_KNOWN_FILE_STATUSES = frozenset({"added", "modified", "removed", "renamed"})


def default_branch(repo: RepoRef, timeout_seconds: float = 30.0) -> str:
    """The name of `repo`'s default branch."""
    status, body = _get(f"repos/{repo.owner}/{repo.repo}", timeout_seconds)
    if status != httpx.codes.OK:
        raise LoreError(
            f"Could not read {repo.slug}'s default branch: {_error_detail(status, body)}. Confirm the "
            "repository exists and is public, or retry if GitHub is rate-limiting the request; "
            "authenticate with `gh auth login` or set GITHUB_TOKEN to raise anonymous rate limits."
        )
    branch = body.get("default_branch") if isinstance(body, dict) else None
    if not branch:
        raise LoreError(
            f"GitHub's response for {repo.slug} did not carry a default_branch. Retry; if it keeps "
            f"happening, run `gh api repos/{repo.owner}/{repo.repo}` directly to inspect the raw response."
        )
    return branch


def head_commit(repo: RepoRef, branch: str, timeout_seconds: float = 30.0) -> tuple[str, str]:
    """The sha and committer date at the head of `branch`."""
    status, body = _get(f"repos/{repo.owner}/{repo.repo}/commits/{branch}", timeout_seconds)
    if status != httpx.codes.OK:
        raise LoreError(
            f"Could not read {repo.slug}'s head of '{branch}': {_error_detail(status, body)}. Confirm "
            "the branch name is correct, or retry if GitHub is rate-limiting the request; authenticate "
            "with `gh auth login` or set GITHUB_TOKEN to raise anonymous rate limits."
        )
    sha, date = _head_commit_from_json(body) if isinstance(body, dict) else (None, None)
    if sha is None or date is None:
        raise LoreError(
            f"GitHub's response for {repo.slug}@{branch} did not carry a commit sha and date. Retry; "
            f"if it keeps happening, run `gh api repos/{repo.owner}/{repo.repo}/commits/{branch}` "
            "directly to inspect the raw response."
        )
    return sha, date


def commits_between(repo: RepoRef, base_sha: str, head: str, timeout_seconds: float = 30.0) -> int | None:
    """How many commits `head` leads `base_sha` by, or None when the comparison could not be made.

    None covers an unknown base sha, a rate limit, or any other failure: an unmeasurable gap is a
    reported unknown here, never a raised error.
    """
    status, body = _get(f"repos/{repo.owner}/{repo.repo}/compare/{base_sha}...{head}", timeout_seconds)
    if status != httpx.codes.OK or not isinstance(body, dict):
        return None
    ahead_by = body.get("ahead_by")
    return ahead_by if isinstance(ahead_by, int) else None


def repository_exists(repo: RepoRef, timeout_seconds: float = 30.0) -> bool:
    """Whether `repo` exists and is visible with the credentials on hand."""
    status, body = _get(f"repos/{repo.owner}/{repo.repo}", timeout_seconds)
    if status == httpx.codes.OK:
        return True
    if status == httpx.codes.NOT_FOUND:
        return False
    raise LoreError(
        f"Could not tell whether {repo.slug} exists: {_error_detail(status, body)}. Retry; if GitHub "
        "is rate-limiting anonymous requests, authenticate with `gh auth login` or set GITHUB_TOKEN."
    )


def changed_files(
    repo: RepoRef, base_sha: str, head: str, timeout_seconds: float = 60.0
) -> tuple[list[FileChange], bool]:
    """Every file changed between `base_sha` and `head`, paginated to exhaustion.

    Returns `(changes, complete)`. `complete` is False when a request failed or returned a
    shape this could not read, which stops the walk wherever it had gotten to. A caller must
    never treat an incomplete result as proof a given file did not change: absence from a
    truncated list is not evidence of anything, only silence.
    """
    changes: list[FileChange] = []
    page = 1
    while True:
        status, body = _get(f"repos/{repo.owner}/{repo.repo}/compare/{base_sha}...{head}?page={page}", timeout_seconds)
        if status != httpx.codes.OK or not isinstance(body, dict):
            return changes, False
        files = body.get("files")
        if not isinstance(files, list):
            return changes, False
        changes.extend(_file_change(entry) for entry in files if isinstance(entry, dict))
        if len(files) < COMPARE_FILES_PAGE_SIZE:
            return changes, True
        page += 1


def file_at_ref(repo: RepoRef, path: str, ref: str, timeout_seconds: float = 30.0) -> str:
    """The text of `path` in `repo` at `ref`, decoded from GitHub's contents API.

    Raises:
        FileAbsentAtRefError: GitHub confirms with a 404 that `path` does not exist at `ref`.
            A caller (see `explain --at-head`) may treat this, and only this, as information
            about the citation rather than a retrieval failure.
        FileNotTextAtRefError: GitHub fetched `path` at `ref` successfully and its content is
            not valid UTF-8 (e.g. a binary file). The fetch itself succeeded, so a caller may
            treat this, like `FileAbsentAtRefError`, as information about the file rather than
            a retrieval failure.
        LoreError: any other failure: a non-200/404 status, a rate limit, a network error, or a
            response that could not be read or whose content was not valid base64. None of
            these are evidence about the file itself, and a caller must not reclassify them as
            such.
    """
    encoded_path = "/".join(quote(segment, safe="") for segment in path.split("/"))
    status, body = _get(f"repos/{repo.owner}/{repo.repo}/contents/{encoded_path}?ref={ref}", timeout_seconds)
    if status == httpx.codes.NOT_FOUND:
        raise FileAbsentAtRefError(
            f"'{path}' does not exist in {repo.slug} at {ref}. It may have been removed or renamed."
        )
    if status != httpx.codes.OK or not isinstance(body, dict):
        raise LoreError(
            f"Could not read {repo.slug}'s '{path}' at {ref}: {_error_detail(status, body)}. Retry; if "
            "GitHub is rate-limiting anonymous requests, authenticate with `gh auth login` or set "
            "GITHUB_TOKEN."
        )
    content = body.get("content")
    if not isinstance(content, str) or body.get("encoding") != "base64":
        raise LoreError(
            f"GitHub's response for {repo.slug}'s '{path}' at {ref} did not carry base64 content. Retry; "
            f"if it keeps happening, run `gh api repos/{repo.owner}/{repo.repo}/contents/{encoded_path}"
            f"?ref={ref}` directly to inspect the raw response."
        )
    try:
        raw = base64.b64decode(content)
    except binascii.Error as error:
        raise LoreError(
            f"Could not decode {repo.slug}'s '{path}' at {ref}: {error}. GitHub's response did not "
            "carry valid base64 content. Retry; if it keeps happening, run "
            f"`gh api repos/{repo.owner}/{repo.repo}/contents/{encoded_path}?ref={ref}` directly to "
            "inspect the raw response."
        ) from error
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        # The fetch above already succeeded: GitHub returned exactly the bytes at this path and
        # ref. A decode failure here is a stable property of the file (it is binary, e.g. an
        # image a wiki page legitimately cites), not a transport failure, so it must raise a
        # type distinct from the plain LoreError a rate limit or network error would -- folding
        # it into that generic type took down an --at-head answer over a legitimately cited
        # binary file even though the retrieval itself worked.
        raise FileNotTextAtRefError(
            f"'{path}' in {repo.slug} at {ref} is not valid UTF-8 text (e.g. a binary file): {error}. "
            "--at-head only supports text files."
        ) from error


def _file_change(entry: dict[str, Any]) -> FileChange:
    status = entry.get("status")
    changes = entry.get("changes")
    normalized_status: FileStatus = status if status in _KNOWN_FILE_STATUSES else "unknown"
    return FileChange(
        filename=str(entry.get("filename", "")),
        status=normalized_status,
        changes=changes if isinstance(changes, int) else 0,
        previous_filename=entry.get("previous_filename"),
    )


def _head_commit_from_json(body: dict[str, Any]) -> tuple[str | None, str | None]:
    sha = body.get("sha")
    committer = (body.get("commit") or {}).get("committer") or {}
    return sha, committer.get("date")


def _error_detail(status: int, body: Any) -> str:
    if isinstance(body, dict):
        message = body.get("message")
        if message:
            return f"HTTP {status}: {message}"
    return f"HTTP {status}: {body}"


def _get(path: str, timeout_seconds: float) -> tuple[int, Any]:
    """The parsed body and status code for one GitHub API path, preferring the `gh` CLI when it is signed in."""
    if _gh_available():
        return _get_via_gh(path, timeout_seconds)
    return _get_via_http(path, timeout_seconds)


def _gh_available() -> bool:
    if shutil.which("gh") is None:
        return False
    try:
        status = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return status.returncode == 0


def _get_via_gh(path: str, timeout_seconds: float) -> tuple[int, Any]:
    try:
        result = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 0, str(error)
    if result.returncode == 0:
        try:
            return httpx.codes.OK, json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise LoreError(
                f"'gh api {path}' returned output that could not be parsed as JSON: {error}. "
                f"Retry the command; if it keeps happening, run `gh api {path}` directly to see the raw response."
            ) from error
    return status_from_gh_stderr(result.stderr), result.stderr.strip()


def _get_via_http(path: str, timeout_seconds: float) -> tuple[int, Any]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get(TOKEN_ENV)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=_timeout(timeout_seconds)) as client:
            response = client.get(f"{API_BASE}/{path}", headers=headers)
    except httpx.HTTPError as error:
        raise LoreError(
            f"GitHub request to {path} failed: {error}. Retry the call, check network connectivity, or "
            "(if GitHub is rate-limiting anonymous requests) authenticate with `gh auth login` or set "
            "GITHUB_TOKEN before rerunning."
        ) from error
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


def status_from_gh_stderr(stderr: str) -> int:
    """The HTTP status `gh api` reported on failure, or 0 when its message does not carry one."""
    match = _GH_STATUS.search(stderr)
    return int(match.group(1)) if match else 0


def _timeout(read_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(connect=10.0, read=read_seconds, write=30.0, pool=10.0)
