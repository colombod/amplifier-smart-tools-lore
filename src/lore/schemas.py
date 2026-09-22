from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

DEFAULT_INTELLIGENCE_MODEL = "gpt-6-astra"
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class LoreError(Exception):
    """Raised for any failure the library can name and explain how to fix."""


# region: Manifest


class ManifestRequirement(BaseModel):
    """One environment prerequisite; `install` references documentation, never a command."""

    name: str
    purpose: str
    install: str
    optional: bool = False


class Manifest(BaseModel):
    """The structured form of SMART_TOOL.md."""

    smart_tool_format: int
    name: str = Field(pattern=SLUG_PATTERN)
    version: str = Field(pattern=SEMVER_PATTERN)
    description: str
    use_cases: list[str]
    platforms: list[str]
    requires: list[ManifestRequirement] = Field(default_factory=list)
    body: str = Field(description="The Markdown below the frontmatter: the skill `--help` renders")


# endregion

# region: Skill


class Capability(NamedTuple):
    """One capability of the tool: its line in the skill's capability list and its own skill."""

    name: str
    summary: str
    model_backed: bool
    skill: str  # the capability's skill body, a Markdown file relative to the skill directory
    resources: tuple[str, ...] = ()  # the files that skill refers to, relative to the skill directory


# endregion

# region: Knowledge sources

# A wiki large enough to need this tool is too large to return, so every path back into cached
# content is capped. 40_000 characters is roughly 10_000 tokens: a generous read that still
# leaves a caller's context intact.
DEFAULT_READ_LIMIT = 40_000
CHARS_PER_TOKEN = 4

StalenessVerdict = Literal["current", "aging", "stale", "unknown"]


class RepoRef(BaseModel):
    """A GitHub repository, as both sources and the freshness check identify one."""

    owner: str
    repo: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


class Freshness(BaseModel):
    """How far DeepWiki's index trails the repository, measured rather than asked.

    `commits_behind` and `days_behind` are None when the comparison could not be made, which
    is a reported outcome and not a failure: the verdict is then `unknown`.
    """

    repo: str
    indexed_sha: str | None = Field(default=None, description="Commit DeepWiki states it indexed")
    indexed_date: str | None = Field(default=None, description="Date DeepWiki states it indexed, ISO 8601")
    head_sha: str | None = Field(default=None, description="Head of the repository's default branch")
    head_date: str | None = None
    default_branch: str | None = None
    commits_behind: int | None = None
    days_behind: int | None = None
    verdict: StalenessVerdict
    summary: str = Field(description="One line a caller can show a person verbatim")
    measured_at: str = Field(description="When this measurement was taken, ISO 8601")
    unmeasured: list[str] = Field(
        default_factory=list, description="Each signal that could not be read, and why, when the verdict is unknown"
    )


class PageEntry(BaseModel):
    """One page of a cached wiki: enough to decide whether to read it, without reading it."""

    number: int
    title: str
    path: str = Field(description="Page file, relative to the cache entry root")
    characters: int
    estimated_tokens: int


class WikiIndex(BaseModel):
    """The map `fetch` returns in place of the content it wrote to disk."""

    repo: str
    source: Literal["deepwiki"] = "deepwiki"
    root: str = Field(description="Cache entry root holding the pages and this index")
    pages: list[PageEntry]
    total_characters: int
    total_estimated_tokens: int
    freshness: Freshness
    fetched_at: str
    from_cache: bool = Field(
        default=False, description="True when `fetch` served this index from the cache instead of refetching"
    )


class ReadResult(BaseModel):
    """A bounded slice of one cached page, which always says what it withheld."""

    repo: str
    page_number: int
    page_title: str
    path: str
    text: str
    start: int = Field(description="Character offset this slice starts at")
    returned_characters: int
    total_characters: int
    truncated: bool
    next_start: int | None = Field(default=None, description="Offset to pass as `start` for the next slice")
    continuation: str | None = Field(default=None, description="Exact invocation that returns the next slice")


class SearchHit(BaseModel):
    """One match from a search across a cached wiki."""

    page_number: int
    page_title: str
    line: int
    text: str


class SearchResult(BaseModel):
    """Matches across a cached wiki, capped, and honest about the cap."""

    repo: str
    pattern: str
    hits: list[SearchHit]
    total_hits: int
    truncated: bool


class LibraryRef(BaseModel):
    """One Context7 library, carrying the freshness fields Context7 itself publishes."""

    id: str
    title: str
    description: str = ""
    last_update_date: str | None = None
    state: str | None = None
    total_tokens: int | None = None
    total_snippets: int | None = None
    stars: int | None = None
    trust_score: float | None = None
    benchmark_score: float | None = None


class DocsResult(BaseModel):
    """Context7 documentation for one library, written to disk and described here."""

    library: LibraryRef
    topic: str
    path: str = Field(description="File the documentation was written to")
    characters: int
    estimated_tokens: int
    preview: str = Field(description="Bounded opening of the documentation, for deciding whether to read more")
    truncated: bool


class Citation(BaseModel):
    """Where one part of an answer came from, so a reader can go check it.

    `caller` marks a claim grounded in material the caller supplied directly (`explain`'s or
    `howto`'s `material` argument) instead of anything retrieved from DeepWiki or Context7.
    """

    source: Literal["deepwiki", "context7", "caller"]
    reference: str = Field(description="Page title, library id, url, or 'caller-supplied material' the claim rests on")


class Answer(BaseModel):
    """What a model-backed capability returns: the answer, its sources, and its age."""

    question: str
    target: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    unanswered: list[str] = Field(
        default_factory=list, description="Parts of the question the retrieved material did not cover"
    )
    freshness: Freshness
    caveat: str | None = Field(
        default=None, description="Staleness warning to show with the answer, when the index trails the repository"
    )


class Reachability(BaseModel):
    """One prerequisite of the tool, and whether it is usable right now."""

    name: str
    ok: bool
    detail: str


class CheckResult(BaseModel):
    """What `check` reports: every prerequisite, and whether the straight paths can run."""

    checks: list[Reachability]
    deterministic_ready: bool
    model_backed_ready: bool


# endregion
