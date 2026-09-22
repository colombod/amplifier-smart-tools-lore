"""Explain: how a project works, its architecture, and how its pieces are wired.

Retrieves DeepWiki's own topic map and its own answer to the question, then synthesizes
both into a grounded `Answer` through `Intelligence`. The model may use only what was
retrieved in this run; nothing it remembers from training is allowed into the answer.
"""

from lore.capabilities.explain.prompt import build_prompt
from lore.capabilities.freshness import core as freshness_core
from lore.grounding import ANSWER_OUTPUT_SCHEMA, answer_from_result
from lore.intelligence.interface import Intelligence, default_intelligence
from lore.intelligence.schemas import AgentRequest
from lore.schemas import DEFAULT_INTELLIGENCE_MODEL, Answer, LoreError, ReasoningEffort
from lore.sources import deepwiki

# AgentRequest.timeout_seconds must be a positive int; a caller passing a sub-second float
# still gets a request the schema accepts rather than a validation error of our own making.
MINIMUM_TIMEOUT_SECONDS = 1


def explain(
    repo: str,
    question: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    intelligence: Intelligence | None = None,
) -> Answer:
    """How `repo` works: its architecture, design, and how its pieces are wired.

    Measures freshness first. A repository DeepWiki has never indexed has nothing to ground
    an answer in, so that case raises before a model is ever asked. Otherwise retrieves
    DeepWiki's own topic map and its own answer to `question`, then synthesizes both through
    `Intelligence`, grounded only in that retrieved material.

    Args:
        repo: A GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL.
        question: A question about the repository's architecture, design, or wiring.
        model: The model to run the synthesis through.
        reasoning_effort: Reasoning effort for that model.
        timeout_seconds: Per-request timeout for each retrieval call and the synthesis itself.
        intelligence: The implementation to run the synthesis through. Defaults to `default_intelligence()`.

    Returns:
        An `Answer` carrying the synthesized text, its citations, anything the retrieved
        material did not cover, the measured `Freshness`, and a `caveat` when the index
        trails the repository.

    Raises:
        LoreError: `repo` does not parse, DeepWiki has no indexed wiki for it, the
            intelligence implementation cannot run, or it produced no usable answer.
    """
    engine = intelligence or default_intelligence()
    engine.preflight()

    measured = freshness_core.measure(repo, timeout_seconds=min(timeout_seconds, 30.0))
    if measured.indexed_sha is None:
        # `measured.summary` already names the DeepWiki URL to visit; asking a model to
        # answer against an index that does not exist would only invite a guess.
        raise LoreError(measured.summary)

    ref = freshness_core.parse_repo(repo)
    structure = deepwiki.read_wiki_structure(ref, timeout_seconds=timeout_seconds)
    deepwiki_answer = deepwiki.ask(ref, question, timeout_seconds=timeout_seconds)

    request = AgentRequest(
        prompt=build_prompt(repo, question, structure, deepwiki_answer),
        model=model,
        output_schema=ANSWER_OUTPUT_SCHEMA,
        reasoning_effort=reasoning_effort,
        timeout_seconds=max(MINIMUM_TIMEOUT_SECONDS, int(timeout_seconds)),
    )
    result = engine.run(request)
    return answer_from_result(question, repo, result, measured)
