"""`ui` build/preview target adapter (FEAT-581, M4).

Implements spec §3 "M4"'s ``parrot.e2e.targets.ui`` factory, per spec §2
"Target and Authentication Design":

    ui | Build/serve with pnpm using fixture backend URL before build; HTTP
    `/admin/` readiness followed by declared browser checks. Health alone
    is not browser evidence.

:meth:`_UIAdapter.prepare` never spawns anything itself (the
:class:`~parrot.e2e.targets.base.TargetAdapter` contract, matching every
sibling M4 adapter): the real ``pnpm build`` then ``pnpm preview`` two-step
runs entirely *inside* the launched child, via this module's own
:func:`run_ui_entrypoint`, the same ``sys.executable -c "..."`` bootstrap
technique :mod:`parrot.e2e.targets.mcp`/:mod:`parrot.e2e.targets.botmanager`
already use. Only presence/prerequisite checks (``pnpm``/``node`` binaries,
an installed ``node_modules``) happen in :meth:`prepare` -- never an
auto-install (spec §7: "target-specific preflight rather than installation
side effects"), and no subprocess is spawned before the supervisor's own
spawn (:mod:`parrot.e2e.targets.base`'s own contract: "raised before any
subprocess is spawned").

Build output (``packages/ai-parrot-server/src/parrot/server/ui/dist/``,
``vite.config.ts``'s own ``build.outDir``) is already ``.gitignore``d
(``.gitignore:399``) -- generated output stays isolated from tracked source
(spec §7 "UI build writes must stay in generated/artifact directories; if a
build changes tracked output, identity validation correctly invalidates
evidence"); this adapter never edits ``vite.config.ts`` and never writes
anywhere under the UI project's own tracked ``src/``.

``PUBLIC_API_URL`` (``options["backend_url"]``, spec: "using fixture backend
URL before build") is exported into the *build's own* environment before
``pnpm build`` runs -- ``vite.config.ts``'s ``envPrefix: ['VITE_',
'PUBLIC_']`` bakes it into the built client bundle as a literal
``import.meta.env`` substitution at build time, never only the dev-server
proxy target (which the production ``vite preview`` server this adapter
launches does not use at all).

:meth:`_UIAdapter.ready` matches the spec row verbatim: "HTTP `/admin/`
readiness followed by declared browser checks. Health alone is not browser
evidence." -- the *declared browser checks* are a later, scenario-level
concern (TASK-3548's own file scope), out of this adapter's own scope. This
adapter's own readiness combines the preview server's ``/admin/`` route with
a best-effort reachability probe of the configured backend URL (spec:
"using fixture backend URL"; any HTTP response counts as reachable -- this
adapter has no way to know which specific health-check shape the plan's
chosen backend target kind exposes, so it never asserts a status code or
body against it).
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import aiohttp

from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.targets.base import LaunchSpec

__all__ = ["build_ui_adapter", "run_ui_entrypoint"]

logger = logging.getLogger(__name__)

# Boots this module's own entry point from inside the child -- the same
# `sys.executable -c "..."` technique `parrot.e2e.targets.{mcp,botmanager}`
# already use, never a bespoke inlined script or the installed `pnpm`
# workflow run directly by the supervisor.
_UI_BOOTSTRAP = "from parrot.e2e.targets.ui import run_ui_entrypoint\nrun_ui_entrypoint()\n"

# The admin UI's own standalone Vite + Svelte 5 project root (CLAUDE.md:
# "Admin UI (Svelte 5 + Vite): packages/ai-parrot-server/ui/"), relative to
# the owning worktree root.
_UI_RELATIVE_DIR = Path("packages") / "ai-parrot-server" / "ui"
# `vite.config.ts`'s own `base: '/admin/'` (TASK-2525: standalone SPA served
# from the aiohttp backend at /admin).
_ADMIN_BASE_PATH = "/admin/"

_SUPPORTED_OPTIONS = frozenset({"backend_url", "port"})

_PNPM_BINARY_ENV = "E2E_UI_PNPM_BINARY"
_UI_DIR_ENV = "E2E_UI_DIR"
_UI_PORT_ENV = "E2E_UI_PORT"
_PUBLIC_API_URL_ENV = "PUBLIC_API_URL"

_READY_HTTP_TIMEOUT_S = 2.0
_BACKEND_READY_HTTP_TIMEOUT_S = 2.0


def _require_kind(config: TargetConfig, expected: str = "ui") -> None:
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


def _reject_unsupported_options(config: TargetConfig) -> None:
    """Reject any ``config.options`` key this target kind does not recognize.

    Args:
        config: The target configuration to validate.

    Raises:
        E2EConfigError: If ``config.options`` contains an unsupported key.
    """
    unsupported = sorted(set(config.options) - _SUPPORTED_OPTIONS)
    if unsupported:
        raise E2EConfigError(
            f"'ui' target does not support option key(s) {unsupported}; supported: {sorted(_SUPPORTED_OPTIONS)}",
            reason_code="unsupported_option",
        )


def _validate_backend_url(config: TargetConfig) -> str:
    """Require and validate ``options["backend_url"]`` (spec: fixture backend URL).

    A pure, environment-independent config check -- called before any
    external prerequisite (``pnpm``/``node``/``node_modules``) is looked
    up, so a malformed/missing ``backend_url`` is always reported as a
    config error (exit code 2), never masked by a BLOCKED prerequisite.

    Args:
        config: The target configuration to validate.

    Returns:
        The validated, absolute ``http``/``https`` backend URL.

    Raises:
        E2EConfigError: If ``options["backend_url"]`` is missing, empty, or
            not an absolute ``http``/``https`` URL.
    """
    backend_url = config.options.get("backend_url")
    if not isinstance(backend_url, str) or not backend_url:
        raise E2EConfigError(
            "'ui' target requires options['backend_url'] (the fixture backend URL baked into "
            "PUBLIC_API_URL before build, spec §2: 'using fixture backend URL before build')",
            reason_code="missing_backend_url",
        )
    parsed = urlsplit(backend_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise E2EConfigError(
            f"options['backend_url'] must be an absolute http(s) URL, got {backend_url!r}",
            reason_code="invalid_option",
        )
    return backend_url


def _validate_port_option(config: TargetConfig) -> Optional[int]:
    """Validate (never allocate) an explicit ``options["port"]`` override.

    Args:
        config: The target configuration to validate.

    Returns:
        The validated positive ``int``, or ``None`` if no override was given.

    Raises:
        E2EConfigError: If ``options["port"]`` is present but is not a
            positive ``int``.
    """
    port_option = config.options.get("port")
    if port_option is None:
        return None
    if isinstance(port_option, bool) or not isinstance(port_option, int) or port_option <= 0:
        raise E2EConfigError(
            f"options['port'] must be a positive integer, got {port_option!r}", reason_code="invalid_option"
        )
    return port_option


def _free_loopback_port() -> int:
    """Allocate one currently-free loopback TCP port.

    Returns:
        A port number free at the moment of the call (spec §2: "Bind
        loopback; allocate ports per run.").
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _resolve_pnpm_binary() -> str:
    """Locate the ``pnpm`` binary on ``PATH``, or fail BLOCKED.

    Never installs anything (spec §7: preflight only).

    Returns:
        The resolved absolute path to the ``pnpm`` executable.

    Raises:
        E2EPrerequisiteError: If no ``pnpm`` binary is found on ``PATH``.
    """
    binary = shutil.which("pnpm")
    if binary is None:
        raise E2EPrerequisiteError(
            "'pnpm' binary not found on PATH; the 'ui' target's build/preview step is blocked "
            "(spec §7: preflight, never auto-install)",
            reason_code="pnpm_binary_missing",
        )
    return binary


def _resolve_node_binary() -> str:
    """Locate the ``node`` binary on ``PATH``, or fail BLOCKED.

    Never installs anything (spec §7: preflight only).

    Returns:
        The resolved absolute path to the ``node`` executable.

    Raises:
        E2EPrerequisiteError: If no ``node`` binary is found on ``PATH``.
    """
    binary = shutil.which("node")
    if binary is None:
        raise E2EPrerequisiteError(
            "'node' binary not found on PATH; the 'ui' target's build/preview step is blocked "
            "(spec §7: preflight, never auto-install)",
            reason_code="node_binary_missing",
        )
    return binary


def _resolve_ui_dir(worktree: Path) -> Path:
    """Locate and preflight-check the admin UI's own project directory.

    Args:
        worktree: The owning worktree root.

    Returns:
        The resolved UI project directory.

    Raises:
        E2EPrerequisiteError: If the UI project directory does not exist
            under ``worktree``, or its ``node_modules`` is missing (spec
            §7: never auto-install; require ``pnpm install`` to have
            already been run manually).
    """
    ui_dir = worktree / _UI_RELATIVE_DIR
    if not ui_dir.is_dir():
        raise E2EPrerequisiteError(
            f"UI project directory not found at {ui_dir}; this worktree does not contain the admin "
            "UI source tree",
            reason_code="ui_dir_missing",
        )
    if not (ui_dir / "node_modules").is_dir():
        raise E2EPrerequisiteError(
            f"'ui' target's dependencies are not installed ({ui_dir / 'node_modules'} is missing); "
            "run 'pnpm install' manually first -- auto-install is not permitted (spec §7)",
            reason_code="ui_dependencies_missing",
        )
    return ui_dir


@dataclass(frozen=True)
class _UIEndpoint:
    """This adapter's own record of one run's preview endpoint and backend URL.

    Attributes:
        host: The loopback host the preview server was told to bind.
        port: The loopback port the preview server was told to bind.
        backend_url: The fixture backend URL baked into this run's build,
            re-probed by :meth:`_UIAdapter.ready` for reachability.
    """

    host: str
    port: int
    backend_url: str


class _UIAdapter:
    """`ui` target: the real, admin UI ``pnpm build``/``pnpm preview`` two-step.

    Tracks its own ``run_id -> _UIEndpoint`` mapping (set in
    :meth:`prepare`, consulted in :meth:`ready`) since
    :attr:`parrot.e2e.models.RunState.endpoint` is never populated by the
    supervisor (M3) for any target kind.
    """

    def __init__(self) -> None:
        """Initialize the adapter with an empty per-run endpoint table."""
        self.logger = logging.getLogger(__name__)
        self._endpoints: dict[str, _UIEndpoint] = {}

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Return the ``pnpm build`` + ``pnpm preview`` launch (spec §2).

        Args:
            config: Must have ``kind == "ui"`` and a nonempty
                ``options["backend_url"]``. ``options["port"]`` (a
                positive ``int``) overrides the default free-port
                allocation for the preview server; every other option key
                is rejected.
            run_id: The run's stable ID (unused beyond logging -- this
                adapter's own state is keyed the same way every sibling
                adapter's is, by ``run_id``).
            worktree: The owning worktree root; the admin UI project is
                resolved as ``worktree / "packages/ai-parrot-server/ui"``.

        Returns:
            A ``stdio=False`` :class:`LaunchSpec` invoking this module's
            own :func:`run_ui_entrypoint`, with ``PUBLIC_API_URL`` and the
            resolved preview port already merged into its environment.

        Raises:
            E2EConfigError: If ``config.kind`` disagrees, ``config.options``
                carries an unsupported key, ``options["backend_url"]`` is
                missing/malformed, or ``options["port"]`` is not a
                positive integer.
            E2EPrerequisiteError: If ``pnpm``/``node`` is not found on
                ``PATH``, the UI project directory is missing, or its
                ``node_modules`` is not installed.
        """
        _require_kind(config)
        _reject_unsupported_options(config)
        backend_url = _validate_backend_url(config)
        port_option = _validate_port_option(config)
        port = port_option if port_option is not None else _free_loopback_port()

        pnpm_binary = _resolve_pnpm_binary()
        _resolve_node_binary()
        ui_dir = _resolve_ui_dir(worktree)

        env = {
            _PNPM_BINARY_ENV: pnpm_binary,
            _UI_DIR_ENV: str(ui_dir),
            _UI_PORT_ENV: str(port),
            _PUBLIC_API_URL_ENV: backend_url,
        }
        self._endpoints[run_id] = _UIEndpoint(host="127.0.0.1", port=port, backend_url=backend_url)
        self.logger.debug(
            "ui prepare: run_id=%s port=%s backend_url=%s ui_dir=%s pnpm=%s",
            run_id,
            port,
            backend_url,
            ui_dir,
            pnpm_binary,
        )
        return LaunchSpec(argv=[sys.executable, "-c", _UI_BOOTSTRAP], env=env, cwd=worktree, stdio=False)

    async def ready(self, state: RunState) -> bool:
        """Poll ``<base_url>/admin/`` then the configured backend URL (spec §2).

        Args:
            state: The run's current state; only ``state.run_id`` is used
                (never ``state.endpoint``, which this target kind's
                supervisor leaves ``None``).

        Returns:
            ``True`` once ``/admin/`` responds HTTP 200 AND the configured
            backend URL answers (any HTTP response, per this adapter's own
            best-effort reachability contract); ``False`` while still
            starting, on any connection error/timeout, or for an unknown
            run.
        """
        endpoint = self._endpoints.get(state.run_id)
        if endpoint is None:
            self.logger.debug("ui ready: no recorded endpoint for run_id=%s", state.run_id)
            return False

        base_url = f"http://{endpoint.host}:{endpoint.port}"
        timeout = aiohttp.ClientTimeout(total=_READY_HTTP_TIMEOUT_S)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{base_url}{_ADMIN_BASE_PATH}") as response:
                    if response.status != 200:
                        return False
        except (aiohttp.ClientError, TimeoutError) as exc:
            self.logger.debug("ui ready: transient error for run_id=%s: %s", state.run_id, exc)
            return False

        return await self._backend_reachable(endpoint.backend_url)

    @staticmethod
    async def _backend_reachable(backend_url: str) -> bool:
        """Best-effort backend reachability probe (spec: "using fixture backend URL").

        Any HTTP response (even an error status) counts as reachable --
        this adapter has no way to know which specific health-check shape
        the plan's chosen backend target kind exposes; only a connection
        failure/timeout means "not yet reachable".

        Args:
            backend_url: The fixture backend URL to probe.

        Returns:
            ``True`` iff an HTTP response (any status) was received before
            the timeout; ``False`` otherwise.
        """
        timeout = aiohttp.ClientTimeout(total=_BACKEND_READY_HTTP_TIMEOUT_S)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(backend_url):
                return True
        except (aiohttp.ClientError, TimeoutError):
            return False


def build_ui_adapter() -> _UIAdapter:
    """Build the `ui` target adapter.

    Returns:
        A fresh :class:`_UIAdapter` with an empty endpoint table.
    """
    return _UIAdapter()


# ---------------------------------------------------------------------------
# Child-process entry point -- runs only inside the launched target, never in
# the E2E harness's own process (matches every sibling M4 adapter's own
# entry-point convention, see e.g. `parrot.e2e.targets.botmanager.
# run_app_entrypoint`'s own module-level note).
# ---------------------------------------------------------------------------


def run_ui_entrypoint() -> None:
    """Build then serve the real admin UI (real, unmocked `pnpm build`/`pnpm preview`).

    The synchronous bootstrap invoked by :data:`_UI_BOOTSTRAP`, inside the
    child process the supervisor spawns. Runs ``pnpm build`` to completion
    first, blocking (``PUBLIC_API_URL`` is already present in this
    process's own environment -- merged in by :meth:`_UIAdapter.prepare`'s
    :class:`~parrot.e2e.targets.base.LaunchSpec` -- so ``vite.config.ts``'s
    ``envPrefix`` bakes it into the built client bundle), then ``chdir``s
    into the UI project directory and ``exec``s into ``pnpm preview`` so
    the *same* process (same PID, same process group) keeps serving --
    the supervisor's own SIGTERM/SIGKILL teardown reaches this process
    transparently across the ``exec``.

    Raises:
        SystemExit: If ``pnpm build`` exits nonzero -- this process exits
            with that same code, which the supervisor's own
            readiness-await loop reports as an early-exit target failure
            (never masked as "still starting").
    """
    ui_dir = os.environ[_UI_DIR_ENV]
    pnpm_binary = os.environ[_PNPM_BINARY_ENV]
    port = os.environ[_UI_PORT_ENV]

    build_result = subprocess.run([pnpm_binary, "build"], cwd=ui_dir, check=False)
    if build_result.returncode != 0:
        raise SystemExit(build_result.returncode)

    os.chdir(ui_dir)
    os.execv(pnpm_binary, [pnpm_binary, "preview", "--port", port, "--host", "127.0.0.1", "--strictPort"])
