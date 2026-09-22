from pathlib import Path
import subprocess

import pytest

from lore.capabilities.check import core
from lore.core.manifest import requirement_install_url, requirement_optional
from lore.sources import context7


def test_context7_api_key_reachability_reports_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(context7.API_KEY_ENV, raising=False)

    result = core._context7_api_key()

    assert result.ok is False
    assert context7.API_KEY_ENV in result.detail


def test_context7_api_key_reachability_reports_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(context7.API_KEY_ENV, "a-key")

    result = core._context7_api_key()

    assert result.ok is True
    assert result.detail == "Set."


def test_context7_api_key_reachability_is_optional_per_the_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(context7.API_KEY_ENV, raising=False)

    result = core._context7_api_key()

    assert result.optional is requirement_optional("context7-api-key")
    assert result.optional is True


def test_cache_directory_reachability_is_writable_under_the_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))

    result = core._cache_directory()

    assert result.ok is True
    assert str(root) in result.detail
    assert list(root.glob(".lore-check-write-probe")) == []


def test_gh_authenticated_is_false_when_gh_is_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)

    assert core._gh_authenticated() is False


def test_gh_authenticated_reflects_a_zero_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(core.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode=0))

    assert core._gh_authenticated() is True


def test_gh_authenticated_is_false_on_a_nonzero_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(core.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode=1))

    assert core._gh_authenticated() is False


def test_gh_authenticated_is_false_when_the_subprocess_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="gh", timeout=10)

    monkeypatch.setattr(core.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(core.subprocess, "run", _raise)

    assert core._gh_authenticated() is False


def test_copilot_prerequisite_names_the_same_install_url_the_manifest_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)

    result = core._copilot_prerequisite()

    assert result.ok is False
    assert requirement_install_url("gh") in result.detail


def test_copilot_prerequisite_is_optional_per_the_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core.shutil, "which", lambda _name: None)

    result = core._copilot_prerequisite()

    assert result.optional is requirement_optional("gh")
    assert result.optional is True
