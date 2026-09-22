Measures whether a cached wiki's pages still match the repository right now, not just
whether the repository as a whole has moved on. Each page's own citations, both its
"Relevant source files" block and its inline `[path:line-range]()` citations, are checked
against the files GitHub reports changed since the wiki was indexed. A page whose cited files
were deleted or renamed is `broken`; a page whose cited files were merely edited is `drifted`;
a page whose citations do not appear in the changed set is `intact`. A repository can be only
lightly behind overall while one page is `broken`: reach for this before trusting an `explain`
or `howto` answer that leans on a specific page, not just `freshness`'s repository-wide number.

`REPO` is the repository slug `fetch` cached. `--page` restricts the measurement to one page,
by number or a case-insensitive title substring, exactly as `read` accepts `PAGE`; omitted,
every cached page is measured. `--timeout-seconds` bounds the GitHub compare call (default
`60.0`). Add `--json` (default `false`) to print the full `DriftReport` model instead of the
human summary.

```bash
lore drift upstash/context7
lore drift upstash/context7 --page 3
```

```python
from lore.lib import drift

result = drift("upstash/context7")
result.verdict, result.changed_file_count, result.comparison_complete
```

Returns a `DriftReport`: `repo`/`indexed_sha`/`head_sha` (the commits compared), `pages` (one
`PageDrift` per page measured: `page_number`, `title`, `cited_files`, `changed` and `removed`
(`FileChange`: `filename`, `status`, `changes`, `previous_filename`; `removed` is the subset of
`changed` whose citation no longer resolves, status `removed` or `renamed`), `intact`,
`verdict` (`intact`, `drifted`, `broken`, or `unknown`), `summary`), `verdict` (the WORST page
verdict present, never an average: one broken page makes the whole report broken),
`changed_file_count`, `comparison_complete` (`False` when GitHub's changed-file list could not
be enumerated in full, or the indexed or head commit is itself unknown, in which case every
page whose citations could not be ruled out is `unknown` rather than `intact`), and `summary`.

## Failures

Raises `LoreError` when no wiki is cached for `REPO`, naming the `lore fetch` command to run,
or when `--page` matches no cached page or more than one.
