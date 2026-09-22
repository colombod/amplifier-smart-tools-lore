"""Adverse-state coverage for howto's Context7 staleness gate.

Context7 publishes `state` and `lastUpdateDate` on every library; before this, `howto`
measured freshness for a GitHub-backed library and reported it, but never refused an
unfinished index and never told the MODEL its own documentation might be behind, only the
reader after the fact. These tests pin the refusal, the false-positive direction (a
`finalized`, current library gets no note), and that the lag note actually reaches the
prompt before synthesis.
"""

import pytest

from lore.capabilities.howto import core
from lore.intelligence.schemas import AgentRequest, AgentResult
from lore.schemas import Freshness, LibraryRef, LoreError


class _RunMustNotBeCalledIntelligence:
    """Preflight succeeds; `run` raises so a test can only pass if a guard fired before it."""

    implementation = "test-run-must-not-be-called"

    def preflight(self) -> None:
        return None

    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError("run() must not be called: the state gate should have raised first")


class _RecordingIntelligence:
    """Captures every request it was given and returns a fixed, valid structured output."""

    implementation = "test-recording"

    def __init__(self) -> None:
        self.requests: list[AgentRequest] = []

    def preflight(self) -> None:
        return None

    def run(self, request: AgentRequest) -> AgentResult:
        self.requests.append(request)
        return AgentResult(
            output={
                "answer": "Use it like this.",
                "citations": [{"source": "context7", "reference": "/owner/repo"}],
                "unanswered": [],
            }
        )


def _measured(head_date: str | None) -> Freshness:
    return Freshness(
        repo="owner/repo",
        indexed_sha="abc123",
        head_sha="def456",
        head_date=head_date,
        verdict="current",
        summary="current",
        measured_at="2026-09-22T00:00:00+00:00",
    )


def test_a_non_finalized_state_refuses_before_any_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = LibraryRef(id="/owner/repo", title="Repo", state="parsing")
    monkeypatch.setattr(core.context7, "resolve_library", lambda *a, **k: resolved)

    with pytest.raises(LoreError, match="not fully indexed"):
        core.howto("repo", "do a thing", intelligence=_RunMustNotBeCalledIntelligence())


def test_a_missing_state_is_not_treated_as_a_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """`state` absent (an older or thin Context7 response) must not be conflated with 'not finalized'."""
    resolved = LibraryRef(id="/websites/example", title="Example", state=None)
    monkeypatch.setattr(core.context7, "resolve_library", lambda *a, **k: resolved)
    monkeypatch.setattr(core.context7, "fetch_context", lambda *a, **k: "docs text")
    engine = _RecordingIntelligence()

    answer = core.howto("example", "do a thing", intelligence=engine)

    assert answer.answer == "Use it like this."


def test_current_context7_docs_carry_no_staleness_note(monkeypatch: pytest.MonkeyPatch) -> None:
    """The false-positive direction: documentation updated the same day as the head must not warn."""
    resolved = LibraryRef(id="/owner/repo", title="Repo", state="finalized", last_update_date="2026-09-01")
    monkeypatch.setattr(core.context7, "resolve_library", lambda *a, **k: resolved)
    monkeypatch.setattr(core.context7, "fetch_context", lambda *a, **k: "docs text")
    monkeypatch.setattr(core.freshness_core, "measure", lambda repo, timeout_seconds=30.0: _measured("2026-09-01"))
    monkeypatch.setattr(core.deepwiki, "ask", lambda ref, task, timeout_seconds=180.0: "deepwiki design answer")
    engine = _RecordingIntelligence()

    answer = core.howto("repo", "do a thing", intelligence=engine)

    assert answer.caveat is None
    assert "behind the repository's live head" not in (engine.requests[0].prompt)


def test_a_docs_lag_past_the_threshold_reaches_the_prompt_and_the_caveat(monkeypatch: pytest.MonkeyPatch) -> None:
    resolved = LibraryRef(id="/owner/repo", title="Repo", state="finalized", last_update_date="2026-01-01")
    monkeypatch.setattr(core.context7, "resolve_library", lambda *a, **k: resolved)
    monkeypatch.setattr(core.context7, "fetch_context", lambda *a, **k: "docs text")
    monkeypatch.setattr(core.freshness_core, "measure", lambda repo, timeout_seconds=30.0: _measured("2026-09-01"))
    monkeypatch.setattr(core.deepwiki, "ask", lambda ref, task, timeout_seconds=180.0: "deepwiki design answer")
    engine = _RecordingIntelligence()

    answer = core.howto("repo", "do a thing", context7_docs_aging_days=30, intelligence=engine)

    assert len(engine.requests) == 1
    assert "past the 30-day threshold" in engine.requests[0].prompt
    assert answer.caveat is not None
    assert "past the 30-day threshold" in answer.caveat


def test_an_unparsable_docs_date_is_treated_with_the_same_caution_as_a_measured_lag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = LibraryRef(id="/owner/repo", title="Repo", state="finalized", last_update_date=None)
    monkeypatch.setattr(core.context7, "resolve_library", lambda *a, **k: resolved)
    monkeypatch.setattr(core.context7, "fetch_context", lambda *a, **k: "docs text")
    monkeypatch.setattr(core.freshness_core, "measure", lambda repo, timeout_seconds=30.0: _measured("2026-09-01"))
    monkeypatch.setattr(core.deepwiki, "ask", lambda ref, task, timeout_seconds=180.0: "deepwiki design answer")
    engine = _RecordingIntelligence()

    answer = core.howto("repo", "do a thing", intelligence=engine)

    assert "could not be compared" in engine.requests[0].prompt
    assert answer.caveat is not None
    assert "could not be compared" in answer.caveat
