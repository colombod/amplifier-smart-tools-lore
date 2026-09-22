from lore.capabilities.docs import core


def test_preview_returns_the_whole_text_untruncated_when_it_fits() -> None:
    text = "x" * 100

    preview, truncated = core._preview(text)

    assert preview == text
    assert truncated is False


def test_preview_caps_at_the_limit_and_reports_truncation() -> None:
    text = "x" * (core.PREVIEW_LIMIT + 500)

    preview, truncated = core._preview(text)

    assert len(preview) == core.PREVIEW_LIMIT
    assert truncated is True


def test_preview_exactly_at_the_limit_is_not_truncated() -> None:
    text = "x" * core.PREVIEW_LIMIT

    preview, truncated = core._preview(text)

    assert preview == text
    assert truncated is False
