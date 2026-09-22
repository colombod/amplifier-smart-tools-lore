"""The prompt `explain` sends to the model: only what was retrieved for one repository."""

from lore.grounding import GROUNDING_RULE


def build_prompt(
    repo: str,
    question: str,
    pages: list[tuple[int, str, str]],
    deepwiki_answer: str,
    drift_note: str | None = None,
) -> str:
    """The full prompt for one `explain` call, carrying only the material retrieved for `repo`.

    Args:
        repo: The repository the question is about, as passed to `explain`.
        question: The question to answer.
        pages: The pages selected as grounding `question` (`lore.selection.select_pages`), as
            `(page_number, title, text)`, in selection order. The primary material to answer
            from; empty when no page could be identified as grounding the question, in which
            case only `deepwiki_answer` and `drift_note` carry anything retrieved.
        deepwiki_answer: DeepWiki's own `ask` answer to `question`, kept as supplementary
            context alongside `pages` rather than the primary material: `pages` is what the
            drift gate actually checked, so citations grounded in a specific page can be
            trusted to match what was verified.
        drift_note: An instruction naming which cited files changed since the wiki was
            indexed (or that per-page drift could not be established), when the measured
            drift for the selected pages is `drifted` or `unknown`. `None` when the pages
            grounding this answer are `intact`, in which case nothing is added.

    Returns:
        The prompt text, carrying `GROUNDING_RULE` and nothing outside what was retrieved.
    """
    intro = (
        f"You are explaining how the GitHub repository '{repo}' works: its architecture, "
        "design, and how its pieces are wired."
    )
    sections = [intro, GROUNDING_RULE]
    if drift_note is not None:
        sections.append(drift_note)
    sections.append(f"## Question\n{question}")
    for number, title, text in pages:
        sections.append(f"## Retrieved: {repo}'s wiki page {number} '{title}'\n{text}")
    sections.append(f"## Supplementary: DeepWiki's own answer to this question\n{deepwiki_answer}")
    sections.append(
        'Cite a claim grounded in one of the numbered wiki pages above with source "deepwiki" and '
        "that page's title as the reference, so provenance stays page-level."
    )
    sections.append("Using only the retrieved material above, submit your answer.")
    return "\n\n".join(sections)


def build_prompt_at_head(
    repo: str,
    question: str,
    head_sha: str,
    included: list[tuple[str, str]],
    excluded: list[str],
    missing: list[str],
    not_text: list[str],
) -> str:
    """The full prompt for one `explain --at-head` call: source read directly at the repository's head.

    Used in place of `build_prompt` when the caller asked to bypass the (possibly stale) wiki
    entirely and ground the answer in the cited files' own current content instead.

    Args:
        repo: The repository the question is about, as passed to `explain`.
        question: The question to answer.
        head_sha: The commit `included`, `missing`, and `not_text` were resolved against.
        included: `(path, text)` pairs actually fetched, in cited order, bounded by the read limit.
        excluded: Cited paths not fetched because the read limit was already spent.
        missing: Cited paths that no longer exist at `head_sha`; this is information about the
            citation, not a failure, and is reported to the model as such.
        not_text: Cited paths fetched successfully at `head_sha` whose content is not valid
            UTF-8 (a binary file, e.g. an image); like `missing`, this is information about
            the file, not a failure, and is reported to the model as such.

    Returns:
        The prompt text, carrying `GROUNDING_RULE` and nothing outside what was retrieved.
    """
    intro = (
        f"You are explaining how the GitHub repository '{repo}' works, grounded directly in its "
        f"source at head commit {head_sha} rather than DeepWiki's index."
    )
    sections = [intro, GROUNDING_RULE, f"## Question\n{question}"]
    for path, text in included:
        sections.append(f"## Retrieved: {repo}'s '{path}' at {head_sha}\n{text}")
    if excluded:
        sections.append(
            "## Not retrieved: cited but left out once the read limit was spent\n"
            + "\n".join(f"- {path}" for path in excluded)
        )
    if missing:
        sections.append(
            "## Cited by the wiki but no longer exists at head (removed or renamed)\n"
            + "\n".join(f"- {path}" for path in missing)
        )
    if not_text:
        sections.append(
            "## Cited by the wiki but not text at head (a binary file, e.g. an image)\n"
            + "\n".join(f"- {path}" for path in not_text)
        )
    sections.append(
        "This material was read directly from the repository at its head commit, not from "
        'DeepWiki. Cite claims grounded in it with source "at_head".'
    )
    sections.append("Using only the retrieved material above, submit your answer.")
    return "\n\n".join(sections)


def build_prompt_from_material(repo: str, question: str, material: str) -> str:
    """The full prompt for one `explain` call grounded in material the caller supplied directly.

    Used in place of `build_prompt` when the caller already holds the material to ground the
    answer in, so nothing is retrieved from DeepWiki for this call.

    Args:
        repo: The repository the question is about, as passed to `explain`.
        question: The question to answer.
        material: The material the caller supplied in place of DeepWiki's own retrieval.

    Returns:
        The prompt text, carrying `GROUNDING_RULE` and nothing outside `material`.
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
            f"## Retrieved: material supplied directly by the caller for {repo}\n{material}",
            (
                "This material was supplied directly by the caller rather than retrieved from "
                'DeepWiki. Cite claims grounded in it with source "caller".'
            ),
            "Using only the retrieved material above, submit your answer.",
        ]
    )
