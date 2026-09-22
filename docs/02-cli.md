# CLI Reference

The CLI is a thin wrapper over the [library](01-library.md): one command per capability, taking the same arguments under the same names, and doing nothing the library does not. 
What each argument means and what a capability returns or raises is documented there. This page covers only what the CLI adds: the invocation shape, and what reaches stdout, stderr, and the exit code.

Results go to stdout and diagnostics to stderr. A failure the library can name prints its message to stderr and exits 1; a bad invocation exits 2.

## Help

```
lore -h                 terse summary for a person: the commands, a line each
lore --help             the tool's skill, written for an agent driving it
lore <command> -h       terse summary of one command: its arguments and defaults
lore <command> --help   that command's skill, written for an agent about to call it
```

`--help` on the tool prints what `lib.skill()` returns and on a command what `lib.skill("<command>")` returns; the CLI adds nothing of its own.

## lore manifest

```bash
lore manifest
```

`lib.load_manifest()`, printed as JSON.

## lore freshness

```bash
lore freshness REPO [--timeout-seconds SECONDS] [--json]
```

`lib.freshness(repo, timeout_seconds)`. Without `--json`, prints one line: the verdict and the
summary. With `--json`, the full `Freshness` model.

## lore check

```bash
lore check [--timeout-seconds SECONDS] [--json]
```

`lib.check(timeout_seconds)`. Without `--json`, one line per prerequisite (`[ok]`, `[optional]`,
or `[FAIL]`) plus a line for `deterministic_ready`/`model_backed_ready`. With `--json`, the full
`CheckResult` model.

## lore fetch

```bash
lore fetch REPO [--refresh] [--timeout-seconds SECONDS] [--json]
```

`lib.fetch(repo, refresh, timeout_seconds)`. Without `--json`, the page count, totals, the
cache path the wiki was written to, and a numbered page list, never page content. With
`--json`, the full `WikiIndex` model.

## lore pages

```bash
lore pages REPO [--json]
```

`lib.pages(repo)`. Without `--json`, the page count, totals, and a numbered page list, never
page content. With `--json`, the full `WikiIndex` model.

## lore read

```bash
lore read REPO PAGE [--start N] [--limit N] [--json]
```

`lib.read(repo, page, start, limit)`, where `PAGE` is converted to an integer when it parses
as one, otherwise passed through as a title substring. Without `--json`, the slice's text; a
truncated result also prints, to stderr, how many characters remain and the exact command to
continue. With `--json`, the full `ReadResult` model.

## lore docs

```bash
lore docs LIBRARY TOPIC [--timeout-seconds SECONDS] [--json]
```

`lib.docs(library, topic, timeout_seconds)`. Without `--json`, the resolved library id, size,
path, and the preview. With `--json`, the full `DocsResult` model.

## lore search

```bash
lore search REPO PATTERN [--max-hits N] [--json]
```

`lib.search(repo, pattern, max_hits)`. Without `--json`, the total hit count and one line per
hit. With `--json`, the full `SearchResult` model.

## lore drift

```bash
lore drift REPO [--page PAGE] [--timeout-seconds SECONDS] [--json]
```

`lib.drift(repo, page, timeout_seconds)`, where `PAGE` is converted to an integer when it
parses as one, otherwise passed through as a title substring, exactly as `lore read`'s `PAGE`
is. Without `--json`, the report verdict and summary, then one block per page that is `broken`
or `drifted` (removed files named first, then that page's own summary), then a count of pages
intact or unknown that are not shown in detail. With `--json`, the full `DriftReport` model.

## lore explain

```bash
lore explain REPO QUESTION [--model MODEL] [--reasoning-effort EFFORT] [--timeout-seconds SECONDS] [--material-file PATH] [--at-head] [--at-head-read-limit N] [--json]
```

`lib.explain(repo, question, model, reasoning_effort, timeout_seconds, material, at_head, at_head_read_limit)`,
where `--material-file` is read and its contents passed as `material`; reading a path is the
CLI's own convenience, the library takes the content directly. Before synthesis, measures
per-page drift for the cached wiki: a `broken` verdict exits non-zero naming the broken
pages, the files, and how to proceed, before any model call is made. `--at-head` grounds on
source read directly from the repository's head commit instead of the wiki, bounded by
`--at-head-read-limit` total characters. Without `--json`, the caveat first when there is
one, then the answer, then citations, then anything unanswered. With `--json`, the full
`Answer` model.

## lore howto

```bash
lore howto LIBRARY TASK [--model MODEL] [--reasoning-effort EFFORT] [--timeout-seconds SECONDS] [--material-file PATH] [--json]
```

`lib.howto(library, task, model, reasoning_effort, timeout_seconds, material)`, where
`--material-file` is read and its contents passed as `material`; reading a path is the CLI's
own convenience, the library takes the content directly. Without `--json`, the caveat first
when there is one, then the answer, then citations, then anything unanswered. With `--json`,
the full `Answer` model.

## Adding a command

Each command gets a section here: the invocation shape with its options and defaults, which library function it calls, and what it prints and exits with. Argument meanings belong in the library reference, not here.
