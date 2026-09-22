---
smart_tool_format: 1
name: lore
version: 0.1.0
description: >-
  Answers how to use a library, how a project works, and what its architecture is, from DeepWiki and Context7 - with every answer carrying measured index freshness so stale knowledge is named rather than guessed - reach for it before writing code against a library or repository you do not already know cold, or whenever an answer's age matters
use_cases:
  - >-
    Understand an unfamiliar open source project before writing code against it. What it is,
    how its pieces fit, and where the extension points are.
  - >-
    Get current usage guidance for a library, with runnable snippets and citations, instead of
    an answer drawn from a model's training memory.
  - >-
    Measure how far behind a repository DeepWiki's index actually is, in commits and days,
    before trusting anything drawn from it.
  - >-
    Work with a generated wiki far larger than a context window, by putting it on disk and
    reading bounded slices of it.
  - >-
    Search a project's documentation for a term and get back page, line, and snippet rather
    than the whole wiki.
platforms:
  - linux
  - macos
  - windows
requires:
  - name: gh
    purpose: >-
      Generates the token that signs in to GitHub Copilot. Without it, the model-backed
      capabilities cannot authenticate.
    optional: true
    install: https://cli.github.com/
  - name: github-copilot-subscription
    purpose: >-
      A Copilot subscription on the account signed in to gh powers the model-backed
      capabilities. Without it, only the deterministic capabilities run.
    optional: true
    install: https://github.com/github/copilot-cli#prerequisites
  - name: context7-api-key
    purpose: >-
      Lifts Context7's anonymous rate limits for docs and howto retrieval. Anonymous
      access already works without it.
    optional: true
    install: https://context7.com/dashboard
---

Answers how to use a library, how a project works, and what its architecture is, from DeepWiki and Context7 - with every answer carrying measured index freshness so stale knowledge is named rather than guessed.

**The library is the tool.** `lore.lib` holds every capability. The CLI is a thin
wrapper over it, so anything you can do from the shell you can also do from Python.

## When to reach for it

Reach for it before writing code against a library or repository you do not already know
cold, and whenever an answer's age matters.

- "How do I use X" or "how does X work" for a public GitHub project or a published library.
- Before implementing against an SDK or API, to get real signatures rather than remembered ones.
- When a wiki or documentation set is too large to read, and you need a map and bounded reads.
- When you need to know whether the documentation you are about to trust is current.

Do not reach for it for code-level ground truth at a specific ref. Clone the repository and
read the source for that. This tool covers the layer above: what a project is, how it fits
together, and how it is meant to be driven.

## Sharp edges

- DeepWiki covers public repositories, and only those it has indexed. An unindexed repository
  is reported as such, with the URL that triggers indexing, rather than answered around.
- A DeepWiki index can trail the repository badly. `explain` measures drift for the cached
  wiki's own pages, not just the repository-wide gap: a page whose cited files no longer
  resolve makes it **refuse** rather than answer around a dead citation; a page whose cited
  files were merely edited still answers, with both the model and the reader told which
  files to treat with caution; a page whose citations are untouched carries no caveat at
  all, whatever the repository-wide gap. `--at-head` reads cited files directly from the
  repository's live head instead of trusting the wiki. `howto` treats Context7's own `state`
  and `lastUpdateDate` the same way.
- The model-backed capabilities answer only from what was retrieved in that run. What the
  sources did not cover comes back under `unanswered` rather than filled in.
- Grounding gives source fidelity, not omniscience: a citation means the sources said it,
  which is a stronger claim than a remembered answer but weaker than reading the code.

## Before writing code

Every capability has its own skill. Read `lore <command> --help` before calling it: it
carries the arguments, a worked invocation, the result, and the failures. Do not fill gaps
from memory. The library source beside this file, `lib.py`, carries the signatures. The
repository's `docs/01-library.md` and `docs/02-cli.md` carry the rest.

## Install

```bash
# as a CLI
uv tool install git+https://github.com/colombod/amplifier-smart-tools-lore

# as a library, from another project
uv add "lore @ git+https://github.com/colombod/amplifier-smart-tools-lore"

# once, without installing
uvx --from git+https://github.com/colombod/amplifier-smart-tools-lore lore --help
```
Verify with `lore manifest`, which needs no credentials.

## Prerequisites

Deterministic capabilities need only `uv`. Model-backed capabilities run through GitHub
Copilot, signed in as the GitHub CLI's user: `gh` must be installed and `gh auth login`
completed with an account that has a Copilot subscription. A model-backed capability never
falls back to a deterministic answer, and it names what to configure either way, but the two
prerequisites are not detected at the same moment. A missing or signed-out `gh` fails
immediately, before any retrieval. A missing Copilot entitlement surfaces only when the model
call itself fails, after retrieval has already run, because the SDK exposes no cheap way to
check entitlement up front.

Runs on Linux, macOS, and Windows.

## Straight and smart paths

Deterministic capabilities run with no provider configured. Model-backed capabilities go
through GitHub Copilot, signed in as the GitHub CLI's user, and say so in their help text.

## Output and failure contract

Results go to stdout, diagnostics to stderr. A failure prints a message naming what went
wrong and how to fix it, and exits non-zero: 1 for a failure the tool can name, 2 for a
bad invocation. Never treat an empty result as success.

## Choosing a surface

Import the library from Python. Shell out to the CLI from anything that cannot import
Python in-process: a shell script, a CI job, or an agent that can run commands but not
load a Python object. Both reach the same capabilities.
