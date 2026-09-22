"""The static agent skill file, `skills/lore/SKILL.md`: it must stay thin.

Per the Amplifier Smart Tool spec, the agent skill carries the manifest's name and
description, the install commands, and the instruction to run `--help` and follow it.
Nothing more: per-capability invocations belong to each capability's own skill, rendered
by `lore <command> --help`, not hand-maintained prose that can drift out of date.
"""

from pathlib import Path

SKILL_PATH = Path(__file__).parents[1] / "skills" / "lore" / "SKILL.md"


def _skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_carries_the_install_commands() -> None:
    text = _skill_text()

    assert "uv tool install" in text
    assert "uv add" in text
    assert "uvx --from" in text


def test_skill_file_instructs_running_help_and_following_it() -> None:
    text = _skill_text()

    assert "lore --help" in text
    assert "Follow it" in text


def test_skill_file_carries_no_per_capability_invocation_block() -> None:
    """The deleted 'Where to start' block hand-maintained per-capability commands that could
    drift from the runtime skills `lore <command> --help` renders. It must not come back."""
    text = _skill_text()

    assert "Where to start" not in text
    assert "lore explain owner/repo" not in text
    assert "lore howto <library>" not in text
