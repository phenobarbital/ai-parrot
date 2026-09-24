"""Deterministic E2E gate CLI: run/verify/up/status/logs/down (FEAT-581, M3).

Implements the spec §2 "New Public Interfaces" CLI contract on top of the
already-frozen M2/M3 building blocks (:func:`parrot.e2e.runner.run_plan`,
:func:`parrot.e2e.evidence.verify_evidence`, :class:`parrot.e2e.supervisor.
E2ESupervisor`, :mod:`parrot.e2e.state`, :mod:`parrot.e2e.watchdog`). This
module owns exactly the process-boundary/CLI concerns those modules
deliberately leave open: worktree discovery, owner-identity defaults, argv
parsing, JSON-on-stdout / diagnostics-on-stderr framing, exit-code mapping
and ``up``'s detached daemon.

``e2e`` (this module's :class:`click.Group`) is registered lazily by core's
``LazyGroup`` (``packages/ai-parrot/src/parrot/cli/__init__.py``); it is
never imported at core CLI import time, so a checkout without
``ai-parrot-server`` installed still runs every other ``parrot`` subcommand.

Every worktree-scoped operation resolves "this worktree" by walking up from
the current working directory to the nearest ``.git`` entry (a plain
directory checkout or a linked worktree's ``.git`` *file* both count) —
consistent with :mod:`parrot.e2e.state`'s own ``sdd/state/e2e/<run_id>.json``
convention, and never an arbitrary path supplied by CLI input.

``up``'s frozen collaborator, :meth:`parrot.e2e.supervisor.E2ESupervisor.
start`, does not accept a caller-chosen ``run_id`` — it always mints its own
(``<target_id>-<12 hex chars>``). This module's own ``--run-id`` flag is
therefore deliberately reinterpreted as an *invocation ticket* ID: a stable
name for the small JSON handoff file the detached daemon writes once
``start()`` returns (success or failure), which this command polls to learn
the *real*, supervisor-minted ``RunState.run_id`` it must report back and
which ``status``/``logs``/``down`` are then invoked against. This ticket
file lives under ``artifacts/logs/e2e/_up_tickets/`` — never inside
:mod:`parrot.e2e.state`'s own ``sdd/state/e2e/`` directory, so it can never
be mistaken for a persisted :class:`~parrot.e2e.models.RunState` by
``status``/``down --all``/``down --stale`` (which only ever iterate that
directory via :func:`parrot.e2e.state.list_run_ids`).
"""

from __future__ import annotations

import asyncio
import contextlib
import getpass
import json
import logging
import os
import re
import signal
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import click
import yaml
from pydantic import ValidationError

from parrot.e2e.errors import (
    EXIT_BLOCKED,
    EXIT_CONFIG,
    EXIT_EVIDENCE,
    EXIT_FAILURE,
    EXIT_SIGINT,
    EXIT_SIGTERM,
    EXIT_SUCCESS,
    E2EConfigError,
    E2EError,
    E2ETargetError,
)
from parrot.e2e.evidence import verify_evidence
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.runner import run_plan
from parrot.e2e import state as e2e_state
from parrot.e2e import watchdog as e2e_watchdog
from parrot.e2e.supervisor import E2ESupervisor
from parrot.e2e.targets import TARGET_KINDS

__all__ = ["e2e"]

logger = logging.getLogger(__name__)

# Same nonempty "safe slug" convention as every other parrot.e2e module's own
# duplicated private validator (parrot.e2e.models/state/supervisor) — kept
# local rather than imported, per this package's own established convention.
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

_DEFAULT_UP_READY_POLL_S = 0.2
_UP_DAEMON_SPAWN_GRACE_S = 30.0
_DAEMON_POLL_INTERVAL_S = 1.0
_TICKETS_DIRNAME = "_up_tickets"
_DAEMON_LOGS_DIRNAME = "_up_daemons"

_VERIFY_EXIT_CODES = {
    "PASS": EXIT_SUCCESS,
    "FAIL": EXIT_FAILURE,
    "BLOCKED": EXIT_BLOCKED,
    "MISSING": EXIT_EVIDENCE,
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _resolve_worktree(start: Optional[Path] = None) -> Path:
    """Resolve "this worktree" by walking up from ``start`` to the nearest ``.git``.

    Args:
        start: Directory to begin the search from; defaults to the current
            working directory.

    Returns:
        The resolved worktree root, or the resolved ``start`` directory
        itself if no ``.git`` entry is found in any ancestor.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _sanitize_slug(raw: str, *, fallback: str) -> str:
    """Coerce ``raw`` into a safe slug, or return ``fallback`` if that is impossible.

    Args:
        raw: Candidate identifier (e.g. an OS username or env var value).
        fallback: Value to use if ``raw`` is empty or sanitizes to nothing.

    Returns:
        A string matching :data:`_SAFE_ID_RE`.
    """
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "-", raw) if raw else ""
    sanitized = sanitized.strip("-") or ""
    if not sanitized or not sanitized[0].isalnum():
        sanitized = f"u-{sanitized}" if sanitized else fallback
    return sanitized or fallback


def _default_owner_id() -> str:
    """Return the invoking runner's default identity (spec §2: "Omitted owner defaults to ...").

    Returns:
        ``$PARROT_E2E_OWNER_ID`` if set, else the current OS user name,
        sanitized to a safe slug; ``"cli"`` if neither is available.
    """
    try:
        username = getpass.getuser()
    except OSError:
        username = ""
    raw = os.environ.get("PARROT_E2E_OWNER_ID") or username
    return _sanitize_slug(raw, fallback="cli")


def _default_feature_id() -> str:
    """Return the bookkeeping ``feature_id`` recorded on an ``up``-started target's RunState.

    ``up`` starts one bare target outside any :class:`~parrot.e2e.models.E2EPlan`
    (unlike ``run``, which gets ``feature_id`` from the plan), so this is a
    fixed, override-only value used purely as :class:`RunState` metadata —
    never consulted by :meth:`parrot.e2e.supervisor.E2ESupervisor.stop`.

    Returns:
        ``$PARROT_E2E_FEATURE_ID`` if set, sanitized to a safe slug, else
        ``"e2e-cli"``.
    """
    return _sanitize_slug(os.environ.get("PARROT_E2E_FEATURE_ID", ""), fallback="e2e-cli")


def _validate_safe_id(value: str, *, field_name: str) -> str:
    """Validate a nonempty safe slug used as a CLI-supplied identifier.

    Args:
        value: The candidate identifier.
        field_name: Name used in the raised error's message/reason code.

    Returns:
        The validated identifier, unchanged.

    Raises:
        E2EConfigError: If ``value`` is empty or contains an unsafe character.
    """
    if not value or not _SAFE_ID_RE.match(value):
        raise E2EConfigError(
            f"{field_name} must be a nonempty safe slug: {value!r}", reason_code=f"{field_name}_unsafe"
        )
    return value


def _echo_json(payload: dict[str, Any]) -> None:
    """Emit one canonical, single-line JSON object to stdout (spec §2 "JSON ... on stdout").

    Args:
        payload: The JSON-serializable object to print.
    """
    click.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _fail(message: str, *, exit_code: int, reason_code: Optional[str] = None) -> None:
    """Log diagnostics to stderr, print a small JSON error envelope to stdout, and exit.

    Args:
        message: Human-readable failure description.
        exit_code: Process exit code (spec §2 exit-code table).
        reason_code: Optional machine-readable reason code.

    Raises:
        SystemExit: Always, with ``exit_code``.
    """
    logger.error(message)
    _echo_json({"status": "ERROR", "error": message, "reason_code": reason_code})
    raise SystemExit(exit_code)


def _fail_from_error(exc: E2EError) -> None:
    """Translate one typed :class:`~parrot.e2e.errors.E2EError` into a CLI failure.

    Args:
        exc: The raised typed error; its own ``exit_code``/``reason_code``
            drive the process exit (spec §2's exit-code mapping is owned by
            the exception classes themselves, never re-guessed here).

    Raises:
        SystemExit: Always, with ``exc.exit_code``.
    """
    _fail(str(exc), exit_code=exc.exit_code, reason_code=exc.reason_code)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write one small JSON coordination file (never partially visible).

    Args:
        path: Destination file path; parent directories are created as needed.
        payload: The JSON-serializable object to persist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.stem}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _signal_exit_code(received: list[int], *, fallback: int) -> int:
    """Map a foreground command's observed interrupt signal to spec §2's exit code.

    Args:
        received: Signal numbers observed by this invocation's own handler,
            in the order received (only the first is meaningful).
        fallback: Exit code to use if no signal was observed.

    Returns:
        ``130`` if the first observed signal was ``SIGINT``, ``143`` if it
        was ``SIGTERM``, else ``fallback``.
    """
    if not received:
        return fallback
    return EXIT_SIGINT if received[0] == signal.SIGINT else EXIT_SIGTERM


def _verify_exit_code(status: str) -> int:
    """Map a :class:`~parrot.e2e.models.VerificationResult.status` to spec §2's exit code.

    Args:
        status: One of ``PASS``/``FAIL``/``BLOCKED``/``MISSING``.

    Returns:
        The corresponding exit code.
    """
    return _VERIFY_EXIT_CODES[status]


def _load_target_config(target: str, config_path: Optional[Path]) -> TargetConfig:
    """Build one :class:`TargetConfig` from a fixed registry name and an optional overlay file.

    Spec §2: "A config supplies a TargetConfig; fixed registry names only,
    not arbitrary shell commands." ``target`` must already be one of the six
    fixed :data:`parrot.e2e.targets.TARGET_KINDS`; ``config_path`` (if given)
    only ever overlays :class:`TargetConfig`'s own declared fields
    (``profile``/timeouts/``options``), never an argv or shell string.

    Args:
        target: The requested target kind.
        config_path: Optional YAML/JSON overlay file.

    Returns:
        The validated :class:`TargetConfig`.

    Raises:
        E2EConfigError: If ``target`` is not a known kind, the overlay file
            cannot be read/parsed, declares a disagreeing ``kind``, or the
            merged payload fails :class:`TargetConfig` validation.
    """
    if target not in TARGET_KINDS:
        raise E2EConfigError(
            f"unknown target kind {target!r}; expected one of {sorted(TARGET_KINDS)}",
            reason_code="unknown_target_kind",
        )
    payload: dict[str, Any] = {"kind": target}
    if config_path is not None:
        try:
            raw_text = config_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise E2EConfigError(
                f"target config file could not be read: {config_path}: {exc}",
                reason_code="target_config_unreadable",
            ) from exc
        try:
            loaded = yaml.safe_load(raw_text)
        except yaml.YAMLError as exc:
            raise E2EConfigError(
                f"target config file is not valid YAML/JSON: {config_path}: {exc}",
                reason_code="target_config_invalid",
            ) from exc
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise E2EConfigError(
                f"target config file must be a mapping: {config_path}", reason_code="target_config_invalid"
            )
        declared_kind = loaded.get("kind")
        if declared_kind is not None and declared_kind != target:
            raise E2EConfigError(
                f"target config kind {declared_kind!r} disagrees with requested target {target!r}",
                reason_code="target_kind_mismatch",
            )
        payload.update(loaded)
        payload["kind"] = target
    try:
        return TargetConfig.model_validate(payload)
    except ValidationError as exc:
        raise E2EConfigError(
            f"invalid target config for {target!r}: {exc}", reason_code="target_config_invalid"
        ) from exc


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group()
def e2e() -> None:
    """Deterministic E2E gate: run, verify, up, status, logs, down (FEAT-581)."""


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


async def _execute_run(plan_path: Path, *, worktree: Path, owner_id: str, received_signal: list[int]) -> Any:
    """Run ``run_plan`` under foreground signal handling.

    Args:
        plan_path: Path to the ``e2e-plan.md`` document.
        worktree: The owning worktree root.
        owner_id: Owner identity authorizing every started target.
        received_signal: Mutated in place with any observed interrupt signal.

    Returns:
        The completed :class:`~parrot.e2e.models.E2EVerdict`.
    """
    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(run_plan(plan_path, worktree=worktree, owner_id=owner_id))

    def _on_signal(signum: int) -> None:
        received_signal.append(signum)
        task.cancel()

    installed: list[int] = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_signal, sig)
            installed.append(sig)
    try:
        return await task
    finally:
        for sig in installed:
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.remove_signal_handler(sig)


@e2e.command("run")
@click.option(
    "--plan", "plan_path", required=True, type=click.Path(path_type=Path), help="Path to the e2e-plan.md document."
)
@click.option("--owner-id", "owner_id", default=None, help="Owner identity; defaults to the invoking runner identity.")
def run_command(plan_path: Path, owner_id: Optional[str]) -> None:
    """Foreground bounded runner: execute a plan; JSON verdict on stdout, diagnostics on stderr."""
    worktree = _resolve_worktree()
    owner = owner_id or _default_owner_id()
    try:
        owner = _validate_safe_id(owner, field_name="owner_id")
    except E2EConfigError as exc:
        _fail_from_error(exc)
        return

    received_signal: list[int] = []
    try:
        verdict = asyncio.run(
            _execute_run(plan_path, worktree=worktree, owner_id=owner, received_signal=received_signal)
        )
    except E2EError as exc:
        _fail_from_error(exc)
        return
    except Exception as exc:  # pragma: no cover - defensive, unexpected collaborator failure
        logger.exception("unexpected failure running plan %s", plan_path)
        _fail(f"unexpected failure running plan: {exc}", exit_code=EXIT_FAILURE)
        return

    _echo_json(verdict.model_dump(mode="json"))
    raise SystemExit(_signal_exit_code(received_signal, fallback=verdict.exit_code))


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@e2e.command("verify")
@click.option(
    "--plan", "plan_path", required=True, type=click.Path(path_type=Path), help="Path to the e2e-plan.md document."
)
def verify_command(plan_path: Path) -> None:
    """Read-only evidence validation; JSON :class:`VerificationResult` on stdout."""
    worktree = _resolve_worktree()
    try:
        result = asyncio.run(verify_evidence(plan_path, worktree=worktree))
    except E2EError as exc:
        _fail_from_error(exc)
        return
    except Exception as exc:  # pragma: no cover - defensive, unexpected collaborator failure
        logger.exception("unexpected failure verifying plan %s", plan_path)
        _fail(f"unexpected failure verifying plan: {exc}", exit_code=EXIT_FAILURE)
        return

    _echo_json(result.model_dump(mode="json"))
    raise SystemExit(_verify_exit_code(result.status))


# ---------------------------------------------------------------------------
# up (+ its internal detached daemon)
# ---------------------------------------------------------------------------


def _ticket_path(worktree: Path, invocation_id: str) -> Path:
    """Return this ``up`` invocation's coordination-ticket path (never a persisted RunState)."""
    return worktree / "artifacts" / "logs" / "e2e" / _TICKETS_DIRNAME / f"{invocation_id}.json"


def _daemon_log_path(worktree: Path, invocation_id: str) -> Path:
    """Return this ``up`` invocation's detached daemon's own stdout/stderr log path."""
    directory = worktree / "artifacts" / "logs" / "e2e" / _DAEMON_LOGS_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{invocation_id}.log"


async def _spawn_detached_target(
    target: str,
    config: TargetConfig,
    *,
    invocation_id: str,
    owner_id: str,
    worktree: Path,
    feature_id: str,
) -> RunState:
    """Spawn ``up``'s detached daemon subprocess and wait for its readiness ticket.

    Args:
        target: The requested fixed target kind.
        config: The target's validated launch/readiness configuration.
        invocation_id: This invocation's own ticket-file name (see module
            docstring — never the supervisor-minted ``RunState.run_id``).
        owner_id: Owner identity authorizing this target.
        worktree: The owning worktree root.
        feature_id: Bookkeeping ``feature_id`` recorded on the started
            target's :class:`RunState`.

    Returns:
        The started target's final :class:`RunState` (``status="ready"`` or
        ``status="failed"``).

    Raises:
        E2ETargetError: If the daemon exits before writing its ticket, or
            never reports readiness within its startup deadline.
    """
    ticket_path = _ticket_path(worktree, invocation_id)
    with contextlib.suppress(OSError):
        ticket_path.unlink()
    daemon_log = _daemon_log_path(worktree, invocation_id)

    argv = [
        sys.executable,
        "-m",
        "parrot.e2e.cli",
        "_run-daemon",
        "--worktree",
        str(worktree),
        "--owner-id",
        owner_id,
        "--feature-id",
        feature_id,
        "--target-id",
        target,
        "--config-json",
        config.model_dump_json(),
        "--ticket-path",
        str(ticket_path),
    ]
    handle = await asyncio.to_thread(open, daemon_log, "ab")
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(worktree),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=handle,
            stderr=handle,
            start_new_session=True,
        )
    finally:
        handle.close()

    deadline = time.monotonic() + config.startup_timeout_s + _UP_DAEMON_SPAWN_GRACE_S
    while True:
        if ticket_path.is_file():
            break
        if process.returncode is not None:
            raise E2ETargetError(
                f"detached target {target!r} daemon exited early (code {process.returncode}) "
                "before writing its readiness ticket",
                reason_code="daemon_exited_early",
            )
        if time.monotonic() >= deadline:
            raise E2ETargetError(
                f"detached target {target!r} did not report readiness within the startup deadline",
                reason_code="up_readiness_timeout",
            )
        await asyncio.sleep(_DEFAULT_UP_READY_POLL_S)

    payload = json.loads(ticket_path.read_text(encoding="utf-8"))
    if "error" in payload:
        raise E2ETargetError(str(payload["error"]), reason_code=payload.get("reason_code") or "target_start_failed")
    return RunState.model_validate(payload)


@e2e.command("up")
@click.argument("target")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Optional TargetConfig overlay (YAML/JSON): profile/timeouts/options.",
)
@click.option(
    "--run-id",
    "invocation_id",
    default=None,
    help="This invocation's own tracking ticket ID (the started target's real run_id is auto-minted and echoed back).",
)
@click.option("--owner-id", "owner_id", default=None, help="Owner identity; defaults to the invoking runner identity.")
@click.option("--timeout", "timeout_s", type=float, default=None, help="Startup readiness timeout override, seconds.")
def up_command(
    target: str,
    config_path: Optional[Path],
    invocation_id: Optional[str],
    owner_id: Optional[str],
    timeout_s: Optional[float],
) -> None:
    """Start a supervised, detached target; one RunState JSON line when ready."""
    worktree = _resolve_worktree()
    owner = owner_id or _default_owner_id()
    ticket_id = invocation_id or f"up-{uuid.uuid4().hex[:12]}"
    try:
        owner = _validate_safe_id(owner, field_name="owner_id")
        ticket_id = _validate_safe_id(ticket_id, field_name="run_id")
        config = _load_target_config(target, config_path)
        if timeout_s is not None:
            config = config.model_copy(update={"startup_timeout_s": timeout_s})
    except E2EConfigError as exc:
        _fail_from_error(exc)
        return

    try:
        final_state = asyncio.run(
            _spawn_detached_target(
                target,
                config,
                invocation_id=ticket_id,
                owner_id=owner,
                worktree=worktree,
                feature_id=_default_feature_id(),
            )
        )
    except E2EError as exc:
        _fail_from_error(exc)
        return
    except Exception as exc:  # pragma: no cover - defensive, unexpected collaborator failure
        logger.exception("unexpected failure starting target %s", target)
        _fail(f"unexpected failure starting target: {exc}", exit_code=EXIT_FAILURE)
        return

    _echo_json(final_state.model_dump(mode="json"))
    raise SystemExit(EXIT_SUCCESS if final_state.status == "ready" else EXIT_FAILURE)


async def _run_daemon(
    target_id: str, config: TargetConfig, *, owner_id: str, worktree: Path, feature_id: str, ticket_path: Path
) -> int:
    """Own one supervised target for its full detached lifetime (spawned by ``up``).

    Args:
        target_id: The fixed target kind to start.
        config: The already-validated launch/readiness configuration.
        owner_id: Owner identity authorizing this target.
        worktree: The owning worktree root.
        feature_id: Bookkeeping ``feature_id`` recorded on the started
            target's :class:`RunState`.
        ticket_path: Where to atomically write the started (or failed)
            :class:`RunState` for ``up`` to poll.

    Returns:
        The process exit code: ``0`` on a clean start-then-stop lifecycle,
        ``1`` if the target never started or its teardown was not verified
        complete.
    """
    supervisor = E2ESupervisor(worktree=worktree, owner_id=owner_id, feature_id=feature_id)
    try:
        state = await supervisor.start(target_id, config)
    except E2EError as exc:
        logger.exception("detached target %s failed to start", target_id)
        _write_json_atomic(ticket_path, {"error": str(exc), "reason_code": exc.reason_code})
        return EXIT_FAILURE
    _write_json_atomic(ticket_path, state.model_dump(mode="json"))

    run_id = state.run_id
    loop = asyncio.get_running_loop()
    stop_requested = asyncio.Event()

    def _on_signal() -> None:
        stop_requested.set()

    installed: list[int] = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _on_signal)
            installed.append(sig)

    try:
        while True:
            if stop_requested.is_set():
                final_state = await supervisor.stop(run_id)
                return EXIT_SUCCESS if final_state.cleanup_complete else EXIT_FAILURE
            try:
                current = e2e_state.read_state(run_id, worktree=worktree)
            except E2EConfigError:
                current = None
            if current is not None and current.cleanup_complete:
                return EXIT_SUCCESS if current.status == "stopped" else EXIT_FAILURE
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop_requested.wait(), timeout=_DAEMON_POLL_INTERVAL_S)
    finally:
        for sig in installed:
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.remove_signal_handler(sig)


@e2e.command("_run-daemon", hidden=True)
@click.option("--worktree", "worktree_arg", required=True, type=click.Path(path_type=Path))
@click.option("--owner-id", "owner_id", required=True)
@click.option("--feature-id", "feature_id", required=True)
@click.option("--target-id", "target_id", required=True)
@click.option("--config-json", "config_json", required=True)
@click.option("--ticket-path", "ticket_path_arg", required=True, type=click.Path(path_type=Path))
def run_daemon_command(
    worktree_arg: Path, owner_id: str, feature_id: str, target_id: str, config_json: str, ticket_path_arg: Path
) -> None:
    """Internal entry point spawned by ``up``: never invoked directly by a user."""
    worktree = worktree_arg.resolve()
    try:
        config = TargetConfig.model_validate_json(config_json)
    except ValidationError as exc:
        logger.error("invalid detached daemon target config: %s", exc)
        raise SystemExit(EXIT_CONFIG) from exc

    exit_code = asyncio.run(
        _run_daemon(
            target_id,
            config,
            owner_id=owner_id,
            worktree=worktree,
            feature_id=feature_id,
            ticket_path=ticket_path_arg,
        )
    )
    raise SystemExit(exit_code)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@e2e.command("status")
@click.argument("run_id", required=False)
def status_command(run_id: Optional[str]) -> None:
    """Print one run's persisted state, or every run's state in this worktree."""
    worktree = _resolve_worktree()
    if run_id is not None:
        try:
            _validate_safe_id(run_id, field_name="run_id")
            state = e2e_state.read_state(run_id, worktree=worktree)
        except E2EConfigError as exc:
            _fail_from_error(exc)
            return
        _echo_json(state.model_dump(mode="json"))
        raise SystemExit(EXIT_SUCCESS)

    try:
        run_ids = e2e_state.list_run_ids(worktree=worktree)
    except E2EConfigError as exc:
        _fail_from_error(exc)
        return

    states: list[dict[str, Any]] = []
    for candidate in run_ids:
        with contextlib.suppress(E2EConfigError):
            states.append(e2e_state.read_state(candidate, worktree=worktree).model_dump(mode="json"))
    _echo_json({"runs": states})
    raise SystemExit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


@e2e.command("logs")
@click.argument("run_id")
@click.option("--tail", "tail_lines", type=int, default=None, help="Only print the last N lines.")
def logs_command(run_id: str, tail_lines: Optional[int]) -> None:
    """Print one run's captured target log (spec §2: ``artifacts/logs/e2e/<run-id>/``)."""
    worktree = _resolve_worktree()
    try:
        _validate_safe_id(run_id, field_name="run_id")
        state = e2e_state.read_state(run_id, worktree=worktree)
    except E2EConfigError as exc:
        _fail_from_error(exc)
        return

    log_path = Path(state.log_path)
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        _fail(f"log file unavailable: {log_path}: {exc}", exit_code=EXIT_CONFIG, reason_code="log_unavailable")
        return

    lines = text.splitlines()
    if tail_lines is not None and tail_lines >= 0:
        lines = lines[-tail_lines:]
    for line in lines:
        click.echo(line)
    raise SystemExit(EXIT_SUCCESS)


# ---------------------------------------------------------------------------
# down
# ---------------------------------------------------------------------------


async def _stop_owned_run(run_id: str, *, worktree: Path, owner_id: str) -> dict[str, Any]:
    """Idempotently stop one run, refusing a cross-owner teardown.

    Args:
        run_id: The run's stable ID.
        worktree: The owning worktree root.
        owner_id: The invoking caller's own identity; must match the run's
            recorded owner.

    Returns:
        A small summary mapping (``run_id``/``status``/``cleanup_complete``).

    Raises:
        E2EConfigError: If ``run_id`` has no persisted state, or its
            recorded owner disagrees with ``owner_id`` (spec §2: "Require
            explicit owner scoping"; never a cross-owner kill).
    """
    state = e2e_state.read_state(run_id, worktree=worktree)
    if state.owner_id != owner_id:
        raise E2EConfigError(
            f"run {run_id!r} is owned by {state.owner_id!r}, not {owner_id!r}; refusing cross-owner teardown",
            reason_code="foreign_owner",
        )
    supervisor = E2ESupervisor(worktree=worktree, owner_id=owner_id, feature_id=state.feature_id)
    final_state = await supervisor.stop(run_id)
    return {"run_id": run_id, "status": final_state.status, "cleanup_complete": final_state.cleanup_complete}


async def _down_all_owned(*, worktree: Path, owner_id: str) -> list[dict[str, Any]]:
    """Stop every run owned by ``owner_id`` in this worktree."""
    results: list[dict[str, Any]] = []
    for candidate in e2e_state.list_run_ids(worktree=worktree):
        try:
            state = e2e_state.read_state(candidate, worktree=worktree)
        except E2EConfigError:
            continue
        if state.owner_id != owner_id:
            continue
        results.append(await _stop_owned_run(candidate, worktree=worktree, owner_id=owner_id))
    return results


async def _down_stale(*, worktree: Path, owner_id: str) -> list[dict[str, Any]]:
    """Reconcile every stale, owner-matching run in this worktree (spec §2's documented recovery path)."""
    results: list[dict[str, Any]] = []
    for candidate in e2e_state.list_run_ids(worktree=worktree):
        try:
            state = e2e_state.read_state(candidate, worktree=worktree)
        except E2EConfigError:
            continue
        if state.owner_id != owner_id or state.cleanup_complete or not e2e_state.is_stale(state):
            continue
        final_state = await e2e_watchdog.reconcile_stale_run(candidate, worktree=worktree)
        results.append(
            {"run_id": candidate, "status": final_state.status, "cleanup_complete": final_state.cleanup_complete}
        )
    return results


@e2e.command("down")
@click.argument("run_id", required=False)
@click.option("--all", "all_owned", is_flag=True, default=False, help="Stop every run owned by --owner-id.")
@click.option(
    "--stale",
    "stale_only",
    is_flag=True,
    default=False,
    help="Reconcile every stale owned run (spec §2's recovery path).",
)
@click.option("--owner-id", "owner_id", default=None, help="Owner identity; defaults to the invoking runner identity.")
def down_command(run_id: Optional[str], all_owned: bool, stale_only: bool, owner_id: Optional[str]) -> None:
    """Idempotently terminate one run, every owned run, or every stale owned run."""
    selectors = [value for value in (run_id is not None, all_owned, stale_only) if value]
    if len(selectors) != 1:
        _fail(
            "exactly one of RUN_ID, --all or --stale is required",
            exit_code=EXIT_CONFIG,
            reason_code="down_selector_invalid",
        )
        return

    worktree = _resolve_worktree()
    owner = owner_id or _default_owner_id()
    try:
        owner = _validate_safe_id(owner, field_name="owner_id")
        if run_id is not None:
            _validate_safe_id(run_id, field_name="run_id")
    except E2EConfigError as exc:
        _fail_from_error(exc)
        return

    async def _run() -> list[dict[str, Any]]:
        if run_id is not None:
            return [await _stop_owned_run(run_id, worktree=worktree, owner_id=owner)]
        if all_owned:
            return await _down_all_owned(worktree=worktree, owner_id=owner)
        return await _down_stale(worktree=worktree, owner_id=owner)

    try:
        results = asyncio.run(_run())
    except E2EError as exc:
        _fail_from_error(exc)
        return
    except Exception as exc:  # pragma: no cover - defensive, unexpected collaborator failure
        logger.exception("unexpected failure tearing down run(s)")
        _fail(f"unexpected failure tearing down run(s): {exc}", exit_code=EXIT_FAILURE)
        return

    _echo_json({"runs": results})
    if any(not entry.get("cleanup_complete", False) for entry in results):
        raise SystemExit(EXIT_FAILURE)
    raise SystemExit(EXIT_SUCCESS)


if __name__ == "__main__":
    e2e()
