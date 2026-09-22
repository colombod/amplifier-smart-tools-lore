Reports whether lore's prerequisites are reachable right now: DeepWiki's MCP endpoint,
deepwiki.com, the Context7 API, the GitHub API (and whether `gh` is signed in, which only
lifts GitHub's anonymous rate limit), whether the optional Context7 API key is set, whether
the on-disk cache directory is writable, and whether the model-backed capabilities have their
prerequisite (`gh` installed and signed in). Run this first when something else is failing and
it is unclear whether the tool or the network is the problem. Every probe is cheap and never
raises: an unreachable service is a reported failure with a `detail` naming what to do, not an
exception.

`--timeout-seconds` bounds each individual probe (default `15.0`). Add `--json` to print the
full `CheckResult` model instead of one line per prerequisite.

```bash
lore check
```

```python
from lore.lib import check

result = check()
result.deterministic_ready, result.model_backed_ready
```

Returns a `CheckResult`: `checks`, one `Reachability` (`name`, `ok`, `detail`) per prerequisite;
`deterministic_ready`, `True` when DeepWiki, GitHub, and the cache are all usable with no
credentials; `model_backed_ready`, `True` when `gh` is installed and signed in.

## Failures

Never raises for an unreachable prerequisite; that is `ok=False` in the result. Only a bug in
`check` itself would raise.
