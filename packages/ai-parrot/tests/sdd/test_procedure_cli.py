"""Tests for ``parrot sdd procedure`` (FEAT-891)."""

from __future__ import annotations

import json
import asyncio
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


def _write_skill(path: Path, name: str, procedure_fields: str = "  mode: advisory\n") -> None:
    """Write a real parser-compatible skill with optional procedure metadata."""
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = f"procedure:\n{procedure_fields}" if procedure_fields else ""
    path.write_text(
        f"---\nname: {name}\ndescription: {name}\ntriggers: []\n{metadata}---\nPerform {name}.\n",
        encoding="utf-8",
    )


def test_skill_build_check_and_discovery_invalidation(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Both skill layouts reach CLI output, and source changes invalidate both readers."""
    from parrot.knowledge.wiki.procedure.index import is_stale, read_index
    from parrot.sdd.scripts.procedure_advice import _fresh_sources

    _write_skill(repo / "skills/first.md", "first", "  next: [second, sdd:spec]\n")
    _write_skill(repo / "skills/second/SKILL.md", "second")
    _write_skill(repo / "skills/learned/lesson.md", "lesson", "  mode: mandatory\n  confirm: true\n")
    _write_skill(repo / "skills/plain.md", "plain", "")
    assert procedure.main(["build"]) == 0
    capsys.readouterr()
    assert procedure.main(["list", "--json"]) == 0
    specs = {item["id"]: item for item in json.loads(capsys.readouterr().out)}
    assert specs["skill:first"]["next"] == ["skill:second", "sdd:spec"]
    assert specs["skill:lesson"]["mode"] == "advisory"
    assert not specs["skill:lesson"]["confirm"]
    assert "skill:plain" not in specs
    assert procedure.main(["check"]) == 0
    index = read_index(repo / PLANE_DIR)
    assert not is_stale(index, root=repo)
    assert _fresh_sources(repo, index)

    _write_skill(repo / "skills/plain.md", "plain")
    assert is_stale(index, root=repo)
    assert not _fresh_sources(repo, index)
    assert procedure.main(["build"]) == 0
    index = read_index(repo / PLANE_DIR)
    _write_skill(repo / "skills/new/SKILL.md", "new")
    assert is_stale(index, root=repo)
    assert not _fresh_sources(repo, index)
    assert procedure.main(["build"]) == 0
    index = read_index(repo / PLANE_DIR)
    (repo / "skills/new/SKILL.md").unlink()
    assert is_stale(index, root=repo)
    assert not _fresh_sources(repo, index)

    _write_skill(repo / "skills/first.md", "first", "  next: [missing]\n")
    assert procedure.main(["check"]) == 1
    assert procedure.main(["build"]) == 1


def test_configured_skill_directories(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Custom locations are discovered and a configuration change expires the index."""
    from parrot.knowledge.wiki.procedure.index import is_stale, read_index
    from parrot.sdd.scripts.procedure_advice import _fresh_sources

    (repo / "sdd/config.json").write_text('{"procedure":{"skill_directories":[".agents/skills"]}}')
    _write_skill(repo / ".agents/skills/custom/SKILL.md", "custom")
    assert procedure.main(["build"]) == 0
    capsys.readouterr()
    assert procedure.main(["show", "skill:custom", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "skill:custom"
    index = read_index(repo / PLANE_DIR)
    (repo / "sdd/config.json").write_text('{"procedure":{"skill_directories":[]}}')
    assert is_stale(index, root=repo)
    assert not _fresh_sources(repo, index)


def test_engine_procedure_briefing(
    repo: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Engine matches CLI output, uses local probes, and is silent on unavailable planes."""
    from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, _FeatureCtx
    from parrot.flows.dev_loop.sdd_coder.models import PlannedTask, RosterConfig, RosterSeat
    from parrot.knowledge.wiki.procedure.plane import ProcedurePlane

    task_file = _seed_feature(repo)
    manifest = repo / MANIFEST_DIR / "demo.yaml"
    manifest.write_text(
        MANIFEST + "  - {id: remote, title: Push, kind: command, preconditions: [{probe: branch.pushed}]}\n"
    )
    engine = SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="native", kind="native")]))
    ctx = _FeatureCtx(str(repo), "FEAT-1", "demo", "feat-FEAT-1-demo", "", "", "dev")
    task = PlannedTask(task_id="TASK-1", task_file=str(task_file), seat_label="native")

    def briefing() -> str:
        """Run the real async briefing method from this synchronous CLI test."""
        return asyncio.run(engine._procedure_briefing_for(ctx, task))

    assert briefing() == ""
    assert procedure.main(["build"]) == 0
    capsys.readouterr()

    def no_remote(*args: object, **kwargs: object) -> None:
        """Remote subprocess probes are forbidden in task context."""
        raise AssertionError("remote probe invoked")

    monkeypatch.setattr("parrot.sdd.scripts.procedure_probes.subprocess.run", no_remote)
    assert procedure.main(["brief", "--task-file", str(task_file)]) == 0
    expected = capsys.readouterr().out.rstrip("\n")
    assert expected.startswith("### Procedure\n")
    assert briefing() == expected
    (repo / "sdd/config.json").write_text('{"procedure":{"enabled":false}}')
    assert briefing() == ""
    (repo / "sdd/config.json").write_text('{"procedure":{"brief_max_lines":2}}')
    assert len(briefing().splitlines()) == 2
    manifest.write_text(MANIFEST)
    assert briefing() == ""  # Engine never rebuilds a stale shared plane.
    assert procedure.main(["build"]) == 0

    async def broken_specs(self: ProcedurePlane) -> list[ProcedureSpec]:
        """Exercise the advisory failure boundary."""
        raise OSError("unreadable plane")

    monkeypatch.setattr(ProcedurePlane, "specs", broken_specs)
    assert briefing() == ""

    async def cancelled_specs(self: ProcedurePlane) -> list[ProcedureSpec]:
        """Cancellation must propagate rather than become an empty successful result."""
        raise asyncio.CancelledError

    monkeypatch.setattr(ProcedurePlane, "specs", cancelled_specs)
    with pytest.raises(asyncio.CancelledError):
        briefing()


def test_engine_uses_task_worktree_state(repo: Path, tmp_path: Path) -> None:
    """Shared plane definitions resolve against the task checkout, not the primary checkout."""
    from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine, _FeatureCtx
    from parrot.flows.dev_loop.sdd_coder.models import PlannedTask, RosterConfig, RosterSeat

    _seed_feature(repo)
    assert procedure.main(["build"]) == 0
    worktree = tmp_path / "task-worktree"
    worktree.mkdir()
    admin = repo / ".git/worktrees/task-worktree"
    admin.mkdir(parents=True)
    (admin / "commondir").write_text("../..\n")
    (admin / "HEAD").write_text("ref: refs/heads/feat-FEAT-1-demo\n")
    (worktree / ".git").write_text(f"gitdir: {admin}\n")
    engine = SddCoderEngine(roster=RosterConfig(seats=[RosterSeat(label="native", kind="native")]))
    task = PlannedTask(task_id="TASK-1", task_file="sdd/tasks/active/TASK-1-demo.md", seat_label="native")
    ctx = _FeatureCtx(str(worktree), "FEAT-1", "demo", "feat-FEAT-1-demo", "", "", "dev")
    text = asyncio.run(engine._procedure_briefing_for(ctx, task))
    assert "Write the spec" in text
    assert "Decompose" not in text
    _seed_feature(worktree)
    text = asyncio.run(engine._procedure_briefing_for(ctx, task))
    assert "Decompose" in text
    assert "Write the spec" not in text


def test_cross_producer_duplicate_is_rejected(repo: Path) -> None:
    """A manifest cannot silently overwrite a skill with the same qualified id."""
    _write_skill(repo / "skills/review.md", "review")
    (repo / MANIFEST_DIR / "demo.yaml").write_text(
        MANIFEST + "  - {id: 'skill:review', title: Collision, kind: command}\n"
    )
    assert procedure.main(["build"]) == 1
    assert procedure.main(["check"]) == 1
