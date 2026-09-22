"""The prompt `explain` sends to the model: only what was retrieved for one repository."""

from lore.grounding import GROUNDING_RULE


def build_prompt(repo: str, question: str, wiki_structure: str, deepwiki_answer: str) -> str:
    """The full prompt for one `explain` call, carrying only the material retrieved for `repo`.

    Args:
        repo: The repository the question is about, as passed to `explain`.
        question: The question to answer.
        wiki_structure: DeepWiki's `read_wiki_structure` result for `repo`, the topic map.
        deepwiki_answer: DeepWiki's own `ask` answer to `question`, already grounded in `repo`.

    Returns:
        The prompt text, carrying `GROUNDING_RULE` and nothing outside what was retrieved.
    """
    intro = (
        f"You are explaining how the GitHub repository '{repo}' works: its architecture, "
        "design, and how its pieces are wired."
    )
    return "\n\n".join(
        [
            intro,
            GROUNDING_RULE,
            f"## Question\n{question}",
            f"## Retrieved: DeepWiki's wiki structure for {repo}\n{wiki_structure}",
            f"## Retrieved: DeepWiki's own answer to this question\n{deepwiki_answer}",
            "Using only the retrieved material above, submit your answer.",
        ]
    )
