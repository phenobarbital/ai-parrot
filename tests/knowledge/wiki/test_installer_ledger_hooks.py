"""FEAT-694 M3 — managed parrot-ledger git hooks."""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest

from parrot.knowledge.wiki.claude_code import assets
from parrot.knowledge.wiki.claude_code import installer
from parrot.knowledge.wiki.claude_code.installer import (
    _git_hook_path,
    _install_git_hook,
    _install_ledger_hooks,
    _uninstall_ledger_hooks,
)


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every convention path (HOME, XDG, PARROT_HOME) inside tmp_path."""
    home = tmp_path / "_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("PARROT_HOME", str(home / ".parrot"))


def _repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def _install_stub(root: Path) -> Path:
    """Stub wikitoolkit that records its arguments into ``<root>/args.log``."""
    bin_dir = root / ".venv" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "wikitoolkit"
    stub.write_text(f'#!/bin/sh\necho "$@" >> "{root / "args.log"}"\nexit 0\n', encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return stub


def test_ledger_hooks_installed_on_four_events(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _install_stub(repo)
    actions = _install_ledger_hooks(repo)
    assert len(actions) == 4
    for event in assets.LEDGER_HOOK_EVENTS:
        path = _git_hook_path(repo, event)
        assert path is not None and path.exists()
        text = path.read_text(encoding="utf-8")
        assert assets.LEDGER_HOOK_BEGIN in text
        if event == "pre-commit":
            assert "FEAT-758" in text
            assert "export-log" not in text
        else:
            assert "import-log" in text
    # idempotent
    assert all("already installed" in a for a in _install_ledger_hooks(repo))


def test_ledger_hook_runs_without_worktree_guard(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _install_stub(repo)
    _install_ledger_hooks(repo)
    post_merge_hook = _git_hook_path(repo, "post-merge")
    assert post_merge_hook is not None
    subprocess.run(["sh", str(post_merge_hook)], cwd=str(repo), check=True, timeout=10)
    assert "ledger import-log --quiet" in (repo / "args.log").read_text()

    pre_commit_hook = _git_hook_path(repo, "pre-commit")
    assert pre_commit_hook is not None
    subprocess.run(["sh", str(pre_commit_hook)], cwd=str(repo), check=True, timeout=10)
    assert "export-log" not in (repo / "args.log").read_text()

    # linked worktree: .git is a file
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text("gitdir: /nowhere\n", encoding="utf-8")
    subprocess.run(["sh", str(post_merge_hook)], cwd=str(wt), check=True, timeout=10)
    # the stub is addressed by absolute path, so it ran (appended to the repo log)
    assert (repo / "args.log").read_text().count("import-log") == 2
    assert "export-log" not in (repo / "args.log").read_text()


def test_uninstall_strips_only_ledger_block(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _install_stub(repo)
    _install_git_hook(repo)
    _install_ledger_hooks(repo)
    pm = _git_hook_path(repo, "post-merge")
    assert pm is not None
    pm.write_text(pm.read_text() + "# >>> sdd-intake-prune >>>\necho x\n# <<< sdd-intake-prune <<<\n")
    actions = _uninstall_ledger_hooks(repo)
    assert len(actions) == 4
    pc = _git_hook_path(repo, "pre-commit")
    assert pc is not None and not pc.exists()
    text = pm.read_text()
    assert assets.LEDGER_HOOK_BEGIN not in text
    assert "sdd-intake-prune" in text
    commit = _git_hook_path(repo, "post-commit")
    assert commit is not None and assets.GIT_HOOK_BEGIN in commit.read_text()


def test_install_claude_integration_action_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _repo(tmp_path)
    _install_stub(repo)
    calls: list[Path] = []
    monkeypatch.setattr(installer, "_install_ledger_hooks", lambda r: calls.append(r) or ["x"])
    on = installer.install_claude_integration(repo, git_hook=True)
    assert calls == [repo]
    assert "x" in on
    off = installer.install_claude_integration(repo, git_hook=False)
    # FEAT-804: a baked-fallback install adds an informational "note:" line
    # unless a managed launcher is on PATH; it is not an action, so ignore it.
    on = [a for a in on if not a.startswith("note: ")]
    off = [a for a in off if not a.startswith("note: ")]
    assert len(on) == len(off) + 2


def test_hook_with_missing_binary_exits_zero(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    path = _git_hook_path(repo, "post-merge")
    assert path is not None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + assets.ledger_hook_block(repo, "post-merge"), encoding="utf-8")
    text = path.read_text().replace(assets.resolve_wikitoolkit_bin(repo), "/nonexistent/wikitoolkit")
    path.write_text(text)
    result = subprocess.run(["sh", str(path)], cwd=str(repo), timeout=10)
    assert result.returncode == 0


def test_unknown_event_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        assets.ledger_hook_block(tmp_path, "pre-push")


def test_outdated_pre_commit_block_is_upgraded_preserving_custom_bytes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    hook = _git_hook_path(repo, "pre-commit")
    assert hook is not None
    hook.parent.mkdir(parents=True, exist_ok=True)
    old_block = (
        f"{assets.LEDGER_HOOK_BEGIN}\n" "wikitoolkit ledger export-log --stage --quiet\n" f"{assets.LEDGER_HOOK_END}\n"
    )
    original = "#!/bin/sh\necho custom-before\n" + old_block + "echo custom-after\n"
    hook.write_text(original, encoding="utf-8")
    hook.chmod(0o755)

    actions = _install_ledger_hooks(repo)

    assert "git pre-commit ledger hook — upgraded" in actions
    updated = hook.read_text(encoding="utf-8")
    assert updated.startswith("#!/bin/sh\necho custom-before\n")
    assert updated.endswith("echo custom-after\n")
    assert "export-log" not in updated
    assert stat.S_IMODE(hook.stat().st_mode) == 0o755

    actions = _install_ledger_hooks(repo)
    assert "git pre-commit ledger hook — already installed" in actions
    assert hook.read_text(encoding="utf-8") == updated


def test_unbalanced_markers_are_left_untouched(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    hook = _git_hook_path(repo, "pre-commit")
    assert hook is not None
    hook.parent.mkdir(parents=True, exist_ok=True)
    original = f"#!/bin/sh\necho custom\n{assets.LEDGER_HOOK_BEGIN}\necho legacy\n"
    hook.write_text(original, encoding="utf-8")

    actions = _install_ledger_hooks(repo)

    assert any("git pre-commit ledger hook — skipped" in action for action in actions)
    assert hook.read_text(encoding="utf-8") == original


def test_non_shell_hook_still_refused(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    hook = _git_hook_path(repo, "pre-commit")
    assert hook is not None
    hook.parent.mkdir(parents=True, exist_ok=True)
    original = "#!/usr/bin/env python3\nprint('custom')\n"
    hook.write_text(original, encoding="utf-8")

    actions = _install_ledger_hooks(repo)

    assert any(
        "git pre-commit ledger hook — skipped (existing hook is not a shell script" in action for action in actions
    )
    assert hook.read_text(encoding="utf-8") == original


# --- TASK-5116 (issue:4c5b3404e8fb): core.hooksPath + receipt-scoped uninstall ---------------------------------


def _git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "gitrepo") -> Path:
    """A real ``git init`` repo, isolated from the developer's global/system git config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / name
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def test_hook_path_follows_core_hookspath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _git_repo(tmp_path, monkeypatch)
    assert _git_hook_path(repo, "pre-commit") == repo / ".git" / "hooks" / "pre-commit"
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".husky"], check=True)
    assert _git_hook_path(repo, "pre-commit") == repo / ".husky" / "pre-commit"
    shared = tmp_path / "shared-hooks"
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", str(shared)], check=True)
    assert _git_hook_path(repo, "post-merge") == shared / "post-merge"


def test_ledger_hooks_installed_under_hookspath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _git_repo(tmp_path, monkeypatch)
    _install_stub(repo)
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".husky"], check=True)
    _install_ledger_hooks(repo)
    for event in assets.LEDGER_HOOK_EVENTS:
        assert assets.LEDGER_HOOK_BEGIN in (repo / ".husky" / event).read_text()
        assert not (repo / ".git" / "hooks" / event).exists()
    assert len(_uninstall_ledger_hooks(repo)) == len(assets.LEDGER_HOOK_EVENTS)
    assert not any((repo / ".husky" / e).exists() for e in assets.LEDGER_HOOK_EVENTS)


def test_uninstall_limited_to_given_events(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _install_stub(repo)
    _install_ledger_hooks(repo)
    actions = _uninstall_ledger_hooks(repo, ["pre-commit"])
    assert actions == ["git pre-commit ledger hook — removed"]
    for event in assets.LEDGER_HOOK_EVENTS:
        hook = _git_hook_path(repo, event)
        assert hook is not None
        assert hook.exists() is (event != "pre-commit")
