"""Tests for the packaged SDD procedure manifest (FEAT-891)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import parrot.sdd
from parrot.knowledge.wiki.procedure.producers import load_manifest, manifest_specs
from parrot.knowledge.wiki.procedure.validate import validate_graph
from parrot.sdd.installer import install_sdd_integration, plan_install
from parrot.sdd.scripts import procedure
from parrot.sdd.scripts.procedure_probes import PROBE_COSTS

ASSETS = Path(parrot.sdd.__file__).resolve().parent / "_assets"
PACKAGED = ASSETS / "sdd" / "procedures" / "sdd-workflow.yaml"
REPO_ROOT = Path(__file__).resolve().parents[4]


def _installed(tmp_path: Path) -> Path:
    """Copy the packaged manifest to <tmp>/sdd/procedures/ and return <tmp>."""
    target = tmp_path / "sdd" / "procedures"
    target.mkdir(parents=True)
    shutil.copy(PACKAGED, target / PACKAGED.name)
    return tmp_path


def test_sdd_manifest_valid(tmp_path: Path) -> None:
    """The packaged manifest has no finding at all; every sdd-* command is covered or listed."""
    root = _installed(tmp_path)
    specs, sources = manifest_specs(root)
    listed = set(load_manifest(sources[0], root=root).uncovered_ok)
    commands = sorted(p.stem for p in (ASSETS / "claude" / "commands").glob("sdd-*.md"))
    known = [name for name in commands if name not in listed]
    assert validate_graph(specs, known_probes=PROBE_COSTS, known_commands=known) == []
    assert {spec.id for spec in specs} == {
        "sdd:spec",
        "sdd:task",
        "sdd:worktree-ensure",
        "sdd:start",
        "sdd:task-close",
        "sdd:codereview",
        "sdd:push",
        "sdd:pr-create",
        "sdd:done",
    }
    assert {spec.id for spec in specs if spec.mode == "mandatory"} == {"sdd:task-close", "sdd:pr-create"}
    task_close = next(spec for spec in specs if spec.id == "sdd:task-close")
    assert [guard.kind for guard in task_close.guards].count("entry") == 1
    assert [guard.kind for guard in task_close.guards].count("bypass") == 2


def test_manifest_twin_in_sync() -> None:
    """sdd/procedures/sdd-workflow.yaml equals the packaged asset."""
    source = REPO_ROOT / "sdd" / "procedures" / "sdd-workflow.yaml"
    if not source.is_file():
        pytest.skip("not running from the monorepo checkout")
    assert source.read_bytes() == PACKAGED.read_bytes()


def test_asset_manifest_lists_the_graph() -> None:
    """The asset manifest carries the entry with the three hosts and no seed flag."""
    entries = json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))["assets"]
    entry = next(e for e in entries if e["target"] == "sdd/procedures/sdd-workflow.yaml")
    assert entry == {
        "source": "sdd/procedures/sdd-workflow.yaml",
        "target": "sdd/procedures/sdd-workflow.yaml",
        "hosts": ["claude", "codex", "google"],
    }


def _git_repo(tmp_path: Path) -> Path:
    """Return an initialized repository accepted by the installer."""
    root = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    return root


def test_install_plans_and_builds_index(tmp_path: Path) -> None:
    """The plan ends with procedure-index and install builds the SDD procedure plane."""
    root = _git_repo(tmp_path)

    assert plan_install(root, ["claude"])[-1].action == "procedure-index"

    actions = install_sdd_integration(
        root,
        dangerous_guard=False,
        sdd_coder=False,
        agy_permissions=False,
    )

    index = json.loads((root / ".parrot/procedure/procedures.json").read_text(encoding="utf-8"))
    assert "sdd:task-close" in index["procedures"]
    assert any(action.startswith(".parrot/procedure/procedures.json — built") for action in actions)


def test_install_survives_a_build_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A procedure build failure is reported but does not make installation fail."""
    root = _git_repo(tmp_path)

    async def failing_build(path: Path) -> dict[str, int]:
        raise ValueError("boom")

    monkeypatch.setattr(procedure, "build", failing_build)

    actions = install_sdd_integration(
        root,
        dangerous_guard=False,
        sdd_coder=False,
        agy_permissions=False,
    )

    assert any(action.startswith("procedure index: skipped (ValueError: boom") for action in actions)


def test_dry_run_lists_the_step_and_writes_nothing(tmp_path: Path) -> None:
    """Dry-run lists the derived index step without writing the procedure plane."""
    root = _git_repo(tmp_path)

    actions = install_sdd_integration(
        root,
        dry_run=True,
        dangerous_guard=False,
        sdd_coder=False,
        agy_permissions=False,
    )

    assert actions[-1] == "plan: procedure-index .parrot/procedure/procedures.json"
    assert not (root / ".parrot/procedure").exists()
