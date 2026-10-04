"""Pytest bridge that captures exact node and phase evidence (FEAT-581, M5).

Implements the spec §3 "M5: Pytest bridge and deterministic scenarios"
contract:

    plugin loaded explicitly with ``-p parrot.e2e.pytest_plugin``, run ID
    and control socket supplied in env by the runner. No auto-loading
    dependency that changes every existing pytest run.

This module is registered on the command line only -- there is no
``pytest11`` entry point in ``ai-parrot-server``'s packaging metadata, so an
ordinary ``pytest`` invocation never loads it. The (not-yet-implemented) M3
:mod:`parrot.e2e.runner` is the intended caller: it invokes pytest as a
subprocess with ``-p parrot.e2e.pytest_plugin`` and the environment
variables below, then reads the JSON file this plugin writes to build a
:class:`parrot.e2e.models.E2EVerdict`.

Environment contract (supplied by the runner, never guessed or defaulted):

- ``PARROT_E2E_RUN_ID`` / ``PARROT_E2E_OWNER_ID`` / ``PARROT_E2E_CONTROL_SOCKET``
  -- this run's identifiers and its private control-channel socket path
  (:mod:`parrot.e2e.control`). Only consumed lazily, by :func:`load_run_context`
  and the fixtures built on it (:func:`e2e_run_context`, :func:`e2e_control_client`)
  -- never read eagerly at collection time, so a plain pytest run that merely
  imports this plugin (e.g. this module's own unit tests) never fails just
  because the context is absent. A test that *depends on* one of these
  fixtures without the runner having supplied the context gets one clear,
  typed :class:`parrot.e2e.errors.E2EConfigError` at fixture setup -- never a
  bare ``KeyError``, never a silently constructed, unusable client.
- ``PARROT_E2E_RESULTS_PATH`` -- where :func:`pytest_sessionfinish` atomically
  writes this session's structured bridge report (schema below). Optional:
  if unset, this plugin still runs (useful for exercising it standalone,
  as this module's own tests do) but writes nothing.

Bridge report JSON schema (schema_version 1), written atomically (temp file
in the same directory, ``fsync``ed, then ``os.replace``d onto the final
path, mode 0600 -- mirrors :func:`parrot.e2e.state.write_state`'s convention):

.. code-block:: json

    {
      "schema_version": 1,
      "run_id": "<PARROT_E2E_RUN_ID, or null>",
      "owner_id": "<PARROT_E2E_OWNER_ID, or null>",
      "argv": ["<the exact invocation_params.args pytest was started with>"],
      "selected_node_ids": ["<every '::'-node-id token in argv, duplicates preserved>"],
      "collected_node_ids": ["<node IDs that survived collection/deselection, i.e. actually ran>"],
      "collection_errors": [{"nodeid": "...", "message": "..."}],
      "results": [
        {
          "node_id": "...",
          "outcome": "passed|failed|skipped|xfailed|xpassed",
          "setup_outcome": "passed|failed|skipped|null",
          "call_outcome": "passed|failed|skipped|null",
          "teardown_outcome": "passed|failed|skipped|null",
          "duration_s": 0.0,
          "longrepr": "<truncated failure text, or null>"
        }
      ],
      "counts": {"passed": 1, "failed": 0},
      "exit_status": 0,
      "started_at": "<ISO-8601 UTC>",
      "completed_at": "<ISO-8601 UTC>"
    }

``selected_node_ids`` deliberately means "every explicit node ID token this
pytest invocation was started with" (matching
:class:`parrot.e2e.models.E2EVerdict.selected_node_ids` -- "Node IDs the plan
selected for this run"), while ``collected_node_ids`` means "node IDs that
actually survived collection and deselection" (pytest's own final
``session.items``, i.e. what it is about to run/ran -- matching
``E2EVerdict.collected_node_ids``, which :func:`parrot.e2e.evidence.verify_evidence`
requires to be a subset of ``selected_node_ids``). A duplicated token in the
originating invocation is preserved verbatim in ``selected_node_ids`` (this
plugin never silently collapses what the runner actually asked for), while
``collected_node_ids`` naturally has no duplicates -- pytest itself collects
one item per concrete node ID. This plugin never invents a "blocked" or
"missing" outcome for a node: those are the runner's/verifier's own
judgement (comparing ``selected`` against ``collected`` and against the
plan's required coverage), not something observable from inside one pytest
session.

A required node that is skipped, xfailed, or whose ``teardown`` phase fails
after a passing ``call`` is *never* silently reported as passed -- a
teardown failure overrides an otherwise-passing ``call`` outcome to
``"failed"`` (spec §2 "Required skips, xfails, zero collection or unresolved
teardown never count as PASS.", also enforced by
:func:`parrot.e2e.evidence.verify_evidence`).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest

from parrot.e2e.control import ControlClient
from parrot.e2e.errors import E2EConfigError

__all__ = [
    "ENV_RUN_ID",
    "ENV_OWNER_ID",
    "ENV_CONTROL_SOCKET",
    "ENV_RESULTS_PATH",
    "RESULTS_FILE_MODE",
    "E2ERunContext",
    "load_run_context",
    "e2e_run_context",
    "e2e_control_client",
]

logger = logging.getLogger(__name__)

# spec §3 M5: "run ID and control socket supplied in env by the runner."
ENV_RUN_ID = "PARROT_E2E_RUN_ID"
ENV_OWNER_ID = "PARROT_E2E_OWNER_ID"
ENV_CONTROL_SOCKET = "PARROT_E2E_CONTROL_SOCKET"
# This plugin's own choice, not fixed by the spec: where pytest_sessionfinish
# atomically writes the structured bridge report described in this module's
# own docstring.
ENV_RESULTS_PATH = "PARROT_E2E_RESULTS_PATH"

# Mirrors parrot.e2e.state.STATE_FILE_MODE's convention for a worktree-local
# E2E artifact: readable/writable by its owner only.
RESULTS_FILE_MODE = 0o600

# A defensive ceiling on captured failure text -- this bridge report is a
# machine artifact consumed by the runner/verifier, not a full pytest log.
_MAX_LONGREPR_CHARS = 4000

_PHASE_ATTRS = {"setup": "setup_outcome", "call": "call_outcome", "teardown": "teardown_outcome"}


def _truncate(text: str) -> str:
    """Bound one captured failure representation to a fixed character ceiling.

    Args:
        text: The raw ``str(report.longrepr)`` text.

    Returns:
        ``text`` unchanged if short enough, otherwise truncated with a
        trailing marker.
    """
    if len(text) <= _MAX_LONGREPR_CHARS:
        return text
    return text[:_MAX_LONGREPR_CHARS] + "... [truncated]"


@dataclass(frozen=True)
class E2ERunContext:
    """The run/control identifiers the E2E runner supplies via environment.

    Attributes:
        run_id: This run's stable ID (:class:`parrot.e2e.models.RunState.run_id`).
        owner_id: This run's owner identity.
        control_socket: Path to this run's private Unix control socket
            (:mod:`parrot.e2e.control`).
    """

    run_id: str
    owner_id: str
    control_socket: Path


def load_run_context() -> E2ERunContext:
    """Read the run/control context the E2E runner supplies via environment.

    Called lazily -- only when a "runner-specific" fixture that depends on
    it is actually requested by a test -- never eagerly at collection time,
    so this plugin never starts a target or opens a control connection just
    because it was loaded.

    Returns:
        The validated :class:`E2ERunContext`.

    Raises:
        E2EConfigError: If one or more of ``PARROT_E2E_RUN_ID``,
            ``PARROT_E2E_OWNER_ID`` or ``PARROT_E2E_CONTROL_SOCKET`` is
            absent from the environment -- a clear, typed error naming
            exactly what is missing, never a bare ``KeyError`` and never a
            fixture that silently proceeds with a guessed value.
    """
    missing = [name for name in (ENV_RUN_ID, ENV_OWNER_ID, ENV_CONTROL_SOCKET) if not os.environ.get(name)]
    if missing:
        raise E2EConfigError(
            "E2E run/control context is missing required environment variable(s) "
            f"{missing!r}. This fixture requires pytest to be invoked by the "
            "parrot.e2e runner (-p parrot.e2e.pytest_plugin plus these variables), "
            "not a plain pytest run.",
            reason_code="run_context_missing",
        )
    return E2ERunContext(
        run_id=os.environ[ENV_RUN_ID],
        owner_id=os.environ[ENV_OWNER_ID],
        control_socket=Path(os.environ[ENV_CONTROL_SOCKET]),
    )


@pytest.fixture(scope="session")
def e2e_run_context() -> E2ERunContext:
    """Session-scoped runner-supplied run/control context.

    Returns:
        The :class:`E2ERunContext` read from environment.

    Raises:
        E2EConfigError: See :func:`load_run_context`.
    """
    return load_run_context()


@pytest.fixture(scope="session")
def e2e_control_client(e2e_run_context: E2ERunContext) -> ControlClient:
    """Session-scoped control-channel client bound to this run's context.

    Constructing a :class:`~parrot.e2e.control.ControlClient` only stores
    identifiers -- it never opens a socket connection until a test calls
    :meth:`~parrot.e2e.control.ControlClient.request`. Combined with this
    fixture's own lazy (test-setup-time, never collection-time) construction,
    no control connection -- let alone a target -- is ever created merely
    because this plugin is loaded.

    Args:
        e2e_run_context: This run's context (see :func:`e2e_run_context`).

    Returns:
        A :class:`~parrot.e2e.control.ControlClient` for this run.
    """
    return ControlClient(
        e2e_run_context.control_socket,
        run_id=e2e_run_context.run_id,
        owner_id=e2e_run_context.owner_id,
    )


@dataclass
class _NodeState:
    """Mutable per-node accumulator for one pytest session's phase reports.

    Attributes:
        node_id: The pytest node ID this state describes.
        setup_outcome: ``setup`` phase outcome, if a report was seen.
        call_outcome: ``call`` phase outcome, if a report was seen.
        teardown_outcome: ``teardown`` phase outcome, if a report was seen.
        wasxfail: Whether the ``call`` report carried an ``xfail`` marker
            (pytest sets a ``wasxfail`` attribute on the report in that case).
        duration_s: Sum of every observed phase's wall-clock duration.
        longrepr: Truncated failure text from the first failing phase seen,
            if any.
    """

    node_id: str
    setup_outcome: Optional[str] = None
    call_outcome: Optional[str] = None
    teardown_outcome: Optional[str] = None
    wasxfail: bool = False
    duration_s: float = 0.0
    longrepr: Optional[str] = None

    def outcome(self) -> str:
        """Classify this node's final outcome from its recorded phases.

        A ``setup``/``teardown`` failure -- including a teardown failure
        *after* a passing ``call`` -- always classifies as ``"failed"``,
        never silently as passed (spec §2 "unresolved teardown never counts
        as PASS"). A ``call`` outcome carrying an ``xfail`` marker
        classifies as ``"xfailed"``/``"xpassed"`` rather than plain
        ``"skipped"``/``"passed"``.

        Returns:
            One of ``"passed"``, ``"failed"``, ``"skipped"``, ``"xfailed"``
            or ``"xpassed"``.
        """
        if self.setup_outcome == "failed" or self.teardown_outcome == "failed":
            return "failed"
        if self.setup_outcome == "skipped":
            return "skipped"
        if self.call_outcome == "failed":
            return "failed"
        if self.call_outcome == "passed":
            return "xpassed" if self.wasxfail else "passed"
        if self.call_outcome == "skipped":
            return "xfailed" if self.wasxfail else "skipped"
        # Defensive: no phase was ever observed passing/skipping for this
        # node (an unexpected pytest internal shape) -- never default to a
        # silent pass.
        return "failed"

    def to_dict(self) -> dict[str, Any]:
        """Render this node's evidence as the bridge report's per-node shape."""
        return {
            "node_id": self.node_id,
            "outcome": self.outcome(),
            "setup_outcome": self.setup_outcome,
            "call_outcome": self.call_outcome,
            "teardown_outcome": self.teardown_outcome,
            "duration_s": round(self.duration_s, 6),
            "longrepr": self.longrepr,
        }


@dataclass
class _BridgeState:
    """Accumulates one pytest session's exact node/phase evidence.

    A fresh instance is installed by :func:`pytest_configure` for every
    session -- this module is stateless between independent pytest process
    invocations (each subprocess the runner starts gets its own Python
    process and therefore its own module-level state; there is no
    cross-session bleed to guard against).
    """

    started_at: Optional[datetime] = None
    selected_node_ids: list[str] = field(default_factory=list)
    collected_node_ids: list[str] = field(default_factory=list)
    collection_errors: list[dict[str, str]] = field(default_factory=list)
    nodes: dict[str, _NodeState] = field(default_factory=dict)

    def node(self, node_id: str) -> _NodeState:
        """Return this node's accumulator, creating it on first reference."""
        state = self.nodes.get(node_id)
        if state is None:
            state = _NodeState(node_id=node_id)
            self.nodes[node_id] = state
        return state


_state = _BridgeState()


def pytest_configure(config: pytest.Config) -> None:
    """Install a fresh :class:`_BridgeState` for this session.

    Args:
        config: The pytest configuration object (unused beyond the standard
            hook signature -- this plugin reads its context lazily via
            environment variables, never from ``config``).
    """
    del config  # unused: context comes from environment, read lazily.
    global _state
    _state = _BridgeState()


def pytest_sessionstart(session: pytest.Session) -> None:
    """Record the session start time and the raw invocation's node-ID tokens.

    ``selected_node_ids`` is derived from ``session.config.invocation_params.args``
    -- the exact argv this pytest process was started with -- filtered to
    tokens that look like an explicit pytest node ID (contain ``::`` and do
    not start with ``-``, so an option's own value is never mistaken for a
    positional node ID). Duplicates are preserved verbatim: this plugin
    never silently collapses what was actually requested.

    Args:
        session: The pytest session being started.
    """
    _state.started_at = datetime.now(timezone.utc)
    _state.selected_node_ids = [
        arg
        for arg in session.config.invocation_params.args
        if isinstance(arg, str) and not arg.startswith("-") and "::" in arg
    ]


def pytest_collectreport(report: pytest.CollectReport) -> None:
    """Record a failed collection report (e.g. a broken test module import).

    A collection error never produces a ``session.items`` entry, so it would
    otherwise vanish from this bridge's evidence entirely; recording it here
    lets the runner/verifier distinguish "nothing was collected because
    nothing exists" from "nothing was collected because collection itself
    failed" -- both must be treated as BLOCKED/FAIL, never PASS.

    Args:
        report: The collection report pytest is announcing.
    """
    if report.failed:
        message = _truncate(str(report.longrepr)) if report.longrepr else "collection failed"
        _state.collection_errors.append({"nodeid": report.nodeid or "<collection>", "message": message})


def pytest_collection_finish(session: pytest.Session) -> None:
    """Record the final, post-deselection set of node IDs pytest will run.

    Fires once collection and every ``pytest_collection_modifyitems`` hook
    (including built-in ``-k``/``-m``/``--deselect`` filtering) has already
    run, so ``session.items`` here is exactly what pytest is about to
    execute -- matching :class:`parrot.e2e.models.E2EVerdict.collected_node_ids`.

    Args:
        session: The pytest session whose collection just finished.
    """
    _state.collected_node_ids = [item.nodeid for item in session.items]


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Accumulate one test node's per-phase (setup/call/teardown) evidence.

    Args:
        report: The phase report pytest is announcing.
    """
    node = _state.node(report.nodeid)
    node.duration_s += report.duration
    attr = _PHASE_ATTRS.get(report.when)
    if attr is not None:
        setattr(node, attr, report.outcome)
    if report.when == "call" and hasattr(report, "wasxfail"):
        node.wasxfail = True
    if report.failed and report.longrepr:
        node.longrepr = _truncate(str(report.longrepr))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Atomically write this session's structured bridge report, if configured.

    A no-op (beyond a debug log line) when ``PARROT_E2E_RESULTS_PATH`` is
    unset -- this plugin never fails an ordinary pytest run (including its
    own unit tests) just because no output path was requested.

    Args:
        session: The finishing pytest session.
        exitstatus: pytest's own overall exit status for this session.
    """
    results_path_value = os.environ.get(ENV_RESULTS_PATH)
    if not results_path_value:
        logger.debug("%s is not set; skipping structured pytest bridge output", ENV_RESULTS_PATH)
        return

    completed_at = datetime.now(timezone.utc)
    started_at = _state.started_at or completed_at

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for node in sorted(_state.nodes.values(), key=lambda n: n.node_id):
        entry = node.to_dict()
        results.append(entry)
        counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1

    payload: dict[str, Any] = {
        "schema_version": 1,
        "run_id": os.environ.get(ENV_RUN_ID),
        "owner_id": os.environ.get(ENV_OWNER_ID),
        "argv": list(session.config.invocation_params.args),
        "selected_node_ids": _state.selected_node_ids,
        "collected_node_ids": _state.collected_node_ids,
        "collection_errors": _state.collection_errors,
        "results": results,
        "counts": counts,
        "exit_status": int(exitstatus),
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }
    _write_atomic(Path(results_path_value), payload)


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` as JSON atomically, mode 0600.

    Writes to a temporary file in the same directory, ``fsync``s it, then
    ``os.replace``s it onto ``path`` -- mirrors
    :func:`parrot.e2e.state.write_state`'s atomic-replacement convention, so
    a concurrent reader (the runner) never observes a partially-written
    file.

    Args:
        path: Destination path (created if its parent directory is missing).
        payload: JSON-serializable bridge report.
    """
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, RESULTS_FILE_MODE)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
