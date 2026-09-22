"""End-to-end coverage: `explain --at-head` spends its read budget in relevance order.

The measured defect: DeepWiki's "Relevant source files" block is emitted alphabetically, and
`lore.drift.cited_files` sorts on top of that, so fetching cited files in that order spent a
fixed budget on whichever files happened to sort first rather than the ones a question was
actually about (`.env.example` beat the transport implementation itself). These tests pin the
fix at the `explain` integration level: the budget now keeps the file(s) relevant to the
question, and `at_head_files` still accounts for every cited path regardless of which side of
the budget it landed on.
"""

from pathlib import Path

import pytest

from lore import store
from lore.capabilities.explain import core
from lore.intelligence.schemas import AgentRequest, AgentResult
from lore.schemas import AtHeadFileStatus, Freshness, RepoRef


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))
    return root


# Citations are deliberately in the order the real defect exploited: `.env.example` sorts
# before `packages/mcp/src/index.ts` alphabetically, and `lore.drift.cited_files` returns them
# sorted, so an unranked fetch would try `.env.example` first and spend the whole budget there.
WIKI_TEXT = (
    "# Page: MCP Transport\n"
    "Configuration values for local development live in [.env.example:1-5](), unrelated to "
    "how requests are actually dispatched.\n"
    "The transport implementation itself lives in [packages/mcp/src/index.ts:1-10](), "
    "handling registration of every tool over stdio and SSE.\n"
)


def _freshness() -> Freshness:
    return Freshness(
        repo="owner/repo",
        indexed_sha="abc123",
        head_sha="def456",
        verdict="stale",
        summary="stale",
        measured_at="2026-09-22T00:00:00+00:00",
    )


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
                "answer": "The transport layer dispatches over stdio and SSE.",
                "citations": [{"source": "at_head", "reference": "packages/mcp/src/index.ts"}],
                "unanswered": [],
            }
        )


def test_at_head_budget_keeps_the_file_ranked_relevant_to_the_question_not_the_alphabetical_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freshness = _freshness()
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    monkeypatch.setattr(core.freshness_core, "measure", lambda repo, timeout_seconds=30.0: freshness)
    monkeypatch.setattr(
        core.drift_core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([], True)
    )

    def _must_not_be_called(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("--at-head must not retrieve from DeepWiki's own ask/structure tools")

    monkeypatch.setattr(core.deepwiki, "read_wiki_structure", _must_not_be_called)
    monkeypatch.setattr(core.deepwiki, "ask", _must_not_be_called)

    fetched: list[str] = []

    def _file_at_ref(ref: object, path: str, ref_sha: str, timeout_seconds: float = 30.0) -> str:
        fetched.append(path)
        # Fixed-length content: whichever path is fetched first exhausts the whole budget,
        # leaving none for a second file. This isolates "which file was tried first" as the
        # only thing the test result depends on.
        return "x" * 10

    monkeypatch.setattr(core.github, "file_at_ref", _file_at_ref)
    engine = _RecordingIntelligence()

    answer = core.explain(
        "owner/repo",
        "How does the MCP transport layer dispatch requests to tool handlers?",
        at_head=True,
        at_head_read_limit=10,
        intelligence=engine,
    )

    # The relevant file must be the one actually fetched, not the alphabetically-first citation.
    assert fetched == ["packages/mcp/src/index.ts"]
    assert "x" * 10 in engine.requests[0].prompt

    # Every cited path is still accounted for, on whichever side of the budget it landed.
    assert sorted(answer.at_head_files, key=lambda status: status.path) == [
        AtHeadFileStatus(path=".env.example", status="excluded_for_budget"),
        AtHeadFileStatus(path="packages/mcp/src/index.ts", status="included"),
    ]


def test_a_file_too_large_for_the_remaining_budget_is_skipped_not_truncated(monkeypatch) -> None:
    """One oversized file must not starve the smaller relevant files ranked after it.

    Measured on upstash/context7: a 35,102 byte docs page ranked third was truncated to fill
    the budget, pushing out four small source files that would all have fitted.
    """
    from lore.capabilities.explain import core as explain_core

    sizes = {"a.ts": 40, "big.mdx": 500, "b.ts": 40, "c.ts": 40}

    def _file_at_ref(ref, path, head_sha, timeout_seconds=30.0):
        return "x" * sizes[path]

    monkeypatch.setattr(explain_core.github, "file_at_ref", _file_at_ref)
    included, excluded, missing, not_text = explain_core._fetch_at_head(
        RepoRef(owner="o", repo="r"), "headsha", ["a.ts", "big.mdx", "b.ts", "c.ts"], 150, 30.0
    )

    assert [path for path, _ in included] == ["a.ts", "b.ts", "c.ts"]
    assert excluded == ["big.mdx"]
    assert missing == []
    assert not_text == []
    assert sorted([p for p, _ in included] + excluded + missing + not_text) == sorted(sizes)


def test_a_first_file_larger_than_the_whole_budget_is_still_truncated(monkeypatch) -> None:
    """Returning part of the one relevant file beats returning nothing at all."""
    from lore.capabilities.explain import core as explain_core

    monkeypatch.setattr(explain_core.github, "file_at_ref", lambda *a, **k: "y" * 900)
    included, excluded, missing, not_text = explain_core._fetch_at_head(
        RepoRef(owner="o", repo="r"), "headsha", ["huge.ts"], 100, 30.0
    )

    assert len(included) == 1
    assert len(included[0][1]) == 100
    assert excluded == []
    assert missing == []
    assert not_text == []


def test_a_binary_file_is_recorded_not_text_and_does_not_consume_the_budget(monkeypatch) -> None:
    """A binary file's fetch succeeds; being unusable as text must not spend any of the budget.

    The measured live defect: a decode failure used to raise the same `LoreError` a transport
    failure raises, taking down the whole `--at-head` call over a legitimately cited binary
    file (e.g. a wiki page citing a screenshot) once the file was even reached.
    """
    from lore.capabilities.explain import core as explain_core
    from lore.sources import github

    def _file_at_ref(ref, path, head_sha, timeout_seconds=30.0):
        if path == "cover.png":
            raise github.FileNotTextAtRefError(f"'{path}' is not valid UTF-8 text (e.g. a binary file).")
        return "x" * 10

    monkeypatch.setattr(explain_core.github, "file_at_ref", _file_at_ref)
    included, excluded, missing, not_text = explain_core._fetch_at_head(
        RepoRef(owner="o", repo="r"), "headsha", ["cover.png", "readme.md"], 100, 30.0
    )

    assert not_text == ["cover.png"]
    assert [path for path, _ in included] == ["readme.md"]
    assert excluded == []
    assert missing == []


def test_fetch_at_head_still_raises_on_a_genuine_retrieval_failure(monkeypatch) -> None:
    """The direction that must never regress: a transport failure fails the whole call.

    Neither a confirmed 404 nor a decode failure may absorb this -- only those two specific,
    named exceptions continue the walk; any other `LoreError` must propagate.
    """
    from lore.capabilities.explain import core as explain_core
    from lore.schemas import LoreError

    def _rate_limited(ref, path, head_sha, timeout_seconds=30.0):
        raise LoreError(f"Could not read '{path}': HTTP 403: API rate limit exceeded")

    monkeypatch.setattr(explain_core.github, "file_at_ref", _rate_limited)

    with pytest.raises(LoreError, match="not proof the file is absent"):
        explain_core._fetch_at_head(RepoRef(owner="o", repo="r"), "headsha", ["a.py"], 100, 30.0)


def test_a_confirmed_404_is_still_recorded_missing_and_the_walk_continues(monkeypatch) -> None:
    from lore.capabilities.explain import core as explain_core
    from lore.sources import github

    def _file_at_ref(ref, path, head_sha, timeout_seconds=30.0):
        if path == "gone.py":
            raise github.FileAbsentAtRefError(f"'{path}' does not exist.")
        return "x" * 10

    monkeypatch.setattr(explain_core.github, "file_at_ref", _file_at_ref)
    included, _excluded, missing, not_text = explain_core._fetch_at_head(
        RepoRef(owner="o", repo="r"), "headsha", ["gone.py", "here.py"], 100, 30.0
    )

    assert missing == ["gone.py"]
    assert [path for path, _ in included] == ["here.py"]
    assert not_text == []


def test_every_cited_path_appears_exactly_once_across_the_four_statuses(monkeypatch) -> None:
    """Property: mixing all four outcomes, every cited path is accounted for exactly once."""
    from lore.capabilities.explain import core as explain_core
    from lore.sources import github

    cited_paths = ["included_a.py", "included_b.py", "excluded_c.py", "missing_d.py", "binary_e.png"]

    def _file_at_ref(ref, path, head_sha, timeout_seconds=30.0):
        if path == "missing_d.py":
            raise github.FileAbsentAtRefError(f"'{path}' does not exist.")
        if path == "binary_e.png":
            raise github.FileNotTextAtRefError(f"'{path}' is not valid UTF-8 text.")
        return "x" * 10

    monkeypatch.setattr(explain_core.github, "file_at_ref", _file_at_ref)
    # A budget of 20 characters admits exactly the first two included files (10 each) before
    # the remaining non-failing citation is pushed into excluded_for_budget.
    included, excluded, missing, not_text = explain_core._fetch_at_head(
        RepoRef(owner="o", repo="r"), "headsha", cited_paths, 20, 30.0
    )

    accounted = [path for path, _ in included] + excluded + missing + not_text
    assert sorted(accounted) == sorted(cited_paths)
    assert len(accounted) == len(cited_paths)

    statuses = explain_core._at_head_file_statuses(included, excluded, missing, not_text)
    assert sorted(status.path for status in statuses) == sorted(cited_paths)
    assert len(statuses) == len(cited_paths)
