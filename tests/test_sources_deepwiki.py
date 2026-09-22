import pytest

from lore.sources import deepwiki

# The exact shape DeepWiki rendered for upstash/context7 on 2026-07-22, minus the attributes
# elided by "..." in the verified sample: the anchor text is truncated to six characters while
# the href carries the fuller sha.
INDEXED_HTML = (
    "<div>Last indexed: <!-- -->20 July 2026<!-- --> "
    '(<a href="https://github.com/upstash/context7/commits/23843e9c" target="_blank" '
    'rel="noopener noreferrer" class="underline">23843e</a>)</div>'
)


def test_extract_indexed_commit_reads_the_sha_from_the_href_and_the_date_from_the_text() -> None:
    sha, date = deepwiki.extract_indexed_commit(INDEXED_HTML)

    assert sha == "23843e9c"
    assert date == "2026-07-20"


def test_extract_indexed_commit_returns_none_pair_when_the_marker_is_absent() -> None:
    sha, date = deepwiki.extract_indexed_commit("<div>Nothing about indexing here.</div>")

    assert (sha, date) == (None, None)


def test_extract_indexed_commit_falls_back_to_the_raw_date_when_it_does_not_parse() -> None:
    html = (
        "<div>Last indexed: <!-- -->not a date<!-- --> "
        '(<a href="https://github.com/owner/repo/commits/abc1234">abc123</a>)</div>'
    )

    sha, date = deepwiki.extract_indexed_commit(html)

    assert sha == "abc1234"
    assert date == "not a date"


def test_extract_indexed_commit_handles_a_missing_commit_link() -> None:
    html = "<div>Last indexed: <!-- -->20 July 2026<!-- --></div>"

    sha, date = deepwiki.extract_indexed_commit(html)

    assert sha is None
    assert date == "2026-07-20"


def test_parse_sse_message_reads_a_single_data_line() -> None:
    text = 'event: message\r\ndata: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"hello"}]}}\r\n'

    message = deepwiki.parse_sse_message(text)

    assert message["result"]["content"][0]["text"] == "hello"


def test_parse_sse_message_prefers_the_last_data_line_carrying_a_result_or_error() -> None:
    text = (
        "event: message\r\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"first"}]}}\r\n'
        "event: message\r\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"second"}]}}\r\n'
    )

    message = deepwiki.parse_sse_message(text)

    assert message["result"]["content"][0]["text"] == "second"


def test_parse_sse_message_reads_an_error_payload() -> None:
    text = 'data: {"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Unknown tool"}}\r\n'

    message = deepwiki.parse_sse_message(text)

    assert message["error"]["message"] == "Unknown tool"


def test_parse_sse_message_raises_when_no_data_line_carries_a_result_or_error() -> None:
    with pytest.raises(ValueError, match="no data:"):
        deepwiki.parse_sse_message("event: ping\r\ndata: {}\r\n")


def test_content_text_returns_the_first_content_blocks_text() -> None:
    message = {"result": {"content": [{"type": "text", "text": "the answer"}]}}

    assert deepwiki._content_text(message, "ask_wiki_question") == "the answer"


def test_content_text_raises_unknown_tool_on_a_jsonrpc_error_naming_it() -> None:
    message = {"error": {"code": -32601, "message": "Unknown tool: ask_wiki_question"}}

    with pytest.raises(deepwiki._ToolCallError) as failure:
        deepwiki._content_text(message, "ask_wiki_question")

    assert failure.value.unknown_tool is True


def test_content_text_raises_non_unknown_tool_error_when_the_tool_reports_ismerror() -> None:
    message = {"result": {"isError": True, "content": [{"type": "text", "text": "bad repoName"}]}}

    with pytest.raises(deepwiki._ToolCallError) as failure:
        deepwiki._content_text(message, "read_wiki_structure")

    assert failure.value.unknown_tool is False
