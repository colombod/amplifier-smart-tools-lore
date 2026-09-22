"""Explain: how a project works, its architecture, and how its pieces are wired.

Selects the wiki pages that plausibly ground the question (`lore.selection`, a no-model
relevance heuristic), retrieves their text and DeepWiki's own answer to the question, then
synthesizes both into a grounded `Answer` through `Intelligence`. The model may use only what
was retrieved in this run; nothing it remembers from training is allowed into the answer.

A stale index and a current one used to take the same path to synthesis: only the caveat
text differed. That let a citation to a file GitHub reports removed or renamed ground an
answer as if it still existed. Before synthesis, this module measures per-page drift for the
pages that will ground the answer (`lore.capabilities.drift`) and acts on it: a `broken`
verdict refuses rather than answering around a citation that does not resolve; `drifted` or
`unknown` tells the model, in the prompt, which specific files to treat with caution;
`intact` answers with no staleness caveat at all, whatever the commit count. Critically, this
gate is scoped to the SELECTED pages, never every page in the wiki: a repository can have
many pages and only a few broken ones, and a question those broken pages have nothing to do
with must still answer normally, however far behind the repository the broken pages make it
look overall (`DriftReport.verdict` is a whole-wiki worst-page verdict; the right input to a
per-question gate is the worst verdict among only the pages that ground THIS question).
`--at-head` bypasses the wiki entirely and grounds the answer in the selected pages' cited
files' own current content, read straight from the repository at its head commit, fetched
under a fixed character budget and in relevance order (`lore.selection.rank_cited_files`)
rather than DeepWiki's own (alphabetical) citation order, so the budget is spent on the files
most likely to matter rather than on whichever happen to sort first.
"""

from lore import drift as lore_drift
from lore import selection as lore_selection
from lore import store
from lore.capabilities.drift import core as drift_core
from lore.capabilities.explain.prompt import build_prompt, build_prompt_at_head, build_prompt_from_material
from lore.capabilities.fetch import core as fetch_core
from lore.capabilities.freshness import core as freshness_core
from lore.grounding import ANSWER_OUTPUT_SCHEMA, answer_from_result
from lore.intelligence.interface import Intelligence, default_intelligence
from lore.intelligence.schemas import AgentRequest
from lore.schemas import (
    DEFAULT_INTELLIGENCE_MODEL,
    DEFAULT_READ_LIMIT,
    Answer,
    AtHeadFileStatus,
    DriftReport,
    Freshness,
    LoreError,
    PageEntry,
    ReasoningEffort,
    RepoRef,
)
from lore.sources import deepwiki, github

# AgentRequest.timeout_seconds must be a positive int; a caller passing a sub-second float
# still gets a request the schema accepts rather than a validation error of our own making.
MINIMUM_TIMEOUT_SECONDS = 1

# A page's own citations must be read whole to extract every one, never a bounded slice:
# `store.read_page` caps and truncates by construction, and drift/citation extraction must
# see every citation on the page. Matches `lore.capabilities.drift.core._FULL_PAGE_LIMIT`.
_FULL_PAGE_LIMIT = 100_000_000


def explain(
    repo: str,
    question: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
    at_head: bool = False,
    at_head_read_limit: int = DEFAULT_READ_LIMIT,
    intelligence: Intelligence | None = None,
) -> Answer:
    """How `repo` works: its architecture, design, and how its pieces are wired.

    Measures freshness first, since `repo` always names a repository to measure it against.
    When `material` is not given, a repository DeepWiki has never indexed has nothing to
    ground an answer in, so that case raises before a model is ever asked.

    Otherwise this selects the cached wiki pages that plausibly ground `question`
    (`lore.selection.select_pages`, a no-model relevance heuristic over page titles and
    bodies), fetching the wiki to the cache first when it is not already there. Before
    synthesis, it measures per-page drift for the SELECTED pages only, never the whole wiki:
    a page whose cited files no longer resolve makes this raise rather than answer around it,
    naming only the selected broken page(s); a page whose cited files were merely edited adds
    an instruction to the model naming exactly which files to treat with caution, and the
    usual staleness caveat; a page whose citations are untouched answers with no caveat at
    all, however many commits the repository is ahead, and however many OTHER pages in the
    same wiki are broken or drifted. When no page can be identified as grounding `question`,
    drift is reported as `unknown` (never silently passed, and never a refusal on pages
    nothing established as relevant) and the answer proceeds with a caveat saying so.
    `at_head` skips the wiki's own content entirely and grounds the answer in the selected
    pages' cited files, read directly from the repository at its live head commit instead.

    When `material` is given, it replaces DeepWiki's retrieval entirely (nothing is fetched,
    drift is not measured, and the never-indexed guard is skipped, since the caller already
    supplied something to ground the answer in) and citations grounded in it are attributed
    to the caller rather than DeepWiki.

    Args:
        repo: A GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL.
        question: A question about the repository's architecture, design, or wiring.
        model: The model to run the synthesis through.
        reasoning_effort: Reasoning effort for that model.
        timeout_seconds: Per-request timeout for each retrieval call and the synthesis itself.
        material: Retrieved material supplied directly by the caller, used in place of DeepWiki's
            own retrieval for this call. `repo`'s freshness is still measured and attached to the
            returned `Answer` either way.
        at_head: Ground the answer in the cited files' own content, read directly from `repo`
            at its live head commit, instead of DeepWiki's index. Ignored when `material` is given.
        at_head_read_limit: Maximum total characters of head-commit source to fetch when
            `at_head` is set; cited files are fetched in relevance order
            (`lore.selection.rank_cited_files`) and files past this budget are named as left
            out rather than fetched.
        intelligence: The implementation to run the synthesis through. Defaults to `default_intelligence()`.

    Returns:
        An `Answer` carrying the synthesized text, its citations, anything the retrieved
        material did not cover, the measured `Freshness`, and a `caveat`. With `at_head`, the
        reported `Freshness` describes the material actually used (the repository's live
        head), not the wiki's own staleness, and `at_head_files` names every cited file's
        fate (included, excluded for budget, missing at head, or not text at head, i.e. a
        binary file), mechanically derived from what was actually retrieved rather than the
        model's own account of it.

    Raises:
        LoreError: `repo` does not parse, DeepWiki has no indexed wiki for it and no `material`
            was supplied, a page selected as grounding the question cites a file GitHub
            reports removed or renamed (naming the pages, the files, and how to proceed),
            `at_head` was requested but the repository's live head commit could not be read,
            an `at_head` fetch for a cited file failed for a reason other than a confirmed
            404 or a decode failure (network error, rate limit, or malformed response -- this
            is never folded into "missing" or "not text", since it is not evidence about the
            file itself), the intelligence implementation cannot run, or it produced no usable
            answer.
    """
    engine = intelligence or default_intelligence()
    engine.preflight()

    measured = freshness_core.measure(repo, timeout_seconds=min(timeout_seconds, 30.0))
    if material is None and measured.indexed_sha is None:
        # `measured.summary` already names the DeepWiki URL to visit; asking a model to
        # answer against an index that does not exist would only invite a guess.
        raise LoreError(measured.summary)

    drift_report: DriftReport | None = None
    head_ref: str | None = None
    freshness_for_answer = measured
    at_head_files: list[AtHeadFileStatus] = []

    if material is not None:
        prompt = build_prompt_from_material(repo, question, material)
    elif at_head:
        ref = freshness_core.parse_repo(repo)
        if measured.head_sha is None:
            raise LoreError(
                f"--at-head has no commit to read '{repo}' at: its live head commit could not be "
                f"measured. {measured.summary}"
            )
        _ensure_cached(repo, ref, measured, timeout_seconds)
        index = store.load_index(repo)
        selected = lore_selection.select_pages(index, question)
        # Selection can come up empty for an unusual question; --at-head reads current source
        # directly from GitHub regardless (there is no staleness risk to guard against here,
        # unlike the drift gate below), so falling back to every cited file across the wiki is
        # a safe, conservative default rather than a hard failure.
        grounding_pages = selected or index.pages
        cited = _cited_files(repo, grounding_pages)
        if not cited:
            raise LoreError(
                f"'{repo}'s cached wiki cites no source files, so --at-head has nothing to fetch at head. "
                "Rerun without --at-head to ground the answer in DeepWiki's own retrieval instead."
            )
        changed_by_path, _complete = drift_core.changed_file_map(
            ref, measured.indexed_sha, measured.head_sha, timeout_seconds=min(timeout_seconds, 60.0)
        )
        ranked_cited = lore_selection.rank_cited_files(
            question, cited, _page_texts(repo, grounding_pages), changed_by_path
        )
        included, excluded, missing, not_text = _fetch_at_head(
            ref, measured.head_sha, ranked_cited, at_head_read_limit, timeout_seconds
        )
        prompt = build_prompt_at_head(repo, question, measured.head_sha, included, excluded, missing, not_text)
        freshness_for_answer = _at_head_freshness(measured)
        head_ref = measured.head_sha
        at_head_files = _at_head_file_statuses(included, excluded, missing, not_text)
    else:
        ref = freshness_core.parse_repo(repo)
        _ensure_cached(repo, ref, measured, timeout_seconds)
        whole_wiki_drift = drift_core.drift(repo, timeout_seconds=min(timeout_seconds, 60.0))
        index = store.load_index(repo)
        selected = lore_selection.select_pages(index, question)
        drift_report = _scoped_drift(repo, whole_wiki_drift, selected)
        if drift_report.verdict == "broken":
            raise LoreError(_broken_drift_message(ref, repo, question, drift_report))
        pages_text = _read_selected_pages(repo, selected)
        deepwiki_answer = deepwiki.ask(ref, question, timeout_seconds=timeout_seconds)
        note = _drift_note(drift_report) if drift_report.verdict in ("drifted", "unknown") else None
        prompt = build_prompt(repo, question, pages_text, deepwiki_answer, drift_note=note)

    request = AgentRequest(
        prompt=prompt,
        model=model,
        output_schema=ANSWER_OUTPUT_SCHEMA,
        reasoning_effort=reasoning_effort,
        timeout_seconds=max(MINIMUM_TIMEOUT_SECONDS, int(timeout_seconds)),
    )
    result = engine.run(request)
    return answer_from_result(
        question,
        repo,
        result,
        freshness_for_answer,
        drift_report=drift_report,
        head_ref=head_ref,
        at_head_files=at_head_files,
    )


def _ensure_cached(repo: str, ref: RepoRef, measured: Freshness, timeout_seconds: float) -> None:
    """Make sure `repo`'s wiki is cached at the commit `measured` reports indexed, fetching it if not.

    Drift and cited-file extraction both read the cached wiki from disk; `explain` itself
    never required a `fetch` before this gate existed, so it makes the one call `fetch` would,
    reusing the cache when one already matches `measured.indexed_sha`.
    """
    fetch_core.fetch(repo, ref, measured, refresh=False, timeout_seconds=timeout_seconds)


def _cited_files(repo: str, pages: list[PageEntry]) -> list[str]:
    """Every file `pages` cite, in page order, deduplicated.

    The set `--at-head` fetches at the repository's live head in place of the wiki's own
    content. Scoped to `pages` (normally the pages selected as grounding the question) rather
    than every page in the wiki: citing files from unrelated pages would fetch source no
    answer needs.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in pages:
        read_result = store.read_page(repo, entry.number, limit=_FULL_PAGE_LIMIT)
        for path in lore_drift.cited_files(read_result.text):
            if path not in seen:
                seen.add(path)
                ordered.append(path)
    return ordered


def _page_texts(repo: str, pages: list[PageEntry]) -> list[str]:
    """`pages`' own full text, read whole rather than through the tool's default bounded read.

    What `rank_cited_files` searches for proximity between a citation and the question's terms;
    a bounded read could truncate before reaching a citation near the end of a large page.
    """
    return [store.read_page(repo, entry.number, limit=_FULL_PAGE_LIMIT).text for entry in pages]


def _scoped_drift(repo: str, whole_wiki_drift: DriftReport, selected: list[PageEntry]) -> DriftReport:
    """`whole_wiki_drift`, scoped to the pages actually selected as grounding the question.

    `DriftReport.verdict` is the worst page verdict across the WHOLE cached wiki, which is the
    right read for `lore drift` reporting on the wiki as a whole, but the wrong input to a gate
    about one question: a wiki with many pages and a few broken ones must not refuse a question
    those broken pages have nothing to do with. This rebuilds the report from only the selected
    pages' already-measured per-page drift (`whole_wiki_drift.pages`), so the returned verdict,
    and any refusal built from it, can never name a page nothing established as relevant.

    Args:
        repo: The repository the report is for.
        whole_wiki_drift: The unscoped `DriftReport` covering every cached page.
        selected: The pages selected as grounding the question (`lore.selection.select_pages`).

    Returns:
        A `DriftReport` carrying only `selected`'s pages. When `selected` is empty, drift
        could not be scoped at all: this returns `verdict="unknown"` with a summary saying so,
        never the whole-wiki verdict (which would treat an unrelated broken page as if it
        applied to this question) and never `"intact"` (which would claim a clean bill of
        health for pages nobody checked).
    """
    if not selected:
        return whole_wiki_drift.model_copy(
            update={
                "pages": [],
                "verdict": "unknown",
                "summary": (
                    f"Could not identify which of {repo}'s cached wiki pages ground this question, "
                    "so their citations could not be checked for drift."
                ),
            }
        )
    selected_numbers = {entry.number for entry in selected}
    selected_pages = [page for page in whole_wiki_drift.pages if page.page_number in selected_numbers]
    return lore_drift.report(
        repo,
        whole_wiki_drift.indexed_sha,
        whole_wiki_drift.head_sha,
        selected_pages,
        whole_wiki_drift.changed_file_count,
        whole_wiki_drift.comparison_complete,
    )


def _read_selected_pages(repo: str, selected: list[PageEntry]) -> list[tuple[int, str, str]]:
    """`selected`'s own text, bounded by the tool's default read limit, in selection order.

    The primary material `explain` grounds its answer in: each selected page's cached text,
    read with the same bounded-read discipline `lore read` itself uses, rather than the whole
    page unconditionally -- a wiki page can run large enough to blow a model's context on its
    own.
    """
    return [(entry.number, entry.title, store.read_page(repo, entry.number).text) for entry in selected]


def _fetch_at_head(
    ref: RepoRef, head_sha: str, cited_paths: list[str], read_limit: int, timeout_seconds: float
) -> tuple[list[tuple[str, str]], list[str], list[str], list[str]]:
    """Fetch `cited_paths` at `head_sha`, bounded by `read_limit` total characters.

    Args:
        ref: The repository to read from.
        head_sha: The commit to read every path at.
        cited_paths: The paths to fetch, in the order they should be tried.
        read_limit: Maximum total characters to fetch across every file combined.
        timeout_seconds: Per-file timeout for the GitHub contents call.

    Returns:
        `(included, excluded, missing, not_text)`. `included` is `(path, text)` pairs actually
        read, in cited order, truncated if the last one would otherwise exceed `read_limit`.
        `excluded` names paths never fetched because the budget was already spent. `missing`
        names paths GitHub confirms with a 404 do not exist at `head_sha`, which is
        information about the citation rather than a failure, and does not consume any of the
        budget. `not_text` names paths GitHub fetched successfully whose content is not valid
        UTF-8 (a binary file legitimately cited, e.g. an image); like `missing`, this is
        information about the file rather than a failure, and does not consume any of the
        budget.

    Raises:
        LoreError: fetching a cited path failed for any reason OTHER than a confirmed 404 or a
            decode failure (network error, rate limit, malformed response). Such a failure is
            not evidence about the file itself, and must never be silently folded into
            `missing` or `not_text`: a partial result caused by a transport failure is a
            failure of this capability, not a documented partial-completion outcome, and this
            fails the whole call rather than answering from whatever fraction happened to be
            retrieved.
    """
    included: list[tuple[str, str]] = []
    excluded: list[str] = []
    missing: list[str] = []
    not_text: list[str] = []
    total_characters = 0
    for path in cited_paths:
        if total_characters >= read_limit:
            excluded.append(path)
            continue
        try:
            text = github.file_at_ref(ref, path, head_sha, timeout_seconds=timeout_seconds)
        except github.FileAbsentAtRefError:
            missing.append(path)
            continue
        except github.FileNotTextAtRefError:
            # The fetch succeeded: GitHub returned exactly what was asked for. Not being text
            # is a stable property of the file, not a retrieval outcome, so this is recorded
            # and the walk continues exactly like a confirmed 404, spending none of the budget.
            not_text.append(path)
            continue
        except LoreError as error:
            raise LoreError(
                f"Could not fetch '{path}' from {ref.slug} at {head_sha} for --at-head: {error} This is "
                "a retrieval failure (network error, rate limit, or a malformed response), not proof "
                "the file is absent, so the answer was not synthesized from a partial result. Retry; "
                "if GitHub keeps rate-limiting anonymous requests, authenticate with `gh auth login` "
                "or set GITHUB_TOKEN first."
            ) from error
        remaining = read_limit - total_characters
        if len(text) > remaining:
            # A file that does not fit is skipped so the next ones still get their chance,
            # rather than truncated to fill the budget and starving everything after it.
            # Measured: a 35,102 byte docs page ranked third consumed the rest of the budget
            # and pushed out four small source files that would all have fitted. Truncation is
            # kept for one case only, a first file larger than the whole budget, because
            # returning part of it beats returning nothing at all. A skipped file is reported
            # `excluded_for_budget` exactly as before, so nothing becomes invisible.
            if included:
                excluded.append(path)
                continue
            text = text[:remaining]
        total_characters += len(text)
        included.append((path, text))
    return included, excluded, missing, not_text


def _at_head_file_statuses(
    included: list[tuple[str, str]], excluded: list[str], missing: list[str], not_text: list[str]
) -> list[AtHeadFileStatus]:
    """`_fetch_at_head`'s own return, restated as one mechanically-derived status per file.

    This is what makes a `--at-head` answer's provenance checkable rather than asserted: a
    caller can see exactly which cited files actually grounded the answer, which were left
    out for budget, which no longer exist at head, and which were fetched but are not text,
    without trusting the model's account of what it was given.
    """
    statuses = [AtHeadFileStatus(path=path, status="included") for path, _ in included]
    statuses += [AtHeadFileStatus(path=path, status="excluded_for_budget") for path in excluded]
    statuses += [AtHeadFileStatus(path=path, status="missing_at_head") for path in missing]
    statuses += [AtHeadFileStatus(path=path, status="not_text") for path in not_text]
    return statuses


def _at_head_freshness(measured: Freshness) -> Freshness:
    """The `Freshness` to report when grounding bypassed the wiki and read source at head.

    `measured` describes DeepWiki's OWN staleness, which this run does not inherit: the
    material grounding this particular answer is the repository's current head, so the honest
    verdict for it is `current`, regardless of how far behind the index itself measured.
    """
    return measured.model_copy(
        update={
            "verdict": "current",
            "commits_behind": 0,
            "summary": (
                f"This answer is grounded directly in {measured.repo}'s source at head commit "
                f"{measured.head_sha}, bypassing DeepWiki's index (indexed at "
                f"{measured.indexed_sha or 'an unknown commit'}, "
                f"{measured.commits_behind if measured.commits_behind is not None else 'an unmeasured number of'} "
                "commit(s) behind)."
            ),
        }
    )


def _drift_note(report: DriftReport) -> str:
    """Instruction to the model naming exactly which cited files changed since the wiki was indexed.

    Structural and architectural claims are unaffected; anything resting on the files named
    here (a signature, flag, endpoint, import, or name) must be marked as needing verification
    at the repository's current head rather than stated as settled fact.
    """
    changed_files: list[str] = []
    seen: set[str] = set()
    for page in report.pages:
        if page.verdict not in ("drifted", "unknown"):
            continue
        for change in page.changed:
            if change.filename not in seen:
                seen.add(change.filename)
                changed_files.append(change.filename)
    if not changed_files:
        return (
            "DRIFT WARNING: whether the cited material still matches the repository could not be fully "
            "established (the changed-file comparison was incomplete). Mark any specific signature, "
            "flag, or API detail as needing verification at the repository's current head rather than "
            "stating it as settled."
        )
    names = ", ".join(changed_files)
    return (
        f"DRIFT WARNING: the following cited file(s) changed in the repository since the wiki was "
        f"indexed: {names}. Any claim resting on one of them (a signature, flag, endpoint, import, or "
        "name) must be marked in your answer as needing verification at the repository's current head. "
        "Structural and architectural claims not resting on these files are unaffected."
    )


def _broken_drift_message(ref: RepoRef, repo: str, question: str, report: DriftReport) -> str:
    """The refusal message for a `DriftReport` whose verdict is `broken`.

    Names every broken page and the exact files that no longer resolve, then the concrete
    next actions in order: read the files at head, rerun with `--at-head`, or wait for
    DeepWiki to reindex. A citation to a file that no longer exists is not evidence of
    anything a model should be allowed to build on, so this is raised instead of answered.
    """
    lines = [
        (
            f"'{repo}'s cached wiki cites file(s) that no longer resolve at head, so this answer would be "
            "grounded in citations that do not exist anymore. Refusing rather than answering around it."
        ),
        "",
        f"Indexed commit: {report.indexed_sha or 'unknown'}. Head commit: {report.head_sha or 'unknown'}.",
        "",
        "Broken pages:",
    ]
    for page in report.pages:
        if page.verdict != "broken":
            continue
        lines.append(f"- Page {page.page_number} '{page.title}':")
        for change in page.removed:
            lines.append(f"    {change.filename} ({change.status})")
            if report.head_sha:
                lines.append(
                    f"      https://github.com/{ref.owner}/{ref.repo}/blob/{report.head_sha}/{change.filename}"
                )
    lines += [
        "",
        "Next actions, in order:",
        (
            f"  1. Read the current file(s) at head: `git clone --depth 1 https://github.com/{ref.owner}/{ref.repo}.git` "
            "then open the path(s) named above, or use the blob URL given for each file directly."
        ),
        f'  2. Rerun with --at-head to have lore fetch the cited source at head itself: `lore explain {repo} "{question}" --at-head`.',
        f"  3. Visit https://deepwiki.com/{repo} to have DeepWiki's index refreshed.",
    ]
    return "\n".join(lines)
