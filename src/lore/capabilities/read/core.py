"""Read: a bounded slice of one cached wiki page, the only way to get page text back."""

from lore import store
from lore.schemas import DEFAULT_READ_LIMIT, ReadResult


def read(repo: str, page: int | str, start: int = 0, limit: int = DEFAULT_READ_LIMIT) -> ReadResult:
    """A bounded slice of one cached page of `repo`'s wiki.

    Args:
        repo: The repository slug `fetch` cached, e.g. `owner/name`.
        page: A page number, or a case-insensitive substring of a page title.
        start: Character offset to start the slice at.
        limit: Maximum characters to return; the result says whether it was truncated.

    Returns:
        The requested slice. `next_start` and `continuation` name exactly how to read on
        when `truncated` is `True`.

    Raises:
        LoreError: No wiki is cached for `repo`, `page` matches no page or more than one,
            or `start`/`limit` is invalid.
    """
    return store.read_page(repo, page, start=start, limit=limit)
