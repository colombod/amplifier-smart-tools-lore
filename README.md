# Lore Smart Tool

Answers how to use a library, how a project works, and what its architecture is, from DeepWiki and Context7 - with every answer carrying measured index freshness so stale knowledge is named rather than guessed.

Lore is a [Smart Tool](https://github.com/microsoft/amplifier-smart-tools): a library with a thin CLI over it, whose model-backed capabilities sit behind an interface.

## Installation

Prerequisites:
- [uv](https://docs.astral.sh/uv/getting-started/installation/).
- [GitHub CLI](https://cli.github.com/) signed in to an account with a [GitHub Copilot subscription](https://github.com/github/copilot-cli#prerequisites) for the model-backed capabilities.

```bash
uv tool install git+https://github.com/colombod/amplifier-smart-tools-lore
```

To use it as a library:

```bash
uv add "lore @ git+https://github.com/colombod/amplifier-smart-tools-lore"
```

To run it once without installing:

```bash
uvx --from git+https://github.com/colombod/amplifier-smart-tools-lore lore --help
```

To teach a coding agent how to use it, install the [skill](skills/lore/SKILL.md):

```bash
npx skills add colombod/amplifier-smart-tools-lore
```

To update:

```bash
uv tool upgrade lore
npx skills update lore   # add --global if the skill was installed globally
```

To uninstall:

```bash
uv tool uninstall lore
npx skills remove lore   # add --global if the skill was installed globally
```

Verify an install with `lore manifest`, which needs no credentials.

## Interface

```bash
# Measure how far DeepWiki's index trails the repository
lore freshness upstash/context7

# Write the wiki to disk and get back a map of it, not 292,000 tokens of content
lore fetch upstash/context7
lore pages upstash/context7
lore read upstash/context7 --page 7
lore search upstash/context7 "rate limit"

# Context7 documentation for a library, written to disk and previewed
lore docs react "server components"

# Grounded answers, model-backed, carrying citations and the measured age
lore explain upstash/context7 "how does the transport layer work?"
lore howto context7 "call the HTTP API from curl"

# Prerequisites, and the manifest that verifies an install
lore check
lore manifest
```

See the [CLI reference](docs/02-cli.md) for every flag and the [library reference](docs/01-library.md) for the Python surface.

## What it is for

Ask an agent how to use a library and it answers from training memory, which is confidently
wrong about anything that moved since its cutoff. A generated wiki fixes that, until the wiki
is bigger than the context window or older than the repository. Both failures are measurable,
so this tool measures them.

One `read_wiki_contents` call for `upstash/context7` returns 1,169,101 characters across 130
pages, roughly 292,000 tokens. `lore fetch` puts that on disk and hands back a 17KB index;
`read` and `search` are the only ways back in, and both are capped.

On the same day, DeepWiki's index for that repository sat at commit `23843e9c` of 20 July
2026 while the default branch was at `eb27b949` of 21 September 2026. `lore freshness` reports
that as 82 commits and 63 days behind, measured against the GitHub compare API rather than
asked of a model, and every model-backed answer carries that verdict with it.

## I/O contract

Results go to stdout and diagnostics to stderr. Every capability takes `--json` for the
structured form. A failure the tool can name exits 1; a bad invocation exits 2. An empty
result is never success.

Deterministic capabilities (`freshness`, `fetch`, `pages`, `read`, `search`, `docs`, `check`,
`manifest`) run with no model provider, no API key, and no GitHub token. `GITHUB_TOKEN` and
`CONTEXT7_API_KEY` are honoured when set and only lift rate limits. `LORE_CACHE_DIR` moves the
cache. The model-backed capabilities (`explain`, `howto`) need `gh` signed in to an account
with a Copilot subscription, and fail immediately naming that when it is missing.

## Documentation

- [docs/00-vision.md](docs/00-vision.md): what the tool is, what it is not, and why.
- [docs/01-library.md](docs/01-library.md): every capability's Python signature and behaviour.
- [docs/02-cli.md](docs/02-cli.md): the invocation shape of each command.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to set up your development environment.
