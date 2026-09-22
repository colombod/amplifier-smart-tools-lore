# Library Reference

Every capability of Lore is reachable from `lore.lib`.
All other surfaces, including the CLI, are thin wrappers over the library and add no capability of their own.

## Intelligence

Model-backed capabilities run through the `Intelligence` protocol in `lore.intelligence.interface`:

```python
class Intelligence(Protocol):
    implementation: str

    def preflight(self) -> None: ...
    def run(self, request: AgentRequest) -> AgentResult: ...
```

`preflight` raises `LoreError` naming what to configure when the implementation cannot run.
`run` executes one agent: `AgentRequest` holds the prompt, model, optional workspace, and optional output schema; `AgentResult` holds the text, structured output, or error.
Setting `AgentRequest.resume` to an earlier `AgentResult.session_id` continues that session instead of starting a fresh one, so the agent keeps what it learned.

`default_intelligence()` returns the shipped implementation, `CopilotIntelligence`, built on the [GitHub Copilot SDK](https://github.com/github/copilot-sdk) and signed in through the GitHub CLI.
Another implementation is a module satisfying the protocol and a branch in that factory.

## Manifest

The tool's `SMART_TOOL.md` as structured data: the frontmatter as fields, the Markdown below it as `Manifest.body`.

```python
def load_manifest() -> Manifest
```

## Skill

What an agent reads once it has decided to drive the tool: the manifest body and the capability list, wrapped so the reader knows where the tool's files are.
Naming a capability returns that capability's own skill instead: the same wrapper, a heading carrying the capability's name, whether it is deterministic or model-backed, and the Markdown beside its code, which covers its arguments, a worked invocation, its result, and its failures.
The CLI's `--help` prints exactly this, the tool's at the root and the capability's on a command.
Raises `LoreError` when the name is not a capability, naming the ones that are.

```python
def skill(capability: str | None = None) -> str
```

The capabilities the skill lists, one entry each, driven by the same table the CLI is built from:

```python
class Capability(NamedTuple):
    name: str
    summary: str
    model_backed: bool
    skill: str
    resources: tuple[str, ...] = ()
```

- `name` and `summary`: the command's name and its line in the tool's capability list.
- `model_backed`: whether it runs through the `Intelligence` interface, which decides the kind shown in both skills.
- `skill`: the capability's skill body, a Markdown file relative to `skill_directory()`, written without frontmatter, title, or kind line because the renderer supplies them.
- `resources`: the files that body refers to, relative to `skill_directory()`, listed under `<skill_resources>` in the capability's skill. The block is omitted when there are none.

The installed package root, resolved at runtime, where the files the skill names can be read.

```python
def skill_directory() -> Path
```

The files the skill lists under `<skill_resources>`, as paths relative to `skill_directory()`. Every one ships inside the package, so each resolves after installation.
The second does the same for one capability's skill, and raises `LoreError` when the name is not a capability.

```python
def skill_resources() -> list[str]


def capability_skill_resources(capability: str) -> list[str]
```

The tool's canonical source, read from the package metadata's `[project.urls]` `Repository` entry, or `None` when the package declares none.
The skill carries it so a caller that can run the tool but not read its files still reaches the documentation.

```python
def repository_url() -> str | None
```

## Freshness

How far DeepWiki's index for a repository trails its live default branch, measured against
DeepWiki's own page and the GitHub API rather than estimated. Deterministic.

```python
def freshness(repo: str, timeout_seconds: float = 30.0) -> Freshness
```

- `repo`: a GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL.
- `timeout_seconds`: per-request timeout for each source this consults.

Returns a `Freshness`. `verdict` is `current` when `commits_behind` is `0`; `aging` when at
most 25 commits and at most 30 days behind; `stale` past either bound; `unknown` when a signal
could not be read, `unmeasured` naming each one and why. `summary` is one line safe to show a
person verbatim. Raises `LoreError` when `repo` does not parse, or GitHub reports no such
repository.

## Check

Whether lore's prerequisites are reachable right now: DeepWiki's MCP endpoint, deepwiki.com,
the Context7 API, the GitHub API, the optional Context7 API key, the cache directory, and the
model-backed capabilities' own prerequisite. Deterministic. Never raises for an unreachable
prerequisite; that is a reported `ok=False`. A prerequisite the manifest declares optional is
never reported as a failure when unsatisfied.

```python
def check(timeout_seconds: float = 15.0) -> CheckResult
```

- `timeout_seconds`: per-probe network timeout.

Returns a `CheckResult`: `checks` (one `Reachability` per prerequisite: `name`, `ok`, `detail`,
`optional`), `deterministic_ready` (DeepWiki, GitHub, and the cache all usable with no
credentials), and `model_backed_ready` (`gh` installed and signed in). `optional` mirrors the
manifest requirement of the same prerequisite, when one is declared.

## Fetch

Writes a repository's DeepWiki wiki to the on-disk cache, one file per page plus an index, and
returns the index in place of the content, which never passes through this function's caller.
Deterministic.

```python
def fetch(repo: str, refresh: bool = False, timeout_seconds: float = 180.0) -> WikiIndex
```

- `repo`: as `freshness`.
- `refresh`: refetch even when a cached index already exists for the commit DeepWiki currently
  reports as indexed. Default: reuse the cache.
- `timeout_seconds`: timeout for the DeepWiki call, which can carry megabytes of Markdown.

Returns a `WikiIndex`: `pages` (title, path, size, estimated tokens, one entry per page),
`total_characters`/`total_estimated_tokens`, `root` (the cache directory), `freshness` (this
fetch's own measurement), and `from_cache` (`True` when an existing cache entry was reused
instead of refetched). Raises `LoreError` when `repo` does not parse, the freshness measurement
fails, or the DeepWiki call fails with no cache to fall back on.

## Pages

The cached wiki index for a repository, read straight from disk with no network call.
Deterministic.

```python
def pages(repo: str) -> WikiIndex
```

- `repo`: the repository slug `fetch` cached, e.g. `owner/name`.

Returns the `WikiIndex` `fetch` last wrote for `repo`. Raises `LoreError` when no wiki is
cached for `repo`, naming the `fetch` call to make first.

## Read

A bounded slice of one cached wiki page: the only way to get page text back. Deterministic.

```python
def read(repo: str, page: int | str, start: int = 0, limit: int = DEFAULT_READ_LIMIT) -> ReadResult
```

- `repo`: as `pages`.
- `page`: a page number, or a case-insensitive substring of a page title.
- `start`: character offset to start the slice at.
- `limit`: maximum characters to return; the result says whether it was truncated.

Returns a `ReadResult`: `text`, `start`/`returned_characters`/`total_characters`, `truncated`,
and, when truncated, `next_start`/`continuation` naming exactly how to read on. Raises
`LoreError` when no wiki is cached for `repo`, `page` matches no page or more than one, or
`start`/`limit` is invalid.

## Docs

Context7 documentation for a library, written to disk and previewed rather than returned
whole. Deterministic. Independent of `fetch`/`pages`/`read`: Context7 and DeepWiki are
separate sources, covering libraries and repositories respectively.

```python
def docs(library: str, topic: str, timeout_seconds: float = 60.0) -> DocsResult
```

- `library`: a library name to resolve against Context7, e.g. `context7` or `fastapi`.
- `topic`: the topic to focus the documentation on, e.g. `routing`.
- `timeout_seconds`: per-request timeout for the resolve and fetch calls.

Returns a `DocsResult`: `library` (the resolved `LibraryRef`), `path` (where the full
documentation was written), `characters`/`estimated_tokens`, `preview` (bounded to 2000
characters), and `truncated`. Raises `LoreError` when Context7 finds no library matching
`library`, or a request fails.

## Search

A regex search across one repository's cached wiki, capped and honest about the cap.
Deterministic.

```python
def search(repo: str, pattern: str, max_hits: int = 50) -> SearchResult
```

- `repo`: as `pages`.
- `pattern`: a regular expression, matched case-insensitively line by line.
- `max_hits`: maximum matches to return; `total_hits` reports the true count.

Returns a `SearchResult`: `hits` (`SearchHit` per match), `total_hits`, and `truncated`.
Raises `LoreError` when no wiki is cached for `repo`, or `pattern` is not a valid regex.

## Drift

Whether a cached wiki's pages still match the repository, page by page, rather than averaged
across it. Intersects each page's own citations (its "Relevant source files" block and its
inline `[path:line-range]()` citations) against the files GitHub reports changed since the
wiki was indexed. A repository that is only lightly behind overall can still carry one page
whose cited files were deleted; `freshness`'s repository-wide number cannot see that, this
does. Deterministic.

```python
def drift(repo: str, page: int | str | None = None, timeout_seconds: float = 60.0) -> DriftReport
```

- `repo`: the repository slug `fetch` cached, e.g. `owner/name`.
- `page`: restrict the measurement to one page, by number or a case-insensitive title
  substring; `None` measures every cached page.
- `timeout_seconds`: per-request timeout for the GitHub compare call.

Returns a `DriftReport`: `repo`/`indexed_sha`/`head_sha` (the commits compared), `pages` (one
`PageDrift` per page measured: `page_number`, `title`, `cited_files`, `changed` and `removed`
(`FileChange`: `filename`, `status`, `changes`, `previous_filename`; `removed` is the subset of
`changed` whose citation no longer resolves, status `removed` or `renamed`), `intact`,
`verdict`, `summary`), `verdict` (`intact`, `drifted`, `broken`, or `unknown`, the WORST page
verdict present, never an average), `changed_file_count`, `comparison_complete` (`False` when
GitHub's changed-file list could not be enumerated in full, or the indexed or head commit is
itself unknown, in which case a page whose citations could not be ruled out is `unknown`
rather than `intact`), and `summary`. Raises `LoreError` when no wiki is cached for `repo`, or
`page` matches no cached page or more than one.

## Explain

How a project works, its architecture, and how its pieces are wired, grounded only in the
wiki pages selected as relevant to the question asked. Measures freshness first: a
repository DeepWiki has never indexed has nothing to ground an answer in, so that case
raises before a model is ever asked. Selects the cached wiki pages that plausibly ground the
question (`lore.selection`, a no-model relevance heuristic over page titles and bodies),
fetching the wiki to the cache first when it is not already there, then measures per-page
drift (`lore.capabilities.drift`) for those SELECTED pages only -- never the whole wiki, since
a report's worst-page verdict is the wrong scope for a gate about one question -- and acts on
it: a selected page whose cited files no longer resolve (`broken`) raises rather than
answering around a dead citation, naming only the selected broken page(s); a selected page
whose cited files were merely edited (`drifted`), or whose drift could not be fully
established (`unknown`), still answers, with the model told exactly which files need
verification and the usual staleness caveat; a selected page whose citations are untouched
(`intact`) carries no caveat at all, whatever the commit count and whatever other pages in
the same wiki are broken. When no page can be identified as grounding the question, drift is
`unknown` and the answer proceeds with a caveat saying so, never a refusal. Model-backed.

```python
def explain(
    repo: str,
    question: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
    at_head: bool = False,
    at_head_read_limit: int = DEFAULT_READ_LIMIT,
) -> Answer
```

- `repo`: a GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL.
- `question`: a question about the repository's architecture, design, or wiring.
- `model`/`reasoning_effort`: the model to run the synthesis through, and its reasoning effort.
- `timeout_seconds`: per-request timeout for each retrieval call and the synthesis itself.
- `material`: retrieved material supplied directly by the caller, used in place of DeepWiki's
  own retrieval for this call. The payload is data, not a reference: pass the content itself,
  never a path. `repo`'s freshness is still measured and attached either way; the
  never-indexed guard and the drift measurement are both skipped, since the caller already
  supplied something to ground the answer in.
- `at_head`: skip the wiki's own content entirely and ground the answer in the cited files'
  current content, read directly from `repo` at its live head commit via GitHub's contents
  API. Cited files are fetched in relevance order (a no-model heuristic scoring proximity to
  the question in the citing page's text, then a match against the file's own path segments),
  not the alphabetical order DeepWiki's citations happen to list in, so the budget below is
  spent on the files most likely to matter; this only ever reorders, never drops a file.
  Ignored when `material` is given.
- `at_head_read_limit`: maximum total characters of head-commit source to fetch when
  `at_head` is set; cited files past this budget are named as left out rather than fetched.

Returns an `Answer`: `answer` (grounded only in retrieved material), `citations` (each
naming `deepwiki`, `at_head` (carrying `ref`, the commit read) when grounded via `at_head`,
or `caller` when grounded in `material` instead, and the page, file, or material the claim
rests on), `unanswered` (parts of the question the retrieved material did not cover),
`freshness` (the measurement `freshness` would report for `repo`, still measured when
`material` is given; with `at_head`, this instead reports the material as current, since it
is the repository's own live head rather than the wiki's index), `caveat`, and
`at_head_files` (empty except with `at_head`; each cited file's fate, mechanically derived,
never asserted by the model: `included`, `excluded_for_budget`, `missing_at_head` for a
confirmed 404, or `not_text` for a file fetched successfully whose content is not valid UTF-8
(e.g. a binary file) -- the one documented partial-completion outcome of this capability).
`caveat` is `None` when the pages grounding the answer are `intact` (or the material is at
head), whatever the commit count; otherwise it names the measured commits and days the index
trails the repository by. Raises `LoreError` when `repo` does not parse, DeepWiki has no
indexed wiki for it and no `material` was supplied, a cached wiki page cites a file GitHub
reports removed or renamed, `at_head` was requested but the repository's live head commit
could not be measured, an `at_head` fetch fails for a reason other than a confirmed 404 or a
decode failure (never folded into `missing_at_head` or `not_text`), the intelligence
implementation cannot run, or it produced no usable answer.

## Howto

How to actually use a library for a task, grounded in Context7's retrieved documentation.
Context7 is retrieved first, since it carries versioned code snippets; when the resolved
library is backed by a GitHub repository, its freshness is also measured and DeepWiki's own
answer for design context is retrieved alongside it. Acts on Context7's own freshness
signals: a resolved library whose `state` is not `finalized` raises rather than answering
from a partial index; for a GitHub-backed library, when `last_update_date` trails the
repository's live head past `context7_docs_aging_days`, the documentation gets the same
treatment `explain` gives a `drifted` page (the model is told, and the caveat names it).
Model-backed.

```python
def howto(
    library: str,
    task: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
    context7_docs_aging_days: int = DEFAULT_CONTEXT7_DOCS_AGING_DAYS,
) -> Answer
```

- `library`: a library name to resolve against Context7, e.g. `context7` or `fastapi`.
- `task`: the task to explain how to accomplish, e.g. "paginate search results".
- `model`/`reasoning_effort`: the model to run the synthesis through, and its reasoning effort.
- `timeout_seconds`: per-request timeout for each retrieval call and the synthesis itself.
- `material`: retrieved material supplied directly by the caller, used in place of Context7's
  (and, when `library` also names a GitHub repository, DeepWiki's) own retrieval for this
  call. The payload is data, not a reference: pass the content itself, never a path. The
  `state` check is skipped too, since nothing is resolved.
- `context7_docs_aging_days`: how many days Context7's `last_update_date` may trail a
  GitHub-backed library's live head before its documentation is treated with the same
  caution as a `drifted` DeepWiki page. Ignored when `library` does not resolve to a
  GitHub-backed library, or `material` is given.

Returns an `Answer`: `answer`, `citations` (each naming `context7`, `deepwiki`, or `caller`
when grounded in `material` instead), `unanswered`, `freshness` (measured against the
repository when Context7 resolved a GitHub-backed library, even with `material` given;
otherwise `unknown`, reporting Context7's own `last_update_date` and `state` in its summary
when there is no `material`, or naming that the material was caller-supplied when there is,
since neither case has a commit to measure against), and `caveat` derived from it, extended
with a note when Context7's own documentation trails the repository's live head past
`context7_docs_aging_days`. Raises `LoreError` when Context7 finds no library matching
`library`, Context7 reports the resolved library is not fully indexed, a retrieval request
fails, the intelligence implementation cannot run, or it produced no usable answer.

## Adding a capability

A capability's code goes in `lore/capabilities/<name>/`, with its prompts, templates, and its own `SKILL.md` beside it, named on its row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports it and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `model` and `reasoning_effort`, defaulting to `DEFAULT_INTELLIGENCE_MODEL` and `low` from `lore.schemas`.
