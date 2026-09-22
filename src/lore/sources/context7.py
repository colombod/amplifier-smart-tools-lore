"""Context7's HTTP API: library search and documentation retrieval."""

import contextlib
import os
from typing import Any

import httpx

from lore.schemas import LibraryRef, LoreError

BASE_URL = "https://context7.com/api/v2"
API_KEY_ENV = "CONTEXT7_API_KEY"


def search_libraries(library_name: str, query: str, limit: int = 5, timeout_seconds: float = 30.0) -> list[LibraryRef]:
    """Libraries Context7 thinks match `library_name`, ranked by Context7 itself."""
    response = _get("/libs/search", {"libraryName": library_name, "query": query}, timeout_seconds)
    _raise_for_status(response, f"a library search for '{library_name}'")
    results = response.json().get("results") or []
    return [_library_from_json(entry) for entry in results[:limit]]


def resolve_library(library_name: str, query: str, timeout_seconds: float = 30.0) -> LibraryRef:
    """The library Context7 ranks first for `library_name`, which is its answer and not ours.

    Re-ranking on the published metadata was tried and measurably made things worse: sorting
    by `trustScore` picked `/jeffersongoncalves/context7-cli` (1 star, trust 9.8) over
    `/upstash/context7` (6679 stars, trust 9.5) for the query "context7", while Context7's own
    order had the canonical library first. The service reranks against the query and we do
    not, so its order stands and the alternatives are reported for an explicit override.
    """
    candidates = search_libraries(library_name, query, timeout_seconds=timeout_seconds)
    if not candidates:
        raise LoreError(
            f"Context7 found no library matching '{library_name}' for query '{query}'.{_near_misses(library_name, timeout_seconds)}"
        )
    return _first_ranked(candidates)


def _first_ranked(candidates: list[LibraryRef]) -> LibraryRef:
    """Context7's own top result. A named function so the choice is testable and explicit."""
    return candidates[0]


def fetch_context(library_id: str, query: str, timeout_seconds: float = 60.0) -> str:
    """Documentation Context7 serves for `library_id`, as Markdown."""
    response = _get("/context", {"libraryId": library_id, "query": query, "type": "txt"}, timeout_seconds)
    _raise_for_status(response, f"documentation for '{library_id}'")
    return response.text


def _near_misses(library_name: str, timeout_seconds: float) -> str:
    """Libraries closest to `library_name` by name alone, for an error message naming what came close."""
    fallback: list[LibraryRef] = []
    with contextlib.suppress(LoreError):
        fallback = search_libraries(library_name, "", timeout_seconds=timeout_seconds)
    if not fallback:
        return ""
    names = ", ".join(f"{candidate.id} ({candidate.title})" for candidate in fallback)
    return f" Closest libraries by name: {names}."


def _library_from_json(payload: dict[str, Any]) -> LibraryRef:
    """One Context7 search result mapped onto `LibraryRef`, tolerant of any field the payload omits."""
    return LibraryRef(
        id=payload.get("id", ""),
        title=payload.get("title", ""),
        description=payload.get("description") or "",
        last_update_date=payload.get("lastUpdateDate"),
        state=payload.get("state"),
        total_tokens=payload.get("totalTokens"),
        total_snippets=payload.get("totalSnippets"),
        stars=payload.get("stars"),
        trust_score=payload.get("trustScore"),
        benchmark_score=payload.get("benchmarkScore"),
    )


def _get(path: str, params: dict[str, str], timeout_seconds: float) -> httpx.Response:
    try:
        with httpx.Client(timeout=_timeout(timeout_seconds)) as client:
            return client.get(f"{BASE_URL}{path}", params=params, headers=_headers())
    except httpx.HTTPError as error:
        raise LoreError(
            f"Context7 request to {path} failed: {error}. Retry once; if it keeps failing, check your "
            "network connection or https://context7.com directly."
        ) from error


def _headers() -> dict[str, str]:
    # A key is optional: Context7 answered both endpoints anonymously, so one is only ever attached.
    key = os.environ.get(API_KEY_ENV)
    return {"Authorization": f"Bearer {key}"} if key else {}


def _raise_for_status(response: httpx.Response, context: str) -> None:
    status = response.status_code
    if status == httpx.codes.OK:
        return
    if status == httpx.codes.ACCEPTED:
        raise LoreError(f"Context7 is still indexing {context}. Retry shortly.")
    if status == httpx.codes.UNAUTHORIZED:
        raise LoreError(f"Context7 rejected the {API_KEY_ENV} key. Check its value.")
    if status in (httpx.codes.FORBIDDEN, httpx.codes.PAYMENT_REQUIRED):
        raise LoreError(f"Context7's plan does not allow {context} (HTTP {status}).")
    if status == httpx.codes.NOT_FOUND:
        raise LoreError(f"Context7 has no {context}.")
    if status == httpx.codes.TOO_MANY_REQUESTS:
        retry_after = response.headers.get("Retry-After")
        suffix = f" Retry after {retry_after} seconds." if retry_after else ""
        raise LoreError(f"Context7 rate limited {context}.{suffix}")
    raise LoreError(f"Context7 returned HTTP {status} for {context}: {response.text[:200]}")


def _timeout(read_seconds: float) -> httpx.Timeout:
    return httpx.Timeout(connect=10.0, read=read_seconds, write=30.0, pool=10.0)
