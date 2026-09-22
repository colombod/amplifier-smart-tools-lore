"""Pages: the cached wiki index for a repository, read straight from disk."""

from lore import store
from lore.schemas import WikiIndex


def pages(repo: str) -> WikiIndex:
    """The cached wiki index for `repo`, without touching the network.

    Args:
        repo: The repository slug `fetch` cached, e.g. `owner/name`.

    Returns:
        The `WikiIndex` `fetch` last wrote for `repo`.

    Raises:
        LoreError: No wiki is cached for `repo`. Names the `lore fetch` command to run.
    """
    return store.load_index(repo)
