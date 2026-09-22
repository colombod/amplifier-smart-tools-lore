import re

import pytest

from lore.capabilities.explain import core
from lore.capabilities.explain.prompt import build_prompt
from lore.grounding import GROUNDING_RULE
from lore.intelligence.schemas import AgentRequest, AgentResult
from lore.schemas import Freshness, LoreError


class _RunMustNotBeCalledIntelligence:
    """Preflight succeeds; `run` raises so it can only prove a guard fires before it."""

    implementation = "test-run-must-not-be-called"

    def preflight(self) -> None:
        return None

    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError("run() must not be called: a guard should have raised first")


class _PreflightFailsIntelligence:
    """`preflight` raises; `run` raises so it can only prove preflight is checked first."""

    implementation = "test-preflight-fails"

    def preflight(self) -> None:
        raise LoreError("gh is not signed in. Run `gh auth login`.")

    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError("run() must not be called: preflight should have raised first")


def test_build_prompt_carries_the_grounding_rule_and_all_retrieved_material() -> None:
    prompt = build_prompt("owner/repo", "How does X work?", "structure text", "deepwiki answer text")

    assert GROUNDING_RULE in prompt
    assert "owner/repo" in prompt
    assert "How does X work?" in prompt
    assert "structure text" in prompt
    assert "deepwiki answer text" in prompt


def test_explain_propagates_a_preflight_failure_without_calling_run() -> None:
    with pytest.raises(LoreError, match="gh auth login"):
        core.explain("owner/repo", "How does it work?", intelligence=_PreflightFailsIntelligence())


def test_explain_raises_before_calling_run_when_deepwiki_has_not_indexed_the_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmeasured = Freshness(
        repo="owner/repo",
        indexed_sha=None,
        verdict="unknown",
        summary="Freshness for owner/repo is unknown. Visit https://deepwiki.com/owner/repo to have it indexed.",
        measured_at="2026-01-01T00:00:00+00:00",
        unmeasured=["Visit https://deepwiki.com/owner/repo to have it indexed."],
    )
    monkeypatch.setattr(core.freshness_core, "measure", lambda repo, timeout_seconds=30.0: unmeasured)

    with pytest.raises(LoreError, match=re.escape("deepwiki.com/owner/repo")):
        core.explain("owner/repo", "How does it work?", intelligence=_RunMustNotBeCalledIntelligence())
