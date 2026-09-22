Measures how far DeepWiki's index for a repository trails the repository's own live default
branch. Reads the commit and date DeepWiki states it indexed off the page it renders for the
repository, reads the live default branch and its head commit through the GitHub API, and
compares them. No model is consulted: the result is a measurement, not an opinion. Reach for
this before trusting anything DeepWiki or a cached wiki says about `REPO`, to know how old
that knowledge is.

`REPO` is a GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL
(a trailing `.git` and any path past the repository name are ignored). `--timeout-seconds`
bounds each of the two sources this consults (default `30.0`). Add `--json` to print the full
`Freshness` model instead of the one-line summary.

```bash
lore freshness upstash/context7
```

```python
from lore.lib import freshness

result = freshness("upstash/context7")
result.verdict, result.commits_behind, result.days_behind, result.summary
```

Returns a `Freshness`: `indexed_sha`/`indexed_date` (what DeepWiki has), `head_sha`/`head_date`/
`default_branch` (what GitHub has now), `commits_behind`/`days_behind` (the gap), `verdict`
(`current`, `aging`, `stale`, or `unknown`), and `summary`, one line safe to show a person
verbatim. `verdict` is `current` when `commits_behind` is `0`; `aging` when at most 25 commits
and at most 30 days behind; `stale` past either bound; `unknown` when a signal could not be
read, in which case `unmeasured` names each one and why.

## Failures

Raises `LoreError` when `REPO` does not parse as either accepted form, or when GitHub reports
no repository at that slug (it may not exist, be private, or be misspelled; DeepWiki covers
public repositories only). A signal DeepWiki or GitHub could not supply is never an exception:
it lands in `unmeasured` and the verdict becomes `unknown`.
