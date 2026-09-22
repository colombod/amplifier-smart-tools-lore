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
# Print the tool's manifest as JSON
lore manifest
```

See the [CLI reference](docs/02-cli.md) for every flag and the [library reference](docs/01-library.md) for the Python surface.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for details on how to set up your development environment.
