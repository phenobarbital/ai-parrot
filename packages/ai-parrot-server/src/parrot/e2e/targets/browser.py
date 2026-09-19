"""`browser` owned/adopted Obscura target adapter (FEAT-581, M4).

Implements spec §3 "M4"'s ``parrot.e2e.targets.browser`` factory, per spec §2
"Target and Authentication Design":

    browser | Own Obscura on unique loopback CDP port/private profile; attach
    DevTools to returned endpoint. Explicit adoption is exploratory-only;
    deterministic browser checks require an owned isolated instance.

This adapter never calls :meth:`parrot.mcp.obscura.ObscuraProcessManager.start`
or :meth:`~parrot.mcp.obscura.ObscuraProcessManager.stop` — spawning and
killing the owned Obscura process stays exclusively the M3
:class:`~parrot.e2e.supervisor.E2ESupervisor`'s job, matching every sibling
M4 adapter's own contract (:meth:`prepare` only ever returns a validated
:class:`~parrot.e2e.targets.base.LaunchSpec`; it never spawns anything
itself). It only reuses :class:`~parrot.mcp.obscura.ObscuraProcessManager`'s
two pure, side-effect-free members — the ``endpoint`` property and
:meth:`~parrot.mcp.obscura.ObscuraProcessManager.is_running` (an
``aiohttp`` probe with no spawn/kill effect) — for its own :meth:`ready`
polling, and :class:`~parrot.mcp.obscura.ObscuraProcessConfig`'s dataclass
validation for host/port bounds. This follows spec §3's own instruction for
``ObscuraProcessManager`` ("uses pattern"): preserve the existing API,
never call it to take ownership away from the supervisor.

Two profiles govern how a run's browser is obtained:

- ``minimal`` (the schema default) — deterministic. This adapter always
  spawns a fresh, isolated Obscura instance (unique loopback CDP port,
  private ``--storage-dir`` profile); ``options["adopt"]`` is rejected
  outright (spec §2: "deterministic browser checks require an owned
  isolated instance").
- ``full`` — exploratory-only. ``options["adopt"] = True`` (with an explicit
  ``options["port"]`` naming the already-running, externally-owned CDP
  endpoint) causes :meth:`prepare` to return a :class:`LaunchSpec` for a
  benign, Obscura-independent **sentinel** process instead — a bare
  ``time.sleep`` loop the supervisor spawns and later signals as this run's
  "target process". Because the sentinel has zero relationship to the real,
  externally-owned browser, the supervisor's own SIGTERM/SIGKILL teardown
  can never reach the adopted process (spec §2: "Adopted browser processes
  are never signaled. A retained non-owned endpoint is compatible with
  cleanup success only when explicit adoption was recorded."). :meth:`ready`
  still verifies the adopted endpoint's own CDP liveness via
  ``ObscuraProcessManager.is_running()`` — adoption never means "assume
  ready", only "never own the kill".

Private profile isolation (spec §2 "concurrent worktrees ... distinct ...
browser profiles", AC6) uses ``--storage-dir <run-private-directory>``
(``sdd/state/FEAT-581/research/lifecycle.md`` §2.2/§5 item 5 — the real,
verified Obscura v0.2.2 flag; there is no ``--profile`` flag). Per that same
research note and spec §6 ("No profile parameter exists on
``ObscuraProcessConfig``; profile handling must be verified in the adapter
spike, not passed as an invented constructor argument"), this adapter never
extends ``ObscuraProcessConfig`` with a new field — it builds the launch
``argv`` directly, appending ``--storage-dir`` itself, alongside the same
``serve``/``--host``/``--port``/``--stealth``/``--allow-private-network``
shape :meth:`ObscuraProcessManager._build_command` already uses.

DevTools attachment: once :meth:`ready` reports ``True``, the CDP endpoint a
caller (e.g. Playwright's ``chromium.connect_over_cdp()``, or a human's
DevTools tab) attaches to is exactly ``ObscuraProcessManager.endpoint`` —
the same real ``http://host:port`` this adapter allocated in :meth:`prepare`.
"""

from __future__ import annotations

import logging
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from parrot.e2e import state as e2e_state
from parrot.e2e.errors import E2EConfigError, E2EPrerequisiteError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.targets.base import LaunchSpec
from parrot.mcp.obscura import ObscuraProcessConfig, ObscuraProcessManager

__all__ = ["build_browser_adapter"]

logger = logging.getLogger(__name__)

_OBSCURA_BINARY_NAME = "obscura"

_PROFILE_FULL = "full"

# `minimal` (deterministic, owned-only): a fresh, unique CDP port every call
# unless explicitly overridden, plus optional passthrough Obscura flags.
_OWNED_SUPPORTED_OPTIONS = frozenset({"port", "stealth", "allow_private_network"})
# `full` + `adopt=True` (exploratory-only): attach to an already-running,
# externally-owned endpoint -- no Obscura flags apply, since this adapter
# never spawns Obscura itself in this mode.
_ADOPTED_SUPPORTED_OPTIONS = frozenset({"adopt", "host", "port"})

_DEFAULT_ADOPTED_HOST = "127.0.0.1"

# A benign, Obscura-independent placeholder the supervisor spawns/kills for
# an *adopted* run -- see this module's own docstring for why it must never
# touch the real, externally-owned browser process it is standing in for.
_SENTINEL_SCRIPT = "import time\nwhile True:\n    time.sleep(3600)\n"


def _require_kind(config: TargetConfig, expected: str = "browser") -> None:
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


def _reject_unsupported_options(config: TargetConfig, *, supported: frozenset[str]) -> None:
    """Reject any ``config.options`` key this mode does not recognize.

    Args:
        config: The target configuration to validate.
        supported: The option keys this mode accepts.

    Raises:
        E2EConfigError: If ``config.options`` contains an unsupported key.
    """
    unsupported = sorted(set(config.options) - supported)
    if unsupported:
        raise E2EConfigError(
            f"'browser' target does not support option key(s) {unsupported}; supported: {sorted(supported)}",
            reason_code="unsupported_option",
        )


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


def _validate_bool_option(config: TargetConfig, key: str) -> bool:
    """Validate an optional boolean passthrough option, defaulting to ``False``.

    Args:
        config: The target configuration to validate.
        key: The option key to read.

    Returns:
        The validated ``bool`` value (``False`` if absent).

    Raises:
        E2EConfigError: If the option is present but not a ``bool``.
    """
    value = config.options.get(key, False)
    if not isinstance(value, bool):
        raise E2EConfigError(f"options[{key!r}] must be a bool, got {value!r}", reason_code="invalid_option")
    return value


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


def _resolve_obscura_binary() -> str:
    """Locate the ``obscura`` binary on ``PATH``, or fail BLOCKED.

    Never installs anything (spec §7: "target-specific preflight rather
    than installation side effects").

    Returns:
        The resolved absolute path to the ``obscura`` executable.

    Raises:
        E2EPrerequisiteError: If no ``obscura`` binary is found on ``PATH``.
    """
    binary = shutil.which(_OBSCURA_BINARY_NAME)
    if binary is None:
        raise E2EPrerequisiteError(
            f"{_OBSCURA_BINARY_NAME!r} binary not found on PATH; owned browser scenarios are blocked (spec §2)",
            reason_code="obscura_binary_missing",
        )
    return binary


@dataclass(frozen=True)
class _BrowserEndpoint:
    """This adapter's own record of one run's CDP endpoint and ownership mode.

    Attributes:
        manager: An :class:`ObscuraProcessManager` used only for its two
            pure, side-effect-free members (``endpoint``, ``is_running()``)
            -- never :meth:`~ObscuraProcessManager.start`/
            :meth:`~ObscuraProcessManager.stop`.
        adopted: Whether this run's browser is an externally-owned,
            adopted endpoint (``True``) or one this run's own sentinel/
            owned-Obscura launch is responsible for (``False``).
    """

    manager: ObscuraProcessManager
    adopted: bool


class _BrowserAdapter:
    """`browser` target: an owned or (exploratory-only) adopted Obscura CDP endpoint.

    Tracks its own ``run_id -> _BrowserEndpoint`` mapping (set in
    :meth:`prepare`, consulted in :meth:`ready`) since
    :attr:`parrot.e2e.models.RunState.endpoint` is never populated by the
    supervisor (M3) for any target kind.
    """

    def __init__(self) -> None:
        """Initialize the adapter with an empty per-run endpoint table."""
        self.logger = logging.getLogger(__name__)
        self._endpoints: dict[str, _BrowserEndpoint] = {}

    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Return the owned-Obscura or adopted-sentinel launch (spec §2).

        Args:
            config: Must have ``kind == "browser"``. ``options["adopt"]``
                (a ``bool``) selects adoption; adoption additionally
                requires ``config.profile == "full"`` (spec §2:
                "Explicit adoption is exploratory-only").
            run_id: The run's stable ID.
            worktree: The owning worktree root.

        Returns:
            A ``stdio=False`` :class:`LaunchSpec` -- either the real,
            owned ``obscura serve`` launch, or (adoption) a benign
            sentinel placeholder never connected to the real browser.

        Raises:
            E2EConfigError: If ``config.kind`` disagrees, ``config.options``
                carries an unsupported key for the selected mode,
                ``options["adopt"]`` is set with ``config.profile !=
                "full"``, or any option value is malformed.
            E2EPrerequisiteError: If ``options["adopt"]`` is not set and no
                ``obscura`` binary is found on ``PATH``.
        """
        _require_kind(config)
        adopt = _validate_bool_option(config, "adopt")
        if adopt and config.profile != _PROFILE_FULL:
            raise E2EConfigError(
                "browser adoption is exploratory-only ('full' profile); deterministic browser "
                "checks (the default 'minimal' profile) require an owned, isolated instance (spec §2)",
                reason_code="browser_adoption_requires_full_profile",
            )
        if adopt:
            return self._prepare_adopted(config, run_id=run_id, worktree=worktree)
        return self._prepare_owned(config, run_id=run_id, worktree=worktree)

    def _prepare_owned(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Build the real, owned ``obscura serve`` launch.

        Args:
            config: The already kind/adopt-checked target configuration.
            run_id: The run's stable ID -- used to place this run's own
                private ``--storage-dir`` profile.
            worktree: The owning worktree root.

        Returns:
            A ``stdio=False`` :class:`LaunchSpec` invoking the resolved
            ``obscura serve`` binary directly (``shell=False``).

        Raises:
            E2EConfigError: If ``config.options`` carries an unsupported
                key, or any option value is malformed.
            E2EPrerequisiteError: If no ``obscura`` binary is found on
                ``PATH``.
        """
        _reject_unsupported_options(config, supported=_OWNED_SUPPORTED_OPTIONS)
        port_option = _validate_port_option(config)
        stealth = _validate_bool_option(config, "stealth")
        allow_private_network = _validate_bool_option(config, "allow_private_network")
        port = port_option if port_option is not None else _free_loopback_port()
        host = "127.0.0.1"

        resolved_binary = _resolve_obscura_binary()

        run_directory = e2e_state.run_dir(run_id, worktree=worktree)
        storage_dir = run_directory / "obscura-profile"
        storage_dir.mkdir(mode=e2e_state.RUN_DIR_MODE, exist_ok=True)
        storage_dir.chmod(e2e_state.RUN_DIR_MODE)

        argv = [
            resolved_binary,
            "serve",
            "--host",
            host,
            "--port",
            str(port),
            "--storage-dir",
            str(storage_dir),
        ]
        if stealth:
            argv.append("--stealth")
        if allow_private_network:
            argv.append("--allow-private-network")

        obscura_config = ObscuraProcessConfig(
            binary_path=resolved_binary,
            port=port,
            host=host,
            stealth=stealth,
            allow_private_network=allow_private_network,
        )
        self._endpoints[run_id] = _BrowserEndpoint(manager=ObscuraProcessManager(obscura_config), adopted=False)
        self.logger.debug(
            "browser prepare (owned): run_id=%s host=%s port=%s storage_dir=%s stealth=%s "
            "allow_private_network=%s binary=%s",
            run_id,
            host,
            port,
            storage_dir,
            stealth,
            allow_private_network,
            resolved_binary,
        )
        return LaunchSpec(argv=argv, cwd=worktree, stdio=False)

    def _prepare_adopted(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        """Build the sentinel placeholder for an exploratory-only adoption.

        Never resolves or spawns the ``obscura`` binary -- adoption means
        this run's browser already exists, owned by something else.

        Args:
            config: The already kind/profile-checked target configuration.
            run_id: The run's stable ID.
            worktree: The owning worktree root.

        Returns:
            A ``stdio=False`` :class:`LaunchSpec` invoking a benign
            ``time.sleep`` loop -- the supervisor's own spawn/kill target
            of record, never the real adopted browser.

        Raises:
            E2EConfigError: If ``config.options`` carries an unsupported
                key, ``options["port"]`` is missing/malformed, or
                ``options["host"]`` is present but not a nonempty string.
        """
        _reject_unsupported_options(config, supported=_ADOPTED_SUPPORTED_OPTIONS)
        port = _validate_port_option(config)
        if port is None:
            raise E2EConfigError(
                "options['adopt']=True requires an explicit options['port'] (positive int) naming the "
                "already-running, externally-owned CDP endpoint to attach to",
                reason_code="adopt_requires_port",
            )
        host = config.options.get("host", _DEFAULT_ADOPTED_HOST)
        if not isinstance(host, str) or not host:
            raise E2EConfigError(
                f"options['host'] must be a nonempty string, got {host!r}", reason_code="invalid_option"
            )

        obscura_config = ObscuraProcessConfig(
            binary_path=_OBSCURA_BINARY_NAME, port=port, host=host, attach_only=True
        )
        self._endpoints[run_id] = _BrowserEndpoint(manager=ObscuraProcessManager(obscura_config), adopted=True)
        self.logger.debug("browser prepare (adopted): run_id=%s host=%s port=%s", run_id, host, port)
        return LaunchSpec(argv=[sys.executable, "-c", _SENTINEL_SCRIPT], cwd=worktree, stdio=False)

    async def ready(self, state: RunState) -> bool:
        """Poll this run's CDP endpoint via ``ObscuraProcessManager.is_running()``.

        Owned and adopted runs are checked identically -- adoption changes
        only which process the supervisor may later signal, never how
        readiness is determined (spec §2: DevTools/CDP liveness is the
        only readiness signal Obscura exposes).

        Args:
            state: The run's current state; only ``state.run_id`` is used
                (never ``state.endpoint``, which this target kind's
                supervisor leaves ``None``).

        Returns:
            ``True`` once the recorded endpoint's ``/json/version`` CDP
            route responds; ``False`` while still starting, on any
            connection error/timeout, or for an unknown run.
        """
        endpoint = self._endpoints.get(state.run_id)
        if endpoint is None:
            self.logger.debug("browser ready: no recorded endpoint for run_id=%s", state.run_id)
            return False
        return await endpoint.manager.is_running()


def build_browser_adapter() -> _BrowserAdapter:
    """Build the `browser` target adapter.

    Returns:
        A fresh :class:`_BrowserAdapter` with an empty endpoint table.
    """
    return _BrowserAdapter()
