"""Explain: how a project works, its architecture, and how its pieces are wired.

Retrieves DeepWiki's own topic map and its own answer to the question, then synthesizes
both into a grounded `Answer` through `Intelligence`. The model may use only what was
retrieved in this run; nothing it remembers from training is allowed into the answer.
"""

from lore.capabilities.explain.prompt import build_prompt, build_prompt_from_material
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
    material: str | None = None,
    intelligence: Intelligence | None = None,
) -> Answer:
    """How `repo` works: its architecture, design, and how its pieces are wired.

    Measures freshness first, since `repo` always names a repository to measure it against.
    When `material` is not given, a repository DeepWiki has never indexed has nothing to
    ground an answer in, so that case raises before a model is ever asked; otherwise this
    retrieves DeepWiki's own topic map and its own answer to `question`, then synthesizes
    both through `Intelligence`, grounded only in that retrieved material. When `material` is
    given, it replaces DeepWiki's retrieval entirely (nothing is fetched, and the
    never-indexed guard is skipped, since the caller already supplied something to ground the
    answer in) and citations grounded in it are attributed to the caller rather than DeepWiki.

    Args:
        repo: A GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL.
        question: A question about the repository's architecture, design, or wiring.
        model: The model to run the synthesis through.
        reasoning_effort: Reasoning effort for that model.
        timeout_seconds: Per-request timeout for each retrieval call and the synthesis itself.
        material: Retrieved material supplied directly by the caller, used in place of DeepWiki's
            own retrieval for this call. `repo`'s freshness is still measured and attached to the
            returned `Answer` either way.
        intelligence: The implementation to run the synthesis through. Defaults to `default_intelligence()`.

    Returns:
        An `Answer` carrying the synthesized text, its citations, anything the retrieved
        material did not cover, the measured `Freshness`, and a `caveat` when the index
        trails the repository.

    Raises:
        LoreError: `repo` does not parse, DeepWiki has no indexed wiki for it and no `material`
            was supplied, the intelligence implementation cannot run, or it produced no usable
            answer.
    """
    engine = intelligence or default_intelligence()
    engine.preflight()

    measured = freshness_core.measure(repo, timeout_seconds=min(timeout_seconds, 30.0))
    if material is None and measured.indexed_sha is None:
        # `measured.summary` already names the DeepWiki URL to visit; asking a model to
        # answer against an index that does not exist would only invite a guess.
        raise LoreError(measured.summary)

    if material is None:
        ref = freshness_core.parse_repo(repo)
        structure = deepwiki.read_wiki_structure(ref, timeout_seconds=timeout_seconds)
        deepwiki_answer = deepwiki.ask(ref, question, timeout_seconds=timeout_seconds)
        prompt = build_prompt(repo, question, structure, deepwiki_answer)
    else:
        prompt = build_prompt_from_material(repo, question, material)

    request = AgentRequest(
        prompt=prompt,
        model=model,
        output_schema=ANSWER_OUTPUT_SCHEMA,
        reasoning_effort=reasoning_effort,
        timeout_seconds=max(MINIMUM_TIMEOUT_SECONDS, int(timeout_seconds)),
    )
    result = engine.run(request)
    return answer_from_result(question, repo, result, measured)
