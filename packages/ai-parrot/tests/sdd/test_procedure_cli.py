"""Tests for ``parrot sdd procedure`` (FEAT-891)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.knowledge.wiki.procedure.models import (
    INDEX_FILE,
    PLANE_DIR,
    ProbeCheck,
    ProbeResult,
    ProcedureSpec,
    ResolvedProcedure,
    Resolution,
)
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
    """Build, list, show, next, check, and brief are mounted in VERBS."""
    assert "procedure" in mounted_modules()
    assert set(VERBS["procedure"]) == {"build", "list", "show", "next", "check", "brief"}

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
        + '  - {id: done, title: Finish, kind: command, command: "/sdd-done <feature>", requires_procedures: [task]}\n',
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


def _seed_feature(root: Path, *, status: str = "pending") -> Path:
    """Write a feature spec, task index, and task file and return the task file."""
    spec = root / "sdd" / "specs" / "demo.spec.md"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text("# Demo\n", encoding="utf-8")
    index = root / "sdd" / "tasks" / "index" / "demo.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"tasks": [{"id": "TASK-1", "status": status}]}), encoding="utf-8")
    task_file = root / "sdd" / "tasks" / "active" / "TASK-1-demo.md"
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text("# TASK-1: Demo\n\n**Spec**: `sdd/specs/demo.spec.md`\n", encoding="utf-8")
    return task_file


def test_next_reports_the_valid_step(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Unchanged procedure state resolves deterministically to the valid next node."""
    _seed_feature(repo)
    assert procedure.main(["build"]) == 0
    capsys.readouterr()

    assert procedure.main(["next", "--feature", "demo", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert procedure.main(["next", "--feature", "demo", "--json"]) == 0
    second = json.loads(capsys.readouterr().out)

    assert first == second
    assert [item["spec"]["id"] for item in first["next"]] == ["sdd:task"]


def test_next_no_remote_marks_remote_probes_unknown(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-remote mode reports remote results as unknown without running subprocesses."""
    (repo / MANIFEST_DIR / "demo.yaml").write_text(
        MANIFEST
        + '  - {id: remote, title: Remote, kind: command, command: "git push", preconditions: [{probe: branch.pushed}]}\n',
        encoding="utf-8",
    )
    assert procedure.main(["build"]) == 0
    capsys.readouterr()

    def fail_subprocess(*args: object, **kwargs: object) -> None:
        """Fail if a remote probe attempts a subprocess."""
        raise AssertionError("remote subprocess must not run")

    monkeypatch.setattr("parrot.sdd.scripts.procedure_probes.subprocess.run", fail_subprocess)
    assert procedure.main(["next", "--feature", "demo", "--no-remote", "--json"]) == 0
    resolution = json.loads(capsys.readouterr().out)
    remote = next(item for item in resolution["next"] if item["spec"]["id"] == "sdd:remote")
    assert remote["preconditions"] == [
        {
            "check": {"probe": "branch.pushed", "expect": True, "args": {}},
            "value": None,
            "cost": "remote",
            "detail": "remote probes are disabled",
        }
    ]


def test_brief_prints_block_or_nothing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Brief returns zero and emits either its block or no output."""
    task_file = _seed_feature(repo)
    (repo / MANIFEST_DIR / "demo.yaml").write_text(
        MANIFEST
        + '  - {id: start, title: Start, kind: command, command: "/sdd-start TASK-1", requires_procedures: [task]}\n',
        encoding="utf-8",
    )
    assert procedure.main(["build"]) == 0
    capsys.readouterr()

    assert procedure.main(["brief", "--task-file", str(task_file)]) == 0
    assert capsys.readouterr().out.startswith("### Procedure\n")

    config = repo / "sdd" / "config.json"
    config.write_text('{"procedure": {"enabled": false}}', encoding="utf-8")
    assert procedure.main(["brief", "--task-file", str(task_file)]) == 0
    assert capsys.readouterr().out == ""

    config.unlink()
    (repo / PLANE_DIR / INDEX_FILE).unlink()
    assert procedure.main(["brief", "--task-file", str(task_file)]) == 0
    assert capsys.readouterr().out == ""


def test_render_brief_limits_lines() -> None:
    """Brief rendering is bounded and has no output for an empty resolution."""
    check = ProbeCheck(probe="task.status", expect="in-progress")
    next_spec = ProcedureSpec(id="sdd:start", title="Start", kind="command", command="/sdd-start TASK-1")
    resolution = Resolution(
        scope={"feature": "demo", "task": "TASK-1"},
        stale=False,
        next=[
            ResolvedProcedure(
                spec=next_spec,
                done=False,
                ready=True,
                preconditions=[ProbeResult(check=check, value=None, cost="local")],
            )
        ],
        mandatory=[
            ProcedureSpec(
                id="sdd:close",
                title="Close",
                kind="command",
                mode="mandatory",
                command="parrot sdd task close TASK-1 demo verified",
                use_instead="parrot sdd task close TASK-1 demo verified",
            )
        ],
    )
    brief = procedure.render_brief(resolution, max_lines=8)
    assert "unmet: task.status=in-progress" in brief
    assert "never by hand; use `parrot sdd task close TASK-1 demo verified`" in brief
    assert len(procedure.render_brief(resolution, max_lines=2).splitlines()) <= 2
    assert procedure.render_brief(Resolution(scope={}, stale=False, next=[], mandatory=[]), max_lines=8) == ""
