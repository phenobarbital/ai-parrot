"""`mcp-toolkit` (HTTP) and `mcp-stdio` target adapters (FEAT-581, M4).

Implements two of spec §3 "M4"'s ``parrot.e2e.targets.mcp`` factories, per
spec §2 "Target and Authentication Design":

    mcp-toolkit | Real working-memory toolkit over HTTP. Poll configured
    <base_path>/info, then initialize/list/call; put/get/drop fixed data
    scoped to the run. No exact tool-count assertion.

    mcp-stdio | Run existing mcp-local entry point; validate initialize,
    notification, list/call, stdout JSON purity and EOF shutdown.
    Supervisor retains pipes.

Both adapters launch the REAL, already-shipped ``parrot`` CLI entry points
(``parrot mcp serve`` / ``parrot mcp-local``) as a child process — never a
bespoke inlined script standing in for one — via the same real-subprocess
bootstrap technique ``tests/mcp/test_mcp_local_e2e.py`` already uses:
``sys.executable -c "from parrot.cli import cli; cli(...)"``, never the
(possibly stale) installed ``parrot`` console script on ``$PATH``. Neither
adapter spawns anything itself: :meth:`prepare` only ever returns a
validated :class:`~parrot.e2e.targets.base.LaunchSpec`; the
:class:`~parrot.e2e.supervisor.E2ESupervisor` (M3) is the sole spawner.

The third ``mcp-agent`` kind this module's factory registry key maps to
(``parrot.e2e.targets._ADAPTER_REGISTRY["mcp-agent"]``) is the M6 deliverable
added by this ``MODIFY`` (TASK-3540): :func:`build_mcp_agent_adapter` spawns
the real, budgeted live-agent fixture server (``python -m parrot.e2e.live``,
:mod:`parrot.e2e.live`) that mounts one fixture tool delegating to a real
:class:`~parrot.bots.agent.Agent`'s ``ask()`` on its own per-agent HTTP path
(:class:`~parrot.mcp.agent_mount.AgentMCPMount`). Exactly like the two
adapters above, :meth:`_MCPAgentAdapter.prepare` never imports
``parrot.e2e.live``'s heavier, function-scoped dependencies
(``parrot.bots.agent``/``parrot.tools``/``parrot.mcp.agent_mount``) in this
(the caller's own) process — only the child, spawned fresh by the
supervisor, ever does. Live opt-in (``PARROT_TEST_E2E``/``PARROT_TEST_REAL_LLM``/
``GOOGLE_API_KEY``) and any ``E2E_MODEL``/``E2E_MAX_LLM_CALLS`` override are
gated inside the child, by the fixture tool itself, on first call only —
this adapter's own ``prepare()``/``ready()`` never construct a provider
client and never perform generation (spec: "handshake/readiness performs no
generation").

Neither adapter ever assumes :attr:`parrot.e2e.models.RunState.endpoint` is
populated: per :mod:`parrot.e2e.supervisor`'s own module docstring, that
field is always persisted as ``None`` (its population is explicitly left to
this M4 layer). The HTTP adapter therefore tracks its own
``run_id -> (host, port, expected server name)`` mapping, set in
:meth:`prepare` and consulted in :meth:`ready` — never a bare "the port
answered" health check: a pre-existing, unrelated service happening to
listen on the same loopback port is rejected by checking that ``/info``'s
``name`` field matches the server this adapter itself configured and
launched (spec §2: "Do not mistake a pre-existing service's health response
for the child: validate child liveness and target identity/handshake.").

The stdio adapter's :meth:`_MCPStdioAdapter.ready` never assumes an HTTP
endpoint either: a `stdio` launch has none, and this module never invents
one. Protocol-level readiness (``initialize``/``notifications/initialized``/
``tools/list``/``tools/call``, stdout JSON purity, EOF shutdown) is verified
out-of-band through the supervisor's own stdio mediation
(:meth:`parrot.e2e.supervisor.E2ESupervisor.request_stdio`) — per that
module's own docstring, the real :meth:`E2ESupervisor._await_ready` never
even calls :meth:`TargetAdapter.ready` for a ``stdio`` launch (liveness
alone is supervisor-level readiness for a retained-pipe target); this
method exists to satisfy the :class:`TargetAdapter` Protocol for any other
caller and intentionally does no I/O of its own.
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
import yaml

from parrot.e2e import live as e2e_live
from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EConfigError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.targets.base import LaunchSpec

__all__ = ["build_mcp_toolkit_adapter", "build_mcp_stdio_adapter", "build_mcp_agent_adapter"]

logger = logging.getLogger(__name__)

# Boots the real `parrot` CLI from inside the child -- the same technique
# `tests/mcp/test_mcp_local_e2e.py` already uses for a real-subprocess MCP
# acceptance test, never the (possibly stale) installed `parrot` console
# script. `sys.argv[1:]` (everything appended to `LaunchSpec.argv` after
# this source string) becomes the CLI's own argv via `cli(prog_name=...)`.
_CLI_BOOTSTRAP = "from parrot.cli import cli\ncli(prog_name='parrot')\n"

# `_run_standalone_server()` (parrot.mcp.cli) builds its `MCPServerConfig`
# without ever overriding `base_path`, so the served route set is always
# this dataclass field's own default (`parrot.mcp.config.MCPServerConfig.
# base_path = "/mcp"`, verified directly against a real spawned child --
# `POST /` and `GET /info` both 404) -- never the bare `/`/`/info` a naive
# reading of spec §2's `<base_path>/info` might suggest.
_HTTP_BASE_PATH = "/mcp"

# Spec §2: "mcp-toolkit | Real working-memory toolkit over HTTP." — fixed,
# never a caller-chosen class; this module hard-codes the one toolkit the
# spec names for both `mcp-toolkit` and `mcp-stdio`.
_TOOLKIT_MODULE = "parrot.tools.working_memory.tool"
_TOOLKIT_CLASS = "WorkingMemoryToolkit"
_TOOLKIT_SECTION_NAME = "memory"

# `mcp-toolkit` alone accepts an explicit `port` override (deterministic
# port selection for tests that must control what a decoy/unrelated service
# binds to); `mcp-stdio` has no HTTP surface and accepts no options at all.
_HTTP_SUPPORTED_OPTIONS = frozenset({"port"})
_STDIO_SUPPORTED_OPTIONS: frozenset[str] = frozenset()

_READY_HTTP_TIMEOUT_S = 2.0


def _reject_unsupported_options(config: TargetConfig, *, supported: frozenset[str], kind: str) -> None:
    """Reject any ``config.options`` key this target kind does not recognize.

    Args:
        config: The target configuration to validate.
        supported: The option keys this target kind accepts.
        kind: This target kind's name (for the error message).

    Raises:
        E2EConfigError: If ``config.options`` contains an unsupported key.
    """
    unsupported = sorted(set(config.options) - supported)
    if unsupported:
        raise E2EConfigError(
            f"{kind!r} target does not support option key(s) {unsupported}; supported: {sorted(supported)}",
            reason_code="unsupported_option",
        )


def _require_kind(config: TargetConfig, expected: str) -> None:
    """Reject a :class:`TargetConfig` whose ``kind`` disagrees with this adapter.

    Args:
        config: The target configuration to validate.
        expected: The one ``kind`` value this adapter handles.

    Raises:
        E2EConfigError: If ``config.kind != expected``.
    """
    if config.kind != expected:
        raise E2EConfigError(
            f"this adapter only handles kind={expected!r}, got {config.kind!r}", reason_code="kind_mismatch"
        )


def _free_loopback_port() -> int:
    """Allocate one currently-free loopback TCP port.

    Returns:
        A port number free at the moment of the call (spec §2: "Bind
        loopback; allocate ports per run."). A subsequent bind race is
        handled by the supervisor's own verified-EADDRINUSE retry, not by
        this helper.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


# ---------------------------------------------------------------------------
# mcp-stdio
# ---------------------------------------------------------------------------


class _MCPStdioAdapter:
    """`mcp-stdio` target: the real `parrot mcp-local <name>` entry point.

    Supervisor retains this launch's stdio pipes (spec §2); protocol
    readiness (``initialize``/notification/``list``/``call``, stdout JSON
    purity, EOF shutdown) is validated by the caller through
    :meth:`parrot.e2e.supervisor.E2ESupervisor.request_stdio`, not by this
    class.
    """

    def __init__(self) -> None:
        """Initialize the adapter."""
        self.logger = logging.getLogger(__name__)

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Return the `parrot mcp-local` launch for the fixed working-memory toolkit.

        Args:
            config: Must have ``kind == "mcp-stdio"``; accepts no options.
            run_id: The run's stable ID (used to place this run's private
                toolkit config file).
            worktree: The owning worktree root.

        Returns:
            A ``stdio=True`` :class:`LaunchSpec` invoking
            ``parrot mcp-local memory --config <run-private-config>``.

        Raises:
            E2EConfigError: If ``config.kind`` disagrees, or ``config.options``
                carries an unsupported key.

        Note:
            This method deliberately never imports
            ``parrot.tools.working_memory.tool`` in this (the caller's own)
            process: importing anything under ``parrot.tools`` transitively
            pulls in navconfig's app bootstrap, which calls
            ``uvloop.install()`` -- silently replacing the *global* asyncio
            event loop policy out from under an already-running loop and
            breaking the very next ``asyncio.create_subprocess_exec`` call
            (verified directly: it corrupts
            :meth:`parrot.e2e.watchdog.spawn_watchdog`'s own subprocess spawn
            when done from inside a running :class:`E2ESupervisor.start`
            call). The fixed toolkit's importability is proven instead by
            the child actually starting -- a missing/broken toolkit surfaces
            as this run's own readiness failure, in the isolated child
            process, where this hazard cannot leak back into the caller.
        """
        _require_kind(config, "mcp-stdio")
        _reject_unsupported_options(config, supported=_STDIO_SUPPORTED_OPTIONS, kind="mcp-stdio")

        run_directory = e2e_state.run_dir(run_id, worktree=worktree)
        config_path = run_directory / "mcp-toolkits.yaml"
        toolkit_class_path = f"{_TOOLKIT_MODULE}.{_TOOLKIT_CLASS}"
        config_path.write_text(
            yaml.safe_dump(
                {"toolkits": {_TOOLKIT_SECTION_NAME: {"class": toolkit_class_path, "kwargs": {}}}},
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        argv = [
            sys.executable,
            "-c",
            _CLI_BOOTSTRAP,
            "mcp-local",
            _TOOLKIT_SECTION_NAME,
            "--config",
            str(config_path),
        ]
        self.logger.debug("mcp-stdio prepare: run_id=%s config=%s", run_id, config_path)
        return LaunchSpec(argv=argv, cwd=worktree, stdio=True)

    async def ready(self, state: RunState) -> bool:
        """Always ``True`` — protocol readiness is verified via ``request_stdio``.

        A `stdio` launch has no HTTP endpoint, and ``state.endpoint`` is
        never populated for one (spec/supervisor contract) — this method
        never assumes otherwise. The real
        :meth:`parrot.e2e.supervisor.E2ESupervisor._await_ready` never even
        calls this for a ``stdio`` launch (liveness alone is its own
        supervisor-level readiness signal for a retained-pipe target); this
        implementation exists only to satisfy the :class:`TargetAdapter`
        Protocol for any other caller.

        Args:
            state: The run's current state (unused).

        Returns:
            ``True``, unconditionally.
        """
        return True


def build_mcp_stdio_adapter() -> _MCPStdioAdapter:
    """Build the `mcp-stdio` target adapter.

    Returns:
        A fresh :class:`_MCPStdioAdapter`.
    """
    return _MCPStdioAdapter()


# ---------------------------------------------------------------------------
# mcp-toolkit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ToolkitEndpoint:
    """This adapter's own record of one run's HTTP endpoint and identity.

    Attributes:
        host: The loopback host the child was told to bind.
        port: The loopback port the child was told to bind.
        expected_name: The MCP server name this run's child was configured
            with — the value :meth:`_MCPToolkitAdapter.ready` requires
            ``GET <base_url>/info`` to echo back before trusting anything
            else on this port.
    """

    host: str
    port: int
    expected_name: str


class _MCPToolkitAdapter:
    """`mcp-toolkit` target: the real working-memory toolkit over HTTP.

    Tracks its own ``run_id -> _ToolkitEndpoint`` mapping (set in
    :meth:`prepare`, consulted in :meth:`ready`) since
    :attr:`parrot.e2e.models.RunState.endpoint` is never populated by the
    supervisor (M3) for any target kind.
    """

    def __init__(self) -> None:
        """Initialize the adapter with an empty per-run endpoint table."""
        self.logger = logging.getLogger(__name__)
        self._endpoints: dict[str, _ToolkitEndpoint] = {}

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Return the `parrot mcp serve` HTTP launch for the fixed working-memory toolkit.

        Args:
            config: Must have ``kind == "mcp-toolkit"``. ``options["port"]``
                (a positive ``int``) overrides the default free-port
                allocation; every other option key is rejected.
            run_id: The run's stable ID — used both to name this run's
                private config file and as this run's own MCP server name
                (the value :meth:`ready` cross-checks against ``/info``).
            worktree: The owning worktree root.

        Returns:
            A ``stdio=False`` :class:`LaunchSpec` invoking
            ``parrot mcp serve <run-private-config> --transport http --port <port>``.

        Raises:
            E2EConfigError: If ``config.kind`` disagrees, ``config.options``
                carries an unsupported key, or ``options["port"]`` is not a
                positive integer.

        Note:
            This method deliberately never imports
            ``parrot.tools.working_memory.tool`` in this (the caller's own)
            process — see :meth:`_MCPStdioAdapter.prepare`'s own note on the
            same hazard (importing anything under ``parrot.tools`` calls
            ``uvloop.install()`` and corrupts the caller's already-running
            event loop). The fixed toolkit's importability is proven by the
            child actually starting, in its own isolated process.
        """
        _require_kind(config, "mcp-toolkit")
        _reject_unsupported_options(config, supported=_HTTP_SUPPORTED_OPTIONS, kind="mcp-toolkit")

        port = self._resolve_port(config)
        server_name = f"e2e-mcp-toolkit-{run_id}"

        run_directory = e2e_state.run_dir(run_id, worktree=worktree)
        config_path = run_directory / "mcp-server.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "name": server_name,
                    "description": "FEAT-581 E2E fixture toolkit HTTP MCP server",
                    "tools": [{"class": _TOOLKIT_CLASS, "module": _TOOLKIT_MODULE}],
                },
                default_flow_style=False,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

        argv = [
            sys.executable,
            "-c",
            _CLI_BOOTSTRAP,
            "mcp",
            "serve",
            str(config_path),
            "--transport",
            "http",
            "--port",
            str(port),
        ]
        self._endpoints[run_id] = _ToolkitEndpoint(host="127.0.0.1", port=port, expected_name=server_name)
        self.logger.debug("mcp-toolkit prepare: run_id=%s port=%s name=%s", run_id, port, server_name)
        return LaunchSpec(argv=argv, cwd=worktree, stdio=False)

    @staticmethod
    def _resolve_port(config: TargetConfig) -> int:
        """Resolve this launch's loopback port from ``config.options`` or allocate one.

        Args:
            config: The target configuration (already option-validated).

        Returns:
            The port to bind: ``options["port"]`` if given, else a freshly
            allocated free loopback port.

        Raises:
            E2EConfigError: If ``options["port"]`` is present but is not a
                positive ``int``.
        """
        port_option = config.options.get("port")
        if port_option is None:
            return _free_loopback_port()
        if isinstance(port_option, bool) or not isinstance(port_option, int) or port_option <= 0:
            raise E2EConfigError(
                f"options['port'] must be a positive integer, got {port_option!r}", reason_code="invalid_option"
            )
        return port_option

    async def ready(self, state: RunState) -> bool:
        """Poll ``<base_url>/info`` then ``initialize``/``tools/list`` (spec §2).

        Never trusts a bare HTTP 200: a pre-existing, unrelated service
        happening to already listen on this run's loopback port is
        rejected unless ``/info`` echoes back exactly the server name this
        adapter itself configured in :meth:`prepare` (spec §2: "Do not
        mistake a pre-existing service's health response for the child").

        Args:
            state: The run's current state; only ``state.run_id`` is used
                (never ``state.endpoint``, which this target kind's
                supervisor leaves ``None``).

        Returns:
            ``True`` once ``/info`` identifies this run's own server AND a
            live JSON-RPC ``initialize`` and ``tools/list`` round-trip both
            succeed; ``False`` while still starting, on any connection
            error/timeout, or against an identity mismatch.
        """
        endpoint = self._endpoints.get(state.run_id)
        if endpoint is None:
            self.logger.debug("mcp-toolkit ready: no recorded endpoint for run_id=%s", state.run_id)
            return False

        base_url = f"http://{endpoint.host}:{endpoint.port}"
        timeout = aiohttp.ClientTimeout(total=_READY_HTTP_TIMEOUT_S)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{base_url}{_HTTP_BASE_PATH}/info") as response:
                    if response.status != 200:
                        return False
                    info = await response.json()
                if not isinstance(info, dict) or info.get("name") != endpoint.expected_name:
                    self.logger.debug(
                        "mcp-toolkit ready: /info identity mismatch for run_id=%s: %r", state.run_id, info
                    )
                    return False
                if info.get("transport") != "http":
                    return False

                init_result = await self._json_rpc(session, base_url, "initialize", request_id=1)
                if init_result is None or "result" not in init_result:
                    return False

                list_result = await self._json_rpc(session, base_url, "tools/list", request_id=2)
                if list_result is None:
                    return False
                tools = (list_result.get("result") or {}).get("tools")
                return isinstance(tools, list)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.logger.debug("mcp-toolkit ready: transient error for run_id=%s: %s", state.run_id, exc)
            return False

    @staticmethod
    async def _json_rpc(
        session: aiohttp.ClientSession, base_url: str, method: str, *, request_id: int
    ) -> Optional[dict]:
        """Send one JSON-RPC 2.0 request to the target's base route and return its body.

        Args:
            session: The open client session to send through.
            base_url: This run's ``http://host:port`` base URL.
            method: The JSON-RPC method name.
            request_id: The JSON-RPC request ID.

        Returns:
            The parsed JSON-RPC response body, or ``None`` on a non-200 status.
        """
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {}}
        async with session.post(f"{base_url}{_HTTP_BASE_PATH}", json=payload) as response:
            if response.status != 200:
                return None
            return await response.json()


def build_mcp_toolkit_adapter() -> _MCPToolkitAdapter:
    """Build the `mcp-toolkit` target adapter.

    Returns:
        A fresh :class:`_MCPToolkitAdapter` with an empty endpoint table.
    """
    return _MCPToolkitAdapter()


# ---------------------------------------------------------------------------
# mcp-agent
# ---------------------------------------------------------------------------

#: ``mcp-agent`` alone accepts an explicit `port` override, mirroring
#: `mcp-toolkit` (deterministic port selection for a decoy/unrelated service
#: test); it accepts no other option key.
_AGENT_SUPPORTED_OPTIONS = frozenset({"port"})


@dataclass(frozen=True)
class _AgentEndpoint:
    """This adapter's own record of one run's HTTP endpoint and credential.

    Attributes:
        host: The loopback host the child was told to bind.
        port: The loopback port the child was told to bind.
        expected_name: The MCP server name this run's child was configured
            with -- the value :meth:`_MCPAgentAdapter.ready` requires
            ``GET <base_url>/mcp/agents/<agent_name>/info`` to echo back
            before trusting anything else on this port.
        api_key: The fixed, run-private API key this adapter generated and
            forwarded to the child (spec §2 identity/auth design) -- the
            only credential the child's single mounted agent accepts.
        agent_name: The one agent name the child mounted
            (:data:`parrot.e2e.live.FIXTURE_AGENT_NAME`).
    """

    host: str
    port: int
    expected_name: str
    api_key: str
    agent_name: str


class _MCPAgentAdapter:
    """`mcp-agent` target: a real, budgeted live-agent fixture over its per-agent HTTP path.

    Spawns ``python -m parrot.e2e.live`` (:mod:`parrot.e2e.live`), which
    mounts exactly one fixture agent
    (:data:`parrot.e2e.live.FIXTURE_AGENT_NAME`) via
    :class:`~parrot.mcp.agent_mount.AgentMCPMount`, API-key authenticated
    with a per-run credential this adapter itself generates and forwards
    (never a real user secret). Tracks its own ``run_id -> _AgentEndpoint``
    mapping since :attr:`parrot.e2e.models.RunState.endpoint` is never
    populated by the supervisor (M3) for any target kind -- identical
    rationale to :class:`_MCPToolkitAdapter`.

    Live provider opt-in (``PARROT_TEST_E2E``/``PARROT_TEST_REAL_LLM``/
    ``GOOGLE_API_KEY``) is gated inside the child, by the mounted fixture
    tool itself, on its first ``tools/call`` only -- never by this class.
    :meth:`prepare` and :meth:`ready` never construct a provider client and
    never perform generation.
    """

    def __init__(self) -> None:
        """Initialize the adapter with an empty per-run endpoint table."""
        self.logger = logging.getLogger(__name__)
        self._endpoints: dict[str, _AgentEndpoint] = {}

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Return the `python -m parrot.e2e.live` launch for the fixture live agent.

        Args:
            config: Must have ``kind == "mcp-agent"``. ``options["port"]``
                (a positive ``int``) overrides the default free-port
                allocation; every other option key is rejected.
            run_id: The run's stable ID -- used as this run's own MCP server
                name (the value :meth:`ready` cross-checks against ``/info``).
            worktree: The owning worktree root.

        Returns:
            A ``stdio=False`` :class:`LaunchSpec` invoking
            ``python -m parrot.e2e.live --host 127.0.0.1 --port <port>
            --server-name <name>``, with :data:`parrot.e2e.live.LIVE_API_KEY_ENV`
            and every :data:`parrot.e2e.live.FORWARDED_ENV_VARS` entry present
            in this process's own environment carried into the child's
            ``env`` (the supervisor strips ``GOOGLE_API_KEY`` as a credential
            var from every spawned child by default; this adapter must
            explicitly re-add it for its own live opt-in gate to see it).

        Raises:
            E2EConfigError: If ``config.kind`` disagrees, ``config.options``
                carries an unsupported key, or ``options["port"]`` is not a
                positive integer.
        """
        _require_kind(config, "mcp-agent")
        _reject_unsupported_options(config, supported=_AGENT_SUPPORTED_OPTIONS, kind="mcp-agent")

        port = self._resolve_port(config)
        server_name = f"e2e-mcp-agent-{run_id}"
        api_key = f"e2e-live-{secrets.token_urlsafe(24)}"

        env: dict[str, str] = {e2e_live.LIVE_API_KEY_ENV: api_key}
        for name in e2e_live.FORWARDED_ENV_VARS:
            value = os.environ.get(name)
            if value is not None:
                env[name] = value

        argv = [
            sys.executable,
            "-m",
            "parrot.e2e.live",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--server-name",
            server_name,
        ]
        self._endpoints[run_id] = _AgentEndpoint(
            host="127.0.0.1",
            port=port,
            expected_name=server_name,
            api_key=api_key,
            agent_name=e2e_live.FIXTURE_AGENT_NAME,
        )
        self.logger.debug("mcp-agent prepare: run_id=%s port=%s name=%s", run_id, port, server_name)
        return LaunchSpec(argv=argv, cwd=worktree, stdio=False, env=env)

    @staticmethod
    def _resolve_port(config: TargetConfig) -> int:
        """Resolve this launch's loopback port from ``config.options`` or allocate one.

        Args:
            config: The target configuration (already option-validated).

        Returns:
            The port to bind: ``options["port"]`` if given, else a freshly
            allocated free loopback port.

        Raises:
            E2EConfigError: If ``options["port"]`` is present but is not a
                positive ``int``.
        """
        port_option = config.options.get("port")
        if port_option is None:
            return _free_loopback_port()
        if isinstance(port_option, bool) or not isinstance(port_option, int) or port_option <= 0:
            raise E2EConfigError(
                f"options['port'] must be a positive integer, got {port_option!r}", reason_code="invalid_option"
            )
        return port_option

    async def ready(self, state: RunState) -> bool:
        """Poll ``<base_url>/mcp/agents/<agent>/info`` then ``initialize``/``tools/list``.

        Never trusts a bare HTTP 200, identical rationale to
        :meth:`_MCPToolkitAdapter.ready`: a pre-existing, unrelated service on
        this run's loopback port is rejected unless ``/info`` echoes back
        exactly the server name this adapter configured in :meth:`prepare`.
        Never calls the mounted ``live_ask`` tool -- handshake/readiness
        performs no generation.

        Args:
            state: The run's current state; only ``state.run_id`` is used.

        Returns:
            ``True`` once ``/info`` identifies this run's own server AND a
            live, API-key-authenticated JSON-RPC ``initialize`` and
            ``tools/list`` (listing ``live_ask``) both succeed; ``False``
            while still starting, on any connection error/timeout, or
            against an identity mismatch.
        """
        endpoint = self._endpoints.get(state.run_id)
        if endpoint is None:
            self.logger.debug("mcp-agent ready: no recorded endpoint for run_id=%s", state.run_id)
            return False

        base_url = f"http://{endpoint.host}:{endpoint.port}"
        agent_path = f"{e2e_live.AGENT_MOUNT_BASE_PATH}/{endpoint.agent_name}"
        headers = {"X-API-Key": endpoint.api_key}
        timeout = aiohttp.ClientTimeout(total=_READY_HTTP_TIMEOUT_S)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{base_url}{agent_path}/info") as response:
                    if response.status != 200:
                        return False
                    info = await response.json()
                if not isinstance(info, dict) or info.get("name") != endpoint.expected_name:
                    self.logger.debug("mcp-agent ready: /info identity mismatch for run_id=%s: %r", state.run_id, info)
                    return False

                init_result = await self._json_rpc(
                    session, base_url, agent_path, "initialize", headers=headers, request_id=1
                )
                if init_result is None or "result" not in init_result:
                    return False

                list_result = await self._json_rpc(
                    session, base_url, agent_path, "tools/list", headers=headers, request_id=2
                )
                if list_result is None:
                    return False
                tools = (list_result.get("result") or {}).get("tools")
                if not isinstance(tools, list):
                    return False
                return any(isinstance(entry, dict) and entry.get("name") == "live_ask" for entry in tools)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            self.logger.debug("mcp-agent ready: transient error for run_id=%s: %s", state.run_id, exc)
            return False

    @staticmethod
    async def _json_rpc(
        session: aiohttp.ClientSession,
        base_url: str,
        path: str,
        method: str,
        *,
        headers: dict[str, str],
        request_id: int,
    ) -> Optional[dict]:
        """Send one JSON-RPC 2.0 request to `path` and return its parsed body.

        Args:
            session: The open client session to send through.
            base_url: This run's ``http://host:port`` base URL.
            path: The route path this run's agent is mounted at.
            method: The JSON-RPC method name.
            headers: Request headers (the API key).
            request_id: The JSON-RPC request ID.

        Returns:
            The parsed JSON-RPC response body, or ``None`` on a non-200 status.
        """
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": {}}
        async with session.post(f"{base_url}{path}", json=payload, headers=headers) as response:
            if response.status != 200:
                return None
            return await response.json()


def build_mcp_agent_adapter() -> _MCPAgentAdapter:
    """Build the `mcp-agent` target adapter.

    Returns:
        A fresh :class:`_MCPAgentAdapter` with an empty endpoint table.
    """
    return _MCPAgentAdapter()
