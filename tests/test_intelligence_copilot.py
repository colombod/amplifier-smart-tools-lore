import pytest

from lore.core.manifest import requirement_install_url
from lore.intelligence.copilot import CopilotIntelligence
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
