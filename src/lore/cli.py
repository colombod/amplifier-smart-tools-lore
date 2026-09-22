"""Command line entry point for Lore."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer

# Typer 0.27 vendors Click, so a command that overrides Click's own hooks has to speak the vendored types.
from typer._click import Context, Parameter
from typer.core import TyperCommand, TyperOption
from typer.models import CommandFunctionType

from lore import lib
from lore.schemas import (
    DEFAULT_INTELLIGENCE_MODEL,
    DEFAULT_READ_LIMIT,
    Answer,
    LoreError,
    Reachability,
    ReasoningEffort,
)


class CapabilityCommand(TyperCommand):
    """Every capability answers `-h` with the generated summary and `--help` with its skill from the library."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["add_help_option"] = False
        super().__init__(*args, **kwargs)

    def get_params(self, ctx: Context) -> list[Parameter]:
        def short(ctx: Context, param: Parameter, value: bool) -> None:
            if value and not ctx.resilient_parsing:
                typer.echo(ctx.get_help())
                ctx.exit()

        def capability_skill(ctx: Context, param: Parameter, value: bool) -> None:
            if value and not ctx.resilient_parsing:
                typer.echo(lib.skill(self.name))
                ctx.exit()

        return [
            *super().get_params(ctx),
            TyperOption(
                param_decls=["-h"],
                is_flag=True,
                is_eager=True,
                expose_value=False,
                callback=short,
                help="Terse summary of this capability.",
            ),
            TyperOption(
                param_decls=["--help"],
                is_flag=True,
                is_eager=True,
                expose_value=False,
                callback=capability_skill,
                help="This capability's skill, for an agent about to call it.",
            ),
        ]


class SmartToolTyper(typer.Typer):
    """A Typer whose commands are CapabilityCommand by default, so a capability added later inherits the help split."""

    def command(
        self, *args: Any, cls: type[TyperCommand] = CapabilityCommand, **kwargs: Any
    ) -> Callable[[CommandFunctionType], CommandFunctionType]:
        return super().command(*args, cls=cls, **kwargs)


app = SmartToolTyper(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    # `-h` is the terse summary and `--help` is the skill, at both scopes. On the root, the callback's parameter
    # claims `--help` and Click drops a help option name a parameter already took, which leaves the generated
    # summary on `-h`; on a capability, CapabilityCommand splits the two itself.
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _print_skill(value: bool) -> None:
    """Answer the root `--help` with the skill the library composes, leaving `-h` to Typer."""
    if value:
        typer.echo(lib.skill())
        raise typer.Exit()


@app.callback()
def cli(
    help: Annotated[
        bool,
        typer.Option(
            "--help", is_eager=True, callback=_print_skill, help="This tool's skill, for an agent driving it."
        ),
    ] = False,
) -> None:
    """Answers how to use a library, how a project works, and what its architecture is, from DeepWiki and Context7 - with every answer carrying measured index freshness so stale knowledge is named rather than guessed - reach for it before writing code against a library or repository you do not already know cold, or whenever an answer's age matters"""


@app.command()
def manifest() -> None:
    """Print the tool's manifest as JSON. Deterministic."""
    typer.echo(lib.load_manifest().model_dump_json(indent=2))


@app.command()
def freshness(
    repo: Annotated[str, typer.Argument(help="Repository as 'owner/name' or a github.com URL.")],
    timeout_seconds: Annotated[float, typer.Option(help="Per-request timeout, in seconds.")] = 30.0,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """How far DeepWiki's index for a repository trails its live default branch. Deterministic."""
    result = lib.freshness(repo, timeout_seconds=timeout_seconds)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(f"{result.verdict}: {result.summary}")


@app.command()
def check(
    timeout_seconds: Annotated[float, typer.Option(help="Per-probe timeout, in seconds.")] = 15.0,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Whether lore's prerequisites are reachable right now. Deterministic."""
    result = lib.check(timeout_seconds=timeout_seconds)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    for entry in result.checks:
        typer.echo(f"[{_reachability_status(entry)}] {entry.name}: {entry.detail}")
    typer.echo(f"deterministic_ready={result.deterministic_ready} model_backed_ready={result.model_backed_ready}")


def _reachability_status(entry: Reachability) -> str:
    """`ok` when satisfied; `optional` when not satisfied but the manifest declares it optional; else `FAIL`."""
    if entry.ok:
        return "ok"
    if entry.optional:
        return "optional"
    return "FAIL"


@app.command()
def fetch(
    repo: Annotated[str, typer.Argument(help="Repository as 'owner/name' or a github.com URL.")],
    refresh: Annotated[bool, typer.Option(help="Refetch even if a cached index already exists.")] = False,
    timeout_seconds: Annotated[float, typer.Option(help="Timeout for the DeepWiki call, in seconds.")] = 180.0,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Write a repository's DeepWiki wiki to the cache and print its index, never its content. Deterministic."""
    result = lib.fetch(repo, refresh=refresh, timeout_seconds=timeout_seconds)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    origin = "cache" if result.from_cache else "DeepWiki"
    typer.echo(f"{result.repo}: {len(result.pages)} pages, {result.total_characters} characters, from {origin}.")
    typer.echo(f"Cache: {result.root}")
    for entry in result.pages:
        typer.echo(f"{entry.number:>3}  {entry.title}")


@app.command()
def pages(
    repo: Annotated[str, typer.Argument(help="Repository slug fetch cached, e.g. 'owner/name'.")],
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Print the cached wiki index for a repository. Deterministic."""
    result = lib.pages(repo)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(f"{result.repo}: {len(result.pages)} pages, {result.total_characters} characters.")
    for entry in result.pages:
        typer.echo(f"{entry.number:>3}  {entry.title}")


@app.command()
def read(
    repo: Annotated[str, typer.Argument(help="Repository slug fetch cached, e.g. 'owner/name'.")],
    page: Annotated[str, typer.Argument(help="Page number, or a title substring.")],
    start: Annotated[int, typer.Option(help="Character offset to start at.")] = 0,
    limit: Annotated[int, typer.Option(help="Maximum characters to return.")] = DEFAULT_READ_LIMIT,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Read a bounded slice of one cached wiki page. Deterministic."""
    result = lib.read(repo, page, start=start, limit=limit)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(result.text)
    if result.truncated:
        typer.echo(
            f"...truncated at {result.returned_characters}/{result.total_characters} characters. {result.continuation}",
            err=True,
        )


@app.command()
def docs(
    library: Annotated[str, typer.Argument(help="Library name to resolve against Context7.")],
    topic: Annotated[str, typer.Argument(help="Topic to focus the documentation on.")],
    timeout_seconds: Annotated[float, typer.Option(help="Per-request timeout, in seconds.")] = 60.0,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Fetch Context7 documentation for a library, written to disk and previewed. Deterministic."""
    result = lib.docs(library, topic, timeout_seconds=timeout_seconds)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(f"{result.library.id}: {result.characters} characters -> {result.path}")
    typer.echo(result.preview)
    if result.truncated:
        typer.echo(f"...truncated. Read {result.path} for the rest.", err=True)


@app.command()
def search(
    repo: Annotated[str, typer.Argument(help="Repository slug fetch cached, e.g. 'owner/name'.")],
    pattern: Annotated[str, typer.Argument(help="Regular expression, matched case-insensitively.")],
    max_hits: Annotated[int, typer.Option(help="Maximum matches to return.")] = 50,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Search one repository's cached wiki for a pattern. Deterministic."""
    result = lib.search(repo, pattern, max_hits=max_hits)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(f"{result.total_hits} hits for '{result.pattern}' in {result.repo}.")
    for hit in result.hits:
        typer.echo(f"{hit.page_number:>3} {hit.page_title}:{hit.line}  {hit.text}")
    if result.truncated:
        typer.echo(f"...truncated to {len(result.hits)}/{result.total_hits} hits.", err=True)


@app.command()
def drift(
    repo: Annotated[str, typer.Argument(help="Repository slug fetch cached, e.g. 'owner/name'.")],
    page: Annotated[
        str | None, typer.Option("--page", help="Restrict to one page, by number or a title substring.")
    ] = None,
    timeout_seconds: Annotated[
        float, typer.Option(help="Per-request timeout for the compare call, in seconds.")
    ] = 60.0,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """Whether a cached wiki's pages still match the repository, page by page. Deterministic."""
    result = lib.drift(repo, page=page, timeout_seconds=timeout_seconds)
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(f"{result.verdict}: {result.summary}")
    for page_entry in result.pages:
        if page_entry.verdict not in ("broken", "drifted"):
            continue
        typer.echo(f"[{page_entry.verdict}] page {page_entry.page_number} '{page_entry.title}'")
        if page_entry.removed:
            removed_names = ", ".join(f"{change.filename} ({change.status})" for change in page_entry.removed)
            typer.echo(f"    removed: {removed_names}")
        typer.echo(f"    {page_entry.summary}")
    intact_count = sum(1 for page_entry in result.pages if page_entry.verdict == "intact")
    unknown_count = sum(1 for page_entry in result.pages if page_entry.verdict == "unknown")
    typer.echo(f"{intact_count} page(s) intact, {unknown_count} page(s) unknown (not shown in detail).")


@app.command()
def explain(
    repo: Annotated[str, typer.Argument(help="Repository as 'owner/name' or a github.com URL.")],
    question: Annotated[str, typer.Argument(help="Question about the repository's architecture or design.")],
    model: Annotated[str, typer.Option(help="Model to run the synthesis through.")] = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: Annotated[ReasoningEffort, typer.Option(help="Reasoning effort for that model.")] = "low",
    timeout_seconds: Annotated[
        float, typer.Option(help="Per-request timeout for each retrieval call and the synthesis, in seconds.")
    ] = 300.0,
    material_file: Annotated[
        Path | None,
        typer.Option(
            "--material-file", help="Read this file and use its contents in place of DeepWiki's own retrieval."
        ),
    ] = None,
    at_head: Annotated[
        bool,
        typer.Option(
            "--at-head",
            help="Ground on cited source read directly at the repository's head commit instead of the wiki.",
        ),
    ] = False,
    at_head_read_limit: Annotated[
        int, typer.Option(help="Maximum total characters of head-commit source to fetch with --at-head.")
    ] = DEFAULT_READ_LIMIT,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """How a project works, its architecture, and how its pieces are wired. Model-backed."""
    result = lib.explain(
        repo,
        question,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        material=_read_material_file(material_file),
        at_head=at_head,
        at_head_read_limit=at_head_read_limit,
    )
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    _echo_answer(result)


@app.command()
def howto(
    library: Annotated[str, typer.Argument(help="Library name to resolve against Context7.")],
    task: Annotated[str, typer.Argument(help="Task to explain how to accomplish.")],
    model: Annotated[str, typer.Option(help="Model to run the synthesis through.")] = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: Annotated[ReasoningEffort, typer.Option(help="Reasoning effort for that model.")] = "low",
    timeout_seconds: Annotated[
        float, typer.Option(help="Per-request timeout for each retrieval call and the synthesis, in seconds.")
    ] = 300.0,
    material_file: Annotated[
        Path | None,
        typer.Option(
            "--material-file",
            help="Read this file and use its contents in place of Context7's (and DeepWiki's) own retrieval.",
        ),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Print the result as JSON.")] = False,
) -> None:
    """How to use a library for a task, grounded in Context7's retrieved snippets. Model-backed."""
    result = lib.howto(
        library,
        task,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        material=_read_material_file(material_file),
    )
    if json_output:
        typer.echo(result.model_dump_json(indent=2))
        return
    _echo_answer(result)


def _read_material_file(path: Path | None) -> str | None:
    """`path`'s contents, or `None` when no `--material-file` was given.

    This is the CLI's own convenience: the library takes the material itself, never a path.
    """
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise LoreError(
            f"Could not read --material-file {path}: {error}. Check that the path exists, is "
            "readable, and is UTF-8 text."
        ) from error


def _echo_answer(result: Answer) -> None:
    """Render an `Answer` for a person: a staleness caveat to stderr, then the answer, citations, and unanswered."""
    if result.caveat:
        typer.echo(f"CAVEAT: {result.caveat}", err=True)
    typer.echo(result.answer)
    if result.citations:
        typer.echo("")
        typer.echo("Citations:")
        for citation in result.citations:
            typer.echo(f"  [{citation.source}] {citation.reference}")
    if result.unanswered:
        typer.echo("")
        typer.echo("Unanswered:")
        for item in result.unanswered:
            typer.echo(f"  - {item}")
    if result.at_head_files:
        typer.echo("")
        typer.echo("At-head file status:")
        for entry in result.at_head_files:
            typer.echo(f"  [{entry.status}] {entry.path}")


def main() -> int:
    try:
        app()
    except LoreError as error:
        typer.echo(error, err=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
