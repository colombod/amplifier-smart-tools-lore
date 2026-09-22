"""Top level entry point for the Lore library."""

from pathlib import Path

from lore.capabilities.check import core as check_core
from lore.capabilities.docs import core as docs_core
from lore.capabilities.explain import core as explain_core
from lore.capabilities.fetch import core as fetch_core
from lore.capabilities.freshness import core as freshness_core
from lore.capabilities.howto import core as howto_core
from lore.capabilities.pages import core as pages_core
from lore.capabilities.read import core as read_core
from lore.capabilities.search import core as search_core
from lore.core import manifest
from lore.core import skill as skill_module
from lore.schemas import (
    DEFAULT_INTELLIGENCE_MODEL,
    DEFAULT_READ_LIMIT,
    Answer,
    CheckResult,
    DocsResult,
    Freshness,
    Manifest,
    ReadResult,
    ReasoningEffort,
    SearchResult,
    WikiIndex,
)


def load_manifest() -> Manifest:
    """The tool's manifest as structured data, read from the SMART_TOOL.md shipped inside the package."""
    return manifest.load_manifest()


def skill(capability: str | None = None) -> str:
    """The tool's skill, or the named capability's own skill, wrapped so a reader knows where the tool's files are."""
    return skill_module.skill(capability)


def skill_directory() -> Path:
    """The installed package root, where the files the skill names can be read."""
    return skill_module.skill_directory()


def skill_resources() -> list[str]:
    """The files the skill lists, as paths relative to the skill directory. Every one ships inside the package."""
    return skill_module.skill_resources()


def capability_skill_resources(capability: str) -> list[str]:
    """The files that capability's skill lists, as paths relative to the skill directory."""
    return skill_module.capability_skill_resources(capability)


def repository_url() -> str | None:
    """The tool's canonical source, from the package metadata, or None when the package declares none."""
    return skill_module.repository_url()


def freshness(repo: str, timeout_seconds: float = 30.0) -> Freshness:
    """How far DeepWiki's index for `repo` trails its live default branch, measured now. Deterministic."""
    return freshness_core.measure(repo, timeout_seconds=timeout_seconds)


def check(timeout_seconds: float = 15.0) -> CheckResult:
    """Whether lore's prerequisites are reachable right now, deterministic and model-backed alike. Deterministic."""
    return check_core.check(timeout_seconds=timeout_seconds)


def fetch(repo: str, refresh: bool = False, timeout_seconds: float = 180.0) -> WikiIndex:
    """Fetch `repo`'s DeepWiki wiki to the cache and return its index, never its content. Deterministic."""
    measured = freshness_core.measure(repo, timeout_seconds=min(timeout_seconds, 30.0))
    ref = freshness_core.parse_repo(repo)
    return fetch_core.fetch(repo, ref, measured, refresh=refresh, timeout_seconds=timeout_seconds)


def pages(repo: str) -> WikiIndex:
    """The cached wiki index for `repo`. Deterministic."""
    return pages_core.pages(repo)


def read(repo: str, page: int | str, start: int = 0, limit: int = DEFAULT_READ_LIMIT) -> ReadResult:
    """A bounded slice of one cached wiki page. Deterministic."""
    return read_core.read(repo, page, start=start, limit=limit)


def docs(library: str, topic: str, timeout_seconds: float = 60.0) -> DocsResult:
    """Context7 documentation for a library, written to disk and previewed. Deterministic."""
    return docs_core.docs(library, topic, timeout_seconds=timeout_seconds)


def search(repo: str, pattern: str, max_hits: int = 50) -> SearchResult:
    """A regex search across one repository's cached wiki. Deterministic."""
    return search_core.search(repo, pattern, max_hits=max_hits)


def explain(
    repo: str,
    question: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
) -> Answer:
    """How a project works, its architecture, and how its pieces are wired. Model-backed."""
    return explain_core.explain(
        repo,
        question,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        material=material,
    )


def howto(
    library: str,
    task: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
) -> Answer:
    """How to use a library for a task, grounded in Context7's retrieved snippets. Model-backed."""
    return howto_core.howto(
        library,
        task,
        model=model,
        reasoning_effort=reasoning_effort,
        timeout_seconds=timeout_seconds,
        material=material,
    )
