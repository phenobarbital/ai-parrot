"""Tests for scripts/sdd/check_asset_sync.py (FEAT-633 M6, spec §4 test_asset_sync_check)."""

from __future__ import annotations

import json
import subprocess
import tomllib
import zipfile
from pathlib import Path

import pytest

from scripts.sdd import check_asset_sync as cas

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A git repo with one source per host family, committed (sources must be git-tracked)."""
    for rel in (".claude/commands/sdd-spec.md", ".agents/skills/sdd-spec/SKILL.md",
                ".agent/workflows/sdd-spec.md", "sdd/templates/task.md", "sdd/WORKFLOW.md"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {rel}\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def _run(repo: Path, *flags: str) -> int:
    return cas.main([*flags, "--root", str(repo), "--assets-dir", str(repo / "assets")])


def test_write_then_check_is_clean(mini_repo: Path) -> None:
    assert _run(mini_repo, "--write") == 0
    assert _run(mini_repo, "--check") == 0
    manifest = json.loads((mini_repo / "assets" / "manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert {"source": "sdd/sdd_templates/task.md", "target": "sdd/templates/task.md",
            "hosts": ["claude", "codex", "google"]} in manifest["assets"]


def test_divergence_missing_and_extra_fail(mini_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _run(mini_repo, "--write")
    (mini_repo / ".claude/commands/sdd-spec.md").write_text("changed\n")      # diverged
    (mini_repo / "assets/agent/workflows/sdd-spec.md").unlink()                 # missing
    (mini_repo / "assets/claude/stray.md").write_text("x")                       # extra
    assert _run(mini_repo, "--check") == 1
    err = capsys.readouterr().err
    assert "diverged: claude/commands/sdd-spec.md" in err
    assert "missing: agent/workflows/sdd-spec.md" in err
    assert "extra: claude/stray.md" in err


def test_untracked_source_is_not_packaged(mini_repo: Path) -> None:
    (mini_repo / "sdd/templates/untracked.json").write_text("{}")
    _run(mini_repo, "--write")
    assert not (mini_repo / "assets/sdd/sdd_templates/untracked.json").exists()


def test_check_wheel_reports_missing_entry(tmp_path: Path) -> None:
    wheel = tmp_path / "ai_parrot-0-py3-none-any.whl"
    manifest = {"schema_version": 1, "assets": [{"source": "claude/commands/a.md", "target": ".claude/commands/a.md", "hosts": ["claude"]}]}
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(cas.WHEEL_PREFIX + "manifest.json", json.dumps(manifest))
    assert cas.check_wheel(wheel) == [f"missing in wheel: {cas.WHEEL_PREFIX}claude/commands/a.md"]


@pytest.mark.parametrize("planted", ["sdd/state/FEAT-1/notes.md", "sdd/ledger/issues.jsonl", ".parrot/wiki.db",
                                     "sdd/tasks/.id_ledger.json", "sdd/references/x.md"])
def test_check_wheel_rejects_forbidden_paths(tmp_path: Path, planted: str) -> None:
    """C11d: a complete manifest does not excuse a forbidden file in the asset tree."""
    wheel = tmp_path / "ai_parrot-0-py3-none-any.whl"
    manifest = {"schema_version": 1, "assets": [{"source": "sdd/WORKFLOW.md", "target": "sdd/WORKFLOW.md", "hosts": ["claude"]}]}
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(cas.WHEEL_PREFIX + "manifest.json", json.dumps(manifest))
        zf.writestr(cas.WHEEL_PREFIX + "sdd/WORKFLOW.md", "# ok\n")
        zf.writestr(cas.WHEEL_PREFIX + planted, "secret\n")
    assert cas.check_wheel(wheel) == [f"forbidden in wheel: {cas.WHEEL_PREFIX}{planted}"]


@pytest.mark.parametrize(
    "line",
    [
        "run packages/ai-parrot/src/x.py",  # C16
        "see tests/sdd_scripts/test_x.py",  # C22 second pattern
        'eval "$(python -c "from navconfig import config")"',
        "PYTHONPATH=src pytest",
        "read reference/sdd-insight/x.md",
    ],
)
def test_monorepo_path_is_reported(mini_repo: Path, capsys: pytest.CaptureFixture[str], line: str) -> None:
    """C16 + C22: a shipped source line matching either pattern fails --check."""
    (mini_repo / "sdd/WORKFLOW.md").write_text(line + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=mini_repo, check=True)
    _run(mini_repo, "--write")
    assert _run(mini_repo, "--check") == 1
    assert f"monorepo-path: sdd/WORKFLOW.md:1: {line}" in capsys.readouterr().err


def test_allowlisted_hook_line_passes_and_insight_never_ships(mini_repo: Path) -> None:
    """C22 D: the single allowlisted hook line is not a finding; C22: /sdd-insight is never packaged."""
    (target, text), = cas.MONOREPO_PATH_ALLOWLIST
    for rel, body in ((target, text + "\n"), (".claude/commands/sdd-insight.md", "# insight\n")):
        (mini_repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (mini_repo / rel).write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=mini_repo, check=True)
    assert _run(mini_repo, "--write") == 0
    assert _run(mini_repo, "--check") == 0
    targets = {e["target"] for e in json.loads((mini_repo / "assets" / "manifest.json").read_text())["assets"]}
    assert target in targets and ".claude/commands/sdd-insight.md" not in targets


def test_check_wheel_reports_monorepo_path(tmp_path: Path) -> None:
    """C16: the wheel check reads each shipped entry FROM THE WHEEL and flags a monorepo source path."""
    wheel = tmp_path / "ai_parrot-0-py3-none-any.whl"
    manifest = {"schema_version": 1, "assets": [{"source": "sdd/WORKFLOW.md", "target": "sdd/WORKFLOW.md", "hosts": ["claude"]}]}
    hook = 'command: python3 "$CLAUDE_PROJECT_DIR/packages/x.py" --hook'
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr(cas.WHEEL_PREFIX + "manifest.json", json.dumps(manifest))
        zf.writestr(cas.WHEEL_PREFIX + "sdd/WORKFLOW.md", hook + "\n")
    assert cas.check_wheel(wheel) == [f"monorepo-path: sdd/WORKFLOW.md:1: {hook}"]


def test_seed_entry_is_flagged(mini_repo: Path) -> None:
    """C10: sdd/CONVENTIONS.md carries `"seed": true`; nothing else carries the key."""
    (mini_repo / "sdd/CONVENTIONS.md").write_text("# Team conventions\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=mini_repo, check=True)
    _run(mini_repo, "--write")
    manifest = json.loads((mini_repo / "assets" / "manifest.json").read_text())
    by_target = {e["target"]: e for e in manifest["assets"]}
    assert by_target["sdd/CONVENTIONS.md"]["seed"] is True
    assert all("seed" not in e for t, e in by_target.items() if t != "sdd/CONVENTIONS.md")


def test_no_rulebook_and_no_dot_rules_ship() -> None:
    """C10: codebase-conventions.md is packaged for no host; the only rule asset is worktree-management."""
    manifest = json.loads((_REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets/manifest.json").read_text())
    targets = {e["target"] for e in manifest["assets"]}
    assert not any(t.endswith("codebase-conventions.md") for t in targets)
    assert ".claude/rules/worktree-management.md" in targets
    assert ".claude/skills/second-opinion/SKILL.md" in targets          # C9
    assert "sdd/CONVENTIONS.md" in targets                              # C10
    assert not any("sdd-insight" in t for t in targets)                  # rev 0.5 C22
    assert len(targets) == 83                                           # rev 0.5 C22 + code-reviewer, qa-runner, CODEX.md (packaged-only)


def test_assets_have_no_publication_findings() -> None:
    """C11c: the committed asset tree has zero org-data / claude-md-ref / branch-literal findings."""
    from parrot.sdd.audit import scan_paths  # TASK-4070

    assets_dir = _REPO_ROOT / "packages/ai-parrot/src/parrot/sdd/_assets"
    findings = scan_paths(sorted(p for p in assets_dir.rglob("*") if p.is_file() and p.name != "manifest.json"))
    bad = [f for f in findings if f.kind in {"org-data", "claude-md-ref", "branch-literal"}]
    assert not bad, [(f.path, f.line, f.kind, f.snippet) for f in bad]


def test_dev_loop_prompts_load_from_packaged_assets() -> None:
    """C2: every dual-sourced prompt is read from parrot/sdd/_assets/claude/agents/; sdd-codereview stays core-only."""
    from importlib.resources import files

    from parrot.flows.dev_flow._subagent_defs import load_subagent_definition as load_flow
    from parrot.flows.dev_loop._subagent_defs import load_subagent_definition as load_loop

    agents = files("parrot.sdd") / "_assets" / "claude" / "agents"
    for name in ("sdd-worker", "sdd-planner", "sdd-secondopinion"):
        body = load_loop(name)
        assert body and body in (agents / f"{name}.md").read_text(encoding="utf-8")
    ideation = load_flow("sdd-ideation")
    assert ideation and ideation in (agents / "sdd-ideation.md").read_text(encoding="utf-8")
    assert load_loop("sdd-codereview")                                   # still served from _subagent_data/
    data_dir = files("parrot.flows.dev_loop") / "_subagent_data"
    assert sorted(p.name for p in data_dir.iterdir() if p.name.endswith(".md")) == ["sdd-codereview.md"]


def test_repo_assets_in_sync() -> None:
    """The committed _assets/ tree matches the monorepo sources (the CI gate, as a test)."""
    assert cas.main(["--check", "--root", str(_REPO_ROOT)]) == 0


def test_package_data_covers_every_manifest_entry() -> None:
    """Every manifest source matches one `"parrot.sdd"` package-data glob in pyproject.toml."""
    pyproject = tomllib.loads((_REPO_ROOT / "packages/ai-parrot/pyproject.toml").read_text())
    patterns = pyproject["tool"]["setuptools"]["package-data"]["parrot.sdd"]
    pkg_dir = _REPO_ROOT / "packages/ai-parrot/src/parrot/sdd"
    covered = {p.relative_to(pkg_dir).as_posix() for pat in patterns for p in pkg_dir.glob(pat) if p.is_file()}
    manifest = json.loads((pkg_dir / "_assets/manifest.json").read_text())
    missing = [e["source"] for e in manifest["assets"] if f"_assets/{e['source']}" not in covered]
    assert not missing, missing
