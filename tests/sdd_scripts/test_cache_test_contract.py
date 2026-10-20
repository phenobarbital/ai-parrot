"""Tests for scripts/sdd/cache_test_contract.py (FEAT-699)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.sdd import cache_test_contract as cli

_SPEC = """# Spec

## 4. Test Specification

### Validation Contract

{body}

## 5. Next
"""
_CONTRACT = "tests:\n- tests/a/test_x.py\nmarkers: none"


def _setup(tmp_path: Path, body: str, index: dict | None = None) -> tuple[Path, Path]:
    spec = tmp_path / "s.spec.md"
    spec.write_text(_SPEC.format(body=body), encoding="utf-8")
    idx = tmp_path / "i.json"
    idx.write_text(
        json.dumps(index or {"feature": "f", "validation_contract": "required", "base_branch": "dev", "tasks": []}),
        encoding="utf-8",
    )
    return spec, idx


def test_cache_is_idempotent(tmp_path: Path) -> None:
    spec, idx = _setup(tmp_path, _CONTRACT)
    assert cli.main(["--spec", str(spec), "--index", str(idx)]) == 0
    first = idx.read_bytes()
    data = json.loads(first)
    assert data["test_contract"]["schema"] == 2
    assert [r["kind"] for r in data["test_contract"]["runners"]] == ["pytest"]
    assert data["test_contract"]["runners"][0]["targets"] == ["tests/a/test_x.py"]
    keys = list(data)
    assert keys.index("test_contract") == keys.index("validation_contract") + 1
    assert cli.main(["--spec", str(spec), "--index", str(idx)]) == 0
    assert idx.read_bytes() == first
    assert cli.main(["--spec", str(spec), "--index", str(idx), "--check"]) == 0


def test_fallback_removes_key(tmp_path: Path, capsys) -> None:
    spec, idx = _setup(tmp_path, "none — fallback", {"base_branch": "dev", "test_contract": {"x": 1}, "tasks": []})
    assert cli.main(["--spec", str(spec), "--index", str(idx)]) == 0
    assert "test_contract" not in json.loads(idx.read_text())
    assert "fallback" in capsys.readouterr().out


def test_malformed_exits_2_without_write(tmp_path: Path) -> None:
    spec, idx = _setup(tmp_path, "garbage line")
    before = idx.read_bytes()
    assert cli.main(["--spec", str(spec), "--index", str(idx)]) == 2
    assert idx.read_bytes() == before


def test_check_detects_drift(tmp_path: Path) -> None:
    spec, idx = _setup(tmp_path, _CONTRACT)
    before = idx.read_bytes()
    assert cli.main(["--spec", str(spec), "--index", str(idx), "--check"]) == 1
    assert idx.read_bytes() == before


def test_after_base_branch_when_no_validation_contract() -> None:
    out = cli._with_contract({"a": 1, "base_branch": "dev", "z": 2}, {"v": 1})
    assert list(out) == ["a", "base_branch", "test_contract", "z"]


_RUNNERS = """runners:
- kind: pytest
  tests:
  - tests/a/test_x.py
  markers: none
- kind: cargo
  crate: crates/demo"""


def test_runners_form_writes_schema_2(tmp_path: Path, monkeypatch) -> None:
    # Adapter settings are validated relative to the current directory (kernel contract).
    (tmp_path / "crates/demo").mkdir(parents=True)
    (tmp_path / "crates/demo/Cargo.toml").write_text("[package]\nname = 'demo'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    spec, idx = _setup(tmp_path, _RUNNERS)
    assert cli.main(["--spec", str(spec), "--index", str(idx), "--root", str(tmp_path)]) == 0
    first = idx.read_bytes()
    payload = json.loads(first)["test_contract"]
    assert payload["schema"] == 2
    assert [r["kind"] for r in payload["runners"]] == ["pytest", "cargo"]
    assert cli.main(["--spec", str(spec), "--index", str(idx), "--root", str(tmp_path), "--check"]) == 0
    assert cli.main(["--spec", str(spec), "--index", str(idx), "--root", str(tmp_path)]) == 0
    assert idx.read_bytes() == first


def test_flat_and_runners_forms_cache_the_same_pytest_contract(tmp_path: Path) -> None:
    flat_dir, runners_dir = tmp_path / "flat", tmp_path / "runners"
    flat_dir.mkdir()
    runners_dir.mkdir()
    spec_a, idx_a = _setup(flat_dir, _CONTRACT)
    spec_b, idx_b = _setup(runners_dir, "runners:\n- kind: pytest\n  tests:\n  - tests/a/test_x.py\n  markers: none")
    assert cli.main(["--spec", str(spec_a), "--index", str(idx_a), "--root", str(flat_dir)]) == 0
    assert cli.main(["--spec", str(spec_b), "--index", str(idx_b), "--root", str(runners_dir)]) == 0
    assert json.loads(idx_a.read_text())["test_contract"] == json.loads(idx_b.read_text())["test_contract"]


def test_unknown_runner_kind_exits_2(tmp_path: Path) -> None:
    spec, idx = _setup(tmp_path, "runners:\n- kind: jest\n  tests:\n  - a.test.ts")
    before = idx.read_bytes()
    assert cli.main(["--spec", str(spec), "--index", str(idx), "--root", str(tmp_path)]) == 2
    assert idx.read_bytes() == before
