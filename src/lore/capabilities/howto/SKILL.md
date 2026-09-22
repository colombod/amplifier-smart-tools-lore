Explains how to use the library `LIBRARY` to accomplish `TASK`. Resolves `LIBRARY` against
Context7 first, since Context7 carries versioned code snippets, and retrieves its
documentation for `TASK`. When the resolved library is backed by a GitHub repository, also
measures its freshness and retrieves DeepWiki's own answer for design context; when it is
not (a Context7 `websites`/`llmstxt` style entry), the freshness reported is Context7's own
`lastUpdateDate` and `state` rather than a commit-level measurement no such entry has.
Synthesizes the retrieved material through the configured model, grounded only in what was
retrieved: every claim carries a citation, and anything not covered is reported in
`unanswered` rather than guessed.

`LIBRARY` is a library name to resolve against Context7, e.g. `context7` or `fastapi`.
`TASK` is the task to explain how to accomplish, e.g. "paginate search results". `--model`
selects the model to run the synthesis through, defaulting to `DEFAULT_INTELLIGENCE_MODEL`
in `schemas.py`. `--reasoning-effort` sets that model's reasoning effort (default `low`).
`--timeout-seconds` bounds each retrieval call and the synthesis itself (default `300.0`).
`--material-file PATH` reads that file and uses its contents in place of Context7's (and,
when `LIBRARY` resolves to a GitHub-backed library, DeepWiki's) own retrieval; its claims are
cited with source `caller` instead. The library's own `material` argument takes this content
directly rather than a path, which is the CLI's convenience alone. Add `--json` to print the
full `Answer` model instead of the rendered answer.

```bash
lore howto context7 "resolve a library id before fetching its documentation"
```

```python
from lore.lib import howto

result = howto("context7", "resolve a library id before fetching its documentation")
result.answer, result.citations, result.unanswered, result.caveat
```

Returns an `Answer`: `answer` (grounded only in retrieved material), `citations` (each
naming `context7`, `deepwiki`, or `caller` when grounded in `--material-file` instead, and
the reference the claim rests on), `unanswered` (parts of the task the retrieved material did
not cover), `freshness` (measured against the repository when Context7 resolved a
GitHub-backed library; Context7's own freshness fields when it did not; or, with
`--material-file` and no GitHub-backed library, an `unknown` record naming that the material
was caller-supplied), and `caveat` derived from it.

## Failures

Raises `LoreError` when Context7 finds no library matching `LIBRARY`, when a retrieval
request fails, when the configured model cannot run (naming what to configure), or when it
produces no usable structured answer.
