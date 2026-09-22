from pathlib import Path
import sys

import pytest
from typer.testing import CliRunner

from lore import cli, lib
from lore.schemas import Answer, CheckResult, Freshness, PageEntry, Reachability, WikiIndex

runner = CliRunner()


def _wiki_index(root: str) -> WikiIndex:
    return WikiIndex(
        repo="owner/repo",
        root=root,
        pages=[PageEntry(number=1, title="One", path="pages/001-one.md", characters=4, estimated_tokens=1)],
        total_characters=4,
        total_estimated_tokens=1,
        freshness=Freshness(
            repo="owner/repo", verdict="current", summary="current", measured_at="2026-01-01T00:00:00+00:00"
        ),
        fetched_at="2026-01-01T00:00:00+00:00",
        from_cache=True,
    )


def test_fetch_default_output_prints_the_cache_location_before_the_page_list(monkeypatch: pytest.MonkeyPatch) -> None:
    index = _wiki_index("/tmp/lore-cache/wiki/owner__repo/abc123")
    monkeypatch.setattr(lib, "fetch", lambda repo, refresh=False, timeout_seconds=180.0: index)

    result = runner.invoke(cli.app, ["fetch", "owner/repo"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    cache_line_index = next(i for i, line in enumerate(lines) if line.startswith("Cache:"))
    page_line_index = next(i for i, line in enumerate(lines) if "One" in line)
    assert index.root in lines[cache_line_index]
    assert cache_line_index < page_line_index


def _answer() -> Answer:
    return Answer(
        question="How does it work?",
        target="owner/repo",
        answer="It works.",
        citations=[],
        unanswered=[],
        freshness=Freshness(
            repo="owner/repo", verdict="current", summary="current", measured_at="2026-01-01T00:00:00+00:00"
        ),
    )


def test_explain_material_file_reads_the_file_and_passes_its_contents_to_the_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    material_path = tmp_path / "material.md"
    material_path.write_text("Some retrieved material.", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_explain(
        repo: str, question: str, model: str, reasoning_effort: str, timeout_seconds: float, material: str | None
    ) -> Answer:
        captured["material"] = material
        return _answer()

    monkeypatch.setattr(lib, "explain", _fake_explain)

    result = runner.invoke(
        cli.app, ["explain", "owner/repo", "How does it work?", "--material-file", str(material_path)]
    )

    assert result.exit_code == 0
    assert captured["material"] == "Some retrieved material."


def test_explain_material_file_missing_is_a_named_failure_not_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`main()` is what the installed `lore` script actually runs: it catches `LoreError` and
    exits 1 with a message on stderr. `CliRunner.invoke(app, ...)` bypasses that wrapper
    entirely and lets the exception escape uncaught, so this drives the real entry point."""
    missing_path = tmp_path / "does-not-exist.md"
    monkeypatch.setattr(
        sys, "argv", ["lore", "explain", "owner/repo", "How does it work?", "--material-file", str(missing_path)]
    )

    exit_code = cli.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "--material-file" in captured.err


def test_howto_material_file_reads_the_file_and_passes_its_contents_to_the_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    material_path = tmp_path / "material.md"
    material_path.write_text("Some docs text.", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_howto(
        library: str, task: str, model: str, reasoning_effort: str, timeout_seconds: float, material: str | None
    ) -> Answer:
        captured["material"] = material
        return _answer()

    monkeypatch.setattr(lib, "howto", _fake_howto)

    result = runner.invoke(cli.app, ["howto", "fastapi", "add routing", "--material-file", str(material_path)])

    assert result.exit_code == 0
    assert captured["material"] == "Some docs text."


def test_check_renders_an_unsatisfied_optional_prerequisite_as_optional_not_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check_result = CheckResult(
        checks=[
            Reachability(name="required thing", ok=False, detail="down", optional=False),
            Reachability(name="optional thing", ok=False, detail="not set", optional=True),
            Reachability(name="satisfied thing", ok=True, detail="fine", optional=True),
        ],
        deterministic_ready=False,
        model_backed_ready=False,
    )
    monkeypatch.setattr(lib, "check", lambda timeout_seconds=15.0: check_result)

    result = runner.invoke(cli.app, ["check"])

    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert "[FAIL] required thing: down" in lines
    assert "[optional] optional thing: not set" in lines
    assert "[ok] satisfied thing: fine" in lines
