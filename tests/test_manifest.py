from importlib.metadata import version
import json
from pathlib import Path

import pytest

from lore.core.manifest import MANIFEST_PATH, requirement_install_url
from lore.lib import load_manifest
from lore.schemas import LoreError

DISTRIBUTION_ROOT = Path(__file__).parents[1]


def test_manifest_matches_the_descriptor_and_package() -> None:
    manifest = load_manifest()
    descriptor = json.loads((DISTRIBUTION_ROOT / "smart-tool.json").read_text(encoding="utf-8"))

    assert DISTRIBUTION_ROOT / descriptor["manifest"] == MANIFEST_PATH
    assert manifest.name == descriptor["cli_argv"][0]
    assert manifest.version == version("lore")


def test_requirement_install_url_reads_the_gh_requirement_from_the_manifest() -> None:
    manifest = load_manifest()
    gh_requirement = next(requirement for requirement in manifest.requires if requirement.name == "gh")

    assert requirement_install_url("gh") == gh_requirement.install


def test_requirement_install_url_names_the_known_requirements_for_an_unknown_name() -> None:
    with pytest.raises(LoreError, match="gh"):
        requirement_install_url("not-a-requirement")


def test_description_is_consistent_everywhere_it_is_duplicated() -> None:
    """The manifest's terse description is copy-pasted in four other places; they must agree.

    Compared with the trailing period stripped, since some of the four are Markdown/docstring
    prose that ends a sentence with one and others are bare literals that do not.
    """
    normalized = load_manifest().description.rstrip(".")

    pyproject_text = (DISTRIBUTION_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    skill_body = (DISTRIBUTION_ROOT / "skills" / "lore" / "SKILL.md").read_text(encoding="utf-8")
    readme = (DISTRIBUTION_ROOT / "README.md").read_text(encoding="utf-8")
    cli_source = (DISTRIBUTION_ROOT / "src" / "lore" / "cli.py").read_text(encoding="utf-8")

    assert f'description = "{normalized}"' in pyproject_text
    assert normalized in skill_body
    assert normalized in readme
    assert normalized in cli_source


def test_description_names_what_the_tool_does_before_when_to_reach_for_it() -> None:
    description = load_manifest().description

    what_index = description.index("Answers how to use a library")
    when_index = description.index("reach for it")

    assert what_index < when_index
