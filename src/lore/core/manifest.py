"""Manifest: the packaged SMART_TOOL.md read back as structured data."""

from pathlib import Path

import yaml

from lore.schemas import LoreError, Manifest

MANIFEST_PATH = Path(__file__).parents[1] / "SMART_TOOL.md"


def load_manifest() -> Manifest:
    """Parse the frontmatter and body of the SMART_TOOL.md shipped inside the package."""
    _, frontmatter, body = MANIFEST_PATH.read_text(encoding="utf-8").split("---", 2)
    return Manifest.model_validate({**yaml.safe_load(frontmatter), "body": body.strip()})


def requirement_install_url(name: str) -> str:
    """The `install` reference the manifest declares for one requirement.

    The single source for an install URL a failure message quotes, so the manifest and the
    message that points at it can never drift apart.

    Args:
        name: The requirement's name, e.g. `gh`.

    Returns:
        That requirement's `install` field.

    Raises:
        LoreError: no requirement named `name` is declared in the manifest.
    """
    manifest = load_manifest()
    for requirement in manifest.requires:
        if requirement.name == name:
            return requirement.install
    known = ", ".join(requirement.name for requirement in manifest.requires)
    raise LoreError(f"'{name}' is not a requirement in the manifest. Requirements are: {known}.")


def requirement_optional(name: str) -> bool:
    """Whether the manifest declares the requirement named `name` optional.

    The single source `check` reads to decide between rendering an unsatisfied
    prerequisite `[optional]` or `[FAIL]`, so that decision can never drift into a second
    opinion hardcoded alongside the check itself.

    Args:
        name: The requirement's name, e.g. `gh`.

    Returns:
        `True` when the manifest declares that requirement `optional: true`. `False` when
        it is declared required, or when no requirement named `name` exists: an undeclared
        requirement carries no opinion on optionality, so it defaults to required.
    """
    manifest = load_manifest()
    for requirement in manifest.requires:
        if requirement.name == name:
            return requirement.optional
    return False
