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

## Explain

How a project works, its architecture, and how its pieces are wired, grounded only in what
DeepWiki's own tools return for the question asked. Measures freshness first: a repository
DeepWiki has never indexed has nothing to ground an answer in, so that case raises before a
model is ever asked. Model-backed.

```python
def explain(
    repo: str,
    question: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
) -> Answer
```

- `repo`: a GitHub repository, as `owner/name` or a full `https://github.com/owner/name` URL.
- `question`: a question about the repository's architecture, design, or wiring.
- `model`/`reasoning_effort`: the model to run the synthesis through, and its reasoning effort.
- `timeout_seconds`: per-request timeout for each retrieval call and the synthesis itself.
- `material`: retrieved material supplied directly by the caller, used in place of DeepWiki's
  own retrieval for this call. The payload is data, not a reference: pass the content itself,
  never a path. `repo`'s freshness is still measured and attached either way, and the
  never-indexed guard is skipped, since the caller already supplied something to ground the
  answer in.

Returns an `Answer`: `answer` (grounded only in retrieved material), `citations` (each
naming `deepwiki`, or `caller` when grounded in `material` instead, and the page or material
the claim rests on), `unanswered` (parts of the question the retrieved material did not
cover), `freshness` (the measurement `freshness` would report for `repo`, still measured when
`material` is given), and `caveat`. `caveat` is `None` when the index is current; otherwise it
names the measured commits and days the index trails the repository by. Raises `LoreError`
when `repo` does not parse, DeepWiki has no indexed wiki for it and no `material` was
supplied, the intelligence implementation cannot run, or it produced no usable answer.

## Howto

How to actually use a library for a task, grounded in Context7's retrieved documentation.
Context7 is retrieved first, since it carries versioned code snippets; when the resolved
library is backed by a GitHub repository, its freshness is also measured and DeepWiki's own
answer for design context is retrieved alongside it. Model-backed.

```python
def howto(
    library: str,
    task: str,
    model: str = DEFAULT_INTELLIGENCE_MODEL,
    reasoning_effort: ReasoningEffort = "low",
    timeout_seconds: float = 300.0,
    material: str | None = None,
) -> Answer
```

- `library`: a library name to resolve against Context7, e.g. `context7` or `fastapi`.
- `task`: the task to explain how to accomplish, e.g. "paginate search results".
- `model`/`reasoning_effort`: the model to run the synthesis through, and its reasoning effort.
- `timeout_seconds`: per-request timeout for each retrieval call and the synthesis itself.
- `material`: retrieved material supplied directly by the caller, used in place of Context7's
  (and, when `library` also names a GitHub repository, DeepWiki's) own retrieval for this
  call. The payload is data, not a reference: pass the content itself, never a path.

Returns an `Answer`: `answer`, `citations` (each naming `context7`, `deepwiki`, or `caller`
when grounded in `material` instead), `unanswered`, `freshness` (measured against the
repository when Context7 resolved a GitHub-backed library, even with `material` given;
otherwise `unknown`, reporting Context7's own `last_update_date` and `state` in its summary
when there is no `material`, or naming that the material was caller-supplied when there is,
since neither case has a commit to measure against), and `caveat` derived from it. Raises
`LoreError` when Context7 finds no library matching `library`, a retrieval request fails,
the intelligence implementation cannot run, or it produced no usable answer.

## Adding a capability

A capability's code goes in `lore/capabilities/<name>/`, with its prompts, templates, and its own `SKILL.md` beside it, named on its row in `core/skill.py` `CAPABILITIES`, and `lib.py` gets a facade function that imports it and is the only caller of it.
Each capability of the library gets a section here: what it does and when to reach for it, the signature `lib.py` exposes, what each argument means, and what it returns or raises.
Model-backed capabilities say so, and take `model` and `reasoning_effort`, defaulting to `DEFAULT_INTELLIGENCE_MODEL` and `low` from `lore.schemas`.
