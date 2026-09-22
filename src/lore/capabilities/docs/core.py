"""Docs: Context7 documentation for a library, written to disk and previewed rather than returned whole."""

from lore import store
from lore.schemas import CHARS_PER_TOKEN, DocsResult
from lore.sources import context7

# Enough to judge whether the documentation is on topic without spending the caller's whole
# context on it; the full text always lands on disk at `DocsResult.path`.
PREVIEW_LIMIT = 2000


def docs(library: str, topic: str, timeout_seconds: float = 60.0) -> DocsResult:
    """Context7 documentation for `library` about `topic`, written to disk and previewed.

    Args:
        library: A library name to resolve against Context7, e.g. `context7` or `fastapi`.
        topic: The topic to focus the documentation on, e.g. `routing`.
        timeout_seconds: Per-request timeout for the resolve and fetch calls.

    Returns:
        The resolved library, the path the full documentation was written to, and a bounded
        preview of its opening; `truncated` says whether the preview is the whole thing.

    Raises:
        LoreError: Context7 has no library matching `library`, or a request failed.
    """
    resolved = context7.resolve_library(library, topic, timeout_seconds=timeout_seconds)
    text = context7.fetch_context(resolved.id, topic, timeout_seconds=timeout_seconds)
    path = store.write_document(resolved.id, text)
    preview, truncated = _preview(text)
    return DocsResult(
        library=resolved,
        topic=topic,
        path=str(path),
        characters=len(text),
        estimated_tokens=len(text) // CHARS_PER_TOKEN,
        preview=preview,
        truncated=truncated,
    )


def _preview(text: str) -> tuple[str, bool]:
    """The bounded opening of `text`, and whether it had to be cut to get there."""
    return text[:PREVIEW_LIMIT], len(text) > PREVIEW_LIMIT
