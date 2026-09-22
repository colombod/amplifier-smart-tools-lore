Explains how the GitHub repository `REPO` works: its architecture, design, and how its
pieces are wired, for the question `QUESTION`. Measures freshness for `REPO` first; a
repository DeepWiki has never indexed has nothing to ground an answer in, so that raises
before a model is ever asked. Retrieves DeepWiki's own topic map and its own answer to
`QUESTION`, then synthesizes both through the configured model, grounded only in that
retrieved material. Nothing the model remembers from training is allowed into the answer:
every claim carries a citation, and anything the retrieved material does not cover is
reported in `unanswered` rather than guessed.

`REPO` is a GitHub repository, as `owner/name` or a full `https://github.com/owner/name`
URL. `QUESTION` is a question about the repository's architecture, design, or wiring.
`--model` selects the model to run the synthesis through, defaulting to
`DEFAULT_INTELLIGENCE_MODEL` in `schemas.py`. `--reasoning-effort` sets that model's
reasoning effort (default `low`). `--timeout-seconds` bounds each retrieval call and the
synthesis itself (default `300.0`). Add `--json` to print the full `Answer` model instead
of the rendered answer.

```bash
lore explain upstash/context7 "How is search request ranking implemented?"
```

```python
from lore.lib import explain

result = explain("upstash/context7", "How is search request ranking implemented?")
result.answer, result.citations, result.unanswered, result.caveat
```

Returns an `Answer`: `answer` (grounded only in retrieved material), `citations` (each
naming `deepwiki` and the page the claim rests on), `unanswered` (parts of the question the
retrieved material did not cover), `freshness` (the measurement `freshness` would report for
`REPO`), and `caveat`. `caveat` is `None` when the index is current, and otherwise names the
measured commits and days the index trails the repository by, so a stale index is never
silently trusted.

## Failures

Raises `LoreError` when `REPO` does not parse, when DeepWiki has no indexed wiki for it
(naming the `deepwiki.com` URL to visit to have it indexed), when the configured model
cannot run (naming what to configure), or when it produces no usable structured answer.
