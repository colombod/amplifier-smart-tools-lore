"""The continuation a bounded read hands back must actually run.

A continuation is the only thing telling a caller how to reach the rest of a page, so a
string that looks right and is rejected by the CLI is worse than no continuation at all.
These tests run it against the real Typer application rather than asserting on its text,
which is what a text assertion missed: `--page` read plausibly and was not an option.
"""

import shlex

import pytest
from typer.testing import CliRunner

from lore import store
from lore.cli import app


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LORE_CACHE_DIR", str(tmp_path))
    return tmp_path


def _freshness(repo: str):
    from datetime import UTC, datetime

    from lore.schemas import Freshness

    return Freshness(repo=repo, verdict="unknown", summary="not measured", measured_at=datetime.now(UTC).isoformat())


def test_the_continuation_of_a_truncated_read_runs_against_the_real_cli(cache_dir) -> None:
    repo = "owner/repo"
    store.write_wiki(repo, f"# Page: Long\n{'x' * 5000}\n", _freshness(repo))

    first = store.read_page(repo, 1, start=0, limit=1000)
    assert first.truncated
    assert first.continuation is not None

    argv = shlex.split(first.continuation)
    assert argv[0] == "lore"
    result = CliRunner().invoke(app, argv[1:])

    assert result.exit_code == 0, result.output
    assert "No such option" not in result.output


def test_following_continuations_reconstructs_the_page_through_the_cli(cache_dir) -> None:
    repo = "owner/repo"
    body = "".join(str(index % 10) for index in range(4500))
    store.write_wiki(repo, f"# Page: Long\n{body}\n", _freshness(repo))

    runner = CliRunner()
    slice_result = store.read_page(repo, 1, start=0, limit=1000)
    collected = slice_result.text
    while slice_result.truncated:
        assert slice_result.continuation is not None
        argv = shlex.split(slice_result.continuation)[1:]
        assert runner.invoke(app, argv).exit_code == 0
        slice_result = store.read_page(repo, 1, start=slice_result.next_start or 0, limit=1000)
        collected += slice_result.text

    assert slice_result.next_start is None
    assert collected == store.read_page(repo, 1, start=0, limit=10_000_000).text
