Prints the cached wiki index for `REPO`: the same `WikiIndex` `fetch` returned, read straight
back from disk with no network call at all. Use this to see what pages are available, and
their sizes, before deciding what to `read` or `search`.

`REPO` is the repository slug `fetch` cached, e.g. `owner/name`. Add `--json` to print the
full `WikiIndex` model instead of the page list.

```bash
lore pages upstash/context7
```

```python
from lore.lib import pages

index = pages("upstash/context7")
[(entry.number, entry.title) for entry in index.pages]
```

Returns the same `WikiIndex` `fetch` wrote: `pages`, `total_characters`,
`total_estimated_tokens`, `root`, and `freshness` as of that fetch.

## Failures

Raises `LoreError` when no wiki has been cached for `REPO`, naming the `lore fetch` command
to run first.
