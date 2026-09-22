Searches every cached wiki page of `REPO` for `PATTERN`, a regular expression matched
case-insensitively line by line. Use this to find which page mentions something before
spending a `read` call on the wrong one.

`REPO` is the repository slug `fetch` cached. `PATTERN` is a regular expression. `--max-hits`
caps how many matches come back (default `50`); `total_hits` in the result always reports the
true count, even when it is larger. Add `--json` to print the full `SearchResult` model
instead of one line per hit.

```bash
lore search upstash/context7 "resolve-library-id"
```

```python
from lore.lib import search

result = search("upstash/context7", "resolve-library-id")
result.total_hits, [(hit.page_title, hit.line) for hit in result.hits]
```

Returns a `SearchResult`: `hits` (`SearchHit` per match: `page_number`, `page_title`, `line`,
`text`), `total_hits`, and `truncated`, whether more matches exist past `--max-hits`.

## Failures

Raises `LoreError` when no wiki is cached for `REPO`, naming the `lore fetch` command to run,
or when `PATTERN` is not a valid regular expression.
