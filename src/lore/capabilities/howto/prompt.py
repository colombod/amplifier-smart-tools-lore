"""The prompt `howto` sends to the model: only what was retrieved for one library and task."""

from lore.grounding import GROUNDING_RULE
from lore.schemas import LibraryRef


def build_prompt(
    library: str,
    task: str,
    resolved: LibraryRef,
    context7_docs: str,
    deepwiki_answer: str | None,
    docs_note: str | None = None,
) -> str:
    """The full prompt for one `howto` call, carrying only the material retrieved for `library`.

    Args:
        library: The library name as passed to `howto`.
        task: The task to explain how to accomplish.
        resolved: The library Context7 resolved `library` to.
        context7_docs: Context7's documentation for `resolved`, focused on `task`.
        deepwiki_answer: DeepWiki's own answer about `resolved`'s design, when `resolved` is
            backed by a GitHub repository; `None` otherwise, in which case its section is
            omitted rather than left carrying nothing.
        docs_note: An instruction naming that Context7's documentation trails the repository's
            live head past the aging threshold, when it does; `None` when it does not (or
            `resolved` is not backed by a GitHub repository, in which case there is nothing
            live to compare it against).

    Returns:
        The prompt text, carrying `GROUNDING_RULE` and nothing outside what was retrieved.
    """
    intro = (
        f"You are explaining how to use the library '{library}' (Context7 resolved this to "
        f"'{resolved.id}') to accomplish a task."
    )
    sections = [intro, GROUNDING_RULE]
    if docs_note is not None:
        sections.append(docs_note)
    sections += [
        f"## Task\n{task}",
        f"## Retrieved: Context7 documentation for {resolved.id}\n{context7_docs}",
    ]
    if deepwiki_answer is not None:
        sections.append(f"## Retrieved: DeepWiki's own answer about {resolved.id}'s design\n{deepwiki_answer}")
    sections.append("Using only the retrieved material above, submit your answer.")
    return "\n\n".join(sections)


def build_prompt_from_material(library: str, task: str, resolved: LibraryRef, material: str) -> str:
    """The full prompt for one `howto` call grounded in material the caller supplied directly.

    Used in place of `build_prompt` when the caller already holds the material to ground the
    answer in, so nothing is retrieved from Context7 or DeepWiki for this call.

    Args:
        library: The library name as passed to `howto`.
        task: The task to explain how to accomplish.
        resolved: The library Context7 resolved `library` to.
        material: The material the caller supplied in place of Context7's (and DeepWiki's) own retrieval.

    Returns:
        The prompt text, carrying `GROUNDING_RULE` and nothing outside `material`.
    """
    intro = (
        f"You are explaining how to use the library '{library}' (Context7 resolved this to "
        f"'{resolved.id}') to accomplish a task."
    )
    return "\n\n".join(
        [
            intro,
            GROUNDING_RULE,
            f"## Task\n{task}",
            f"## Retrieved: material supplied directly by the caller for {resolved.id}\n{material}",
            (
                "This material was supplied directly by the caller rather than retrieved from "
                'Context7 or DeepWiki. Cite claims grounded in it with source "caller".'
            ),
            "Using only the retrieved material above, submit your answer.",
        ]
    )
