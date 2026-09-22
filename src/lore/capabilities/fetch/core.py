"""Fetch: write a repository's DeepWiki wiki to the on-disk cache, and return the map to it.

The map is `WikiIndex`: page titles, sizes, and the freshness this fetch measured. The wiki's
actual content never returns from this function; it lands on disk, and `pages`, `read`, and
`search` are the only ways back into it.
"""

from lore import store
from lore.schemas import Freshness, LoreError, RepoRef, WikiIndex
from lore.sources import deepwiki


def fetch(
    repo: str, ref: RepoRef, freshness: Freshness, refresh: bool = False, timeout_seconds: float = 180.0
) -> WikiIndex:
    """Fetch `repo`'s DeepWiki wiki to the cache and return its index.

    Args:
        repo: The repository slug the cache is keyed on, e.g. `owner/name`.
        ref: `repo` already parsed, for the DeepWiki call.
        freshness: This fetch's own freshness measurement, written alongside the wiki.
        refresh: Refetch even when a cached index already exists for `freshness.indexed_sha`.
        timeout_seconds: Timeout for the DeepWiki call, which can carry megabytes of Markdown.

    Returns:
        The index just written, or the cached one for the same indexed commit when `refresh`
        is `False` and one already exists. `from_cache` says which; either way, the wiki's
        content itself never comes back through this function.
    """
    if not refresh:
        try:
            cached = store.load_index(repo, freshness.indexed_sha)
        except LoreError:
            cached = None
        if cached is not None:
            return cached.model_copy(update={"from_cache": True})

    contents = deepwiki.read_wiki_contents(ref, timeout_seconds=timeout_seconds)
    return store.write_wiki(repo, contents, freshness)
