# packages/ai-parrot/tests/sdd/test_scripts_ledger_worktree.py
"""FEAT-633 move A: ledger/worktree helpers live in parrot.sdd.scripts; scripts/sdd shims alias them."""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SRC = REPO_ROOT / "packages" / "ai-parrot" / "src"
MOVED = ("id_ledger", "reserve_ids", "check_id_collisions", "ensure_worktree")
MOVED_HOOK = SRC / "parrot" / "sdd" / "scripts" / "worktree_environment.py"  # rev 0.3 C16
OLD_HOOK = SRC / "parrot" / "flows" / "dev_loop" / "worktree_environment.py"  # rev 0.5 C19 shim
MOVED_LIBS = ("brief_meta",)  # rev 0.4 C17: library module, no main() until TASK-4299 adds the CLI
SDD_META_NAMES = (
    "KNOWN_BRANCHES", "KNOWN_PROJECTS", "PROJECT_ALIASES", "WORK_KIND_FLOW", "WORKTREE_ROOT", "DocTaxonomy",
    "FlowMeta", "WorktreePlan", "emit", "normalize_project", "normalize_tag", "parse", "parse_taxonomy",
    "plan_worktree", "resolve_flow",
)


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC), str(REPO_ROOT), env.get("PYTHONPATH", "")])
    return env


def _run(module: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", module, *args], cwd=cwd, env=_env(), capture_output=True, text=True)


@pytest.mark.parametrize("name", (*MOVED, *MOVED_LIBS, "sdd_meta"))
def test_importable_from_package(name: str) -> None:
    assert importlib.import_module(f"parrot.sdd.scripts.{name}") is not None


@pytest.mark.parametrize("name", MOVED)
def test_module_help_from_foreign_cwd(name: str, tmp_path: Path) -> None:
    assert _run(f"parrot.sdd.scripts.{name}", "--help", cwd=tmp_path).returncode == 0


@pytest.mark.parametrize("name", (*MOVED, *MOVED_LIBS))
def test_shim_aliases_package_module(name: str) -> None:
    assert importlib.import_module(f"scripts.sdd.{name}") is importlib.import_module(f"parrot.sdd.scripts.{name}")


@pytest.mark.parametrize("name", ("reserve_ids", "ensure_worktree"))
def test_live_cli_help_and_usage_error_unchanged(name: str) -> None:
    shim, pkg = _run(f"scripts.sdd.{name}", "--help", cwd=REPO_ROOT), _run(f"parrot.sdd.scripts.{name}", "--help", cwd=REPO_ROOT)
    assert (shim.returncode, shim.stdout) == (pkg.returncode, pkg.stdout)
    assert _run(f"scripts.sdd.{name}", cwd=REPO_ROOT).returncode == _run(f"parrot.sdd.scripts.{name}", cwd=REPO_ROOT).returncode == 2


def test_sdd_meta_reexport_identity() -> None:
    pkg = importlib.import_module("parrot.sdd.scripts.sdd_meta")
    src = importlib.import_module("parrot.knowledge.wiki.ledger.sdd_meta")
    for name in SDD_META_NAMES:
        assert getattr(pkg, name) is getattr(src, name), name


def test_worktree_environment_shim_reexports_moved_module() -> None:  # rev 0.3 C16 / AC-8
    old = importlib.import_module("parrot.flows.dev_loop.worktree_environment")
    moved = importlib.import_module("parrot.sdd.scripts.worktree_environment")
    for name in ("command_policy_error", "protected_argv", "validate_write_path"):
        assert getattr(old, name) is getattr(moved, name), name


def test_guard_loader_module_mode_never_imports_dev_loop() -> None:  # rev 0.5 C19 (1) / AC-9
    code = (
        "import sys; from parrot.sdd.scripts import worktree_environment as we; "
        "print(we._load_guard_bash().__module__); "
        "print(any(m == 'parrot.flows.dev_loop' or m.startswith('parrot.flows.dev_loop.') for m in sys.modules))"
    )
    proc = subprocess.run([sys.executable, "-c", code], env=_env(), capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == ["test_scope.guard", "False"]


@pytest.mark.parametrize("hook", (MOVED_HOOK, OLD_HOOK))
def test_hook_answers_with_bare_interpreter(hook: Path, tmp_path: Path) -> None:  # rev 0.5 C19 (2) / AC-10
    # -I -S: stdlib only (no site-packages, no PYTHONPATH, no script dir on sys.path).
    proc = subprocess.run(
        [sys.executable, "-I", "-S", str(hook), "--hook"],
        input="{}", cwd=tmp_path, capture_output=True, text=True, timeout=10,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_scope_guard_blocks_after_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # AC-11
    from parrot.sdd.scripts import worktree_environment as we

    we._load_guard_bash()
    guard_mod = sys.modules["test_scope.guard"]
    from test_scope.datatypes import ScopePlan

    empty = ScopePlan(tier="task", invocations=(), escalated=(), core_hits=(), skipped_escalations=(), notes=())
    monkeypatch.setattr(guard_mod, "_task_plan", lambda worktree: empty)
    monkeypatch.setattr(we, "repository_paths", lambda cwd: (tmp_path, tmp_path))
    action, message = we._scope_guard("python -m pytest", tmp_path)
    assert action == "block", (action, message)


def test_kernel_lookup_from_wheel_layout(tmp_path: Path) -> None:  # AC-12
    pkg = tmp_path / "parrot"
    (pkg / "sdd" / "scripts").mkdir(parents=True)
    shutil.copy(MOVED_HOOK, pkg / "sdd" / "scripts" / "worktree_environment.py")
    shutil.copytree(
        SRC / "parrot" / "flows" / "dev_loop" / "test_scope",
        pkg / "flows" / "dev_loop" / "test_scope",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    copy = pkg / "sdd" / "scripts" / "worktree_environment.py"
    code = (
        "import importlib.util as u, sys; "
        f"s = u.spec_from_file_location('we', {str(copy)!r}); "
        "m = u.module_from_spec(s); s.loader.exec_module(m); "
        "g = m._load_guard_bash(); "
        "print(g.__module__, sys.modules['test_scope.guard'].__file__)"
    )
    proc = subprocess.run([sys.executable, "-I", "-S", "-c", code], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    mod, path = proc.stdout.split()
    assert mod == "test_scope.guard"
    assert path.startswith(str(pkg))


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "feature-x"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"],
        cwd=path,
        check=True,
    )
    return path


def test_remove_worktree_root_is_primary_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    worktree = primary / ".claude" / "worktrees" / "wt"
    worktree.parent.mkdir(parents=True)
    subprocess.run(["git", "worktree", "add", "-q", str(worktree), "-b", "wt"], cwd=primary, check=True)
    monkeypatch.chdir(worktree)
    remove_worktree._ROOT = None

    assert remove_worktree.repo_root() == primary.resolve()


def test_remove_worktree_list_and_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None
    assert remove_worktree.main(["list"]) == 0

    worktree = primary / ".claude" / "worktrees" / "wt"
    worktree.parent.mkdir(parents=True)
    subprocess.run(["git", "worktree", "add", "-q", str(worktree), "-b", "wt"], cwd=primary, check=True)
    assert remove_worktree.main(["remove", "wt", "--dry-run"]) == 0
    assert worktree.is_dir()


def test_remove_worktree_refuses_dirty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    worktree = primary / ".claude" / "worktrees" / "wt"
    worktree.parent.mkdir(parents=True)
    subprocess.run(["git", "worktree", "add", "-q", str(worktree), "-b", "wt"], cwd=primary, check=True)
    (worktree / "dirty.txt").write_text("uncommitted\n")
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "wt"]) != 0
    assert worktree.is_dir()


def _pool_with_registered_child(
    primary: Path, pool_name: str = "feat-FEAT-999-x--pool"
) -> tuple[Path, Path]:
    """Build an unregistered pool dir holding one registered worktree.

    Returns ``(pool, child)``. This is the FEAT-823 D1 shape: the pool itself is
    never a git worktree, only the ``TASK-*`` child inside it is.
    """
    pool = primary / ".claude" / "worktrees" / pool_name
    pool.mkdir(parents=True)
    child = pool / "TASK-1-a1"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(child), "-b", "task-1-a1"],
        cwd=primary,
        check=True,
    )
    return pool, child


def _registered_paths(primary: Path) -> set[str]:
    """Return the worktree paths git currently tracks in ``primary``."""
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=primary,
        capture_output=True,
        text=True,
        check=True,
    )
    return {ln.split(" ", 1)[1] for ln in proc.stdout.splitlines() if ln.startswith("worktree ")}


def _deregister_keeping_dir(primary: Path, name: str, stash: Path) -> None:
    """Drop git's record of a worktree while leaving its directory in place.

    Moves the admin dir OUT of ``.git/worktrees/`` entirely — renaming it
    *inside* that directory merely re-registers the worktree under the new
    admin name, which does not reproduce the FEAT-823 D2 shape.
    """
    shutil.move(str(primary / ".git" / "worktrees" / name), str(stash / name))
    subprocess.run(["git", "worktree", "prune"], cwd=primary, check=True)


def test_stale_refuses_orphan_holding_registered_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC1 / issue:751782605094
    """--stale must not rmtree a pool dir that still holds a registered worktree."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    pool, child = _pool_with_registered_child(primary)
    (child / "draft.py").write_text("uncommitted coder work\n")
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "--stale"]) != 0
    assert pool.is_dir(), "pool dir was deleted despite holding a registered worktree"
    assert child.is_dir(), "registered child was deleted"
    assert (child / "draft.py").exists(), "uncommitted coder work was discarded"
    assert str(child.resolve()) in _registered_paths(primary), "git's record of the child was dropped"


def test_stale_force_reports_nested_registrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:  # FEAT-823 AC2 + AC3
    """--force removes the pool but still names every nested worktree first."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    _pool, child = _pool_with_registered_child(primary)
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    remove_worktree.main(["remove", "--stale", "--force"])
    err = capsys.readouterr().err

    assert "TASK-1-a1" in err, "the nested worktree was not named before removal"
    # Match on the tokens, not on counts: a fresh `git worktree add` has 0 of each.
    assert "dirty:" in err and "unpushed:" in err, "per-child work state was not reported"


def test_stale_refuses_dirty_orphan_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC4 / issue:65a431065cae
    """A deregistered-but-live checkout with uncommitted work is gated."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    orphan = primary / ".claude" / "worktrees" / "wt"
    orphan.parent.mkdir(parents=True)
    subprocess.run(["git", "worktree", "add", "-q", str(orphan), "-b", "wt"], cwd=primary, check=True)
    (orphan / "dirty.txt").write_text("precious uncommitted work\n")

    stash = tmp_path / "admin-stash"
    stash.mkdir()
    _deregister_keeping_dir(primary, "wt", stash)
    assert str(orphan.resolve()) not in _registered_paths(primary), "fixture still registered"
    assert (orphan / ".git").exists(), "fixture is no longer a checkout"

    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "--stale"]) != 0
    assert (orphan / "dirty.txt").exists(), "uncommitted work was discarded without --force"

    assert remove_worktree.main(["remove", "--stale", "--force"]) == 0
    assert not orphan.exists()


def test_stale_skips_symlinked_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC5 / issue:65a431065cae
    """A symlink is skipped with a warning; the sweep still completes."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    worktrees = primary / ".claude" / "worktrees"
    worktrees.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keepme.txt").write_text("outside the worktree tree\n")
    # Names matter: discover() iterates sorted(), so the symlink is visited
    # first and an OSError would leave zzz-plain untouched.
    link = worktrees / "aaa-link"
    link.symlink_to(elsewhere, target_is_directory=True)
    plain = worktrees / "zzz-plain"
    plain.mkdir()

    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "--stale"]) == 0
    assert link.is_symlink(), "the symlink itself must be left alone"
    assert (elsewhere / "keepme.txt").exists(), "the symlink target must never be touched"
    assert not plain.exists(), "the sweep stopped early instead of continuing"


def test_stale_still_removes_plain_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # FEAT-823 AC7 — non-regression
    """An emptied pool dir is still swept without --force."""
    from parrot.sdd.scripts import remove_worktree

    primary = _git_repo(tmp_path / "repo")
    pool = primary / ".claude" / "worktrees" / "feat-FEAT-998-y--pool"
    pool.mkdir(parents=True)
    (pool / "leftover.log").write_text("scratch\n")
    monkeypatch.chdir(primary)
    remove_worktree._ROOT = None

    assert remove_worktree.main(["remove", "--stale"]) == 0
    assert not pool.exists()


def test_remove_worktree_shim_aliases() -> None:
    package_module = importlib.import_module("parrot.sdd.scripts.remove_worktree")
    sys.modules.pop("scripts.remove_worktree", None)

    shim_module = importlib.import_module("scripts.remove_worktree")

    assert shim_module is package_module


def test_worktree_verbs_mounted() -> None:
    from parrot.sdd.cli import VERBS, mounted_modules

    assert "remove_worktree" in mounted_modules()
    assert VERBS["worktree"]["list"][0] == "remove_worktree"
