"""Tests for the pytest bridge that captures node/phase evidence (FEAT-581, M5).

Every scenario named in this task's Scope ("empty collection, collection
error, deselection, duplicates, teardown failures and required skips") is
exercised through a *real* pytest subprocess -- never faked in-process --
because the behavior under test is pytest's own collection/deselection and
per-phase reporting machinery, which only a real invocation exercises
faithfully. Only the pure, session-independent :func:`load_run_context`
helper is tested in-process.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from pathlib import Path
from typing import Optional

import pytest

from parrot.e2e.errors import E2EConfigError
from parrot.e2e.pytest_plugin import (
    ENV_CONTROL_SOCKET,
    ENV_OWNER_ID,
    ENV_RESULTS_PATH,
    ENV_RUN_ID,
    E2ERunContext,
    load_run_context,
)

_PLUGIN_MODULE = "parrot.e2e.pytest_plugin"
_SUBPROCESS_TIMEOUT_S = 60.0


def _child_env(overrides: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build one subprocess pytest invocation's environment.

    Prepends this process's own ``sys.path`` (plus any existing
    ``PYTHONPATH``) so the child imports this worktree's ``parrot.e2e``
    package rather than whatever the shared venv's editable install points
    at (see ``.claude/rules/worktree-management.md``), then overlays
    ``overrides`` (typically the ``PARROT_E2E_*`` variables under test).
    """
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    entries = [p for p in sys.path if p]
    if existing:
        entries.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(entries))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if overrides:
        env.update(overrides)
    return env


async def _run_pytest(
    cwd: Path,
    args: list[str],
    *,
    env_overrides: Optional[dict[str, str]] = None,
    load_plugin: bool = True,
) -> tuple[int, str, str]:
    """Run one real pytest subprocess and return ``(returncode, stdout, stderr)``."""
    argv = [sys.executable, "-m", "pytest"]
    if load_plugin:
        argv += ["-p", _PLUGIN_MODULE]
    argv += args
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        env=_child_env(env_overrides),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=_SUBPROCESS_TIMEOUT_S)
    assert process.returncode is not None
    return process.returncode, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# load_run_context() -- pure, session-independent (in-process is legitimate here)
# ---------------------------------------------------------------------------


def test_load_run_context_raises_typed_error_listing_every_missing_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_RUN_ID, raising=False)
    monkeypatch.delenv(ENV_OWNER_ID, raising=False)
    monkeypatch.delenv(ENV_CONTROL_SOCKET, raising=False)

    with pytest.raises(E2EConfigError) as exc_info:
        load_run_context()

    assert exc_info.value.reason_code == "run_context_missing"
    message = str(exc_info.value)
    assert ENV_RUN_ID in message
    assert ENV_OWNER_ID in message
    assert ENV_CONTROL_SOCKET in message


def test_load_run_context_raises_when_only_one_variable_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_RUN_ID, "run-1")
    monkeypatch.setenv(ENV_OWNER_ID, "owner-1")
    monkeypatch.delenv(ENV_CONTROL_SOCKET, raising=False)

    with pytest.raises(E2EConfigError) as exc_info:
        load_run_context()

    message = str(exc_info.value)
    assert ENV_CONTROL_SOCKET in message
    assert ENV_RUN_ID not in message
    assert ENV_OWNER_ID not in message


def test_load_run_context_returns_context_when_fully_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    socket_path = tmp_path / "run.sock"
    monkeypatch.setenv(ENV_RUN_ID, "run-1")
    monkeypatch.setenv(ENV_OWNER_ID, "owner-1")
    monkeypatch.setenv(ENV_CONTROL_SOCKET, str(socket_path))

    context = load_run_context()

    assert isinstance(context, E2ERunContext)
    assert context.run_id == "run-1"
    assert context.owner_id == "owner-1"
    assert context.control_socket == socket_path


# ---------------------------------------------------------------------------
# Collection/execution evidence -- real pytest subprocess boundary
# ---------------------------------------------------------------------------


async def test_empty_collection_reports_no_nodes_and_preserves_exit_status(tmp_path: Path) -> None:
    _write(tmp_path / "test_empty.py", "")
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path, ["test_empty.py", "-q"], env_overrides={ENV_RESULTS_PATH: str(results_path)}
    )

    assert returncode == 5  # pytest's own "no tests collected" exit code
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["collected_node_ids"] == []
    assert payload["results"] == []
    assert payload["collection_errors"] == []
    assert payload["exit_status"] == 5


async def test_collection_error_is_recorded_and_never_silently_dropped(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_broken.py",
        "import totally_missing_module_xyz\n\n\ndef test_a():\n    assert True\n",
    )
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path, ["test_broken.py", "-q"], env_overrides={ENV_RESULTS_PATH: str(results_path)}
    )

    assert returncode == 2  # pytest's own "interrupted by collection error" exit code
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["collected_node_ids"] == []
    assert payload["results"] == []
    assert len(payload["collection_errors"]) == 1
    error = payload["collection_errors"][0]
    assert error["nodeid"] == "test_broken.py"
    assert "totally_missing_module_xyz" in error["message"]


async def test_deselection_excludes_the_node_from_collected_but_not_from_reporting(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_x.py",
        "def test_keep():\n    assert True\n\n\ndef test_drop():\n    assert True\n",
    )
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path,
        ["test_x.py", "-k", "not test_drop", "-q"],
        env_overrides={ENV_RESULTS_PATH: str(results_path)},
    )

    assert returncode == 0
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    # A bare file argument (no "::") is never mistaken for a selected node ID.
    assert payload["selected_node_ids"] == []
    assert payload["collected_node_ids"] == ["test_x.py::test_keep"]
    assert [entry["node_id"] for entry in payload["results"]] == ["test_x.py::test_keep"]


async def test_duplicate_selected_node_id_is_preserved_but_collected_once(tmp_path: Path) -> None:
    _write(tmp_path / "test_dup.py", "def test_a():\n    assert True\n")
    results_path = tmp_path / "results.json"
    node_id = "test_dup.py::test_a"

    returncode, _, _ = await _run_pytest(
        tmp_path, [node_id, node_id, "-q"], env_overrides={ENV_RESULTS_PATH: str(results_path)}
    )

    assert returncode == 0
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    # The originating request is reflected verbatim, duplicate included --
    # this plugin never silently collapses what was actually asked for.
    assert payload["selected_node_ids"] == [node_id, node_id]
    # pytest itself collects one item per concrete node ID.
    assert payload["collected_node_ids"] == [node_id]
    assert len(payload["results"]) == 1
    assert payload["results"][0]["outcome"] == "passed"


async def test_teardown_failure_after_a_passing_call_is_never_reported_as_passed(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_teardown.py",
        "def test_bad_teardown(request):\n"
        "    def bad():\n"
        "        raise RuntimeError('teardown boom')\n"
        "    request.addfinalizer(bad)\n"
        "    assert True\n",
    )
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path,
        ["test_teardown.py::test_bad_teardown", "-q"],
        env_overrides={ENV_RESULTS_PATH: str(results_path)},
    )

    assert returncode == 1
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    result = payload["results"][0]
    assert result["call_outcome"] == "passed"
    assert result["teardown_outcome"] == "failed"
    assert result["outcome"] == "failed"
    assert result["longrepr"] and "teardown boom" in result["longrepr"]


async def test_setup_failure_never_reported_as_passed_and_call_phase_never_ran(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_setup.py",
        "import pytest\n\n\n"
        "@pytest.fixture\n"
        "def broken():\n"
        "    raise RuntimeError('fixture boom')\n\n\n"
        "def test_uses_broken_fixture(broken):\n"
        "    assert True\n",
    )
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path,
        ["test_setup.py::test_uses_broken_fixture", "-q"],
        env_overrides={ENV_RESULTS_PATH: str(results_path)},
    )

    assert returncode == 1
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    result = payload["results"][0]
    assert result["setup_outcome"] == "failed"
    assert result["call_outcome"] is None
    assert result["outcome"] == "failed"


async def test_required_skip_and_xfail_never_pass(tmp_path: Path) -> None:
    """Named after the spec §4 unit test table entry for M2/M5.

    pytest itself exits 0 for a run containing only skip/xfail/xpass nodes;
    this bridge's job is to report each node's true outcome so the
    runner/verifier can still refuse to treat any of them as satisfied
    required coverage (spec §2).
    """
    _write(
        tmp_path / "test_skip_xfail.py",
        "import pytest\n\n\n"
        "def test_skipped():\n"
        "    pytest.skip('not ready')\n\n\n"
        "@pytest.mark.xfail(reason='known issue')\n"
        "def test_expected_fail():\n"
        "    assert False\n\n\n"
        "@pytest.mark.xfail(reason='known issue')\n"
        "def test_unexpected_pass():\n"
        "    assert True\n",
    )
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path, ["test_skip_xfail.py", "-q"], env_overrides={ENV_RESULTS_PATH: str(results_path)}
    )

    assert returncode == 0
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    outcomes = {entry["node_id"].rsplit("::", 1)[-1]: entry["outcome"] for entry in payload["results"]}
    assert outcomes == {
        "test_skipped": "skipped",
        "test_expected_fail": "xfailed",
        "test_unexpected_pass": "xpassed",
    }
    assert all(outcome != "passed" for outcome in outcomes.values())


async def test_run_id_and_owner_id_are_recorded_in_the_report_when_supplied(tmp_path: Path) -> None:
    _write(tmp_path / "test_ok.py", "def test_a():\n    assert True\n")
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path,
        ["test_ok.py", "-q"],
        env_overrides={
            ENV_RESULTS_PATH: str(results_path),
            ENV_RUN_ID: "run-xyz",
            ENV_OWNER_ID: "owner-xyz",
        },
    )

    assert returncode == 0
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-xyz"
    assert payload["owner_id"] == "owner-xyz"


async def test_run_id_and_owner_id_are_null_when_not_supplied(tmp_path: Path) -> None:
    _write(tmp_path / "test_ok.py", "def test_a():\n    assert True\n")
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path, ["test_ok.py", "-q"], env_overrides={ENV_RESULTS_PATH: str(results_path)}
    )

    assert returncode == 0
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["run_id"] is None
    assert payload["owner_id"] is None


# ---------------------------------------------------------------------------
# Atomic output and "results path optional" behavior
# ---------------------------------------------------------------------------


async def test_missing_results_path_env_writes_nothing_and_does_not_fail(tmp_path: Path) -> None:
    _write(tmp_path / "test_ok.py", "def test_a():\n    assert True\n")
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(tmp_path, ["test_ok.py", "-q"])

    assert returncode == 0
    assert not results_path.exists()


async def test_results_file_is_written_atomically_mode_0600_with_no_leftover_temp_file(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "test_ok.py", "def test_a():\n    assert True\n")
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path, ["test_ok.py", "-q"], env_overrides={ENV_RESULTS_PATH: str(results_path)}
    )

    assert returncode == 0
    assert results_path.exists()
    mode = stat.S_IMODE(results_path.stat().st_mode)
    assert mode == 0o600
    leftover = list(tmp_path.glob(f".{results_path.name}.*.tmp"))
    assert leftover == []


# ---------------------------------------------------------------------------
# Explicit -p loading only; no client/target creation during collection
# ---------------------------------------------------------------------------


async def test_plugin_never_auto_loads_without_the_explicit_p_flag(tmp_path: Path) -> None:
    _write(tmp_path / "test_ok.py", "def test_a():\n    assert True\n")
    results_path = tmp_path / "results.json"

    returncode, _, _ = await _run_pytest(
        tmp_path,
        ["test_ok.py", "-q"],
        env_overrides={ENV_RESULTS_PATH: str(results_path)},
        load_plugin=False,
    )

    assert returncode == 0
    assert not results_path.exists()


async def test_run_context_fixture_is_a_clear_error_when_context_is_absent(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_needs_context.py",
        "def test_uses_context(e2e_run_context):\n    assert e2e_run_context.run_id\n",
    )

    returncode, stdout, stderr = await _run_pytest(tmp_path, ["test_needs_context.py", "-q"])

    assert returncode == 1
    combined = stdout + stderr
    assert "E2EConfigError" in combined
    assert ENV_RUN_ID in combined
    assert ENV_OWNER_ID in combined
    assert ENV_CONTROL_SOCKET in combined


async def test_run_context_fixture_never_evaluated_at_collection_time(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_needs_context.py",
        "def test_uses_context(e2e_run_context):\n    assert e2e_run_context.run_id\n",
    )

    # Absent context would fail fixture *setup*; --collect-only never
    # reaches setup, so collection alone must succeed regardless.
    returncode, stdout, stderr = await _run_pytest(tmp_path, ["test_needs_context.py", "--collect-only", "-q"])

    assert returncode == 0
    assert "error" not in (stdout + stderr).lower()


async def test_control_client_fixture_is_constructed_without_opening_a_connection(tmp_path: Path) -> None:
    _write(
        tmp_path / "test_client.py",
        "from parrot.e2e.control import ControlClient\n\n\n"
        "def test_client_type(e2e_control_client):\n"
        "    assert isinstance(e2e_control_client, ControlClient)\n",
    )
    # Deliberately never bound: if the fixture tried to connect, this test
    # would fail with a connection error instead of passing.
    unbound_socket = tmp_path / "never-bound.sock"

    returncode, stdout, stderr = await _run_pytest(
        tmp_path,
        ["test_client.py", "-q"],
        env_overrides={
            ENV_RUN_ID: "run-1",
            ENV_OWNER_ID: "owner-1",
            ENV_CONTROL_SOCKET: str(unbound_socket),
        },
    )

    assert returncode == 0, stdout + stderr
    assert not unbound_socket.exists()
