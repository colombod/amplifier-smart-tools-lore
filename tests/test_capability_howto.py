import pytest

from lore.capabilities.howto import core
from lore.capabilities.howto.prompt import build_prompt, build_prompt_from_material
from lore.grounding import GROUNDING_RULE
from lore.intelligence.schemas import AgentRequest, AgentResult
from lore.schemas import Freshness, LibraryRef, LoreError


class _PreflightFailsIntelligence:
    """`preflight` raises; `run` raises so it can only prove preflight is checked first."""

    implementation = "test-preflight-fails"

    def preflight(self) -> None:
        raise LoreError("gh is not signed in. Run `gh auth login`.")

    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError("run() must not be called: preflight should have raised first")


@pytest.mark.parametrize(
    ("library_id", "expected"),
    [
        ("/upstash/context7", True),
        ("/vercel/next.js", True),
        ("/websites/fastapi_tiangolo", False),
        ("/llmstxt/something", False),
        ("/WEBSITES/uppercase-namespace", False),
        ("/just-one-segment", False),
        ("/a/b/c", False),
        ("", False),
    ],
)
def test_is_github_repo_id_classifies_context7_ids(library_id: str, expected: bool) -> None:
    assert core.is_github_repo_id(library_id) is expected


def test_non_repository_freshness_is_unknown_and_reports_context7_fields() -> None:
    resolved = LibraryRef(
        id="/websites/fastapi_tiangolo", title="FastAPI", last_update_date="2026-05-01", state="finalized"
    )

    freshness = core.non_repository_freshness(resolved)

    assert freshness.verdict == "unknown"
    assert freshness.repo == "/websites/fastapi_tiangolo"
    assert "2026-05-01" in freshness.summary
    assert "finalized" in freshness.summary
    assert any("not backed by a GitHub repository" in reason for reason in freshness.unmeasured)


def test_non_repository_freshness_handles_missing_context7_fields() -> None:
    resolved = LibraryRef(id="/websites/example", title="Example")

    freshness = core.non_repository_freshness(resolved)

    assert "an unknown date" in freshness.summary
    assert "'unknown'" in freshness.summary


def test_build_prompt_carries_the_grounding_rule_and_omits_the_deepwiki_section_when_absent() -> None:
    resolved = LibraryRef(id="/websites/example", title="Example")

    prompt = build_prompt("example", "how do I paginate?", resolved, "context7 docs text", None)

    assert GROUNDING_RULE in prompt
    assert "context7 docs text" in prompt
    assert "DeepWiki" not in prompt


def test_build_prompt_includes_the_deepwiki_section_when_present() -> None:
    resolved = LibraryRef(id="/upstash/context7", title="Context7")

    prompt = build_prompt("context7", "how do I paginate?", resolved, "context7 docs text", "deepwiki design answer")

    assert "deepwiki design answer" in prompt


def test_build_prompt_from_material_carries_the_grounding_rule_and_the_material_and_names_the_caller_source() -> None:
    resolved = LibraryRef(id="/upstash/context7", title="Context7")

    prompt = build_prompt_from_material("context7", "how do I paginate?", resolved, "caller-supplied text")

    assert GROUNDING_RULE in prompt
    assert "how do I paginate?" in prompt
    assert "caller-supplied text" in prompt
    assert '"caller"' in prompt


def test_howto_propagates_a_preflight_failure_without_calling_run() -> None:
    with pytest.raises(LoreError, match="gh auth login"):
        core.howto("fastapi", "how do I add routing?", intelligence=_PreflightFailsIntelligence())


def test_caller_supplied_freshness_is_unknown_and_names_the_material_as_the_reason() -> None:
    resolved = LibraryRef(id="/websites/fastapi_tiangolo", title="FastAPI")

    freshness = core.caller_supplied_freshness(resolved)

    assert freshness.verdict == "unknown"
    assert freshness.repo == "/websites/fastapi_tiangolo"
    assert any("caller" in reason for reason in freshness.unmeasured)


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
                "answer": "Use it like this.",
                "citations": [{"source": "caller", "reference": "caller-supplied material"}],
                "unanswered": [],
            }
        )


def test_howto_with_material_never_retrieves_and_reports_unknown_freshness_for_a_non_repo_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = LibraryRef(id="/websites/fastapi_tiangolo", title="FastAPI")
    monkeypatch.setattr(core.context7, "resolve_library", lambda *a, **k: resolved)

    def _must_not_be_called(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("must not retrieve when material is supplied")

    monkeypatch.setattr(core.context7, "fetch_context", _must_not_be_called)
    monkeypatch.setattr(core.deepwiki, "ask", _must_not_be_called)
    engine = _RecordingIntelligence()

    answer = core.howto("fastapi", "add routing", material="Supplied docs text.", intelligence=engine)

    assert "Supplied docs text." in engine.requests[0].prompt
    assert answer.freshness.verdict == "unknown"
    assert answer.citations[0].source == "caller"


def test_howto_with_material_resolves_nothing_and_never_borrows_another_repos_freshness(
    monkeypatch,
) -> None:
    """Caller-supplied material is the ground, so nothing is resolved or measured.

    Resolving anyway was observed returning an unrelated library for an internal name and
    attaching THAT repository's staleness to an answer drawn entirely from the caller's own
    text. Provenance that names the wrong repository is worse than provenance that says it
    cannot tell, so the honest answer here is `unknown`.
    """

    def _must_not_run(*args, **kwargs):
        raise AssertionError("caller-supplied material must not trigger retrieval or resolution")

    monkeypatch.setattr(core.context7, "resolve_library", _must_not_run)
    monkeypatch.setattr(core.context7, "fetch_context", _must_not_run)
    monkeypatch.setattr(core.freshness_core, "measure", _must_not_run)
    engine = _RecordingIntelligence()

    answer = core.howto("some-internal-thing", "start it", material="Run frobctl up.", intelligence=engine)

    assert answer.freshness.verdict == "unknown"
    assert "caller" in " ".join(answer.freshness.unmeasured).lower()
    assert "some-internal-thing" in answer.freshness.repo
