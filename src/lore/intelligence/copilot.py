"""GitHub Copilot SDK implementation of the intelligence interface."""

import asyncio
import contextlib
from importlib.metadata import version
import shutil
import subprocess
import time
from typing import Any

from copilot import CopilotClient, PermissionHandler, Tool, ToolInvocation, ToolResult
import jsonschema

from lore.core.manifest import requirement_install_url
from lore.intelligence.schemas import AgentRequest, AgentResult
from lore.schemas import LoreError

SUBMIT_TOOL = "submit"
MAX_INVALID_SUBMISSIONS = 2


class CopilotIntelligence:
    """Runs agents through a Copilot CLI runtime on this machine, signed in as the GitHub CLI's user."""

    def __init__(self) -> None:
        self.implementation = f"copilot-sdk {version('github-copilot-sdk')}"
        self._token: str | None = None

    def preflight(self) -> None:
        """Checked up front, cheaply: `gh` is installed and a token can be minted.

        Not checked here: whether the account that token belongs to actually has a Copilot
        subscription. There is no cheap way to learn that without a model call, so it is not
        probed for. When the account lacks one, it surfaces on first use instead: `run` raises
        a `LoreError` naming the `github-copilot-subscription` requirement.
        """
        self._github_token()

    def run(self, request: AgentRequest) -> AgentResult:
        working_directory = str(request.workspace.path) if request.workspace is not None else None
        client = CopilotClient(working_directory=working_directory, github_token=self._github_token())
        return asyncio.run(self._run(client, request))

    def _github_token(self) -> str:
        if self._token is not None:
            return self._token
        if shutil.which("gh") is None:
            raise LoreError(
                "Model-backed capabilities need the GitHub CLI. Install it "
                f"({requirement_install_url('gh')}) and sign in with `gh auth login`."
            )
        minted = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if minted.returncode != 0:
            raise LoreError(
                f"The GitHub CLI is not signed in: {minted.stderr.strip()} "
                "Run `gh auth login` with an account that has Copilot access."
            )
        self._token = minted.stdout.strip()
        return self._token

    async def _run(self, client: CopilotClient, request: AgentRequest) -> AgentResult:
        submitted: dict[str, Any] | None = None

        def capture(invocation: ToolInvocation) -> ToolResult:
            nonlocal submitted
            submitted = invocation.arguments
            return ToolResult(text_result_for_llm="Submission received.")

        session_options: dict[str, Any] = {
            "model": request.model,
            "reasoning_effort": request.reasoning_effort,
            "on_permission_request": PermissionHandler.approve_all,
            "skip_custom_instructions": True,
            "available_tools": [],
        }
        if request.workspace is not None:
            session_options["working_directory"] = str(request.workspace.path)
            session_options["available_tools"] = ["view", "grep", "bash"]
            if request.writable:
                # bash is not sandboxed to the workspace; the caller's prompt bounds the agent
                # and the caller validates before anything the agent wrote is kept.
                session_options["available_tools"] = [*session_options["available_tools"], "edit", "write"]
        if request.output_schema is not None:
            session_options["tools"] = [
                Tool(
                    name=SUBMIT_TOOL,
                    description="Submit your final answer. Call it exactly once, when you are done.",
                    parameters=request.output_schema,
                    handler=capture,
                    skip_permission=True,
                    is_terminal=True,
                )
            ]
            session_options["available_tools"] = [*session_options["available_tools"], SUBMIT_TOOL]
        deadline = time.monotonic() + request.timeout_seconds
        # Carried out of the try so the failure paths can name the session the caller could resume.
        session_id: str | None = None
        try:
            await client.start()
            if request.resume is not None:
                session = await client.resume_session(request.resume, **session_options)
            else:
                session = await client.create_session(**session_options)
            session_id = session.session_id
            prompt = request.prompt
            invalid = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    event = await session.send_and_wait(prompt, timeout=remaining)
                except TimeoutError:
                    await session.abort()
                    return AgentResult(
                        error=f"The agent did not finish within {request.timeout_seconds} seconds.",
                        session_id=session_id,
                    )
                text = str(getattr(event.data, "content", "") or "") if event is not None else ""
                if request.output_schema is None:
                    return AgentResult(text=text, session_id=session_id)
                problem = _submission_problem(submitted, request.output_schema)
                if problem is None:
                    return AgentResult(output=submitted, text=text, session_id=session_id)
                if invalid >= MAX_INVALID_SUBMISSIONS:
                    return AgentResult(
                        text=text,
                        error=f"No valid submission after {invalid} retries: {problem}",
                        session_id=session_id,
                    )
                invalid += 1
                submitted = None
                prompt = (
                    f"Your answer was not accepted: {problem}. "
                    f"Call the {SUBMIT_TOOL} tool now with an answer matching its schema."
                )
        except TimeoutError:
            return AgentResult(
                error=f"The agent did not finish within {request.timeout_seconds} seconds.", session_id=session_id
            )
        except Exception as error:  # an SDK or runtime failure is the caller's data, not a crash
            return _agent_result_for_failure(error, session_id)
        finally:
            with contextlib.suppress(Exception):
                await client.stop()


# Markers observed in the Copilot CLI/SDK's own failure text when the signed-in account has
# no usable Copilot entitlement, e.g. "Failed to fetch token entitlements: Server returned 403".
# The SDK does not raise a distinct exception type for this, so matching the message is a
# heuristic, not a guaranteed classification: anything that does not match is still reported
# through `AgentResult.error` as a plain agent-run failure.
_ENTITLEMENT_FAILURE_MARKERS = ("401", "403", "unauthorized", "forbidden", "entitlement")


def _is_entitlement_failure(error: Exception) -> bool:
    """Whether `error` looks like the signed-in `gh` account lacking a usable Copilot entitlement."""
    message = str(error).lower()
    return any(marker in message for marker in _ENTITLEMENT_FAILURE_MARKERS)


def _agent_result_for_failure(error: Exception, session_id: str | None) -> AgentResult:
    """What `_run` reports for a failure caught at its boundary.

    Raises `LoreError` for the narrow class of failure that means the account signed in to
    `gh` has no usable Copilot entitlement: an environment problem `preflight` could not check
    cheaply, the same category it already raises for. Anything else is a plain in-flight agent
    failure, reported through `AgentResult.error` as usual, never raised.
    """
    if _is_entitlement_failure(error):
        raise LoreError(
            f"GitHub Copilot rejected this request: {error}. The account signed in to `gh` needs "
            f"a Copilot subscription ({requirement_install_url('github-copilot-subscription')})."
        ) from error
    return AgentResult(error=f"{type(error).__name__}: {error}", session_id=session_id)


def _submission_problem(submitted: dict[str, Any] | None, schema: dict[str, Any]) -> str | None:
    if submitted is None:
        return f"the {SUBMIT_TOOL} tool was never called"
    try:
        jsonschema.validate(submitted, schema)
    except jsonschema.ValidationError as error:
        return f"the submission does not match the schema ({error.message})"
    return None
