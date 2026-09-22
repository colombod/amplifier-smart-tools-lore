import pytest

from lore.core.manifest import requirement_install_url
from lore.intelligence.copilot import CopilotIntelligence, _agent_result_for_failure, _is_entitlement_failure
from lore.schemas import LoreError


def test_github_token_failure_names_the_same_install_url_the_manifest_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("lore.intelligence.copilot.shutil.which", lambda _name: None)
    intelligence = CopilotIntelligence()

    with pytest.raises(LoreError) as failure:
        intelligence.preflight()

    assert requirement_install_url("gh") in str(failure.value)
    assert "gh auth login" in str(failure.value)


@pytest.mark.parametrize(
    "message",
    [
        "Failed to fetch token entitlements: Server returned 403",
        "401 Unauthorized",
        "Forbidden",
        "no Copilot entitlement for this account",
    ],
)
def test_is_entitlement_failure_matches_known_authorization_markers(message: str) -> None:
    assert _is_entitlement_failure(RuntimeError(message)) is True


def test_is_entitlement_failure_does_not_match_an_ordinary_agent_failure() -> None:
    assert _is_entitlement_failure(RuntimeError("the agent did not call submit")) is False


def test_agent_result_for_failure_raises_a_named_lore_error_for_an_entitlement_failure() -> None:
    error = RuntimeError("Failed to fetch token entitlements: Server returned 403")

    with pytest.raises(LoreError) as failure:
        _agent_result_for_failure(error, session_id="session-1")

    assert requirement_install_url("github-copilot-subscription") in str(failure.value)
    assert "Copilot subscription" in str(failure.value)


def test_agent_result_for_failure_reports_an_ordinary_failure_through_agent_result_instead_of_raising() -> None:
    error = RuntimeError("the agent crashed for an unrelated reason")

    result = _agent_result_for_failure(error, session_id="session-1")

    assert result.error is not None
    assert "unrelated reason" in result.error
    assert result.session_id == "session-1"
