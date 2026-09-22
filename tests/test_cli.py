from pathlib import Path
import sys

import pytest
from typer.testing import CliRunner

from lore import cli, lib
from lore.schemas import Answer, CheckResult, DriftReport, Freshness, PageEntry, Reachability, ReadResult, WikiIndex

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
        repo: str,
        question: str,
        model: str,
        reasoning_effort: str,
        timeout_seconds: float,
        material: str | None,
        at_head: bool,
        at_head_read_limit: int,
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


def test_explain_caveat_goes_to_stderr_not_stdout_in_human_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A staleness caveat is a diagnostic, not part of the answer a caller may pipe onward.

    Uses `CliRunner`, which captures stdout and stderr as separate streams (`result.stdout`,
    `result.stderr`), rather than `cli.main()`: a successful run exits through Click's own
    `ctx.exit()`, which raises `SystemExit` past `main()`'s `except LoreError` and out of the
    test, so only the error path can be driven through `main()` directly.
    """
    answer = Answer(
        question="How does it work?",
        target="owner/repo",
        answer="It works.",
        citations=[],
        unanswered=[],
        freshness=Freshness(
            repo="owner/repo", verdict="stale", summary="stale", measured_at="2026-01-01T00:00:00+00:00"
        ),
        caveat="The index is 10 commits (5 days) behind.",
    )
    monkeypatch.setattr(
        lib,
        "explain",
        lambda repo, question, model, reasoning_effort, timeout_seconds, material, at_head, at_head_read_limit: answer,
    )

    result = runner.invoke(cli.app, ["explain", "owner/repo", "How does it work?"])

    assert result.exit_code == 0
    assert "CAVEAT" not in result.stdout
    assert result.stdout.startswith("It works.")
    assert "CAVEAT: The index is 10 commits (5 days) behind." in result.stderr


def test_explain_json_output_still_carries_the_caveat_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--json` is the structured result, so the caveat is a field there rather than a diagnostic."""
    answer = Answer(
        question="How does it work?",
        target="owner/repo",
        answer="It works.",
        citations=[],
        unanswered=[],
        freshness=Freshness(
            repo="owner/repo", verdict="stale", summary="stale", measured_at="2026-01-01T00:00:00+00:00"
        ),
        caveat="The index is 10 commits (5 days) behind.",
    )
    monkeypatch.setattr(
        lib,
        "explain",
        lambda repo, question, model, reasoning_effort, timeout_seconds, material, at_head, at_head_read_limit: answer,
    )

    result = runner.invoke(cli.app, ["explain", "owner/repo", "How does it work?", "--json"])

    assert result.exit_code == 0
    assert '"caveat": "The index is 10 commits (5 days) behind."' in result.stdout


def test_explain_material_file_with_invalid_utf8_is_a_named_failure_naming_encoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bad_path = tmp_path / "material.md"
    bad_path.write_bytes(b"\xff\xfe not utf-8")
    monkeypatch.setattr(
        sys, "argv", ["lore", "explain", "owner/repo", "How does it work?", "--material-file", str(bad_path)]
    )

    exit_code = cli.main()

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "--material-file" in captured.err
    assert "UTF-8" in captured.err


def test_read_passes_the_page_argument_through_unconverted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI must not decide whether a page selector is a number or a title substring; that
    decision belongs to the library (`store._resolve_page`), so the raw string passes through."""
    captured: dict[str, object] = {}

    def _fake_read(repo: str, page: object, start: int, limit: int) -> ReadResult:
        captured["page"] = page
        return ReadResult(
            repo=repo,
            page_number=7,
            page_title="Seven",
            path="pages/007-seven.md",
            text="seven",
            start=0,
            returned_characters=5,
            total_characters=5,
            truncated=False,
        )

    monkeypatch.setattr(lib, "read", _fake_read)

    result = runner.invoke(cli.app, ["read", "owner/repo", "7"])

    assert result.exit_code == 0
    assert captured["page"] == "7"
    assert type(captured["page"]) is str


def test_drift_passes_the_page_option_through_unconverted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same contract as `read`: `--page` is passed through, never normalized by the CLI."""
    captured: dict[str, object] = {}

    def _fake_drift(repo: str, page: object, timeout_seconds: float) -> DriftReport:
        captured["page"] = page
        return DriftReport(
            repo=repo,
            indexed_sha="abc123",
            head_sha="def456",
            pages=[],
            verdict="intact",
            changed_file_count=0,
            comparison_complete=True,
            summary="ok",
        )

    monkeypatch.setattr(lib, "drift", _fake_drift)

    result = runner.invoke(cli.app, ["drift", "owner/repo", "--page", "7"])

    assert result.exit_code == 0
    assert captured["page"] == "7"
    assert type(captured["page"]) is str


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
