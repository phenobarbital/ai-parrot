"""Behavioral acceptance tests for Core AgentMemoryToolkit and lazy CLI operations."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from parrot.mcp.toolkit_config import ToolkitSection
from parrot.memory.agent_memory.toolkit import AgentMemoryToolkit
from parrot.memory.dynamics.cli import register_memory_commands


def _config(path: Path, *, user_memory: bool = False) -> dict[str, Any]:
    """Return explicit serialized configuration for an isolated store."""
    return {
        "enable_episodic_memory": True,
        "enable_user_memory": user_memory,
        "memory_dynamics": True,
        "storage_path": str(path),
    }


def _namespace(*, tenant_id: str = "tenant-operations", user_id: str | None = None) -> dict[str, Any]:
    """Return an explicit trusted serialized namespace."""
    return {
        "tenant_id": tenant_id,
        "agent_id": "agent-operations",
        "user_id": user_id,
        "session_id": "session-operations" if user_id is not None else None,
    }


@pytest.mark.asyncio
async def test_explicit_yaml_lazy_construct_close_reopen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify explicit YAML construction is lazy and close permits a clean reopen."""
    database_path = tmp_path / "memory.sqlite3"
    section = ToolkitSection.model_validate(
        {
            "class": "parrot.memory.agent_memory.toolkit.AgentMemoryToolkit",
            "kwargs": {"config": _config(database_path), "namespace": _namespace()},
        }
    )
    module_name, class_name = section.class_path.rsplit(".", 1)
    toolkit_class = getattr(importlib.import_module(module_name), class_name)
    toolkit = toolkit_class(**section.kwargs)

    assert isinstance(toolkit, AgentMemoryToolkit)
    assert toolkit._manager is None
    assert toolkit._opened is False
    assert database_path.exists() is False

    first_status = await toolkit.memory_status()
    assert first_status["capabilities"]["episodic"] is True
    assert database_path.exists() is True
    assert toolkit._opened is True

    await toolkit._close()
    assert toolkit._manager is None
    assert toolkit._opened is False

    second_status = await toolkit.memory_status()
    assert second_status == first_status
    assert toolkit._opened is True
    await toolkit._close()

    async def fail_to_open(*args: Any, **kwargs: Any) -> Any:
        """Simulate a factory failure after its own partial-resource unwind."""
        raise RuntimeError("open failed")

    monkeypatch.setattr("parrot.memory.agent_memory.toolkit.create_memory_manager", fail_to_open)
    failed = AgentMemoryToolkit(config=_config(tmp_path / "failed.sqlite3"), namespace=_namespace())
    with pytest.raises(RuntimeError, match="open failed"):
        await failed.memory_status()
    assert failed._manager is None
    assert failed._opened is False


@pytest.mark.asyncio
async def test_cli_scope_and_evidence_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify fixed scope, trusted evidence, shared-root import and profile opt-in."""
    toolkit = AgentMemoryToolkit(config=_config(tmp_path / "episodic.sqlite3"), namespace=_namespace())
    assert "memory_forget" not in toolkit.list_tool_names()

    cross_scope_signal = {
        "outcome_id": "outcome-operations",
        "outcome_revision": 0,
        "observed_at": "2026-11-16T12:00:00Z",
        "scope": {
            "tenant_id": "other-tenant",
            "agent_id": "agent-operations",
            "turn_id": "turn-operations",
            "identity_provenance": "server_resolved",
        },
        "evidence_ref": "coder-review/v1/execution-1/TASK-5678/attempt-1",
        "source": "coder_engine",
        "outcome": "success",
        "first_attempt": True,
        "correction_count": 0,
        "passed_check_ids": ["pytest:test_operations"],
    }
    with pytest.raises(ValueError, match="does not match"):
        await toolkit.memory_review([], cross_scope_signal, "exposure-operations")

    supplied_grade = dict(cross_scope_signal, grade=4)
    with pytest.raises(ValidationError):
        await toolkit.memory_review([], supplied_grade, "exposure-operations")

    shared_root = tmp_path / "main-checkout"
    observed: dict[str, Any] = {}

    async def fake_import(root: Path, *, store: Any, namespace: Any) -> dict[str, int]:
        """Capture root and scope without reading a shared ledger fixture."""
        observed.update(root=root, store=store, namespace=namespace)
        return {"imported": 1, "skipped": 0, "retracted": 0}

    monkeypatch.setattr("parrot.memory.agent_memory.toolkit.find_shared_root", lambda _cwd: shared_root)
    monkeypatch.setattr("parrot.memory.agent_memory.toolkit.import_feedback", fake_import)
    imported = await toolkit.memory_import_feedback()
    assert imported == {"imported": 1, "skipped": 0, "retracted": 0}
    assert observed["root"] == shared_root
    assert observed["namespace"].tenant_id == "tenant-operations"
    await toolkit._close()

    user_toolkit = AgentMemoryToolkit(
        config=_config(tmp_path / "user.sqlite3", user_memory=True),
        namespace=_namespace(user_id="user-operations"),
    )
    assert "memory_forget" in user_toolkit.list_tool_names()
    receipt = await user_toolkit.memory_forget(
        {
            "event_id": "forget-operations",
            "knowledge_id": "unknown-knowledge",
            "expected_revision": 0,
            "operation": "forget",
        }
    )
    assert receipt["status"] == "ignored"
    await user_toolkit._close()


def test_jsonrpc_stdout_and_no_optimizer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify command registration is pure, JSON output is clean and fitting is absent."""
    from parrot.knowledge.wiki.cli import wiki

    assert "memory" in wiki.commands
    assert capsys.readouterr().out == ""

    @click.group()
    def root() -> None:
        """Test command root."""

    register_memory_commands(root)
    assert capsys.readouterr().out == ""
    memory = root.commands["memory"]
    assert isinstance(memory, click.Group)
    assert set(memory.commands) == {
        "status",
        "recall",
        "cite",
        "review",
        "forget",
        "sync",
        "import-feedback",
        "export-reviews",
    }
    assert "fit" not in memory.commands

    result = CliRunner().invoke(
        root,
        [
            "memory",
            "--storage-path",
            str(tmp_path / "cli.sqlite3"),
            "--tenant-id",
            "tenant-cli",
            "--agent-id",
            "agent-cli",
            "status",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["namespace"]["tenant_id"] == "tenant-cli"
    assert payload["namespace"]["agent_id"] == "agent-cli"
    assert payload["capabilities"] == {
        "brain": False,
        "dynamics": True,
        "episodic": True,
        "user_memory": False,
    }


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (OSError("disk unavailable"), "Error: OSError: disk unavailable"),
        (RuntimeError("SQLiteEpisodeBackend is not configured"), "Error: RuntimeError: SQLiteEpisodeBackend is not"),
        (ValueError("limit must be positive"), "Error: limit must be positive"),
        (click.ClickException("episodic memory is not enabled"), "Error: episodic memory is not enabled"),
    ],
)
def test_memory_cli_reports_unexpected_failures_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: Exception, message: str
) -> None:
    """A failing command exits non-zero with one error line that names an unexpected failure's type."""

    async def failing_status(self: AgentMemoryToolkit) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr(AgentMemoryToolkit, "memory_status", failing_status)

    @click.group()
    def root() -> None:
        """Test command root."""

    register_memory_commands(root)
    result = CliRunner().invoke(
        root,
        ["memory", "--storage-path", str(tmp_path / "cli.sqlite3"), "--agent-id", "agent-cli", "status"],
    )

    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert result.output.strip().startswith(message)
    assert len(result.output.strip().splitlines()) == 1
    assert "Traceback" not in result.output


@pytest.mark.asyncio
async def test_sync_observes_backend_health_and_unknown_capabilities(tmp_path: Path) -> None:
    """Sync never claims success for missing capabilities, degraded vectors or closed storage."""
    from types import SimpleNamespace

    toolkit = AgentMemoryToolkit(config=_config(tmp_path / "sync.db"), namespace=_namespace())
    try:
        healthy = await toolkit.memory_sync()
        assert healthy == {"status": "synchronized", "replayed": 0, "durable_pending_reviews": 0}
        manager = toolkit._manager
        backend = manager.episodic._backend
        manager.episodic._backend = SimpleNamespace()
        unknown = await toolkit.memory_sync()
        assert unknown["status"] != "synchronized"
        assert unknown["durable_pending_reviews"] is None
        manager.episodic._backend = backend
        original_status = backend.vector_status

        async def degraded(namespace_filter: dict[str, Any]) -> dict[str, Any]:
            """Expose the measured vector ceiling degradation."""
            return {"status": "degraded"}

        backend.vector_status = degraded
        assert (await toolkit.memory_sync())["status"] == "degraded"
        backend.vector_status = original_status
        await backend.close()
        with pytest.raises(RuntimeError, match="not configured"):
            await toolkit.memory_sync()
    finally:
        await toolkit._close()
