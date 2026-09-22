"""Search: a regex search across one repository's cached wiki, capped and honest about the cap."""

from lore import store
from lore.schemas import SearchResult


def search(repo: str, pattern: str, max_hits: int = 50) -> SearchResult:
    """Search `repo`'s cached wiki pages for `pattern`, capped at `max_hits`.

    Args:
        repo: The repository slug `fetch` cached, e.g. `owner/name`.
        pattern: A regular expression, matched case-insensitively line by line.
        max_hits: Maximum matches to return; `total_hits` reports the true count.

    Returns:
        The matches found, capped, and honest about whether more exist.

    Raises:
        LoreError: No wiki is cached for `repo`, or `pattern` is not a valid regular expression.
    """
    return store.search_pages(repo, pattern, max_hits=max_hits)
