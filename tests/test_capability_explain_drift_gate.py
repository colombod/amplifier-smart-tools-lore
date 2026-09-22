"""Adverse-state coverage for explain's drift gate and --at-head escalation.

A stale index and a current one used to take the same path to synthesis, differing only in
the caveat text attached at the end. That let a page whose cited file GitHub reports removed
ground an answer as if the file still existed. These tests pin the load-bearing guarantees
that replaced it: a `broken` page refuses BEFORE any model call, an `intact` page carries no
caveat however far behind the repository is, `unknown` is never silently treated as `intact`,
the drift detail actually reaches the model's prompt, and `--at-head` grounds on fetched
source with citations carrying the head ref rather than the wiki.
"""

from pathlib import Path

import pytest

from lore import store
from lore.capabilities.drift import core as drift_core
from lore.capabilities.explain import core
from lore.intelligence.schemas import AgentRequest, AgentResult
from lore.schemas import FileChange, Freshness, LoreError


@pytest.fixture(autouse=True)
def cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("LORE_CACHE_DIR", str(root))
    return root


WIKI_TEXT = (
    "# Page: Session Store\n"
    "createSessionStore lives in [packages/mcp/src/lib/sessionStore.ts:1-10]().\n"
    "# Page: Overview\n"
    "Nothing changed here.\n"
)

# The measured regression scenario: several pages broken, one page (the one the question is
# actually about) untouched. Page 1 and 2 cite files marked removed below; page 3 does not.
MULTI_PAGE_WIKI_TEXT = (
    "# Page: MCP Server Implementation\n"
    "The MCP server lives in [packages/mcp/src/index.ts:1-10]().\n"
    "# Page: Skills Management\n"
    "Skills config lives in [.changeset/avoid-shell-github-token.md:1-5]().\n"
    "# Page: Enterprise Offering\n"
    "The Enterprise offering includes SSO support, described in [docs/enterprise.md:1-20]().\n"
)


def _freshness(
    indexed_sha: str | None = "abc123", head_sha: str | None = "def456", verdict: str = "stale", **overrides: object
) -> Freshness:
    fields: dict[str, object] = {
        "repo": "owner/repo",
        "indexed_sha": indexed_sha,
        "indexed_date": "2026-07-01",
        "head_sha": head_sha,
        "head_date": "2026-09-01",
        "default_branch": "main",
        "commits_behind": 84,
        "days_behind": 63,
        "verdict": verdict,
        "summary": f"{verdict} summary",
        "measured_at": "2026-09-22T00:00:00+00:00",
    }
    fields.update(overrides)
    return Freshness.model_validate(fields)


class _RunMustNotBeCalledIntelligence:
    """Preflight succeeds; `run` raises so a test can only pass if a guard fired before it."""

    implementation = "test-run-must-not-be-called"

    def preflight(self) -> None:
        return None

    def run(self, request: AgentRequest) -> AgentResult:
        raise AssertionError("run() must not be called: the drift gate should have raised first")


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
                "answer": "It works like this.",
                "citations": [{"source": "at_head", "reference": "packages/mcp/src/lib/sessionStore.ts"}],
                "unanswered": [],
            }
        )


def _patch_measure(monkeypatch: pytest.MonkeyPatch, freshness: Freshness) -> None:
    monkeypatch.setattr(core.freshness_core, "measure", lambda repo, timeout_seconds=30.0: freshness)


def _patch_deepwiki(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core.deepwiki, "read_wiki_structure", lambda ref, timeout_seconds=60.0: "structure text")
    monkeypatch.setattr(core.deepwiki, "ask", lambda ref, question, timeout_seconds=180.0: "deepwiki answer text")


def test_broken_page_refuses_before_any_model_call_and_names_the_removed_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load-bearing case: a citation to a removed file must never reach the model."""
    freshness = _freshness()
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    removed = FileChange(filename="packages/mcp/src/lib/sessionStore.ts", status="removed", changes=12)
    monkeypatch.setattr(
        drift_core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([removed], True)
    )
    _patch_measure(monkeypatch, freshness)
    _patch_deepwiki(monkeypatch)

    with pytest.raises(LoreError) as excinfo:
        core.explain(
            "owner/repo",
            "How does the session store work?",
            intelligence=_RunMustNotBeCalledIntelligence(),
        )

    message = str(excinfo.value)
    assert "packages/mcp/src/lib/sessionStore.ts" in message
    assert "Session Store" in message
    assert "--at-head" in message
    assert "git clone --depth 1 https://github.com/owner/repo.git" in message
    assert "https://deepwiki.com/owner/repo" in message


def test_intact_page_carries_no_caveat_however_many_commits_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    """The false-positive direction: a repository can be far behind while every cited file is untouched."""
    freshness = _freshness(commits_behind=84, days_behind=63, verdict="stale")
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    monkeypatch.setattr(drift_core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([], True))
    _patch_measure(monkeypatch, freshness)
    _patch_deepwiki(monkeypatch)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does the session store work?", intelligence=engine)

    assert answer.caveat is None


def test_unknown_drift_is_never_treated_as_intact_and_the_caveat_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """An incomplete comparison must never be read as proof nothing changed."""
    freshness = _freshness(verdict="stale")
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    # A short, complete-looking page carries no evidence either way when the walk itself failed.
    monkeypatch.setattr(drift_core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([], False))
    _patch_measure(monkeypatch, freshness)
    _patch_deepwiki(monkeypatch)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does the session store work?", intelligence=engine)

    assert answer.caveat is not None
    assert "could not be established" in answer.caveat


def test_drifted_files_reach_the_model_prompt_not_just_the_reader_caveat(monkeypatch: pytest.MonkeyPatch) -> None:
    """The thing the caveat used to ask a human to do, now also told to the model that answers."""
    freshness = _freshness(verdict="aging", commits_behind=5, days_behind=3)
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    changed = FileChange(filename="packages/mcp/src/lib/sessionStore.ts", status="modified", changes=4)
    monkeypatch.setattr(
        drift_core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: ([changed], True)
    )
    _patch_measure(monkeypatch, freshness)
    _patch_deepwiki(monkeypatch)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does the session store work?", intelligence=engine)

    assert len(engine.requests) == 1
    prompt = engine.requests[0].prompt
    assert "DRIFT WARNING" in prompt
    assert "packages/mcp/src/lib/sessionStore.ts" in prompt
    assert answer.caveat is not None


def test_at_head_grounds_on_fetched_source_and_citations_carry_the_head_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--at-head` must ground on current source, not the wiki, and prove it in the citation."""
    freshness = _freshness(indexed_sha="abc123", head_sha="def456", verdict="stale")
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    _patch_measure(monkeypatch, freshness)
    _patch_changed(monkeypatch, [])

    def _must_not_be_called(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("--at-head must not retrieve from DeepWiki's own ask/structure tools")

    monkeypatch.setattr(core.deepwiki, "read_wiki_structure", _must_not_be_called)
    monkeypatch.setattr(core.deepwiki, "ask", _must_not_be_called)
    monkeypatch.setattr(
        core.github,
        "file_at_ref",
        lambda ref, path, ref_sha, timeout_seconds=30.0: "current file contents",
    )
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does the session store work?", at_head=True, intelligence=engine)

    assert len(engine.requests) == 1
    prompt = engine.requests[0].prompt
    assert "current file contents" in prompt
    assert "def456" in prompt
    assert answer.freshness.verdict == "current"
    assert answer.citations[0].source == "at_head"
    assert answer.citations[0].ref == "def456"


def test_at_head_reports_a_file_missing_at_head_as_information_not_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cited file that no longer exists at head is an expected, reportable state, not an error."""
    freshness = _freshness(indexed_sha="abc123", head_sha="def456", verdict="stale")
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    _patch_measure(monkeypatch, freshness)
    _patch_changed(monkeypatch, [])
    monkeypatch.setattr(core.deepwiki, "read_wiki_structure", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(core.deepwiki, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    def _missing(ref: object, path: str, ref_sha: str, timeout_seconds: float = 30.0) -> str:
        raise core.github.FileAbsentAtRefError(
            f"'{path}' does not exist in owner/repo at {ref_sha}. It may have been removed or renamed."
        )

    monkeypatch.setattr(core.github, "file_at_ref", _missing)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does the session store work?", at_head=True, intelligence=engine)

    prompt = engine.requests[0].prompt
    assert "no longer exists at head" in prompt
    assert "packages/mcp/src/lib/sessionStore.ts" in prompt
    assert answer.freshness.verdict == "current"
    assert answer.at_head_files == [
        core.AtHeadFileStatus(path="packages/mcp/src/lib/sessionStore.ts", status="missing_at_head")
    ]


def test_at_head_reports_a_binary_file_as_not_text_and_still_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cited binary file (e.g. an image) is recorded `not_text` and the call still succeeds.

    The measured live defect: the fetch succeeds (GitHub returns exactly the bytes asked for),
    so this must not be folded into the generic retrieval-failure path that takes the whole
    call down. It is information about the file, exactly like a confirmed 404.
    """
    freshness = _freshness(indexed_sha="abc123", head_sha="def456", verdict="stale")
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    _patch_measure(monkeypatch, freshness)
    _patch_changed(monkeypatch, [])
    monkeypatch.setattr(core.deepwiki, "read_wiki_structure", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(core.deepwiki, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    def _binary(ref: object, path: str, ref_sha: str, timeout_seconds: float = 30.0) -> str:
        raise core.github.FileNotTextAtRefError(
            f"'{path}' in owner/repo at {ref_sha} is not valid UTF-8 text (e.g. a binary file)."
        )

    monkeypatch.setattr(core.github, "file_at_ref", _binary)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "How does the session store work?", at_head=True, intelligence=engine)

    prompt = engine.requests[0].prompt
    assert "not text at head" in prompt
    assert "packages/mcp/src/lib/sessionStore.ts" in prompt
    assert answer.freshness.verdict == "current"
    assert answer.at_head_files == [
        core.AtHeadFileStatus(path="packages/mcp/src/lib/sessionStore.ts", status="not_text")
    ]


def test_at_head_fails_the_whole_call_when_a_fetch_fails_for_a_reason_other_than_a_confirmed_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The load-bearing regression: a rate limit or dropped connection must never be silently

    reclassified as 'file missing' and answered around. Only a confirmed 404 may continue.
    """
    freshness = _freshness(indexed_sha="abc123", head_sha="def456", verdict="stale")
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    _patch_measure(monkeypatch, freshness)
    _patch_changed(monkeypatch, [])
    monkeypatch.setattr(core.deepwiki, "read_wiki_structure", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(core.deepwiki, "ask", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))

    def _rate_limited(ref: object, path: str, ref_sha: str, timeout_seconds: float = 30.0) -> str:
        raise LoreError("Could not read owner/repo's 'x' at def456: HTTP 403: API rate limit exceeded")

    monkeypatch.setattr(core.github, "file_at_ref", _rate_limited)

    with pytest.raises(LoreError) as excinfo:
        core.explain(
            "owner/repo",
            "How does the session store work?",
            at_head=True,
            intelligence=_RunMustNotBeCalledIntelligence(),
        )

    message = str(excinfo.value)
    assert "packages/mcp/src/lib/sessionStore.ts" in message
    assert "def456" in message
    assert "not proof the file is absent" in message


def test_at_head_file_statuses_classifies_each_list_into_its_own_status() -> None:
    statuses = core._at_head_file_statuses(
        included=[("a.py", "text a"), ("b.py", "text b")],
        excluded=["c.py"],
        missing=["d.py"],
        not_text=["e.png"],
    )

    assert statuses == [
        core.AtHeadFileStatus(path="a.py", status="included"),
        core.AtHeadFileStatus(path="b.py", status="included"),
        core.AtHeadFileStatus(path="c.py", status="excluded_for_budget"),
        core.AtHeadFileStatus(path="d.py", status="missing_at_head"),
        core.AtHeadFileStatus(path="e.png", status="not_text"),
    ]


def test_at_head_raises_before_any_model_call_when_the_live_head_commit_is_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    freshness = _freshness(indexed_sha="abc123", head_sha=None, verdict="unknown")
    store.write_wiki("owner/repo", WIKI_TEXT, freshness)
    _patch_measure(monkeypatch, freshness)

    with pytest.raises(LoreError, match="no commit to read"):
        core.explain(
            "owner/repo",
            "How does the session store work?",
            at_head=True,
            intelligence=_RunMustNotBeCalledIntelligence(),
        )


def _patch_changed(monkeypatch: pytest.MonkeyPatch, changes: list[FileChange], complete: bool = True) -> None:
    monkeypatch.setattr(
        drift_core.github, "changed_files", lambda ref, base, head, timeout_seconds=60.0: (changes, complete)
    )


def test_question_matching_an_intact_page_answers_normally_while_other_pages_are_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measured regression: 4 of 130 pages broken must not refuse a question about page 91.

    Scaled down to 3 pages here, but the shape is exact: the question is answered by a page
    (`Enterprise Offering`) that is itself untouched, while two OTHER pages in the same wiki
    (`MCP Server Implementation`, `Skills Management`) cite files GitHub reports removed. The
    gate must be scoped to the page that actually grounds this question, not the whole wiki.
    """
    freshness = _freshness()
    store.write_wiki("owner/repo", MULTI_PAGE_WIKI_TEXT, freshness)
    _patch_changed(
        monkeypatch,
        [
            FileChange(filename="packages/mcp/src/index.ts", status="removed", changes=3),
            FileChange(filename=".changeset/avoid-shell-github-token.md", status="removed", changes=1),
        ],
    )
    _patch_measure(monkeypatch, freshness)
    _patch_deepwiki(monkeypatch)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "What does the Enterprise offering include?", intelligence=engine)

    assert len(engine.requests) == 1
    assert answer.caveat is None
    assert "Enterprise Offering" in engine.requests[0].prompt


def test_question_matching_a_broken_page_refuses_and_names_only_the_selected_broken_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate still refuses when the SELECTED page is the broken one -- and names only it."""
    freshness = _freshness()
    store.write_wiki("owner/repo", MULTI_PAGE_WIKI_TEXT, freshness)
    _patch_changed(
        monkeypatch,
        [
            FileChange(filename="packages/mcp/src/index.ts", status="removed", changes=3),
            FileChange(filename=".changeset/avoid-shell-github-token.md", status="removed", changes=1),
        ],
    )
    _patch_measure(monkeypatch, freshness)
    _patch_deepwiki(monkeypatch)

    with pytest.raises(LoreError) as excinfo:
        core.explain(
            "owner/repo",
            "How does the MCP server implementation work?",
            intelligence=_RunMustNotBeCalledIntelligence(),
        )

    message = str(excinfo.value)
    assert "MCP Server Implementation" in message
    assert "packages/mcp/src/index.ts" in message
    # The other broken page must never be named: it was never selected as grounding this question.
    assert "Skills Management" not in message
    assert ".changeset/avoid-shell-github-token.md" not in message


def test_selection_finding_nothing_reports_unknown_drift_and_still_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No page scoring above zero is honestly reported as unknown, never a refusal, never a silent pass."""
    freshness = _freshness()
    store.write_wiki("owner/repo", MULTI_PAGE_WIKI_TEXT, freshness)
    _patch_changed(monkeypatch, [])
    _patch_measure(monkeypatch, freshness)
    _patch_deepwiki(monkeypatch)
    engine = _RecordingIntelligence()

    answer = core.explain("owner/repo", "xyzzy plugh wobble", intelligence=engine)

    assert len(engine.requests) == 1
    assert answer.caveat is not None
    assert "could not identify" in answer.caveat.lower()
    assert "could not be established" in answer.caveat
