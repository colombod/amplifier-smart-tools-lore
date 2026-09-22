from typing import Literal, NamedTuple

from pydantic import BaseModel, Field

DEFAULT_INTELLIGENCE_MODEL = "gpt-6-astra"
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max"]

SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class LoreError(Exception):
    """Raised for any failure the library can name and explain how to fix."""


class FileAbsentAtRefError(LoreError):
    """Raised only for a CONFIRMED 404: `path` genuinely does not exist at `ref`.

    Deliberately distinct from `LoreError` itself, which still covers every other retrieval
    failure (network error, rate limit, malformed response, decode failure). A caller reading
    a file at a ref needs to tell "this citation is stale, the file is gone" apart from "this
    attempt to check failed" without parsing a message: the former is real information safe to
    record and continue past; the latter is not evidence of anything and must fail loud instead
    of being silently folded into the former.
    """


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


FileStatus = Literal["added", "modified", "removed", "renamed", "unknown"]
DriftVerdict = Literal["intact", "drifted", "broken", "unknown"]


class FileChange(BaseModel):
    """One file GitHub reports changed between two commits."""

    filename: str
    status: FileStatus
    changes: int = 0
    previous_filename: str | None = Field(default=None, description="Prior path, carried only when status is 'renamed'")


class PageDrift(BaseModel):
    """Whether one cached wiki page's own citations still match the repository.

    Measured against the page's own "Relevant source files" block and inline citations, not
    against the repository as a whole: a repo that is only lightly behind can still carry one
    page whose entire cited files were deleted, and that page must be reported as broken
    regardless of how current the rest of the repository looks.
    """

    page_number: int
    title: str
    cited_files: list[str]
    changed: list[FileChange]
    removed: list[FileChange] = Field(
        description="The subset of `changed` whose citation no longer resolves: status 'removed' or 'renamed'"
    )
    intact: list[str]
    verdict: DriftVerdict
    summary: str = Field(description="One line safe to show a person verbatim, carrying the real counts")


class DriftReport(BaseModel):
    """Whether a cached wiki's pages still match the repository, page by page.

    `verdict` is the WORST `PageDrift.verdict` present, never an average: one broken page
    makes the report broken, regardless of how many other pages are intact.
    """

    repo: str
    indexed_sha: str | None
    head_sha: str | None
    pages: list[PageDrift]
    verdict: DriftVerdict
    changed_file_count: int
    comparison_complete: bool = Field(
        description="False when GitHub's changed-file list could not be enumerated in full"
    )
    summary: str = Field(description="One line safe to show a person verbatim")


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
    `at_head` marks a claim grounded in source `explain --at-head` read directly from the
    repository at its live head commit, rather than DeepWiki's (possibly stale) index; `ref`
    carries that commit and is set mechanically by the library, never trusted from the model.
    """

    source: Literal["deepwiki", "context7", "caller", "at_head"]
    reference: str = Field(
        description="Page title, library id, file path, url, or 'caller-supplied material' the claim rests on"
    )
    ref: str | None = Field(
        default=None, description="Commit the material was read at; carried only when source is 'at_head'"
    )


AtHeadFileVerdict = Literal["included", "excluded_for_budget", "missing_at_head"]


class AtHeadFileStatus(BaseModel):
    """One cited file's fate when `explain --at-head` fetched cited files directly from GitHub.

    Populated mechanically by the library from what `--at-head` actually retrieved, never by
    the model: a caller must be able to tell which files actually grounded the answer, which
    were left out for budget, and which no longer exist at head, rather than trusting the
    model's own account of what it was given.
    """

    path: str
    status: AtHeadFileVerdict


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
    at_head_files: list[AtHeadFileStatus] = Field(
        default_factory=list,
        description=(
            "Per-file fate when the answer was grounded via --at-head: included, excluded for "
            "budget, or missing at head. Empty when --at-head was not used."
        ),
    )


class Reachability(BaseModel):
    """One prerequisite of the tool, and whether it is usable right now.

    `optional` mirrors the manifest requirement of the same prerequisite, when one is
    declared: an unsatisfied optional prerequisite is a reported state, not a failure.
    """

    name: str
    ok: bool
    detail: str
    optional: bool = False


class CheckResult(BaseModel):
    """What `check` reports: every prerequisite, and whether the straight paths can run."""

    checks: list[Reachability]
    deterministic_ready: bool
    model_backed_ready: bool


# endregion
