# Vision

Answers how to use a library, how a project works, and what its architecture is, from DeepWiki and Context7 - with every answer carrying measured index freshness so stale knowledge is named rather than guessed.

## The problem

An agent asked "how do I use X" has three bad options and one good one.

It can answer from training memory, which is confidently wrong about anything that moved
since the cutoff. It can search the web, which returns prose about the code rather than the
code. Or it can read a generated wiki, which is the good option right up until the wiki is
larger than the context window, or older than the repository.

Both failures are measurable, and this tool measures them rather than describing them.

**Size.** One `read_wiki_contents` call for `upstash/context7` returns 2,412,495 bytes of
JSON carrying 1,169,101 characters of Markdown across 130 pages. That is roughly 292,000
tokens in a single response, for a mid-sized repository. It does not fit, and a tool that
hands it to a caller has moved the problem rather than solved it.

**Age.** On the same day, `deepwiki.com/upstash/context7` reported its index at commit
`23843e9c` of 20 July 2026, while the repository's default branch was at `eb27b949` of
21 September 2026. The GitHub compare API puts the gap at 82 commits and 63 days. An answer
drawn from that index is not wrong, but it is 82 commits old, and the caller deserves to be
told so in those words.

## Goals

**Measure staleness, never estimate it.** `freshness` reads the indexed commit off the
DeepWiki page and compares it against the live default branch through the GitHub API. It
reports the indexed SHA and date, the head SHA and date, commits behind, days behind, and a
verdict. No model is consulted, so the number is a measurement and not an opinion. Done when
a caller can tell a one-hour-old index from an 82-commit-old one without reading prose.

**Spill big reads to disk, return a map.** `fetch` writes a wiki to a cache directory as one
file per page plus an index, and returns the index: page titles, byte sizes, token estimates,
and the freshness record. The content never passes through the caller's context on the way to
disk. Done when fetching a 292,000 token wiki costs the caller a few hundred tokens.

**Make reading bounded by construction.** `pages`, `read`, and `search` are the only ways
back into cached content, and each one caps what it returns and says what it withheld and how
to reach the rest. Done when no single call can exceed its cap, whatever the repository.

**Ground every answer in retrieved text.** The model-backed capabilities receive only what
was retrieved in that run, and return citations plus the freshness verdict alongside the
answer. Done when an answer names its sources and its age, and says it does not know rather
than filling a gap from memory.

**Act on staleness, not just narrate it.** A repository-wide "82 commits behind" is a red
herring on its own: measured on `upstash/context7`, 130 cached pages split 4 broken (a cited
file no longer resolves), 112 drifted (a cited file was edited), 14 intact (untouched) --
and refusing on `drifted` would refuse 86% of pages into uselessness, while an intact page is
correct regardless of the commit count. The same measurement also shows the worst-page
verdict is the wrong SCOPE for a gate about one question: refusing every question against
that wiki because 4 of 130 pages are broken answers nothing at all. `explain` selects the
pages that plausibly ground the question first (no model call), measures per-page drift for
only THOSE pages, and acts on the verdict they actually earned: `broken` refuses rather than
answer around a citation that does not exist anymore, naming only the selected broken
page(s); `drifted`/`unknown` tells the *model*, in the prompt, which specific files need
verification, not just the reader after the fact; `intact` carries no staleness caveat at
all, whatever other pages in the same wiki are broken or drifted. `--at-head` escalates past
the wiki entirely, reading the selected pages' cited files directly from the repository's
live head. Context7's own `state` and `lastUpdateDate` get the equivalent treatment in
`howto`. Done when a stale citation changes the answer's shape, not just its footnote, and a
question intact pages ground still answers however broken the rest of the wiki is.

**Run the straight paths with nothing configured.** Everything above works with no model
provider, no API key, and no GitHub token. Done when the deterministic capabilities pass on a
machine with no credentials at all.

## Non-Goals

**Not a code search tool.** For imports, signatures, and what a function actually does at a
given ref, clone the repository and read it. This tool covers the layer above: what the
project is, how its pieces fit, and how a caller is meant to drive it.

**Not a cache of record.** The disk cache is a scratch area keyed by repository and index
commit, safe to delete at any time. It is not a database and makes no promise of retention.

**Not an index builder.** DeepWiki and Context7 own their indexes. When an index is stale,
this tool reports the gap and points at the source; it does not attempt to refresh, mirror,
or correct someone else's index.

**Not a private repository tool.** The public DeepWiki endpoint covers public repositories.
Private repository support belongs to whoever holds the credential.

## Principles

- The library is the tool. The CLI and any other surface are thin wrappers over it.
- Deterministic capabilities run with no model provider configured, and never refuse to load without one.
- The intelligence is behind an interface, so another implementation is a new module rather than a rewrite.
- The tool works on Windows, macOS, and Linux seamlessly.
- Large content goes to disk and is read back under a cap. A capability that can return an unbounded amount of text is a defect.
- An answer without provenance and an age is an unfinished answer.
