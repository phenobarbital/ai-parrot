"""Exit matrix and portability tests for the decision-audit gate (FEAT-784 M9)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.sdd.check_spec_consequences as gate

_SPEC_NO_BLOCK = "# Feature Specification: demo\n\n## 2. Architectural Design\n\ntext\n"
_SPEC_WITH_BLOCK = (
    _SPEC_NO_BLOCK + "\n## Decisions\n\n```yaml\nschema_version: 1\ndocument_id: demo\nentries: []\n```\n"
)


class _Report:
    """Minimal report double exposing the gate's serialized report contract."""

    def __init__(self, status: str, exit_code: int) -> None:
        self.status = status
        self.exit_code = exit_code

    def model_dump(self, *, mode: str) -> dict[str, object]:
        """Return the JSON-compatible consequence-report shape used by the gate."""
        assert mode == "json"
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "input_digest": "input",
            "evaluation_digest": "evaluation",
            "findings": [],
            "diagnostics": [],
            "coverage": {},
            "snapshot": None,
        }


class _CheckResult:
    """Minimal check-result double for selecting the check exit branch."""

    def __init__(self, status: str, report: _Report) -> None:
        self.status = status
        self.report = report


def _write(tmp_path: Path, text: str) -> Path:
    """Write a spec in the conventional temporary repository layout."""
    spec = tmp_path / "sdd/specs/demo.spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(text, encoding="utf-8")
    return spec


def _configured_repo(tmp_path: Path) -> None:
    """Create the minimal configuration marker without opening a wiki store."""
    taxonomy = tmp_path / "sdd/taxonomy/subsystems.yaml"
    taxonomy.parent.mkdir(parents=True, exist_ok=True)
    taxonomy.write_text("subsystems: {}\n", encoding="utf-8")


def _patch_check(monkeypatch: pytest.MonkeyPatch, status: str, check_status: str = "current") -> None:
    """Patch the configured check path with a deterministic report double."""
    report = _Report(status, gate.EXIT_BY_STATUS[status])

    async def fake_check(service: object, spec: Path) -> _CheckResult:
        """Return the test's configured check outcome."""
        assert service is sentinel
        assert spec.name == "demo.spec.md"
        return _CheckResult(check_status, report)

    sentinel = object()
    monkeypatch.setattr(gate, "open_consequence_service", lambda root, *, base_branch: sentinel)
    monkeypatch.setattr(gate, "check_spec", fake_check)


def test_unconfigured_without_block_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A portable repository with no decision block is skipped before store opening."""
    spec = _write(tmp_path, _SPEC_NO_BLOCK)

    def fail_open(root: Path, *, base_branch: str) -> object:
        """Make an incorrect attempt to open the plane observable."""
        raise AssertionError("the unconfigured path must not open a consequence service")

    monkeypatch.setattr(gate, "open_consequence_service", fail_open)
    assert gate.main([str(spec), "--root", str(tmp_path)]) == 0
    assert gate.NOT_CONFIGURED_LINE in capsys.readouterr().out


def test_unconfigured_with_block_is_invalid(tmp_path: Path) -> None:
    """A declared decision block requires configuration."""
    spec = _write(tmp_path, _SPEC_WITH_BLOCK)
    assert gate.main([str(spec), "--root", str(tmp_path)]) == 2


@pytest.mark.parametrize("status,code", [("pass", 0), ("conflict", 1), ("invalid", 2), ("incomplete", 3)])
def test_exit_matrix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str, code: int) -> None:
    """Current reports map directly through the frozen public exit matrix."""
    _configured_repo(tmp_path)
    spec = _write(tmp_path, _SPEC_WITH_BLOCK)
    _patch_check(monkeypatch, status)
    assert gate.main([str(spec), "--root", str(tmp_path)]) == code


def test_stale_and_missing_fail_check_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Persisted sections that are stale or absent are incomplete evidence."""
    _configured_repo(tmp_path)
    spec = _write(tmp_path, _SPEC_WITH_BLOCK)
    _patch_check(monkeypatch, "pass", "stale")
    assert gate.main([str(spec), "--root", str(tmp_path)]) == 3
    _patch_check(monkeypatch, "pass", "missing")
    assert gate.main([str(spec), "--root", str(tmp_path)]) == 3


def test_advisory_never_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Advisory mode warns only for contrary reports and never blocks its caller."""
    _configured_repo(tmp_path)
    spec = _write(tmp_path, _SPEC_WITH_BLOCK)
    _patch_check(monkeypatch, "conflict")
    assert gate.main([str(spec), "--root", str(tmp_path), "--advisory"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "warning:" in captured.err

    _patch_check(monkeypatch, "pass", "missing")
    assert gate.main([str(spec), "--root", str(tmp_path), "--advisory"]) == 0
    assert capsys.readouterr().err == ""

    unconfigured = _write(tmp_path / "portable", _SPEC_NO_BLOCK)
    assert gate.main([str(unconfigured), "--root", str(tmp_path / "portable"), "--advisory"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_operational_failure_is_never_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Configured operational errors only downgrade under advisory mode."""
    _configured_repo(tmp_path)
    spec = _write(tmp_path, _SPEC_WITH_BLOCK)

    def fail_open(root: Path, *, base_branch: str) -> object:
        """Raise the representative operational failure."""
        raise RuntimeError("wiki plane unavailable")

    monkeypatch.setattr(gate, "open_consequence_service", fail_open)
    assert gate.main([str(spec), "--root", str(tmp_path)]) == 3
    assert gate.main([str(spec), "--root", str(tmp_path), "--advisory"]) == 0


def test_json_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """JSON check output contains the complete report payload plus check state."""
    _configured_repo(tmp_path)
    spec = _write(tmp_path, _SPEC_WITH_BLOCK)
    _patch_check(monkeypatch, "pass")
    assert gate.main([str(spec), "--root", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {
        "status",
        "exit_code",
        "input_digest",
        "evaluation_digest",
        "findings",
        "diagnostics",
        "coverage",
        "snapshot",
        "check",
    } <= payload.keys()
