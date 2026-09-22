"""Grounding: what every model-backed capability of lore shares.

The instruction that the model may use only material retrieved in that run, the JSON schema
its structured answer must satisfy, the caveat derived from a measured `Freshness`, and how a
completed agent run becomes an `Answer`. This is the tool's governing rule made mechanical:
put in the prompt, and enforced on the way out. `explain` and `howto` both build their prompts
around `GROUNDING_RULE` and both read their model's submission back through
`answer_from_result`, so neither can drift from what the other enforces.
"""

from typing import Any

from pydantic import ValidationError

from lore.intelligence.schemas import AgentResult
from lore.schemas import Answer, AtHeadFileStatus, Citation, DriftReport, Freshness, LoreError

GROUNDING_RULE = (
    "GROUNDING RULE: you may use ONLY the material retrieved above, and nothing you remember "
    "from training. Every claim in your answer must carry a citation naming the retrieved "
    "source it rests on. Anything the retrieved material does not cover goes in `unanswered`, "
    "stated plainly, and must never be filled in from memory. Do not state a version number, "
    "API signature, import path, or flag unless it appears in the retrieved material above."
)

# The `submit` tool's schema for every model-backed capability: the answer, its citations,
# and what the retrieved material left uncovered. `answer_from_result` is the only reader.
ANSWER_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The synthesized answer, grounded only in the retrieved material above.",
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "enum": ["deepwiki", "context7", "caller", "at_head"]},
                    "reference": {
                        "type": "string",
                        "description": (
                            "Page title, library id, or url the claim rests on; "
                            "'caller-supplied material' when source is 'caller'."
                        ),
                    },
                },
                "required": ["source", "reference"],
            },
        },
        "unanswered": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Parts of the question the retrieved material did not cover.",
        },
    },
    "required": ["answer", "citations", "unanswered"],
}

AGING_CAVEAT = "Recent API changes may be missing."
STALE_CAVEAT = (
    "Architecture and design are probably still sound, but API details may have moved. "
    "Check signatures against the repository at its current head."
)


def caveat_for(freshness: Freshness) -> str | None:
    """The staleness warning to show alongside an answer, derived from the measured verdict.

    Built from the real numbers on `freshness`: a caveat with no numbers in it, for a verdict
    that has numbers to give, would be a defect this function must not produce.

    Args:
        freshness: The measurement an `explain` or `howto` call grounded its retrieval in.

    Returns:
        `None` when `freshness.verdict` is `"current"`. Otherwise one line naming the gap
        (`"aging"`/`"stale"`) or naming why the age could not be measured (`"unknown"`).
    """
    if freshness.verdict == "current":
        return None
    if freshness.verdict == "unknown":
        reason = " ".join(freshness.unmeasured) if freshness.unmeasured else "the required signals could not be read."
        return f"The index's age for {freshness.repo} could not be measured: {reason}"
    gap = _gap_clause(freshness.commits_behind, freshness.days_behind)
    if freshness.verdict == "aging":
        return f"The index for {freshness.repo} trails the repository by {gap}. {AGING_CAVEAT}"
    return f"The index for {freshness.repo} is {gap} behind the repository. {STALE_CAVEAT}"


def caveat_for_drift(freshness: Freshness, drift_report: DriftReport | None) -> str | None:
    """The staleness caveat to show, given a per-page drift measurement of the pages that ground the answer.

    `broken` never reaches here: a capability that measures drift refuses before synthesis
    runs rather than answering around a citation that no longer resolves. `intact` overrides
    `freshness` entirely, whatever the commit count: a repository can be many commits behind
    while every file the answer's pages cite is untouched, and reporting a caveat in that case
    would train a caller to ignore it. `unknown` is treated with the same caution as
    `drifted`, and the caveat says explicitly that per-page drift could not be established,
    since folding it silently into the repository-wide gap would understate the risk of a
    citation that quietly does not resolve. `None` (drift not measured at all, e.g.
    `explain --at-head` or caller-supplied material) falls back to `caveat_for` alone,
    unchanged.

    Args:
        freshness: The measurement an `explain` call grounded its retrieval in.
        drift_report: The per-page drift measurement for the pages that grounded this answer,
            or `None` when drift was not measured for this call.

    Returns:
        The caveat text to show, or `None` when there is nothing to warn about.
    """
    base = caveat_for(freshness)
    if drift_report is None:
        return base
    if drift_report.verdict == "intact":
        return None
    if drift_report.verdict == "unknown":
        note = f"Per-page drift for {drift_report.repo} could not be established: {drift_report.summary}"
        return note if base is None else f"{base} {note}"
    return base


def _gap_clause(commits_behind: int | None, days_behind: int | None) -> str:
    """`commits_behind`/`days_behind` as a phrase, e.g. '5 commits and 3 days'."""
    if commits_behind is None:
        return "an unmeasured number of commits"
    commit_word = "commit" if commits_behind == 1 else "commits"
    clause = f"{commits_behind} {commit_word}"
    if days_behind is not None:
        day_word = "day" if days_behind == 1 else "days"
        clause = f"{clause} and {days_behind} {day_word}"
    return clause


def answer_from_result(
    question: str,
    target: str,
    result: AgentResult,
    freshness: Freshness,
    drift_report: DriftReport | None = None,
    head_ref: str | None = None,
    at_head_files: list[AtHeadFileStatus] | None = None,
) -> Answer:
    """Build the `Answer` a model-backed capability returns, from one completed agent run.

    Args:
        question: The question or task the caller asked.
        target: The repository or library the answer is about.
        result: The completed run to read the structured submission from.
        freshness: The measurement to attach to the answer and to derive its caveat from.
        drift_report: The per-page drift measurement for the pages that grounded this answer,
            when one was made; passed to `caveat_for_drift` in place of `caveat_for` alone.
        head_ref: The commit citations sourced `at_head` were read at. When given, every such
            citation's `ref` is set to this value mechanically, regardless of what the model
            submitted: the model is told the ref in the prompt, but this is what enforces it.
        at_head_files: Every cited file's fate when grounded via `--at-head` (included,
            excluded for budget, missing at head, or not text at head), mechanically derived
            by the caller from what it actually retrieved. `None` (the default) becomes an
            empty list: this is never populated from the model's own submission.

    Returns:
        An `Answer` carrying the submitted text, citations, and unanswered parts, alongside
        `freshness`, the `caveat` derived from it, and `at_head_files`.

    Raises:
        LoreError: the run failed, or its structured output is missing, malformed, or carries an empty answer.
    """
    if result.error is not None:
        raise LoreError(
            f"Could not synthesize an answer for '{target}': {result.error}. Check `gh auth status`, "
            "confirm the signed-in account has an active GitHub Copilot subscription, or retry."
        )
    if not result.output:
        raise LoreError(
            f"The model returned no structured output for '{target}'. Retry the call; if it keeps "
            "happening, raise --reasoning-effort so the model is more likely to reach the submit step."
        )
    answer_text = result.output.get("answer")
    if not isinstance(answer_text, str) or not answer_text.strip():
        raise LoreError(
            f"The model's answer for '{target}' was empty. Retry, or narrow the question so there is "
            "less ground for it to cover in one pass."
        )
    try:
        citations = [Citation.model_validate(entry) for entry in result.output.get("citations") or []]
    except ValidationError as error:
        raise LoreError(f"The model's citations for '{target}' did not match the citation contract: {error}") from error
    if head_ref is not None:
        citations = [
            citation.model_copy(update={"ref": head_ref}) if citation.source == "at_head" else citation
            for citation in citations
        ]
    unanswered = [str(item) for item in result.output.get("unanswered") or []]
    return Answer(
        question=question,
        target=target,
        answer=answer_text,
        citations=citations,
        unanswered=unanswered,
        freshness=freshness,
        caveat=caveat_for_drift(freshness, drift_report),
        at_head_files=at_head_files or [],
    )
