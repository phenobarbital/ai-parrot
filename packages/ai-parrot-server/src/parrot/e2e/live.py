"""Live Google budget opt-in gating and the ``mcp-agent`` fixture entry point (FEAT-581, M6).

Two responsibilities, both scoped to the *optional* live tier (spec §2 "Live
Provider Budget"), never the deterministic gate:

1. **Opt-in gating and per-run budget resolution** (:func:`require_live_opt_in`,
   :func:`build_live_generation_budget`, :func:`build_live_client`) — pure,
   side-effect-free helpers safe to import and call directly from a unit test
   or from :mod:`parrot.e2e.targets.mcp` (the harness/parent process). No
   provider client is constructed until :func:`require_live_opt_in` has
   already succeeded, and :func:`require_live_opt_in` itself never touches a
   client, an env var it does not name, or the network.
2. **The ``mcp-agent`` child process entry point** (:func:`serve_live_agent_mount`,
   plus the ``python -m parrot.e2e.live`` CLI in :func:`_main`) — boots a real,
   budgeted :class:`~parrot.bots.agent.Agent` mounted at its own per-agent
   HTTP path via :class:`~parrot.mcp.agent_mount.AgentMCPMount`, exposing one
   fixture tool (``live_ask``) that delegates to that agent's real ``ask()``.
   Handshake/readiness (``initialize``/``tools/list``, both served over the
   unauthenticated-at-the-transport ``/info`` route and the per-agent PBAC
   route) never triggers generation; only an actual ``tools/call`` for
   ``live_ask`` constructs the agent and calls it.

Every symbol that would otherwise import ``parrot.bots.agent``,
``parrot.tools``, ``parrot.mcp.agent_mount``, ``parrot.mcp.oauth_server``,
``parrot.clients.factory`` or ``parrot.clients.google.budget`` at module
scope is deliberately deferred inside a function body. Importing anything
under ``parrot.tools`` transitively pulls in navconfig's app bootstrap,
which calls ``uvloop.install()`` and silently replaces the *global* asyncio
event loop policy out from under an already-running loop — corrupting the
very next ``asyncio.create_subprocess_exec`` call in the parent harness
process (the same hazard :mod:`parrot.e2e.targets.mcp` already documents and
avoids for its own ``mcp-toolkit``/``mcp-stdio`` adapters). Verified this is
not limited to ``parrot.tools``: ``parrot.clients`` (any submodule, e.g.
even the dependency-free ``parrot.clients.google.budget``) triggers the same
bootstrap through its own package ``__init__.py`` (``from .base import
...``), so it gets the identical treatment here. This module is therefore
always safe to import from the parent/harness process at module scope --
only calling :func:`build_live_generation_budget`, :func:`build_live_client`
or :func:`serve_live_agent_mount` (or running this module as ``python -m
parrot.e2e.live``, i.e. inside the freshly spawned ``mcp-agent`` child) ever
touches those heavier imports.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
import sys
from typing import TYPE_CHECKING, Any, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field

from parrot.e2e.errors import E2EBudgetError, E2EConfigError, E2EPrerequisiteError
from parrot.e2e.models import LiveBudget

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed
    from parrot.clients.base import AbstractClient
    from parrot.clients.google.budget import GenerationBudget

__all__ = [
    "LIVE_PROVIDER",
    "PARROT_TEST_E2E_ENV",
    "PARROT_TEST_REAL_LLM_ENV",
    "GOOGLE_API_KEY_ENV",
    "E2E_MODEL_ENV",
    "E2E_MAX_LLM_CALLS_ENV",
    "FORWARDED_ENV_VARS",
    "LIVE_API_KEY_ENV",
    "FIXTURE_AGENT_NAME",
    "FIXTURE_MARKER_VALUE",
    "AGENT_MOUNT_BASE_PATH",
    "LiveOptIn",
    "require_live_opt_in",
    "build_live_generation_budget",
    "build_live_client",
    "LiveAskArgs",
    "LiveAskResult",
    "serve_live_agent_mount",
]

logger = logging.getLogger(__name__)

#: The only live provider v1 accepts (spec §2 "Live Provider Budget": "V1
#: accepts Google model IDs only when the same guard can enforce the budget;
#: unsupported provider overrides are configuration errors, never fallbacks.").
LIVE_PROVIDER = "google"

#: Opt-in flags and credential env var names (spec §2).
PARROT_TEST_E2E_ENV = "PARROT_TEST_E2E"
PARROT_TEST_REAL_LLM_ENV = "PARROT_TEST_REAL_LLM"
GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"

#: Plan-default overrides, captured into evidence when present (spec §2).
E2E_MODEL_ENV = "E2E_MODEL"
E2E_MAX_LLM_CALLS_ENV = "E2E_MAX_LLM_CALLS"

#: Every env var the ``mcp-agent`` adapter must explicitly forward into its
#: child (the supervisor strips ``GOOGLE_API_KEY`` from every spawned child
#: as a credential var -- see ``E2ESupervisor._build_child_env`` -- so the
#: adapter must re-add it, and the other four opt-in/override vars, via its
#: own ``LaunchSpec.env`` for this module's own gate to see them at all).
FORWARDED_ENV_VARS: tuple[str, ...] = (
    PARROT_TEST_E2E_ENV,
    PARROT_TEST_REAL_LLM_ENV,
    GOOGLE_API_KEY_ENV,
    E2E_MODEL_ENV,
    E2E_MAX_LLM_CALLS_ENV,
)

#: The fixture's own private credential -- generated by the parent adapter,
#: never derived from a real user secret, and used only to authenticate the
#: adapter's own readiness/test HTTP calls against its own spawned child.
LIVE_API_KEY_ENV = "PARROT_E2E_LIVE_API_KEY"

#: The one agent this module ever mounts; matches ``AgentMCPMountConfig``'s
#: own default ``base_path`` (verified: ``parrot/mcp/config.py:46``), spelled
#: out here rather than imported so this constant stays available without
#: pulling in ``parrot.mcp.config`` at module scope.
FIXTURE_AGENT_NAME = "e2e-live-fixture"
AGENT_MOUNT_BASE_PATH = "/mcp/agents"

#: The exact marker value the fixture prompt asks the live agent to record.
#: Kept fixed (not per-call random) so evidence/log correlation stays simple;
#: the *effect* asserted is that the real live call actually invoked the
#: synthetic tool, not that the value is unpredictable.
FIXTURE_MARKER_VALUE = "e2e-live-smoke"

_FIXTURE_SYSTEM_PROMPT = (
    "You are a deterministic end-to-end test fixture with exactly one tool "
    "available: record_fixture_marker. When asked to record a marker, call "
    "record_fixture_marker exactly once with the exact marker value you were "
    "given as its `marker` argument, then reply with one short confirmation "
    "sentence. Never skip the tool call."
)


class LiveOptIn(BaseModel):
    """Captured, validated live-provider opt-in state for one E2E run.

    Attributes:
        model: The resolved ``"google:<model-id>"`` spec :func:`build_live_client`
            must resolve through :class:`~parrot.clients.factory.LLMFactory`.
        max_calls: The resolved generation-attempt ceiling for the run's shared
            :class:`~parrot.clients.google.budget.GenerationBudget`.
        env_overrides: The subset of :data:`E2E_MODEL_ENV`/:data:`E2E_MAX_LLM_CALLS_ENV`
            that were actually present and applied, verbatim -- persisted into
            evidence by the caller (never a fabricated/default value).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    max_calls: int = Field(gt=0)
    env_overrides: dict[str, str] = Field(default_factory=dict)


def require_live_opt_in(
    *, budget: Optional[LiveBudget] = None, env: Optional[Mapping[str, str]] = None
) -> LiveOptIn:
    """Validate live opt-in flags/credential and env overrides before any client exists.

    Must be called -- and must succeed -- before :func:`build_live_client` (or
    anything that would construct a provider client) ever runs. Every check
    here is pure env/string validation; nothing constructs a client, opens a
    socket, or imports a provider SDK.

    Args:
        budget: The plan's :class:`~parrot.e2e.models.LiveBudget` defaults
            (``model``/``max_calls``); a fresh default instance if omitted.
        env: The environment mapping to read. Defaults to ``os.environ`` --
            tests should pass an explicit mapping instead of mutating global
            process state.

    Returns:
        The validated :class:`LiveOptIn` (resolved model, resolved
        ``max_calls``, and the env overrides actually applied).

    Raises:
        E2EPrerequisiteError: If :data:`PARROT_TEST_E2E_ENV`,
            :data:`PARROT_TEST_REAL_LLM_ENV` is not exactly ``"1"``, or
            :data:`GOOGLE_API_KEY_ENV` is unset/empty.
        E2EConfigError: If :data:`E2E_MODEL_ENV` names a non-``google``
            provider, or :data:`E2E_MAX_LLM_CALLS_ENV` is not a positive
            integer.
    """
    environ = env if env is not None else os.environ
    budget = budget or LiveBudget()

    if environ.get(PARROT_TEST_E2E_ENV) != "1":
        raise E2EPrerequisiteError(
            f"{PARROT_TEST_E2E_ENV}=1 is required before any live provider client is constructed",
            reason_code="live_opt_in_missing",
        )
    if environ.get(PARROT_TEST_REAL_LLM_ENV) != "1":
        raise E2EPrerequisiteError(
            f"{PARROT_TEST_REAL_LLM_ENV}=1 is required before any live provider client is constructed",
            reason_code="live_opt_in_missing",
        )
    if not environ.get(GOOGLE_API_KEY_ENV):
        raise E2EPrerequisiteError(
            f"{GOOGLE_API_KEY_ENV} must be set before any live provider client is constructed",
            reason_code="live_credential_missing",
        )

    captured: dict[str, str] = {}
    model = budget.model
    model_override = environ.get(E2E_MODEL_ENV)
    if model_override:
        provider = model_override.split(":", 1)[0].strip().lower()
        if provider != LIVE_PROVIDER:
            raise E2EConfigError(
                f"{E2E_MODEL_ENV} override {model_override!r} names unsupported provider "
                f"{provider!r}; v1 only supports {LIVE_PROVIDER!r}",
                reason_code="unsupported_provider",
            )
        model = model_override
        captured[E2E_MODEL_ENV] = model_override

    max_calls = budget.max_calls
    calls_override = environ.get(E2E_MAX_LLM_CALLS_ENV)
    if calls_override is not None:
        try:
            parsed = int(calls_override)
        except ValueError as exc:
            raise E2EConfigError(
                f"{E2E_MAX_LLM_CALLS_ENV} override {calls_override!r} must be an integer",
                reason_code="invalid_override",
            ) from exc
        if parsed <= 0:
            raise E2EConfigError(
                f"{E2E_MAX_LLM_CALLS_ENV} override {calls_override!r} must be a positive integer",
                reason_code="invalid_override",
            )
        max_calls = parsed
        captured[E2E_MAX_LLM_CALLS_ENV] = calls_override

    return LiveOptIn(model=model, max_calls=max_calls, env_overrides=captured)


def build_live_generation_budget(opt_in: LiveOptIn, *, budget: Optional[LiveBudget] = None) -> "GenerationBudget":
    """Build the one shared :class:`GenerationBudget` for this run's live scenarios.

    One instance is meant to be constructed once per run and reused by every
    sequential live scenario/tool call against the same ``mcp-agent`` child
    (spec §2: "sequential live scenarios reuse it and cannot create fresh
    allowances per test") -- callers must not call this more than once per
    run.

    Args:
        opt_in: The already-validated :class:`LiveOptIn` (only ``max_calls``
            is consumed here; the byte/output/timeout ceilings come from
            ``budget``).
        budget: The plan's :class:`~parrot.e2e.models.LiveBudget` defaults; a
            fresh default instance if omitted.

    Returns:
        A fresh :class:`~parrot.clients.google.budget.GenerationBudget`.

    Raises:
        E2EPrerequisiteError: If ``ai-parrot-client-google`` is not installed.
    """
    try:
        from parrot.clients.google.budget import GenerationBudget as _GenerationBudget
    except ImportError as exc:
        raise E2EPrerequisiteError(
            "ai-parrot-client-google is not installed; the mcp-agent live target requires it",
            reason_code="target_adapter_unavailable",
        ) from exc
    budget = budget or LiveBudget()
    return _GenerationBudget(
        max_calls=opt_in.max_calls,
        max_output_tokens=budget.max_output_tokens,
        max_request_bytes=budget.max_request_bytes,
        timeout_s=budget.timeout_s,
    )


def build_live_client(opt_in: LiveOptIn, generation_budget: "GenerationBudget") -> "AbstractClient":
    """Resolve the pinned live model through ``LLMFactory`` with the shared budget wired in.

    Must only be called after :func:`require_live_opt_in` succeeded. Never
    calls the provider SDK itself -- construction alone makes no network call
    (spec: "handshake/readiness performs no generation").

    Args:
        opt_in: The already-validated :class:`LiveOptIn` naming the resolved
            ``"google:<model-id>"`` spec.
        generation_budget: This run's shared
            :class:`~parrot.clients.google.budget.GenerationBudget`.

    Returns:
        The constructed, budgeted :class:`~parrot.clients.base.AbstractClient`.

    Raises:
        ImportError: If ``opt_in.model``'s provider is not installed.
    """
    from parrot.clients.factory import LLMFactory

    return LLMFactory.create(opt_in.model, generation_budget=generation_budget)


class LiveAskArgs(BaseModel):
    """Arguments for the ``live_ask`` fixture MCP tool."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(
        default=f"Call record_fixture_marker with marker={FIXTURE_MARKER_VALUE!r}.",
        description="Prompt sent to the real, budgeted live agent.",
    )


class LiveAskResult(BaseModel):
    """Observable, schema-validated result of one ``live_ask`` invocation.

    Deliberately structured, never prose: the assertion this fixture exists
    to support is "the real live call invoked the synthetic tool", not any
    judgement of the model's free-form reply text.

    Attributes:
        tool_called: Whether ``record_fixture_marker`` was actually invoked
            during this ``ask()`` call.
        marker: The marker value the synthetic tool recorded, if any.
        model: The ``"google:<model-id>"`` spec actually used.
        calls_used: The shared budget's cumulative reserved-call count after
            this call (spec: run-scoped, shared across sequential scenarios).
    """

    model_config = ConfigDict(extra="forbid")

    tool_called: bool
    marker: Optional[str] = None
    model: str
    calls_used: int


async def _wait_for_shutdown() -> None:
    """Block until SIGINT or SIGTERM, then return -- always removing installed handlers.

    Mirrors ``parrot.mcp.cli._wait_for_shutdown_signal``'s own HTTP keep-alive
    fix (M1) for this module's own standalone aiohttp server.
    """
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    installed: list[signal.Signals] = []

    def _handle_signal(sig: signal.Signals) -> None:
        logger.info("mcp-agent live fixture received signal %s, shutting down", sig.name)
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal, sig)
        except (NotImplementedError, RuntimeError):
            continue
        installed.append(sig)

    try:
        await stop_event.wait()
    finally:
        for sig in installed:
            with contextlib.suppress(ValueError):
                loop.remove_signal_handler(sig)


async def serve_live_agent_mount(*, host: str, port: int, server_name: str, api_key: str) -> None:
    """Boot the standalone ``mcp-agent`` HTTP server -- the child process entry point.

    Mounts exactly one agent (:data:`FIXTURE_AGENT_NAME`) at
    ``{host}:{port}{AGENT_MOUNT_BASE_PATH}/{FIXTURE_AGENT_NAME}`` via
    :class:`~parrot.mcp.agent_mount.AgentMCPMount`, API-key authenticated
    with the single ``api_key`` the spawning adapter generated. The mounted
    agent exposes exactly one MCP tool, ``live_ask``
    (:class:`LiveAskArgs`/:class:`LiveAskResult`), whose handler:

    - Lazily constructs the real, budgeted :class:`~parrot.bots.agent.Agent`
      on first call only (never at server startup, never at handshake) --
      re-validating opt-in via :func:`require_live_opt_in` first.
    - Shares one :class:`~parrot.clients.google.budget.GenerationBudget`
      across every subsequent ``live_ask`` call this process serves (spec:
      one run-scoped budget for all sequential live scenarios).
    - Converts a :class:`~parrot.clients.google.budget.GenerationBudgetExceeded`
      into :class:`~parrot.e2e.errors.E2EBudgetError` at this harness
      boundary (the two packages do not share an exception hierarchy).

    Runs until SIGINT/SIGTERM (:func:`_wait_for_shutdown`), then cleans up
    the aiohttp runner.

    Args:
        host: Loopback host to bind.
        port: Loopback port to bind.
        server_name: The value this run's ``/info`` responses must echo
            (identity check consumed by the adapter's own ``ready()``).
        api_key: The fixed API key the spawning adapter generated; the only
            credential this server's single mounted agent accepts.
    """
    from aiohttp import web
    from parrot.bots.agent import Agent
    from parrot.clients.google.budget import GenerationBudgetExceeded
    from parrot.mcp.agent_mount import AgentMCPMount
    from parrot.mcp.agent_tools import mcp_tool
    from parrot.mcp.config import AgentMCPMountConfig, AuthMethod, MCPServerConfig
    from parrot.mcp.oauth_server import APIKeyStore
    from parrot.tools import tool

    fixture_markers: list[str] = []

    @tool
    def record_fixture_marker(marker: str) -> dict:
        """Record a fixture marker string exactly once (E2E live-tool smoke)."""
        fixture_markers.append(marker)
        return {"recorded": marker}

    class _FixtureToolManager:
        """Duck-typed empty ``tool_manager`` -- the fixture host owns no other tools."""

        def list_tools(self) -> list[str]:
            return []

        def get_tool(self, name: str) -> None:
            return None

    class _FixtureBotManager:
        """Duck-typed ``BotManager`` -- ``AgentMCPMount`` only ever calls ``get_bots()``."""

        def __init__(self, bots: dict[str, Any]) -> None:
            self._bots = bots

        def get_bots(self) -> dict[str, Any]:
            return dict(self._bots)

    async def _allow_all(pctx: Any, resource: str, required_permissions: Any) -> bool:
        """Permissive PBAC resolver: the fixture's only gate is its API key."""
        return True

    class _LiveFixtureAgentHost:
        """The one mounted "agent": exposes ``live_ask``, delegating to a real inner Agent."""

        name = FIXTURE_AGENT_NAME

        def __init__(self) -> None:
            self.tool_manager = _FixtureToolManager()
            self._agent: Optional[Agent] = None
            self._budget: Optional["GenerationBudget"] = None
            self._opt_in: Optional[LiveOptIn] = None

        def _ensure_agent(self) -> tuple[Agent, "GenerationBudget", LiveOptIn]:
            if self._agent is None:
                opt_in = require_live_opt_in()
                budget = build_live_generation_budget(opt_in)
                client = build_live_client(opt_in, budget)
                self._agent = Agent(
                    name="e2e-live-fixture-agent",
                    agent_id="e2e-live-fixture-agent",
                    llm=client,
                    tools=[record_fixture_marker],
                    use_tools=True,
                    system_prompt=_FIXTURE_SYSTEM_PROMPT,
                )
                self._budget = budget
                self._opt_in = opt_in
            return self._agent, self._budget, self._opt_in

        @mcp_tool(
            name="live_ask",
            description="Ask the real, budgeted live Google agent to invoke a synthetic fixture tool.",
            args_schema=LiveAskArgs,
            returns=LiveAskResult,
            scope="e2e:live",
        )
        async def live_ask(self, prompt: str) -> dict:
            """Delegate to the real inner agent's ``ask()``; report the observed tool effect."""
            agent, budget, opt_in = self._ensure_agent()
            fixture_markers.clear()
            try:
                await agent.ask(prompt)
            except GenerationBudgetExceeded as exc:
                raise E2EBudgetError(str(exc), reason_code=exc.reason_code) from exc
            marker = fixture_markers[-1] if fixture_markers else None
            return LiveAskResult(
                tool_called=bool(fixture_markers),
                marker=marker,
                model=opt_in.model,
                calls_used=budget.calls_used,
            ).model_dump()

    api_key_store = APIKeyStore()
    api_key_store.add_key(api_key, user_id="e2e-live", scopes=["e2e:live"])
    auth_template = MCPServerConfig(name=server_name, auth_method=AuthMethod.API_KEY, api_key_store=api_key_store)
    bot_manager = _FixtureBotManager({FIXTURE_AGENT_NAME: _LiveFixtureAgentHost()})
    mount_config = AgentMCPMountConfig(
        agents=[FIXTURE_AGENT_NAME],
        resource_server_url=f"http://{host}:{port}{AGENT_MOUNT_BASE_PATH}/{FIXTURE_AGENT_NAME}",
        default_tenant_id="e2e-live",
    )
    mount = AgentMCPMount(bot_manager, mount_config, pbac_resolver=_allow_all, auth_template=auth_template)
    app = web.Application()
    mount.setup(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info("mcp-agent live fixture server listening on %s:%s (name=%s)", host, port, server_name)
    try:
        await _wait_for_shutdown()
    finally:
        await runner.cleanup()


def _main(argv: Optional[list[str]] = None) -> int:
    """``python -m parrot.e2e.live`` entry point -- boots :func:`serve_live_agent_mount`.

    Args:
        argv: Explicit argv for testing; ``sys.argv[1:]`` if omitted.

    Returns:
        Process exit code: ``0`` on a clean shutdown, ``2`` if
        :data:`LIVE_API_KEY_ENV` was not set by the spawning adapter.
    """
    parser = argparse.ArgumentParser(prog="python -m parrot.e2e.live")
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--server-name", required=True)
    args = parser.parse_args(argv)

    api_key = os.environ.get(LIVE_API_KEY_ENV)
    if not api_key:
        print(f"{LIVE_API_KEY_ENV} must be set by the spawning mcp-agent adapter", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        serve_live_agent_mount(host=args.host, port=args.port, server_name=args.server_name, api_key=api_key)
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    sys.exit(_main())
