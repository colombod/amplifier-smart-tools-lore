import httpx
import pytest

from lore.schemas import LibraryRef, LoreError
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


def _response(status_code: int, text: str = "") -> httpx.Response:
    return httpx.Response(status_code, content=text.encode("utf-8"))


def test_raise_for_status_ok_does_not_raise() -> None:
    context7._raise_for_status(_response(200), "documentation for 'x'")


def test_raise_for_status_403_names_plan_access_the_spending_limit_and_the_api_key_env() -> None:
    with pytest.raises(LoreError) as failure:
        context7._raise_for_status(_response(403), "documentation for 'x'")

    message = str(failure.value)
    assert "https://context7.com" in message
    assert context7.API_KEY_ENV in message
    assert "spending limit" in message


def test_raise_for_status_402_gets_the_same_remedy_as_403() -> None:
    """402 and 403 are both a plan restriction from Context7's own side, so they share a remedy."""
    with pytest.raises(LoreError) as failure:
        context7._raise_for_status(_response(402), "documentation for 'x'")

    message = str(failure.value)
    assert "https://context7.com" in message
    assert context7.API_KEY_ENV in message


def test_raise_for_status_404_points_at_checking_the_name_or_searching_first() -> None:
    with pytest.raises(LoreError, match=r"typo|search") as failure:
        context7._raise_for_status(_response(404), "a library search for 'nonexistent'")

    assert "spending limit" not in str(failure.value)


def test_raise_for_status_generic_error_points_at_retrying_and_the_context7_site() -> None:
    with pytest.raises(LoreError) as failure:
        context7._raise_for_status(_response(500, text="internal error"), "documentation for 'x'")

    message = str(failure.value)
    assert "Retry" in message
    assert "https://context7.com" in message


def test_raise_for_status_messages_are_not_all_identical() -> None:
    """Each status must carry its own remedy, not one sentence copied across every case."""
    messages = {status: str(_raised_message(status)) for status in (403, 402, 404, 500)}

    assert len(set(messages.values())) == len(messages)


def _raised_message(status: int) -> str:
    try:
        context7._raise_for_status(_response(status), "documentation for 'x'")
    except LoreError as error:
        return str(error)
    raise AssertionError(f"status {status} did not raise")
