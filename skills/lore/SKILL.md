---
name: lore
description: >-
  Answers how to use a library, how a project works, and what its architecture is, grounded in
  DeepWiki and Context7 rather than model memory, with the index's measured age attached to
  every answer. Use it before writing code against an unfamiliar library, SDK, API, or GitHub
  project, when asked how something works or how it is put together, or when documentation is
  too large to read and needs a map and bounded reads. Puts oversized wikis on disk and reads
  capped slices, and reports how many commits and days behind the source an index is. Drive it
  from the command line as `lore`, or from Python through `lore.lib`.
license: MIT
metadata:
  repository: https://github.com/colombod/amplifier-smart-tools-lore
---

# Using lore

Answers how to use a library, how a project works, and what its architecture is, from DeepWiki and Context7 - with every answer carrying measured index freshness so stale knowledge is named rather than guessed.

## Install

```bash
# as a CLI
uv tool install git+https://github.com/colombod/amplifier-smart-tools-lore

# as a library, from another project
uv add "lore @ git+https://github.com/colombod/amplifier-smart-tools-lore"

# once, without installing
uvx --from git+https://github.com/colombod/amplifier-smart-tools-lore lore --help
```
## Use it

Run `lore --help`. It prints the tool's skill: when to use it, every capability, sharp
edges, and which files to read. Follow it. Then read the capability's own skill with
`lore <command> --help` before calling it: it carries the arguments, a worked
invocation, the result, and the failures. Never work from memory.

Where to start, by what is being asked:

```bash
lore explain owner/repo "how does X work?"   # architecture, wiring, design
lore howto <library> "<task>"                # usage, with runnable snippets
lore freshness owner/repo                    # how old is the index, in commits and days
lore fetch owner/repo && lore search owner/repo "<term>"   # large wiki, bounded reads
```

`explain` and `howto` are model-backed and need `gh` signed in to a Copilot account.
Everything else runs with nothing configured.
