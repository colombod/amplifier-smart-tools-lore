import re

import pytest

from lore.capabilities.explain import core
from lore.capabilities.explain.prompt import build_prompt, build_prompt_from_material
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
    prompt = build_prompt(
        "owner/repo", "How does X work?", [(1, "Some Page", "page body text")], "deepwiki answer text"
    )

    assert GROUNDING_RULE in prompt
    assert "owner/repo" in prompt
    assert "How does X work?" in prompt
    assert "Some Page" in prompt
    assert "page body text" in prompt
    assert "deepwiki answer text" in prompt


def test_build_prompt_from_material_carries_the_grounding_rule_and_the_material_and_names_the_caller_source() -> None:
    prompt = build_prompt_from_material("owner/repo", "How does X work?", "caller-supplied text")

    assert GROUNDING_RULE in prompt
    assert "owner/repo" in prompt
    assert "How does X work?" in prompt
    assert "caller-supplied text" in prompt
    assert '"caller"' in prompt


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


class _RecordingIntelligence:
    """Captures the request it was given and returns a fixed, valid structured output."""

    implementation = "test-recording"

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []

    def preflight(self) -> None:
        return None

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            output={
                "answer": "It works like this.",
                "citations": [{"source": "caller", "reference": "caller-supplied material"}],
                "unanswered": [],
            }
        )


def test_explain_with_material_never_calls_deepwiki_and_skips_the_never_indexed_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unmeasured = Freshness(
        repo="owner/repo",
        indexed_sha=None,
        verdict="unknown",
        summary="Freshness for owner/repo is unknown.",
        measured_at="2026-01-01T00:00:00+00:00",
        unmeasured=["DeepWiki has no indexed wiki for owner/repo."],
    )
    monkeypatch.setattr(core.freshness_core, "measure", lambda repo, timeout_seconds=30.0: unmeasured)

    def _must_not_be_called(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("must not retrieve from DeepWiki when material is supplied")

    monkeypatch.setattr(core.deepwiki, "read_wiki_structure", _must_not_be_called)
    monkeypatch.setattr(core.deepwiki, "ask", _must_not_be_called)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does it work?", material="Supplied material text.", intelligence=engine)

    assert len(engine.requests) == 1
    assert "Supplied material text." in engine.requests[0].prompt
    assert answer.freshness is unmeasured
    assert answer.citations[0].source == "caller"


def test_explain_with_material_still_measures_freshness_for_the_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    measured_calls: list[str] = []

    def _measure(repo: str, timeout_seconds: float = 30.0) -> Freshness:
        measured_calls.append(repo)
        return Freshness(
            repo=repo,
            indexed_sha="abc123",
            verdict="current",
            summary="current",
            measured_at="2026-01-01T00:00:00+00:00",
        )

    monkeypatch.setattr(core.freshness_core, "measure", _measure)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does it work?", material="Supplied material.", intelligence=engine)

    assert measured_calls == ["owner/repo"]
    assert answer.freshness.verdict == "current"
