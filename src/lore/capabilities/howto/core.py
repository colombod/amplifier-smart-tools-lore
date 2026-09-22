"""Howto: how to actually use a library for a task, grounded in Context7's retrieved snippets.

Context7 is retrieved first, since it carries versioned code snippets. When the resolved
library id names a GitHub repository, its freshness is also measured and DeepWiki's own
answer about that repository's design is retrieved alongside it. When it does not (a
Context7 `websites`/`llmstxt` style entry), the returned `Freshness` reports what Context7
itself publishes instead of a commit-level measurement no such entry has.

Context7 publishes its own freshness signals, and this module acts on them rather than only
reporting them. A `state` other than `finalized` means the library is not fully indexed, so
this refuses rather than answer from a partial index. Context7 exposes no per-page source
provenance the way a DeepWiki wiki does, so there is no `broken` equivalent here: the only
signal available is `last_update_date` against the repository's live head, and when that gap
passes `DEFAULT_CONTEXT7_DOCS_AGING_DAYS`, this gets the same treatment `explain` gives a
`drifted` page: still answered, but the model is told which source is aging, and the reader
sees it in the caveat.
"""

from datetime import UTC, datetime

from lore.capabilities.freshness import core as freshness_core
from lore.capabilities.howto.prompt import build_prompt, build_prompt_from_material
from lore.grounding import ANSWER_OUTPUT_SCHEMA, answer_from_result
from lore.intelligence.interface import Intelligence, default_intelligence
from lore.intelligence.schemas import AgentRequest
from lore.schemas import DEFAULT_INTELLIGENCE_MODEL, Answer, Freshness, LibraryRef, LoreError, ReasoningEffort
from lore.sources import context7, deepwiki

# AgentRequest.timeout_seconds must be a positive int; a caller passing a sub-second float
# still gets a request the schema accepts rather than a validation error of our own making.
MINIMUM_TIMEOUT_SECONDS = 1

# Context7 publishes library ids as `/owner/repo` for GitHub-backed libraries, and as
# `/namespace/slug` for everything else it indexes. These are the non-repository namespaces
# Context7 documents; an id under one of them is never a GitHub repository.
NON_REPOSITORY_NAMESPACES = frozenset({"websites", "llmstxt"})

FINALIZED_STATE = "finalized"

# Context7's own `last_update_date` can trail a GitHub-backed library's live head by a wide
# margin even while `state` is `finalized`. Matches `AGING_DAYS_LIMIT` in
# `lore.capabilities.freshness.core`: the same 30-day cutoff already used to decide when
# DeepWiki's index is worth a caveat, applied here to Context7's own documentation snapshot.
DEFAULT_CONTEXT7_DOCS_AGING_DAYS = 30


def is_github_repo_id(library_id: str) -> bool:
    """Whether a Context7 library id names a GitHub repository rather than another source.

    Two path segments alone is not enough to tell them apart: `/websites/fastapi_tiangolo`
    has exactly two as well. The first segment is checked against Context7's known
    non-repository namespaces instead.

    Args:
        library_id: A Context7 library id, e.g. `/upstash/context7` or `/websites/fastapi_tiangolo`.

    Returns:
        `True` when `library_id` is a two-segment path whose first segment is not one of
        Context7's known non-repository namespaces.
    """
    segments = [segment for segment in library_id.split("/") if segment]
    if len(segments) != 2:
        return False
    owner, _ = segments
    return owner.lower() not in NON_REPOSITORY_NAMESPACES


def caller_supplied_freshness(resolved: LibraryRef) -> Freshness:
    """The `Freshness` reported when the caller supplied `material` directly and it names no repository.

    Never reports caller-supplied material as current: with nothing retrieved and no repository
    to measure against, the honest answer is `unknown`, naming exactly why.

    Args:
        resolved: The Context7 library `material` was supplied in place of retrieving for.

    Returns:
        A `Freshness` with `verdict="unknown"`, naming that the material was caller-supplied.
    """
    reason = (
        f"'{resolved.id}' material was supplied directly by the caller instead of retrieved, and "
        "it is not backed by a GitHub repository to measure freshness against."
    )
    return Freshness(
        repo=resolved.id,
        verdict="unknown",
        summary=f"The freshness of '{resolved.id}' could not be measured: {reason}",
        measured_at=datetime.now(UTC).isoformat(),
        unmeasured=[reason],
    )


def non_repository_freshness(resolved: LibraryRef) -> Freshness:
    """The `Freshness` reported for a Context7 entry that is not a GitHub repository.

    Nothing here measures commit-level age, since a `websites`/`llmstxt` entry has no
    default branch to compare against. Context7's own `last_update_date` and `state` are
    reported in the summary instead, and `unmeasured` names why a real measurement was
    never attempted.

    Args:
        resolved: The Context7 library this freshness record is for.

    Returns:
        A `Freshness` with `verdict="unknown"`, carrying no commit or date fields of its own.
    """
    summary = (
        f"Context7 reports '{resolved.id}' last updated "
        f"{resolved.last_update_date or 'an unknown date'}, state '{resolved.state or 'unknown'}'."
    )
    reason = (
        f"'{resolved.id}' is not backed by a GitHub repository, so its index age cannot be "
        "measured against a live default branch."
    )
    return Freshness(
        repo=resolved.id,
        verdict="unknown",
        summary=summary,
        measured_at=datetime.now(UTC).isoformat(),
        unmeasured=[reason],
    )


def _require_finalized(resolved: LibraryRef) -> None:
    """Raise when Context7 reports `resolved` is not fully indexed.

    A `state` other than `finalized` (Context7 uses values such as `parsing`, `error`, or an
    in-progress state while a library is still being processed) means the retrieved
    documentation may be partial or in flux; answering from it silently would be the same
    mistake a stale wiki makes. `None` is left untreated as a failure: a missing `state` on an
    older or thin Context7 response is already handled elsewhere in this module (see
    `non_repository_freshness`) as an unknown to report, not an absence to refuse on.

    Args:
        resolved: The library Context7 resolved.

    Raises:
        LoreError: `resolved.state` is present and is not `finalized`.
    """
    if resolved.state is not None and resolved.state != FINALIZED_STATE:
        raise LoreError(
            f"Context7 reports '{resolved.id}' is not fully indexed (state: '{resolved.state}'). "
            "Retry shortly once indexing finishes."
        )


def _context7_docs_lag_days(resolved: LibraryRef, head_date: str | None) -> int | None:
    """Days Context7's `last_update_date` for `resolved` trails `head_date`, or `None` when unmeasurable."""
    published = freshness_core.parse_moment(resolved.last_update_date)
    head = freshness_core.parse_moment(head_date)
    if published is None or head is None:
        return None
    return max((head - published).days, 0)


def _context7_docs_note(resolved: LibraryRef, lag_days: int | None, threshold_days: int) -> str:
    """Instruction naming Context7's documentation lag, used both in the prompt and the caveat.

    `lag_days` is `None` when the comparison could not be made at all (an unparsable or
    missing date on either side), which is treated with the same caution as a measured lag
    past the threshold, never as evidence the documentation is current.
    """
    if lag_days is None:
        return (
            f"Context7's documentation for '{resolved.id}' could not be compared against the "
            "repository's live head (a date on one side could not be read). Mark any specific "
            "signature, flag, or API detail from it as needing verification at the repository's "
            "current head."
        )
    return (
        f"Context7's documentation for '{resolved.id}' was last updated {resolved.last_update_date}, "
        f"{lag_days} day(s) behind the repository's live head, past the {threshold_days}-day threshold. "
        "Mark any specific signature, flag, or API detail from it as needing verification at the "
        "repository's current head."
    )


def _with_docs_note_caveat(answer: Answer, docs_note: str | None) -> Answer:
    """`answer`, with `docs_note` folded into its caveat, when there is one to fold in."""
    if docs_note is None:
        return answer
    combined = docs_note if answer.caveat is None else f"{answer.caveat} {docs_note}"
    return answer.model_copy(update={"caveat": combined})


def howto(
    library: str,
    task: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
    context7_docs_aging_days: int = DEFAULT_CONTEXT7_DOCS_AGING_DAYS,
    intelligence: Intelligence | None = None,
) -> Answer:
    """How to use `library` to accomplish `task`.

    Args:
        library: A library name to resolve against Context7, e.g. `context7` or `fastapi`.
        task: The task to explain how to accomplish, e.g. "paginate search results".
        model: The model to run the synthesis through.
        reasoning_effort: Reasoning effort for that model.
        timeout_seconds: Per-request timeout for each retrieval call and the synthesis itself.
        material: Retrieved material supplied directly by the caller, used in place of Context7's
            (and, when `library` also names a GitHub repository, DeepWiki's) own retrieval for
            this call. When `library` resolves to a GitHub-backed library, its freshness is still
            measured; when it does not, the returned `Freshness` is `unknown`, naming that the
            material was caller-supplied rather than silently reporting it as current.
        context7_docs_aging_days: How many days Context7's `last_update_date` may trail a
            GitHub-backed library's live head before its documentation is treated with the
            same caution as a `drifted` DeepWiki page. Ignored when `library` does not resolve
            to a GitHub-backed library, or `material` is given.
        intelligence: The implementation to run the synthesis through. Defaults to `default_intelligence()`.

    Returns:
        An `Answer` carrying the synthesized text, its citations, anything the retrieved
        material did not cover, a `Freshness` (measured against the repository when Context7
        resolved a GitHub-backed library, otherwise Context7's own freshness fields, or, with
        caller-supplied material and no repository, an `unknown` record naming that), and a
        `caveat` derived from that `Freshness`, extended with a note when Context7's own
        documentation trails the repository's live head past `context7_docs_aging_days`.

    Raises:
        LoreError: Context7 has no library matching `library`, Context7 reports the resolved
            library is not fully indexed, a retrieval request failed, the intelligence
            implementation cannot run, or it produced no usable answer.
    """
    engine = intelligence or default_intelligence()
    engine.preflight()

    docs_note: str | None = None

    if material is not None:
        # Caller-supplied material IS the ground, so nothing is resolved or retrieved. Resolving
        # anyway let Context7 return an unrelated library and attach ITS repository's freshness to
        # an answer drawn entirely from the caller's own text, which is provenance that lies.
        resolved = LibraryRef(id=library, title=library)
        measured = caller_supplied_freshness(resolved)
        prompt = build_prompt_from_material(library, task, resolved, material)
    else:
        resolved = context7.resolve_library(library, task, timeout_seconds=timeout_seconds)
        _require_finalized(resolved)
        github_backed = is_github_repo_id(resolved.id)
        context_docs = context7.fetch_context(resolved.id, task, timeout_seconds=timeout_seconds)
        deepwiki_answer: str | None = None
        if github_backed:
            repo_slug = resolved.id.strip("/")
            measured = freshness_core.measure(repo_slug, timeout_seconds=min(timeout_seconds, 30.0))
            ref = freshness_core.parse_repo(repo_slug)
            deepwiki_answer = deepwiki.ask(ref, task, timeout_seconds=timeout_seconds)
            lag_days = _context7_docs_lag_days(resolved, measured.head_date)
            if lag_days is None or lag_days > context7_docs_aging_days:
                docs_note = _context7_docs_note(resolved, lag_days, context7_docs_aging_days)
        else:
            measured = non_repository_freshness(resolved)
        prompt = build_prompt(library, task, resolved, context_docs, deepwiki_answer, docs_note=docs_note)

    request = AgentRequest(
        prompt=prompt,
        model=model,
        output_schema=ANSWER_OUTPUT_SCHEMA,
        reasoning_effort=reasoning_effort,
        timeout_seconds=max(MINIMUM_TIMEOUT_SECONDS, int(timeout_seconds)),
    )
    result = engine.run(request)
    answer = answer_from_result(task, library, result, measured)
    return _with_docs_note_caveat(answer, docs_note)
