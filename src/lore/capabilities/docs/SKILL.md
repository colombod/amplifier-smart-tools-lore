Fetches Context7 documentation for `LIBRARY` focused on `TOPIC`. Resolves the library name
against Context7's own search and ranking, fetches the documentation, writes the full text to
disk, and returns a bounded preview of its opening plus the path to the rest. Use this for
library usage documentation the way `fetch`/`pages`/`read` cover a project's own wiki; the two
sources are independent, so a library covered by Context7 need not be on DeepWiki at all.

`LIBRARY` is a library name to resolve, e.g. `context7` or `fastapi`. `TOPIC` focuses both the
resolution and the fetched documentation, e.g. `routing`. `--timeout-seconds` bounds each of
the two Context7 requests (default `60.0`). Add `--json` (default `false`) to print the full
`DocsResult` model instead of the preview.

```bash
lore docs context7 "resolving a library id"
```

```python
from lore.lib import docs

result = docs("context7", "resolving a library id")
result.library.id, result.path, result.preview, result.truncated
```

Returns a `DocsResult`: `library` (the resolved `LibraryRef`: `id`, `title`, `description`,
`last_update_date`, `state`, `total_tokens`, `total_snippets`, `stars`, `trust_score`,
`benchmark_score`), `topic` (echoed input), `path` (where the full documentation was
written), `characters`/`estimated_tokens`, `preview` (bounded to 2000 characters), and
`truncated`, whether the preview is the whole document.

## Failures

Raises `LoreError` when Context7 finds no library matching `LIBRARY` (naming the closest
matches by name), or when either Context7 request fails.
