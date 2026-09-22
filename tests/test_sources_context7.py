from lore.schemas import LibraryRef
from lore.sources import context7

FULL_PAYLOAD = {
    "id": "/reactjs/react.dev",
    "title": "React",
    "description": "The library for web and native user interfaces.",
    "branch": "main",
    "lastUpdateDate": "2026-07-01T00:00:00Z",
    "state": "finalized",
    "totalTokens": 123456,
    "totalSnippets": 789,
    "stars": 42,
    "trustScore": 9.5,
    "benchmarkScore": 8.1,
    "versions": ["19.0.0"],
}


def test_library_from_json_maps_every_field_context7_documents() -> None:
    library = context7._library_from_json(FULL_PAYLOAD)

    assert library == LibraryRef(
        id="/reactjs/react.dev",
        title="React",
        description="The library for web and native user interfaces.",
        last_update_date="2026-07-01T00:00:00Z",
        state="finalized",
        total_tokens=123456,
        total_snippets=789,
        stars=42,
        trust_score=9.5,
        benchmark_score=8.1,
    )


def test_library_from_json_tolerates_a_payload_with_every_optional_field_absent() -> None:
    library = context7._library_from_json({"id": "/owner/lib"})

    assert library.id == "/owner/lib"
    assert library.title == ""
    assert library.description == ""
    assert library.last_update_date is None
    assert library.state is None
    assert library.total_tokens is None
    assert library.total_snippets is None
    assert library.stars is None
    assert library.trust_score is None
    assert library.benchmark_score is None


def test_library_from_json_tolerates_a_completely_empty_payload() -> None:
    library = context7._library_from_json({})

    assert library.id == ""
    assert library.title == ""


def test_resolve_library_keeps_context7s_own_ranking() -> None:
    """Context7 reranks against the query and we do not, so its first result is the answer.

    Re-ranking on `trustScore` was measured picking a 1-star CLI wrapper over the canonical
    6679-star library, so this test pins the ordering that is not ours to change.
    """
    canonical = LibraryRef(id="/upstash/context7", title="Context7", trust_score=9.5, stars=6679)
    higher_trust_wrapper = LibraryRef(id="/jeffersongoncalves/context7-cli", title="CLI", trust_score=9.8, stars=1)

    assert context7._first_ranked([canonical, higher_trust_wrapper]) is canonical
