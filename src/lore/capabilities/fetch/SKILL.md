Writes `REPO`'s DeepWiki wiki to the on-disk cache, one file per page plus an index, and
returns the index: page titles, sizes, and the freshness this fetch measured. The wiki's
content, which can run into the hundreds of thousands of tokens, never passes through the
caller on its way to disk. Call this once per repository before `pages`, `read`, or `search`
can do anything; those three are the only way back into what this writes.

`REPO` is a GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL.
`--refresh` refetches even when a cached index already exists for the commit DeepWiki
currently reports as indexed (default: reuse the cache). `--timeout-seconds` bounds the
DeepWiki call, which can carry megabytes of Markdown (default `180.0`). Add `--json` to print
the full `WikiIndex` model instead of the page list.

```bash
lore fetch upstash/context7
```

```python
from lore.lib import fetch

index = fetch("upstash/context7")
index.pages, index.total_estimated_tokens, index.freshness.verdict, index.from_cache
```

Returns a `WikiIndex`: `pages` (`PageEntry` per page: `number`, `title`, `path`, `characters`,
`estimated_tokens`), `total_characters`/`total_estimated_tokens`, `root` (the cache directory
this index and its pages live under), `freshness` (this fetch's own measurement), and
`from_cache`, `True` when this call reused an existing cache entry instead of refetching.

## Failures

Raises `LoreError` when `REPO` does not parse, or when the freshness measurement itself fails
(GitHub reports no such repository). A DeepWiki call that fails once no cache can cover it
raises `LoreError` naming what DeepWiki said.
