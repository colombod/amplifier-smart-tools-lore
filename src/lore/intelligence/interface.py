"""The contract every model-backed capability runs through, so the implementation is swappable."""

from typing import Protocol

from lore.intelligence.schemas import AgentRequest, AgentResult


class Intelligence(Protocol):
    """Runs agents against models; the library depends on this contract, never on an SDK."""

    implementation: str

    def preflight(self) -> None:
        """Raise LoreError naming exactly what to configure when the implementation cannot run."""
        ...

    def run(self, request: AgentRequest) -> AgentResult:
        """Run one agent to completion.

        When the request carries an output schema, the result either holds a conforming
        `output` or an `error`; retry mechanics are the implementation's own business. The
        one exception is a prerequisite failure `preflight` could not check cheaply up
        front (e.g. the account lacks an entitlement that only a model call reveals): that
        raises `LoreError`, the same as `preflight` itself, rather than hiding an
        environment problem inside `error`.
        """
        ...


def default_intelligence() -> Intelligence:
    from lore.intelligence.copilot import CopilotIntelligence

    return CopilotIntelligence()
