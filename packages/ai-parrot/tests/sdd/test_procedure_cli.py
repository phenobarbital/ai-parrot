"""Tests for ``parrot sdd procedure`` (FEAT-891)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure.models import INDEX_FILE, PLANE_DIR
from parrot.knowledge.wiki.procedure.producers import MANIFEST_DIR
from parrot.sdd.cli import VERBS, mounted_modules
from parrot.sdd.config import ProcedureSettings, SddConfig
from parrot.sdd.scripts import procedure

MANIFEST = """\
schema_version: 1
graph: sdd
procedures:
  - {id: spec, title: Write the spec, kind: command, command: "/sdd-spec <slug>", done_when: [{probe: spec.exists}], next: [task]}
  - {id: task, title: Decompose, kind: command, command: "/sdd-task <spec>", requires_procedures: [spec], done_when: [{probe: index.exists}]}
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a repository with one valid procedure manifest and make it current."""
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    manifest = root / MANIFEST_DIR / "demo.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(MANIFEST, encoding="utf-8")
    monkeypatch.chdir(root)
    return root


def test_cli_verbs(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Build, list, show, and check work, and the noun is mounted in VERBS."""
    assert "procedure" in mounted_modules()
    assert {"build", "list", "show", "check"} <= set(VERBS["procedure"])

    assert procedure.main(["build"]) == 0
    assert (repo / PLANE_DIR / INDEX_FILE).is_file()
    capsys.readouterr()

    assert procedure.main(["list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in listed] == ["sdd:spec", "sdd:task"]

    assert procedure.main(["show", "sdd:task"]) == 0
    assert "id: sdd:task" in capsys.readouterr().out
    assert procedure.main(["show", "sdd:nope"]) == 1
    assert "unknown procedure: sdd:nope" in capsys.readouterr().err
    assert procedure.main(["check"]) == 0


@pytest.mark.parametrize(
    "broken_manifest",
    [
        """schema_version: 1
graph: sdd
procedures:
  - {id: one, title: One, kind: command, next: [missing]}
""",
        """schema_version: 1
graph: sdd
procedures:
  - {id: one, title: One, kind: command, requires_procedures: [two]}
  - {id: two, title: Two, kind: command, requires_procedures: [one]}
""",
        """schema_version: 1
graph: sdd
procedures:
  - {id: one, title: One, kind: command, done_when: [{probe: missing}]}
""",
    ],
    ids=("broken-edge", "requires-cycle", "unknown-probe"),
)
def test_check_fails_on_graph_errors(repo: Path, broken_manifest: str) -> None:
    """A broken edge, requires cycle, or unknown probe makes check and build exit 1."""
    (repo / MANIFEST_DIR / "demo.yaml").write_text(broken_manifest, encoding="utf-8")

    assert procedure.main(["check"]) == 1
    assert procedure.main(["build"]) == 1
    assert not (repo / PLANE_DIR / INDEX_FILE).exists()


def test_list_rebuilds_a_stale_plane(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """After a manifest edit, list rebuilds and shows the new node."""
    assert procedure.main(["build"]) == 0
    capsys.readouterr()
    manifest = repo / MANIFEST_DIR / "demo.yaml"
    manifest.write_text(
        MANIFEST
        + "  - {id: done, title: Finish, kind: command, command: \"/sdd-done <feature>\", requires_procedures: [task]}\n",
        encoding="utf-8",
    )

    assert procedure.main(["list", "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in listed] == ["sdd:done", "sdd:spec", "sdd:task"]


def test_sdd_config_procedure_section() -> None:
    """Procedure config is optional, accepts known settings, and rejects unknown keys."""
    assert SddConfig().procedure is None
    assert SddConfig.model_validate({"procedure": {"enforce": False}}).procedure == ProcedureSettings(enforce=False)
    with pytest.raises(ValueError):
        SddConfig.model_validate({"procedure": {"nope": 1}})


def test_invalid_config_warns_and_uses_defaults(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A corrupt config warns once and does not prevent a procedure command."""
    config = repo / "sdd" / "config.json"
    config.write_text("{not json", encoding="utf-8")

    assert procedure.main(["check", "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err.count("warning:") == 1
    assert isinstance(json.loads(captured.out), list)
