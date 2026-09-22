---
name: lore
description: >-
  Answers how to use a library, how a project works, and what its architecture is, from DeepWiki and Context7 - with every answer carrying measured index freshness so stale knowledge is named rather than guessed. Drive it from the command line as `lore`, or from Python through
  `lore.lib`. Triggers on "lore".
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
