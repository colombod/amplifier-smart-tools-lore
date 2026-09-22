Explains how the GitHub repository `REPO` works: its architecture, design, and how its
pieces are wired, for the question `QUESTION`. Measures freshness for `REPO` first; a
repository DeepWiki has never indexed has nothing to ground an answer in, so that raises
before a model is ever asked. Selects the cached wiki pages that plausibly ground `QUESTION`
(a no-model relevance heuristic over page titles and bodies, fetching the wiki to the cache
first when it is not already there), then, before synthesis, measures per-page drift for
those SELECTED pages against the files GitHub reports changed since the wiki was indexed --
never for the whole wiki: a repository can have many pages and only a few broken ones, and a
question those broken pages have nothing to do with must still answer normally.

- A selected page whose cited files no longer resolve (`broken`) makes this **refuse** rather
  than answer around a citation that does not exist anymore, naming only the selected
  broken page(s) (never an unrelated broken page elsewhere in the wiki), the exact files, the
  indexed and head commits, and the next actions: read the files at head, rerun with
  `--at-head`, or wait for DeepWiki to reindex.
- A selected page whose cited files were merely edited (`drifted`), or whose drift could not
  be fully established (`unknown`), still answers, but the model is told exactly which files
  to treat with caution, and the usual staleness caveat still applies.
- A selected page whose citations are untouched (`intact`) answers with **no staleness
  caveat at all**, however many commits the repository is ahead overall, and however many
  OTHER pages in the same wiki are broken or drifted.
- When no page can be identified as grounding `QUESTION`, drift is reported as `unknown`
  (never silently passed as clean, and never a refusal on pages nothing established as
  relevant) and the answer proceeds with a caveat saying the grounding pages could not be
  identified.

`--at-head` skips the wiki's own content entirely and grounds the answer in the SELECTED
pages' cited files' current content, read directly from the repository at its head commit
through GitHub's contents API, bounded by `--at-head-read-limit` total characters across
every file combined. Cited files are fetched in relevance order, not the order DeepWiki's
own "Relevant source files" block lists them in (which is alphabetical): a no-model heuristic
ranks them by how closely question terms sit to each citation and to the file's own path,
so the budget is spent on the files most likely to matter first, never on whichever happen
to sort first. This only ever reorders which files are tried first; it never removes a file
from consideration -- the budget is the only thing that does that. Every cited file ends up
in exactly one of four states, mechanically recorded in `at_head_files` rather than
asserted: `included` (fetched and used),
`excluded_for_budget` (left out once the read limit was spent), `missing_at_head` (GitHub
confirms with a 404 that the file no longer exists there -- information about the citation,
not a failure), or `not_text` (GitHub fetched the file successfully but its content is not
valid UTF-8, e.g. a binary file such as an image -- information about the file, not a
failure). This is the one documented partial-completion outcome of this capability: a run
that ends with some files `missing_at_head`, `excluded_for_budget`, or `not_text` still
answers, and says exactly which files those were. Any OTHER retrieval failure (a network
error, a rate limit, a malformed response) is never folded into `missing_at_head` or
`not_text` -- it fails the whole call instead, since it is not evidence about the file
itself. Citations grounded via `--at-head` carry source `at_head` and the head commit they
were read at.

`REPO` is a GitHub repository, as `owner/name` or a full `https://github.com/owner/name`
URL. `QUESTION` is a question about the repository's architecture, design, or wiring.
`--model` selects the model to run the synthesis through, defaulting to
`DEFAULT_INTELLIGENCE_MODEL` in `schemas.py`. `--reasoning-effort` sets that model's
reasoning effort (default `low`). `--timeout-seconds` bounds each retrieval call and the
synthesis itself (default `300.0`). `--material-file PATH` (default: none) reads that file
and uses its contents in place of DeepWiki's own retrieval; the never-indexed guard and the
drift measurement are both skipped, since the file already supplies something to ground the
answer in, and its claims are cited with source `caller` instead of `deepwiki`. The library's
own `material` argument (default `None`) takes this content directly rather than a path,
which is the CLI's convenience alone. `--at-head` (default `false`) and
`--at-head-read-limit` (default `DEFAULT_READ_LIMIT` in `schemas.py`) are described above.
Add `--json` (default `false`) to print the full `Answer` model instead of the rendered answer.

```bash
lore explain upstash/context7 "How is search request ranking implemented?"
lore explain upstash/context7 "How is search request ranking implemented?" --at-head
```

```python
from lore.lib import explain

result = explain("upstash/context7", "How is search request ranking implemented?")
result.answer, result.citations, result.unanswered, result.caveat
```

Returns an `Answer`: `question`/`target` (the question asked and the repository targeted,
echoed back), `answer` (grounded only in retrieved material), `citations` (each naming
`deepwiki`, `at_head` (carrying `ref`, the head commit read) when grounded via `--at-head`,
or `caller` when grounded in `--material-file` instead, and the page, file, or material the
claim rests on), `unanswered` (parts of the question the retrieved material did not cover),
`freshness` (the measurement `freshness` would report for `REPO`, still measured with
`--material-file`; with `--at-head`, this instead reports the material as current, since it
is the repository's own live head rather than the wiki's index), `caveat`, and
`at_head_files` (empty except with `--at-head`; each cited file's `included` /
`excluded_for_budget` / `missing_at_head` / `not_text` fate, described above). `caveat` is
`None` when the pages grounding the answer are `intact` (or the material is at head),
whatever the commit count, and otherwise names the measured commits and days the index
trails the repository by, so a stale index is never silently trusted.

## Failures

Raises `LoreError` when `REPO` does not parse, when DeepWiki has no indexed wiki for it
(naming the `deepwiki.com` URL to visit to have it indexed), when a cached wiki page cites a
file GitHub reports removed or renamed (naming the pages, the files, and how to proceed),
when `--at-head` was requested but the repository's live head commit could not be measured,
when an `--at-head` fetch for a cited file fails for a reason other than a confirmed 404 or a
decode failure (network error, rate limit, malformed response -- never silently reported as
`missing_at_head` or `not_text`), when `gh` is not installed or not signed in (naming what to
run), or when it produces no usable structured answer. A signed-in account lacking a Copilot
subscription is not detected upfront: no cheap check exists for it, so it surfaces only once
the model call itself fails, naming `github-copilot-subscription` to install.
