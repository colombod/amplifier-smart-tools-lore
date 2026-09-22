import pytest

from lore.capabilities.howto import core
from lore.capabilities.howto.prompt import build_prompt
from lore.grounding import GROUNDING_RULE
from lore.intelligence.schemas import AgentRequest, AgentResult
from lore.schemas import LibraryRef, LoreError


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


def test_howto_propagates_a_preflight_failure_without_calling_run() -> None:
    with pytest.raises(LoreError, match="gh auth login"):
        core.howto("fastapi", "how do I add routing?", intelligence=_PreflightFailsIntelligence())
