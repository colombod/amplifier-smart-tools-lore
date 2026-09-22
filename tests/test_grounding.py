import pytest

from lore import grounding
from lore.intelligence.schemas import AgentResult
from lore.schemas import AtHeadFileStatus, Citation, DriftReport, Freshness, LoreError


def _freshness(verdict: str, **overrides: object) -> Freshness:
    fields: dict[str, object] = {
        "repo": "owner/repo",
        "verdict": verdict,
        "summary": "summary",
        "measured_at": "2026-01-01T00:00:00+00:00",
        "unmeasured": [],
    }
    fields.update(overrides)
    return Freshness.model_validate(fields)


def _drift_report(verdict: str, **overrides: object) -> DriftReport:
    fields: dict[str, object] = {
        "repo": "owner/repo",
        "indexed_sha": "abc123",
        "head_sha": "def456",
        "pages": [],
        "verdict": verdict,
        "changed_file_count": 0,
        "comparison_complete": True,
        "summary": f"{verdict} summary",
    }
    fields.update(overrides)
    return DriftReport.model_validate(fields)


def test_caveat_is_none_for_current() -> None:
    assert grounding.caveat_for(_freshness("current")) is None


def test_caveat_for_unknown_names_the_unmeasured_reason() -> None:
    freshness = _freshness("unknown", unmeasured=["DeepWiki has no indexed wiki for owner/repo."])

    caveat = grounding.caveat_for(freshness)

    assert caveat is not None
    assert "owner/repo" in caveat
    assert "DeepWiki has no indexed wiki for owner/repo." in caveat


def test_caveat_for_unknown_has_a_fallback_reason_when_nothing_was_recorded() -> None:
    freshness = _freshness("unknown", unmeasured=[])

    caveat = grounding.caveat_for(freshness)

    assert caveat is not None
    assert "owner/repo" in caveat


def test_caveat_for_aging_carries_the_measured_numbers_and_warns_about_recent_changes() -> None:
    freshness = _freshness("aging", commits_behind=10, days_behind=5)

    caveat = grounding.caveat_for(freshness)

    assert caveat is not None
    assert "10 commits" in caveat
    assert "5 days" in caveat
    assert "may be missing" in caveat


def test_caveat_for_stale_carries_the_measured_numbers_and_says_check_the_current_head() -> None:
    freshness = _freshness("stale", commits_behind=82, days_behind=63)

    caveat = grounding.caveat_for(freshness)

    assert caveat is not None
    assert "82 commits" in caveat
    assert "63 days" in caveat
    assert "current head" in caveat
    assert "probably still sound" in caveat


def test_caveat_for_stale_singularizes_one_commit_and_one_day() -> None:
    freshness = _freshness("stale", commits_behind=1, days_behind=1)

    caveat = grounding.caveat_for(freshness)

    assert caveat is not None
    assert "1 commit " in caveat
    assert "1 day" in caveat
    assert "1 commits" not in caveat
    assert "1 days" not in caveat


def test_caveat_for_stale_omits_the_days_clause_when_days_behind_is_unknown() -> None:
    freshness = _freshness("stale", commits_behind=25, days_behind=None)

    caveat = grounding.caveat_for(freshness)

    assert caveat is not None
    assert "25 commits" in caveat
    assert "days" not in caveat


def test_answer_from_result_maps_a_well_formed_output() -> None:
    freshness = _freshness("current")
    result = AgentResult(
        output={
            "answer": "It works like this.",
            "citations": [{"source": "deepwiki", "reference": "Architecture"}],
            "unanswered": ["Deployment topology"],
        },
        text="It works like this.",
        session_id="session-1",
    )

    answer = grounding.answer_from_result("How does it work?", "owner/repo", result, freshness)

    assert answer.question == "How does it work?"
    assert answer.target == "owner/repo"
    assert answer.answer == "It works like this."
    assert answer.citations == [Citation(source="deepwiki", reference="Architecture")]
    assert answer.unanswered == ["Deployment topology"]
    assert answer.freshness is freshness
    assert answer.caveat is None


def test_answer_from_result_defaults_citations_and_unanswered_when_absent() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={"answer": "It works."})

    answer = grounding.answer_from_result("q", "owner/repo", result, freshness)

    assert answer.citations == []
    assert answer.unanswered == []


def test_answer_from_result_raises_on_an_agent_error() -> None:
    freshness = _freshness("current")
    result = AgentResult(error="The agent did not finish within 300 seconds.")

    with pytest.raises(LoreError, match="did not finish"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_names_a_remedy_for_an_agent_error() -> None:
    freshness = _freshness("current")
    result = AgentResult(error="RuntimeError: the SDK could not start a session.")

    with pytest.raises(LoreError, match=r"gh auth status"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_raises_when_output_is_empty() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={})

    with pytest.raises(LoreError, match="no structured output"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_names_a_remedy_when_output_is_missing() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={})

    with pytest.raises(LoreError, match="Retry the call"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_raises_when_output_is_none() -> None:
    freshness = _freshness("current")
    result = AgentResult(output=None)

    with pytest.raises(LoreError, match="no structured output"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_raises_when_the_answer_text_is_empty() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={"answer": "   ", "citations": [], "unanswered": []})

    with pytest.raises(LoreError, match="was empty"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_names_a_remedy_when_the_answer_text_is_empty() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={"answer": "   ", "citations": [], "unanswered": []})

    with pytest.raises(LoreError, match="Retry, or narrow the question"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_raises_when_the_answer_field_is_missing() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={"citations": [], "unanswered": []})

    with pytest.raises(LoreError, match="was empty"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_answer_from_result_raises_on_a_malformed_citation() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={"answer": "ok", "citations": [{"source": "not-a-source"}], "unanswered": []})

    with pytest.raises(LoreError, match="citation contract"):
        grounding.answer_from_result("q", "owner/repo", result, freshness)


def test_caveat_for_drift_is_none_for_an_intact_page_however_stale_the_index() -> None:
    """The false-positive direction: many commits behind, but every cited file untouched."""
    freshness = _freshness("stale", commits_behind=84, days_behind=63)
    drift = _drift_report("intact")

    assert grounding.caveat_for_drift(freshness, drift) is None


def test_caveat_for_drift_names_the_unestablished_comparison_for_unknown_drift() -> None:
    """`unknown` must never read as `intact`, and the caveat must say why it could not be measured."""
    freshness = _freshness("stale", commits_behind=10, days_behind=5)
    drift = _drift_report("unknown", summary="owner/repo: unknown, the changed-file comparison was incomplete.")

    caveat = grounding.caveat_for_drift(freshness, drift)

    assert caveat is not None
    assert "could not be established" in caveat
    assert "changed-file comparison was incomplete" in caveat


def test_caveat_for_drift_falls_back_to_the_plain_freshness_caveat_for_drifted() -> None:
    freshness = _freshness("aging", commits_behind=5, days_behind=3)
    drift = _drift_report("drifted")

    caveat = grounding.caveat_for_drift(freshness, drift)

    assert caveat == grounding.caveat_for(freshness)


def test_caveat_for_drift_falls_back_to_caveat_for_when_drift_was_not_measured() -> None:
    freshness = _freshness("stale", commits_behind=82, days_behind=63)

    assert grounding.caveat_for_drift(freshness, None) == grounding.caveat_for(freshness)


def test_answer_from_result_uses_caveat_for_drift_when_a_drift_report_is_given() -> None:
    freshness = _freshness("stale", commits_behind=84, days_behind=63)
    drift = _drift_report("intact")
    result = AgentResult(output={"answer": "ok", "citations": [], "unanswered": []})

    answer = grounding.answer_from_result("q", "owner/repo", result, freshness, drift_report=drift)

    assert answer.caveat is None


def test_answer_from_result_sets_the_head_ref_on_at_head_citations_regardless_of_the_model() -> None:
    """The library enforces `ref` mechanically; it is never trusted from what the model submitted."""
    freshness = _freshness("current")
    result = AgentResult(
        output={
            "answer": "ok",
            "citations": [
                {"source": "at_head", "reference": "src/module.py", "ref": "wrong-sha-from-model"},
                {"source": "deepwiki", "reference": "Architecture"},
            ],
            "unanswered": [],
        }
    )

    answer = grounding.answer_from_result("q", "owner/repo", result, freshness, head_ref="def456")

    assert answer.citations[0].source == "at_head"
    assert answer.citations[0].ref == "def456"
    assert answer.citations[1].source == "deepwiki"
    assert answer.citations[1].ref is None


def test_answer_from_result_leaves_citations_untouched_when_head_ref_is_not_given() -> None:
    freshness = _freshness("current")
    result = AgentResult(
        output={"answer": "ok", "citations": [{"source": "at_head", "reference": "src/module.py"}], "unanswered": []}
    )

    answer = grounding.answer_from_result("q", "owner/repo", result, freshness)

    assert answer.citations[0].ref is None


def test_answer_from_result_defaults_at_head_files_to_an_empty_list() -> None:
    freshness = _freshness("current")
    result = AgentResult(output={"answer": "ok", "citations": [], "unanswered": []})

    answer = grounding.answer_from_result("q", "owner/repo", result, freshness)

    assert answer.at_head_files == []


def test_answer_from_result_carries_the_at_head_files_it_was_given_mechanically() -> None:
    """This is set by the caller from what was actually retrieved, never from the model's output."""
    freshness = _freshness("current")
    result = AgentResult(
        output={
            "answer": "ok",
            "citations": [],
            "unanswered": [],
            # A model claiming its own at_head_files must have no effect: the field isn't even
            # part of the output schema, and the library sets it from its own bookkeeping.
            "at_head_files": [{"path": "ignored-by-model.py", "status": "included"}],
        }
    )
    statuses = [
        AtHeadFileStatus(path="src/module.py", status="included"),
        AtHeadFileStatus(path="src/big.py", status="excluded_for_budget"),
        AtHeadFileStatus(path="src/gone.py", status="missing_at_head"),
    ]

    answer = grounding.answer_from_result("q", "owner/repo", result, freshness, at_head_files=statuses)

    assert answer.at_head_files == statuses
