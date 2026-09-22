"""The prompt `howto` sends to the model: only what was retrieved for one library and task."""

from lore.grounding import GROUNDING_RULE
from lore.schemas import LibraryRef


def build_prompt(library: str, task: str, resolved: LibraryRef, context7_docs: str, deepwiki_answer: str | None) -> str:
    """The full prompt for one `howto` call, carrying only the material retrieved for `library`.

    Args:
        library: The library name as passed to `howto`.
        task: The task to explain how to accomplish.
        resolved: The library Context7 resolved `library` to.
        context7_docs: Context7's documentation for `resolved`, focused on `task`.
        deepwiki_answer: DeepWiki's own answer about `resolved`'s design, when `resolved` is
            backed by a GitHub repository; `None` otherwise, in which case its section is
            omitted rather than left carrying nothing.

    Returns:
        The prompt text, carrying `GROUNDING_RULE` and nothing outside what was retrieved.
    """
    intro = (
        f"You are explaining how to use the library '{library}' (Context7 resolved this to "
        f"'{resolved.id}') to accomplish a task."
    )
    sections = [
        intro,
        GROUNDING_RULE,
        f"## Task\n{task}",
        f"## Retrieved: Context7 documentation for {resolved.id}\n{context7_docs}",
    ]
    if deepwiki_answer is not None:
        sections.append(f"## Retrieved: DeepWiki's own answer about {resolved.id}'s design\n{deepwiki_answer}")
    sections.append("Using only the retrieved material above, submit your answer.")
    return "\n\n".join(sections)
