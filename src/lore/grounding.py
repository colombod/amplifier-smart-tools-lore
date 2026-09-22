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
from lore.schemas import Answer, Citation, Freshness, LoreError

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
                    "source": {"type": "string", "enum": ["deepwiki", "context7"]},
                    "reference": {
                        "type": "string",
                        "description": "Page title, library id, or url the claim rests on.",
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


def answer_from_result(question: str, target: str, result: AgentResult, freshness: Freshness) -> Answer:
    """Build the `Answer` a model-backed capability returns, from one completed agent run.

    Args:
        question: The question or task the caller asked.
        target: The repository or library the answer is about.
        result: The completed run to read the structured submission from.
        freshness: The measurement to attach to the answer and to derive its caveat from.

    Returns:
        An `Answer` carrying the submitted text, citations, and unanswered parts, alongside
        `freshness` and the `caveat` derived from it.

    Raises:
        LoreError: the run failed, or its structured output is missing, malformed, or carries an empty answer.
    """
    if result.error is not None:
        raise LoreError(f"Could not synthesize an answer for '{target}': {result.error}")
    if not result.output:
        raise LoreError(f"The model returned no structured output for '{target}'.")
    answer_text = result.output.get("answer")
    if not isinstance(answer_text, str) or not answer_text.strip():
        raise LoreError(f"The model's answer for '{target}' was empty.")
    try:
        citations = [Citation.model_validate(entry) for entry in result.output.get("citations") or []]
    except ValidationError as error:
        raise LoreError(f"The model's citations for '{target}' did not match the citation contract: {error}") from error
    unanswered = [str(item) for item in result.output.get("unanswered") or []]
    return Answer(
        question=question,
        target=target,
        answer=answer_text,
        citations=citations,
        unanswered=unanswered,
        freshness=freshness,
        caveat=caveat_for(freshness),
    )
