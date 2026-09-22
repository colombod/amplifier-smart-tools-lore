Reads a bounded slice of one cached wiki page: the only way to get page text back once
`fetch` has written it to disk. Every slice is capped and honest about what it withheld, so no
single call can return more than `--limit` characters, whatever the page's real size.

`REPO` is the repository slug `fetch` cached. `PAGE` is a page number, or a case-insensitive
substring of a page title (e.g. `2` or `getting started`); an ambiguous substring is an error
naming every title it matched. `--start` is the character offset to begin at (default `0`).
`--limit` is the maximum characters to return (default `40000`, roughly 10,000 tokens). Add
`--json` to print the full `ReadResult` model instead of the raw text.

```bash
lore read upstash/context7 1 --start 0 --limit 4000
```

```python
from lore.lib import read

result = read("upstash/context7", 1, start=0, limit=4000)
result.text, result.truncated, result.next_start
```

Returns a `ReadResult`: `text` (the slice), `start`/`returned_characters`/`total_characters`,
`truncated`, and, when truncated, `next_start` and `continuation`, the exact invocation that
reads on from where this slice stopped.

## Failures

Raises `LoreError` when no wiki is cached for `REPO`, when `PAGE` matches no page or more than
one (naming the candidates), or when `--start` is negative or `--limit` is not positive.
