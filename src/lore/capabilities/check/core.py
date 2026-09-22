"""Check: whether lore's prerequisites are reachable right now, deterministic and model-backed alike.

Every probe here is cheap and never raises: an unreachable service is a reported `ok=False`
with a `detail` naming what to do, never a failure of `check` itself.
"""

import os
import shutil
import subprocess

import httpx

from lore import store
from lore.core.manifest import requirement_install_url
from lore.schemas import CheckResult, LoreError, Reachability, RepoRef
from lore.sources import context7, deepwiki, github

_GH_AUTH_TIMEOUT_SECONDS = 10.0
# A repository that is certain to exist and to stay public, used only to probe reachability.
_GITHUB_PROBE_REPO = RepoRef(owner="octocat", repo="Hello-World")

_DEEPWIKI_MCP_NAME = "DeepWiki MCP"
_DEEPWIKI_PAGE_NAME = "deepwiki.com"
_CONTEXT7_NAME = "Context7 API"
_GITHUB_NAME = "GitHub API"
_COPILOT_NAME = "GitHub Copilot (model-backed capabilities)"


def check(timeout_seconds: float = 15.0) -> CheckResult:
    """Whether lore's prerequisites are usable right now.

    Args:
        timeout_seconds: Per-probe network timeout.

    Returns:
        One `Reachability` per prerequisite, plus whether the deterministic capabilities
        (`deterministic_ready`) and the model-backed ones (`model_backed_ready`) can run.
    """
    deepwiki_mcp = _deepwiki_mcp(timeout_seconds)
    deepwiki_page = _deepwiki_page(timeout_seconds)
    context7_api = _context7_api(timeout_seconds)
    github_api = _github_api(timeout_seconds)
    context7_key = _context7_api_key()
    cache_directory = _cache_directory()
    copilot = _copilot_prerequisite()

    deterministic_ready = deepwiki_mcp.ok and deepwiki_page.ok and github_api.ok and cache_directory.ok
    return CheckResult(
        checks=[deepwiki_mcp, deepwiki_page, context7_api, github_api, context7_key, cache_directory, copilot],
        deterministic_ready=deterministic_ready,
        model_backed_ready=copilot.ok,
    )


def _deepwiki_mcp(timeout_seconds: float) -> Reachability:
    """Whether DeepWiki's MCP endpoint answers a generic, repo-independent JSON-RPC call."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(deepwiki.ENDPOINT, json=payload, headers=deepwiki.HEADERS)
    except httpx.HTTPError as error:
        return Reachability(name=_DEEPWIKI_MCP_NAME, ok=False, detail=f"Could not reach {deepwiki.ENDPOINT}: {error}")
    return Reachability(
        name=_DEEPWIKI_MCP_NAME, ok=True, detail=f"{deepwiki.ENDPOINT} responded with HTTP {response.status_code}."
    )


def _deepwiki_page(timeout_seconds: float) -> Reachability:
    """Whether DeepWiki's own site, which `freshness` scrapes the indexed commit from, answers."""
    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            response = client.get(deepwiki.PAGE_BASE)
    except httpx.HTTPError as error:
        return Reachability(name=_DEEPWIKI_PAGE_NAME, ok=False, detail=f"Could not reach {deepwiki.PAGE_BASE}: {error}")
    return Reachability(
        name=_DEEPWIKI_PAGE_NAME, ok=True, detail=f"{deepwiki.PAGE_BASE} responded with HTTP {response.status_code}."
    )


def _context7_api(timeout_seconds: float) -> Reachability:
    """Whether Context7 answers a cheap, anonymous library search."""
    try:
        context7.search_libraries("python", "", limit=1, timeout_seconds=timeout_seconds)
    except LoreError as error:
        return Reachability(name=_CONTEXT7_NAME, ok=False, detail=str(error))
    return Reachability(name=_CONTEXT7_NAME, ok=True, detail=f"{context7.BASE_URL} answered a library search.")


def _github_api(timeout_seconds: float) -> Reachability:
    """Whether the GitHub API is reachable, and separately whether `gh` lifts its rate limit."""
    try:
        github.repository_exists(_GITHUB_PROBE_REPO, timeout_seconds)
    except LoreError as error:
        return Reachability(name=_GITHUB_NAME, ok=False, detail=str(error))
    authenticated = _gh_authenticated()
    detail = f"Reachable. gh authenticated: {authenticated} (only lifts GitHub's anonymous rate limit)."
    return Reachability(name=_GITHUB_NAME, ok=True, detail=detail)


def _context7_api_key() -> Reachability:
    """Whether the optional Context7 API key is set. Anonymous access works without it."""
    is_set = bool(os.environ.get(context7.API_KEY_ENV))
    detail = "Set." if is_set else f"Not set. Optional: {context7.API_KEY_ENV} lifts Context7's anonymous limits."
    return Reachability(name=context7.API_KEY_ENV, ok=is_set, detail=detail)


def _cache_directory() -> Reachability:
    """Whether lore's on-disk cache directory can actually be written to, not just created."""
    try:
        root = store.cache_root()
        probe_file = root / ".lore-check-write-probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink()
    except OSError as error:
        return Reachability(name="cache directory", ok=False, detail=f"Not writable: {error}")
    return Reachability(name="cache directory", ok=True, detail=f"{root} is writable.")


def _copilot_prerequisite() -> Reachability:
    """Whether the model-backed capabilities can run: `gh` installed and signed in."""
    authenticated = _gh_authenticated()
    detail = (
        "gh is installed and signed in."
        if authenticated
        else (
            f"gh must be installed ({requirement_install_url('gh')}) and `gh auth login` completed, "
            "with a Copilot subscription on that account."
        )
    )
    return Reachability(name=_COPILOT_NAME, ok=authenticated, detail=detail)


def _gh_authenticated() -> bool:
    """Whether the `gh` CLI is installed and signed in.

    Kept local rather than imported from `lore.sources.github`, which does not export this
    check: that module's own `gh` probe is an internal implementation detail of its transport
    choice, not a public reachability signal.
    """
    if shutil.which("gh") is None:
        return False
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=_GH_AUTH_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
