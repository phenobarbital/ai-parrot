"""Unit tests for ``parrot.e2e.targets`` (TASK-3525, M4).

Covers ``LaunchSpec`` construction/rejection, its env redaction contract
(``repr``/``str``/``model_dump``/``model_dump_json``), its argv-without-shell
execution contract via real subprocesses (process-boundary behavior is
never faked), the ``TargetAdapter`` protocol's runtime-checkable shape, and
the lazy fixed registry's success/failure/import-scoping behavior.

No concrete target module (``parrot.e2e.targets.{mcp,botmanager,ui,
browser}``) exists yet in this checkout — the "missing optional
implementation" prerequisite-failure path is exercised against the real,
current repository state for every one of the six target kinds, with no
mocking required. Only the "module exists but the factory disagrees"
sub-cases inject a synthetic ``sys.modules`` entry, and always through
``monkeypatch.setitem``/``monkeypatch.setattr`` so it is undone automatically.
"""

from __future__ import annotations

import subprocess
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.e2e.errors import EXIT_BLOCKED, EXIT_CONFIG, E2EConfigError, E2EPrerequisiteError
from parrot.e2e.models import RunState, TargetConfig
from parrot.e2e.targets import TARGET_KINDS, TargetAdapter, get_target_adapter
from parrot.e2e.targets.base import LaunchSpec

# ---------------------------------------------------------------------------
# LaunchSpec — construction / rejection
# ---------------------------------------------------------------------------


def test_launch_spec_constructs_successfully(tmp_path: Path) -> None:
    spec = LaunchSpec(argv=["true"], env={"FOO": "bar"}, cwd=tmp_path, stdio=True)
    assert spec.argv == ["true"]
    assert spec.env == {"FOO": "bar"}
    assert spec.cwd == tmp_path
    assert spec.stdio is True


def test_launch_spec_defaults_env_empty_and_stdio_false(tmp_path: Path) -> None:
    spec = LaunchSpec(argv=["true"], cwd=tmp_path)
    assert spec.env == {}
    assert spec.stdio is False


def test_launch_spec_rejects_empty_argv(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        LaunchSpec(argv=[], cwd=tmp_path)


def test_launch_spec_rejects_empty_argv_token(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        LaunchSpec(argv=["true", ""], cwd=tmp_path)


def test_launch_spec_rejects_unknown_field(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        LaunchSpec(argv=["true"], cwd=tmp_path, unexpected="nope")


# ---------------------------------------------------------------------------
# LaunchSpec — env redaction (repr/str/serialization)
# ---------------------------------------------------------------------------


def test_launch_spec_repr_and_str_redact_env(tmp_path: Path) -> None:
    spec = LaunchSpec(argv=["true"], env={"API_KEY": "super-secret-value"}, cwd=tmp_path)
    assert "super-secret-value" not in repr(spec)
    assert "super-secret-value" not in str(spec)
    assert "redacted:1 keys" in repr(spec)


def test_launch_spec_model_dump_redacts_env_values_but_keeps_keys(tmp_path: Path) -> None:
    spec = LaunchSpec(argv=["true"], env={"API_KEY": "super-secret-value"}, cwd=tmp_path)
    dumped = spec.model_dump()
    assert "API_KEY" in dumped["env"]
    assert dumped["env"]["API_KEY"] != "super-secret-value"
    assert "super-secret-value" not in repr(dumped)


def test_launch_spec_model_dump_json_redacts_env(tmp_path: Path) -> None:
    spec = LaunchSpec(argv=["true"], env={"API_KEY": "super-secret-value"}, cwd=tmp_path)
    dumped_json = spec.model_dump_json()
    assert "super-secret-value" not in dumped_json
    assert "API_KEY" in dumped_json


# ---------------------------------------------------------------------------
# LaunchSpec — real subprocess, argv execution without shell (process boundary)
# ---------------------------------------------------------------------------


def test_launch_spec_argv_runs_literally_without_shell_expansion(tmp_path: Path) -> None:
    """A shell metacharacter embedded in one argv token stays literal.

    Under ``shell=True`` this ``;`` would separate two commands; under a
    direct ``argv`` exec (this ``LaunchSpec``'s only intended usage) ``echo``
    receives it as one literal argument.
    """
    marker_file = tmp_path / "should-not-exist"
    spec = LaunchSpec(argv=["echo", f"hello; touch {marker_file}"], cwd=tmp_path)

    result = subprocess.run(spec.argv, cwd=spec.cwd, capture_output=True, text=True, shell=False, check=True)

    assert result.stdout.strip() == f"hello; touch {marker_file}"
    assert not marker_file.exists()


def test_launch_spec_missing_executable_fails_closed_without_shell_fallback(tmp_path: Path) -> None:
    """A nonexistent executable raises directly — no ``/bin/sh`` ever runs it.

    Under ``shell=True`` a missing command does not raise in Python; the
    shell itself prints "command not found" and returns a nonzero exit
    code. Raising ``FileNotFoundError`` here is exactly the argv-without-
    shell contract this ``LaunchSpec`` is built for.
    """
    spec = LaunchSpec(argv=["this-binary-does-not-exist-anywhere-xyz"], cwd=tmp_path)

    with pytest.raises(FileNotFoundError):
        subprocess.run(spec.argv, cwd=spec.cwd, shell=False)


# ---------------------------------------------------------------------------
# TargetAdapter — runtime-checkable protocol shape
# ---------------------------------------------------------------------------


class _ConformingAdapter:
    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        return LaunchSpec(argv=["true"], cwd=worktree)

    async def ready(self, state: RunState) -> bool:
        return True


class _MissingReadyAdapter:
    async def prepare(self, config: TargetConfig, *, run_id: str, worktree: Path) -> LaunchSpec:
        return LaunchSpec(argv=["true"], cwd=worktree)


def test_target_adapter_protocol_accepts_conforming_shape() -> None:
    assert isinstance(_ConformingAdapter(), TargetAdapter)


def test_target_adapter_protocol_rejects_incomplete_shape() -> None:
    assert not isinstance(_MissingReadyAdapter(), TargetAdapter)


# ---------------------------------------------------------------------------
# Registry — fixed target kinds
# ---------------------------------------------------------------------------


def test_target_kinds_matches_spec_six_public_kinds() -> None:
    assert TARGET_KINDS == frozenset({"mcp-toolkit", "mcp-stdio", "mcp-agent", "botmanager", "ui", "browser"})
    assert len(TARGET_KINDS) == 6


# ---------------------------------------------------------------------------
# Registry — unknown kind
# ---------------------------------------------------------------------------


def test_get_target_adapter_rejects_unknown_kind() -> None:
    with pytest.raises(E2EConfigError) as excinfo:
        get_target_adapter("not-a-real-kind")
    assert excinfo.value.exit_code == EXIT_CONFIG
    assert excinfo.value.reason_code == "unknown_target_kind"


# ---------------------------------------------------------------------------
# Registry — missing optional implementation (real repository state, no mock)
# ---------------------------------------------------------------------------


_STILL_UNIMPLEMENTED_KINDS = sorted(TARGET_KINDS - {"mcp-toolkit", "mcp-stdio", "botmanager"})


@pytest.mark.parametrize("kind", _STILL_UNIMPLEMENTED_KINDS)
def test_get_target_adapter_raises_prerequisite_error_for_unimplemented_kind(kind: str) -> None:
    """Every kind whose adapter module genuinely does not exist yet in this checkout.

    `mcp-toolkit`/`mcp-stdio` are excluded here since TASK-3529 implemented
    real adapters for them in `parrot.e2e.targets.mcp` (see
    `test_mcp_targets.py` for their own prerequisite-error-free coverage).
    `botmanager` is excluded since TASK-3530 implemented a real adapter in
    `parrot.e2e.targets.botmanager` (see `test_botmanager_target.py`).
    """
    with pytest.raises(E2EPrerequisiteError) as excinfo:
        get_target_adapter(kind)
    assert excinfo.value.exit_code == EXIT_BLOCKED
    assert excinfo.value.reason_code == "target_adapter_unavailable"


def test_get_target_adapter_only_imports_the_requested_module(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolving one kind must never attempt to import a different kind's module."""
    import importlib

    calls: list[str] = []
    real_import_module = importlib.import_module

    def _spy_import_module(name: str, *args: object, **kwargs: object) -> types.ModuleType:
        calls.append(name)
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr("parrot.e2e.targets.importlib.import_module", _spy_import_module)

    with pytest.raises(E2EPrerequisiteError):
        get_target_adapter("browser")

    assert calls == ["parrot.e2e.targets.browser"]


# ---------------------------------------------------------------------------
# Registry — module resolves but is missing the expected factory attribute
# ---------------------------------------------------------------------------


def test_get_target_adapter_raises_prerequisite_error_for_missing_factory_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_module = types.ModuleType("parrot.e2e.targets.botmanager")
    monkeypatch.setitem(sys.modules, "parrot.e2e.targets.botmanager", fake_module)

    with pytest.raises(E2EPrerequisiteError) as excinfo:
        get_target_adapter("botmanager")

    assert excinfo.value.exit_code == EXIT_BLOCKED
    assert excinfo.value.reason_code == "target_adapter_unavailable"


# ---------------------------------------------------------------------------
# Registry — success path (synthetic module injected via sys.modules)
# ---------------------------------------------------------------------------


def test_get_target_adapter_returns_adapter_from_injected_module(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = types.ModuleType("parrot.e2e.targets.mcp")
    fake_module.build_mcp_toolkit_adapter = lambda: _ConformingAdapter()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "parrot.e2e.targets.mcp", fake_module)

    adapter = get_target_adapter("mcp-toolkit")

    assert isinstance(adapter, TargetAdapter)
    assert isinstance(adapter, _ConformingAdapter)
