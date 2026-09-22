"""DeepWiki's MCP endpoint, spoken directly over JSON-RPC and its indexed-commit page, scraped."""

from datetime import datetime
import json
import re
from typing import Any

import httpx

from lore.schemas import LoreError, RepoRef

ENDPOINT = "https://mcp.deepwiki.com/mcp"
PAGE_BASE = "https://deepwiki.com"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

# DeepWiki advertises `ask_wiki_question` today, but the older `ask_question` name still answers,
# so a caller that hits an unrenamed deployment is not left without a working question tool.
ASK_TOOL = "ask_wiki_question"
ASK_TOOL_FALLBACK = "ask_question"

INDEXED_MARKER = "Last indexed:"
_COMMENT_MARKER = re.compile(r"<!--\s*-->")
_COMMIT_HREF = re.compile(r'href="[^"]*?/commits/([0-9a-fA-F]+)"')
_TAG = re.compile(r"<[^>]+>")


class _ToolCallError(Exception):
    """A tool call that did not succeed, carrying whether the tool itself was the problem."""

    def __init__(self, message: str, unknown_tool: bool) -> None:
        super().__init__(message)
        self.unknown_tool = unknown_tool


def read_wiki_structure(repo: RepoRef, timeout_seconds: float = 60.0) -> str:
    """The wiki's page structure for `repo`, as DeepWiki's `read_wiki_structure` tool returns it."""
    return _invoke_or_raise("read_wiki_structure", {"repoName": repo.slug}, timeout_seconds)


def read_wiki_contents(repo: RepoRef, timeout_seconds: float = 180.0) -> str:
    """The full cached wiki for `repo`. Responses run into the millions of characters; timeouts are generous."""
    return _invoke_or_raise("read_wiki_contents", {"repoName": repo.slug}, timeout_seconds)


def ask(repo: RepoRef, question: str, timeout_seconds: float = 180.0) -> str:
    """A question answered against `repo`'s cached wiki, DeepWiki's own retrieval and synthesis."""
    arguments = {"repoName": repo.slug, "question": question}
    try:
        return _invoke(ASK_TOOL, arguments, timeout_seconds)
    except _ToolCallError as failure:
        if not failure.unknown_tool:
            raise LoreError(str(failure)) from failure
    try:
        return _invoke(ASK_TOOL_FALLBACK, arguments, timeout_seconds)
    except _ToolCallError as failure:
        raise LoreError(str(failure)) from failure


def indexed_commit(repo: RepoRef, timeout_seconds: float = 30.0) -> tuple[str | None, str | None]:
    """The commit and date DeepWiki states it indexed, read from the page it renders for `repo`.

    Returns `(None, None)` when the page does not carry the marker, which is a reported unknown
    rather than a failure: DeepWiki's page shape changing is not this caller's problem to raise on.
    """
    url = f"{PAGE_BASE}/{repo.slug}"
    try:
        with httpx.Client(timeout=_timeout(timeout_seconds), follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError as error:
        raise LoreError(f"Could not reach DeepWiki's page for {repo.slug}: {error}") from error
    if response.status_code != httpx.codes.OK:
        raise LoreError(
            f"DeepWiki's page for {repo.slug} returned HTTP {response.status_code}. "
            "The repository must be public. A brand new repository may need a retry while DeepWiki indexes it."
        )
    return extract_indexed_commit(response.text)


def parse_sse_message(text: str) -> dict[str, Any]:
    """The JSON-RPC message carried by an SSE response body.

    DeepWiki frames every response, even a single result, as `event: message` / `data: {...}` lines.
    When more than one `data:` line carries a JSON-RPC payload, the last one carrying a `result` or
    `error` wins.
    """
    message: dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        candidate = json.loads(line.removeprefix("data:").strip())
        if "result" in candidate or "error" in candidate:
            message = candidate
    if message is None:
        raise ValueError("no data: line carried a JSON-RPC result or error")
    return message


def extract_indexed_commit(html: str) -> tuple[str | None, str | None]:
    """The commit sha and human date DeepWiki's page renders next to "Last indexed:".

    The rendered link text is truncated to six characters while its href carries the fuller sha,
    so the sha always comes from the href, never the link text.
    """
    marker_index = html.find(INDEXED_MARKER)
    if marker_index == -1:
        return None, None
    tail = html[marker_index + len(INDEXED_MARKER) :]
    href_match = _COMMIT_HREF.search(tail)
    sha = href_match.group(1) if href_match else None
    date_segment = tail[: href_match.start()] if href_match else tail
    date_text = _COMMENT_MARKER.sub("", date_segment)
    date_text = date_text.split("(")[0]
    date_text = _TAG.sub("", date_text).strip()
    if not date_text:
        return sha, None
    return sha, _normalize_indexed_date(date_text)


def _normalize_indexed_date(raw: str) -> str:
    """`raw` as ISO 8601, or `raw` unchanged when it does not match DeepWiki's rendered date shape."""
    try:
        parsed = datetime.strptime(raw, "%d %B %Y")
    except ValueError:
        return raw
    return parsed.date().isoformat()


def _invoke_or_raise(tool: str, arguments: dict[str, Any], timeout_seconds: float) -> str:
    try:
        return _invoke(tool, arguments, timeout_seconds)
    except _ToolCallError as failure:
        raise LoreError(str(failure)) from failure


def _invoke(tool: str, arguments: dict[str, Any], timeout_seconds: float) -> str:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
    try:
        with httpx.Client(timeout=_timeout(timeout_seconds)) as client:
            response = client.post(ENDPOINT, json=payload, headers=HEADERS)
    except httpx.HTTPError as error:
        raise _ToolCallError(
            f"DeepWiki request for '{tool}' failed: {error}. Retry once; if it keeps failing, check "
            "https://status.deepwiki.com or https://deepwiki.com directly.",
            unknown_tool=False,
        ) from error
    if response.status_code != httpx.codes.OK:
        raise _ToolCallError(
            f"DeepWiki returned HTTP {response.status_code} calling '{tool}': {response.text[:200]}. "
            "Retry once; if it persists, check https://status.deepwiki.com or https://deepwiki.com directly.",
            unknown_tool=False,
        )
    try:
        message = parse_sse_message(response.text)
    except ValueError as error:
        raise _ToolCallError(
            f"DeepWiki's response to '{tool}' could not be parsed: {error}. Retry once; DeepWiki's response "
            "shape may have changed, so check https://deepwiki.com directly if it keeps happening.",
            unknown_tool=False,
        ) from error
    return _content_text(message, tool, arguments)


def _content_text(message: dict[str, Any], tool: str, arguments: dict[str, Any]) -> str:
    if "error" in message:
        detail = _error_message(message["error"])
        raise _ToolCallError(
            f"DeepWiki rejected '{tool}': {detail}. {_repo_remedy(arguments)}",
            unknown_tool=_is_unknown_tool(detail),
        )
    result = message.get("result") or {}
    if result.get("isError"):
        detail = _first_text(result) or "no detail returned"
        raise _ToolCallError(
            f"DeepWiki tool '{tool}' failed: {detail}. {_repo_remedy(arguments)}",
            unknown_tool=_is_unknown_tool(detail),
        )
    text = _first_text(result)
    if text is None:
        raise _ToolCallError(
            f"DeepWiki tool '{tool}' returned no text content. Retry once; if it persists, check "
            "https://deepwiki.com directly.",
            unknown_tool=False,
        )
    return text


def _repo_remedy(arguments: dict[str, Any]) -> str:
    """The concrete next action for a rejected or failed tool call, naming the repository when known.

    A rejection or an `isError` result from these tools is almost always either a misspelled
    `owner/repo` or a repository DeepWiki has not indexed yet, so the remedy names both rather
    than repeating the raw service text with nothing a caller can act on.
    """
    repo_name = arguments.get("repoName")
    if not repo_name:
        return "Retry once; if it persists, check https://deepwiki.com directly."
    return (
        f"Check that '{repo_name}' is spelled correctly, or visit https://deepwiki.com/{repo_name} "
        "to have it indexed if it is a valid but unindexed repository."
    )


def _first_text(result: dict[str, Any]) -> str | None:
    content = result.get("content")
    if not content or not isinstance(content[0], dict):
        return None
    return content[0].get("text")


def _error_message(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("message", error))
    return str(error)


def _is_unknown_tool(message: str) -> bool:
    lowered = message.lower()
    return "unknown tool" in lowered or "no such tool" in lowered or "not found" in lowered


def _timeout(read_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(connect=10.0, read=read_seconds, write=30.0, pool=10.0)
