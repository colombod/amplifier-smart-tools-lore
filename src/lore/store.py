"""Store: the on-disk cache for wiki content and the bounded reader over it.

A single DeepWiki fetch can return hundreds of thousands of characters of Markdown, far more
than a caller's context can hold. This module writes that content to disk once and gives every
path back into it a hard cap, so nothing downstream of `fetch` can accidentally return the
whole wiki at once.
"""

from datetime import UTC, datetime
import os
from pathlib import Path
import re
import sys

from lore.schemas import (
    CHARS_PER_TOKEN,
    DEFAULT_READ_LIMIT,
    Freshness,
    LoreError,
    PageEntry,
    ReadResult,
    SearchHit,
    SearchResult,
    WikiIndex,
)

# Verified against a real DeepWiki fetch: this is exactly how it delimits pages.
PAGE_MARKER = re.compile(r"^# Page: (.+)$\n?", re.MULTILINE)

MAX_SLUG_LENGTH = 60


def cache_root() -> Path:
    """The root directory the cache lives under, created if it does not already exist."""
    override = os.environ.get("LORE_CACHE_DIR")
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "lore"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches" / "lore"
    else:
        root = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "lore"

    root.mkdir(parents=True, exist_ok=True)
    return root


def entry_root(repo: str, indexed_sha: str | None) -> Path:
    """Where one repository's wiki at one indexed commit lives.

    Keyed on the indexed commit rather than just the repo: when DeepWiki reindexes, the new
    content lands beside the old instead of overwriting it, so a cached answer can never be
    silently attributed to the wrong commit.
    """
    return cache_root() / "wiki" / _repo_slug(repo) / (indexed_sha or "unknown")


def write_wiki(repo: str, contents: str, freshness: Freshness) -> WikiIndex:
    """Split `contents` into pages, write each to disk, and return the index describing them."""
    root = entry_root(repo, freshness.indexed_sha)
    entries: list[PageEntry] = []
    for number, (title, body) in enumerate(_split_pages(contents), start=1):
        relative_path = f"pages/{number:03d}-{_page_slug(title)}.md"
        _atomic_write(root / relative_path, body)
        entries.append(
            PageEntry(
                number=number,
                title=title,
                path=relative_path,
                characters=len(body),
                estimated_tokens=len(body) // CHARS_PER_TOKEN,
            )
        )

    index = WikiIndex(
        repo=repo,
        root=str(root),
        pages=entries,
        total_characters=sum(entry.characters for entry in entries),
        total_estimated_tokens=sum(entry.estimated_tokens for entry in entries),
        freshness=freshness,
        fetched_at=datetime.now(UTC).isoformat(),
    )
    _atomic_write(root / "index.json", index.model_dump_json(indent=2))
    return index


def load_index(repo: str, indexed_sha: str | None = None) -> WikiIndex:
    """The cached index for `repo`, at `indexed_sha` when given, otherwise the freshest one cached."""
    if indexed_sha is not None:
        return _read_index(entry_root(repo, indexed_sha) / "index.json", repo, indexed_sha)

    repo_directory = cache_root() / "wiki" / _repo_slug(repo)
    candidates = sorted(repo_directory.glob("*/index.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not candidates:
        raise LoreError(_not_cached_message(repo))
    return _read_index(candidates[0], repo, indexed_sha)


def read_page(
    repo: str,
    page: int | str,
    start: int = 0,
    limit: int = DEFAULT_READ_LIMIT,
    indexed_sha: str | None = None,
) -> ReadResult:
    """A bounded slice of one cached page, honest about whatever it withheld."""
    if limit <= 0:
        raise LoreError(f"limit must be a positive number of characters, got {limit}.")
    if start < 0:
        raise LoreError(f"start must not be negative, got {start}.")

    index = load_index(repo, indexed_sha)
    entry = _resolve_page(index, page)
    root = Path(index.root)
    text = (root / entry.path).read_text(encoding="utf-8")

    total_characters = len(text)
    # A start beyond the page end is a valid, honest answer (an empty slice), not an error.
    clamped_start = min(start, total_characters)
    slice_end = min(clamped_start + limit, total_characters)
    returned = text[clamped_start:slice_end]
    truncated = slice_end < total_characters
    next_start = slice_end if truncated else None
    continuation = f"lore read {repo} --page {entry.number} --start {next_start}" if truncated else None

    return ReadResult(
        repo=repo,
        page_number=entry.number,
        page_title=entry.title,
        path=entry.path,
        text=returned,
        start=clamped_start,
        returned_characters=len(returned),
        total_characters=total_characters,
        truncated=truncated,
        next_start=next_start,
        continuation=continuation,
    )


def search_pages(
    repo: str,
    pattern: str,
    max_hits: int = 50,
    context_characters: int = 200,
    indexed_sha: str | None = None,
) -> SearchResult:
    """Regex search across every cached page, capped at `max_hits` but honest about the true total."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as error:
        raise LoreError(f"'{pattern}' is not a valid regular expression: {error}") from error

    index = load_index(repo, indexed_sha)
    root = Path(index.root)
    hits: list[SearchHit] = []
    total_hits = 0
    for entry in index.pages:
        text = (root / entry.path).read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not regex.search(line):
                continue
            total_hits += 1
            if len(hits) < max_hits:
                hits.append(
                    SearchHit(
                        page_number=entry.number,
                        page_title=entry.title,
                        line=line_number,
                        text=line[:context_characters],
                    )
                )

    return SearchResult(repo=repo, pattern=pattern, hits=hits, total_hits=total_hits, truncated=total_hits > len(hits))


def write_document(name: str, text: str) -> Path:
    """Write arbitrary text (Context7 documentation) to the cache and return its path."""
    path = cache_root() / "docs" / f"{_sanitised_document_name(name)}.md"
    _atomic_write(path, text)
    return path


def clear(repo: str | None = None) -> int:
    """Delete the cache for one repository, or the whole cache when `repo` is None. Returns files removed."""
    root = cache_root() if repo is None else cache_root() / "wiki" / _repo_slug(repo)
    return _remove_tree(root)


def _split_pages(contents: str) -> list[tuple[str, str]]:
    """Split wiki text on `# Page: <title>` markers into (title, body) pairs.

    Content before the first marker, if any, becomes page 1 titled "Overview". Text with no
    marker at all becomes a single page titled "Contents".
    """
    parts = PAGE_MARKER.split(contents)
    if len(parts) == 1:
        return [("Contents", contents)]

    pages: list[tuple[str, str]] = []
    if parts[0].strip():
        pages.append(("Overview", parts[0]))
    for index in range(1, len(parts), 2):
        pages.append((parts[index].strip(), parts[index + 1]))
    return pages


def _page_slug(title: str) -> str:
    """A filename-safe slug for a page title: lowercased, non-alphanumerics collapsed, capped at 60 characters."""
    collapsed = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return collapsed[:MAX_SLUG_LENGTH].strip("-") or "page"


def _repo_slug(repo: str) -> str:
    """A filesystem-safe form of a repo slug: the `/` between owner and repo cannot be a path separator."""
    return repo.replace("/", "__")


def _resolve_page(index: WikiIndex, page: int | str) -> PageEntry:
    """The page `page` names, by number or by a case-insensitive title substring."""
    if isinstance(page, int):
        for entry in index.pages:
            if entry.number == page:
                return entry
        raise LoreError(f"Page {page} does not exist for '{index.repo}'. Pages range from 1 to {len(index.pages)}.")

    needle = page.lower()
    matches = [entry for entry in index.pages if needle in entry.title.lower()]
    if not matches:
        titles = ", ".join(entry.title for entry in index.pages)
        raise LoreError(f"No cached page title matches '{page}' for '{index.repo}'. Titles: {titles}.")
    if len(matches) > 1:
        titles = ", ".join(entry.title for entry in matches)
        raise LoreError(f"'{page}' matches more than one page title for '{index.repo}': {titles}.")
    return matches[0]


def _read_index(path: Path, repo: str, indexed_sha: str | None) -> WikiIndex:
    """Parse the index at `path`, or raise LoreError naming how to populate the cache."""
    if not path.is_file():
        raise LoreError(_not_cached_message(repo, indexed_sha))
    return WikiIndex.model_validate_json(path.read_text(encoding="utf-8"))


def _not_cached_message(repo: str, indexed_sha: str | None = None) -> str:
    detail = f" at commit {indexed_sha}" if indexed_sha else ""
    return f"No cached wiki for '{repo}'{detail}. Run `lore fetch {repo}` first."


def _sanitised_document_name(name: str) -> str:
    """`name`, flattened to a single safe filename that cannot escape the docs directory.

    A Context7 library id is a path, `/upstash/context7`, so separators are the normal input
    and rejecting them would reject every real caller. They are folded to `__` instead. A
    `..` segment has no such legitimate reading and is still refused: this is a security
    boundary, because the name derives from a library id a remote service supplies.
    """
    if not name.strip():
        raise LoreError("Document name must not be empty.")
    segments = [segment for segment in name.replace("\\", "/").split("/") if segment]
    if any(segment == ".." for segment in segments):
        raise LoreError(f"'{name}' is not a safe document name: it must not contain a '..' segment.")
    flattened = "__".join(segments)
    if not flattened:
        raise LoreError(f"'{name}' is not a safe document name: it names no file.")
    return flattened


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` to `path` via a temporary file in the same directory, then an atomic rename.

    So an interrupted write (a crashed fetch, a killed process) never leaves a later reader
    trusting a half-written file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)


def _remove_tree(root: Path) -> int:
    """Delete `root` and everything under it, returning the number of files removed."""
    if not root.is_dir():
        return 0
    removed = 0
    for path in sorted(root.rglob("*"), key=lambda candidate: len(candidate.parts), reverse=True):
        if path.is_file():
            path.unlink()
            removed += 1
        else:
            path.rmdir()
    root.rmdir()
    return removed
