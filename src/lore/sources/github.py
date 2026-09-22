"""GitHub's REST API: the live side of a freshness measurement, working with no credentials."""

import json
import os
import re
import shutil
import subprocess
from typing import Any

import httpx

from lore.schemas import LoreError, RepoRef

API_BASE = "https://api.github.com"
TOKEN_ENV = "GITHUB_TOKEN"

_GH_STATUS = re.compile(r"\(HTTP (\d+)\)")


def default_branch(repo: RepoRef, timeout_seconds: float = 30.0) -> str:
    """The name of `repo`'s default branch."""
    status, body = _get(f"repos/{repo.owner}/{repo.repo}", timeout_seconds)
    if status != httpx.codes.OK:
        raise LoreError(f"Could not read {repo.slug}'s default branch: {_error_detail(status, body)}")
    branch = body.get("default_branch") if isinstance(body, dict) else None
    if not branch:
        raise LoreError(f"GitHub's response for {repo.slug} did not carry a default_branch.")
    return branch


def head_commit(repo: RepoRef, branch: str, timeout_seconds: float = 30.0) -> tuple[str, str]:
    """The sha and committer date at the head of `branch`."""
    status, body = _get(f"repos/{repo.owner}/{repo.repo}/commits/{branch}", timeout_seconds)
    if status != httpx.codes.OK:
        raise LoreError(f"Could not read {repo.slug}'s head of '{branch}': {_error_detail(status, body)}")
    sha, date = _head_commit_from_json(body) if isinstance(body, dict) else (None, None)
    if sha is None or date is None:
        raise LoreError(f"GitHub's response for {repo.slug}@{branch} did not carry a commit sha and date.")
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
    raise LoreError(f"Could not tell whether {repo.slug} exists: {_error_detail(status, body)}")


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
        raise LoreError(f"GitHub request to {path} failed: {error}") from error
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
