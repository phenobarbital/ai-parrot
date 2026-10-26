"""Tests for parrot.sdd.installer (FEAT-633 M6; spec §4 test_sdd_install_into_empty_repo,
integration test_sdd_flow_in_foreign_repo)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.launcher import script_path
from parrot.sdd.installer import (
    GITIGNORE_BEGIN,
    GUARD_HOOK_LINE,
    RECEIPT_PATH,
    guard_hook_command,
    install_sdd_integration,
    load_manifest,
    sdd_status,
    uninstall_sdd_integration,
)


@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """A fresh, non-Python git repository."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# foreign repo\n")
    return tmp_path


def _claude_targets() -> list[str]:
    """Claude assets the installer records (seeds are team-owned: written once, never recorded or removed)."""
    return [e["target"] for e in load_manifest() if "claude" in e["hosts"] and not e.get("seed", False)]


def test_sdd_install_into_empty_repo(empty_repo: Path) -> None:
    """Deploy + uninstall round-trip, marker-block safe (spec §4)."""
    install_sdd_integration(empty_repo)
    assert all((empty_repo / t).is_file() for t in _claude_targets())
    assert GITIGNORE_BEGIN in (empty_repo / ".gitignore").read_text()
    assert (empty_repo / "sdd/tasks/.id_ledger.json").is_file()
    uninstall_sdd_integration(empty_repo)
    assert not any((empty_repo / t).exists() for t in _claude_targets())
    assert GITIGNORE_BEGIN not in (empty_repo / ".gitignore").read_text()
    assert (empty_repo / "README.md").read_text() == "# foreign repo\n"
    assert (empty_repo / "sdd/tasks/.id_ledger.json").is_file()  # state is never removed


def test_reinstall_is_idempotent(empty_repo: Path) -> None:
    install_sdd_integration(empty_repo)
    actions = install_sdd_integration(empty_repo)
    # asset lines end with the verb; the wiring note / hook lines mention "installed" in other positions
    assert not any(a.endswith((" — installed", " — upgraded")) or "overwritten" in a for a in actions)


def _tree_digest(root: Path) -> dict[str, str]:
    """{relative path: sha256} for every file under root except .git/ (C5 no-write assertion)."""
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }


def test_modified_file_skipped_unless_force_and_kept_on_uninstall(empty_repo: Path) -> None:
    """C4: a file in the receipt whose bytes changed is `edited` — kept unless --force, never uninstalled."""
    install_sdd_integration(empty_repo)
    target = empty_repo / _claude_targets()[0]
    target.write_text("user edit\n")
    assert any(a.startswith("warning:") for a in install_sdd_integration(empty_repo))
    assert target.read_text() == "user edit\n"
    uninstall_sdd_integration(empty_repo)
    assert target.read_text() == "user edit\n"
    install_sdd_integration(empty_repo, force=True)
    assert target.read_text() != "user edit\n"
    assert sdd_status(empty_repo)["hosts"]["claude"]["current"]  # re-recorded after --force


def test_untouched_file_upgrades_from_older_record(empty_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C4: a file untouched since an OLDER release (receipt sha == on-disk sha != packaged) upgrades without --force."""
    install_sdd_integration(empty_repo)
    target = _claude_targets()[0]
    old_bytes = b"# older packaged copy\n"
    (empty_repo / target).write_bytes(old_bytes)
    receipt = json.loads((empty_repo / RECEIPT_PATH).read_text())
    receipt["files"][target] = hashlib.sha256(old_bytes).hexdigest()
    receipt["version"] = "0.0.1"
    (empty_repo / RECEIPT_PATH).write_text(json.dumps(receipt))
    assert sdd_status(empty_repo)["hosts"]["claude"]["outdated"] == [target]
    actions = install_sdd_integration(empty_repo)
    assert any(a.endswith("upgraded") and target in a for a in actions)
    assert (empty_repo / target).read_bytes() != old_bytes
    assert json.loads((empty_repo / RECEIPT_PATH).read_text())["version"] != "0.0.1"


def test_foreign_file_never_touched_even_with_force(empty_repo: Path) -> None:
    """C4: a target that exists but was not written by us (and is not byte-identical) is `foreign`."""
    target = empty_repo / _claude_targets()[0]
    target.parent.mkdir(parents=True)
    target.write_text("theirs\n")
    for force in (False, True):
        actions = install_sdd_integration(empty_repo, force=force)
        assert any(a.startswith("warning:") and "never overwritten" in a for a in actions)
        assert target.read_text() == "theirs\n"
    assert sdd_status(empty_repo)["hosts"]["claude"]["foreign"] == [_claude_targets()[0]]
    uninstall_sdd_integration(empty_repo)
    assert target.read_text() == "theirs\n"


def test_unrecorded_identical_file_is_adopted(empty_repo: Path) -> None:
    """C4 interpretation: byte-identical to the packaged copy but missing from the receipt → current + recorded."""
    install_sdd_integration(empty_repo)
    (empty_repo / RECEIPT_PATH).unlink()
    install_sdd_integration(empty_repo)
    receipt = json.loads((empty_repo / RECEIPT_PATH).read_text())
    assert set(receipt["files"]) >= set(_claude_targets())


def test_dry_run_changes_nothing(empty_repo: Path) -> None:
    """C5: install/uninstall --dry-run print a plan and leave the tree byte-for-byte unchanged."""
    before = _tree_digest(empty_repo)
    plan = install_sdd_integration(empty_repo, dry_run=True)
    assert plan and all(p.startswith("plan: ") for p in plan)
    assert any(p.startswith("plan: write ") for p in plan)
    assert any(p.startswith(("plan: gitignore", "plan: ledger-seed", "plan: config-seed")) for p in plan)
    assert _tree_digest(empty_repo) == before and not (empty_repo / RECEIPT_PATH).exists()
    install_sdd_integration(empty_repo)
    before = _tree_digest(empty_repo)
    plan = uninstall_sdd_integration(empty_repo, dry_run=True)
    assert any(p.startswith("plan: remove ") for p in plan)
    assert _tree_digest(empty_repo) == before


def _seed_targets() -> list[str]:
    """Every manifest entry flagged `"seed": true` (TASK-4090 rev 0.2) — generic, never a hardcoded path."""
    return [e["target"] for e in load_manifest() if e.get("seed", False)]


def test_seeds_written_once_never_overwritten_or_removed(empty_repo: Path) -> None:
    """C6/C10: sdd/config.json and EVERY `"seed": true` asset are written iff absent; --force and uninstall leave them."""
    seeds = _seed_targets()
    assert seeds, "TASK-4090 must flag at least one seed (sdd/CONVENTIONS.md)"
    install_sdd_integration(empty_repo)
    config = empty_repo / "sdd/config.json"
    assert config.is_file() and json.loads(config.read_text())["base_branch"] == "dev"
    assert all((empty_repo / t).is_file() for t in seeds)
    config.write_text('{"base_branch": "develop", "hotfix_base": "main"}\n')
    for t in seeds:
        (empty_repo / t).write_text("# ours\n")
    install_sdd_integration(empty_repo, force=True)
    assert "develop" in config.read_text()
    assert all((empty_repo / t).read_text() == "# ours\n" for t in seeds)
    receipt = json.loads((empty_repo / RECEIPT_PATH).read_text())
    assert "sdd/config.json" not in receipt["files"] and not set(seeds) & set(receipt["files"])
    uninstall_sdd_integration(empty_repo)
    assert config.is_file() and all((empty_repo / t).read_text() == "# ours\n" for t in seeds)
    report = sdd_status(empty_repo)
    assert all(report["seeds"][t] == "seed-present" for t in seeds)
    assert not any(
        t in report["hosts"][h][state] for t in seeds for h in report["hosts"] for state in report["hosts"][h]
    )


def test_existing_gitignore_content_preserved(empty_repo: Path) -> None:
    (empty_repo / ".gitignore").write_text("node_modules/\n")
    install_sdd_integration(empty_repo)
    assert (empty_repo / ".gitignore").read_text().startswith("node_modules/\n")


@pytest.mark.parametrize("host", ["claude", "codex", "google"])
def test_gitattributes_block_written_recorded_and_removed(empty_repo: Path, host: str) -> None:
    """rev 0.5 C23: any host writes the ledger merge=union block, keeps foreign lines, uninstall removes it."""
    (empty_repo / ".gitattributes").write_text("*.png binary\n")
    install_sdd_integration(empty_repo, hosts=(host,))
    text = (empty_repo / ".gitattributes").read_text()
    assert text.startswith("*.png binary\n")
    assert "sdd/ledger/events.jsonl merge=union" in text and "sdd/ledger/archive/*.jsonl merge=union" in text
    assert json.loads((empty_repo / "sdd/.sdd-installed.json").read_text())["blocks"][".gitattributes"]
    uninstall_sdd_integration(empty_repo, hosts=(host,))
    assert (empty_repo / ".gitattributes").read_text() == "*.png binary\n"


def test_ledger_hooks_installed_for_any_host(empty_repo: Path) -> None:
    """rev 0.5 C23: the four FEAT-694 ledger hooks are installed through the claude installer's function."""
    install_sdd_integration(empty_repo, hosts=("codex",))
    for event in ("pre-commit", "post-merge", "post-checkout", "post-rewrite"):
        assert "# >>> parrot-ledger >>>" in (empty_repo / ".git/hooks" / event).read_text()


def test_install_refuses_malformed_config_before_writing(empty_repo: Path) -> None:
    """PR #1746 review (Codex P1): a malformed existing sdd/config.json aborts before any write."""
    from parrot.sdd.config import SddConfigError

    (empty_repo / "sdd").mkdir()
    (empty_repo / "sdd/config.json").write_text("{not json")
    before = sorted(p.relative_to(empty_repo) for p in empty_repo.rglob("*") if ".git" not in p.parts)
    for dry_run in (True, False):
        with pytest.raises(SddConfigError):
            install_sdd_integration(empty_repo, hosts=("codex",), dry_run=dry_run)
    after = sorted(p.relative_to(empty_repo) for p in empty_repo.rglob("*") if ".git" not in p.parts)
    assert after == before
    assert not any((empty_repo / ".git/hooks" / e).exists() for e in ("pre-commit", "post-merge"))


def test_ledger_hooks_removed_on_uninstall_when_sdd_created_them(empty_repo: Path) -> None:
    """PR #1746 review (Codex P2): install → uninstall round trip leaves no parrot-ledger block."""
    install_sdd_integration(empty_repo, hosts=("codex",))
    assert json.loads((empty_repo / "sdd/.sdd-installed.json").read_text())["ledger_hooks"]
    uninstall_sdd_integration(empty_repo, hosts=("codex",))
    for event in ("pre-commit", "post-merge", "post-checkout", "post-rewrite"):
        hook = empty_repo / ".git/hooks" / event
        assert not hook.exists() or "# >>> parrot-ledger >>>" not in hook.read_text()


def test_ledger_hooks_kept_when_shared_with_claude_integration(empty_repo: Path) -> None:
    """PR #1746 review: hooks `parrot claude install` also owns are kept (and reported) on sdd uninstall."""
    from parrot.knowledge.wiki.claude_code.installer import _install_git_hook, _install_ledger_hooks

    _install_git_hook(empty_repo)  # parrot-wiki post-commit block, as `parrot claude install` writes
    _install_ledger_hooks(empty_repo)  # pre-existing ledger blocks → this install records none
    install_sdd_integration(empty_repo, hosts=("claude",))
    actions = uninstall_sdd_integration(empty_repo, hosts=("claude",))
    assert "# >>> parrot-ledger >>>" in (empty_repo / ".git/hooks/pre-commit").read_text()
    assert any("keep-ledger-hooks" in a or "kept" in a for a in actions)


def test_install_warns_when_test_command_is_null(empty_repo: Path) -> None:
    """rev 0.5 C21: a seeded (or existing) sdd/config.json with test_command null yields one warning line."""
    actions = install_sdd_integration(empty_repo)
    assert any(a.startswith("warning:") and "test_command" in a for a in actions)


def test_unknown_host_rejected(empty_repo: Path) -> None:
    with pytest.raises(ValueError):
        install_sdd_integration(empty_repo, hosts=("vim",))


def test_status_shape(empty_repo: Path) -> None:
    install_sdd_integration(empty_repo, hosts=("codex",))
    report = sdd_status(empty_repo)
    assert set(report) >= {"hosts", "seeds", "config", "gitignore", "id_ledger", "receipt_version"}
    assert set(report["hosts"]["codex"]) == {"current", "outdated", "edited", "foreign", "missing"}
    assert report["hosts"]["codex"]["missing"] == []
    assert set(report) >= {"gitattributes", "ledger_hooks", "guard_hook"}
    claude_only = [e["target"] for e in load_manifest() if e["hosts"] == ["claude"]]
    assert claude_only
    assert sorted(report["hosts"]["claude"]["missing"]) == sorted(claude_only)  # codex install: claude-only absent
    assert report["receipt_version"]


@pytest.mark.parametrize("hosts", [("claude",), ("codex",), ("google",)])
def test_sdd_flow_in_foreign_repo(empty_repo: Path, hosts: tuple[str, ...]) -> None:
    """Integration (spec §4, rev 0.2): installed markdown invokes helpers ONLY as `parrot sdd run <name>`,
    every such name is a real parrot.sdd.scripts module, and no `python -m` / repo-script form remains."""
    install_sdd_integration(empty_repo, hosts=hosts)
    installed = [empty_repo / e["target"] for e in load_manifest() if set(hosts) & set(e["hosts"])]
    texts = [p.read_text(encoding="utf-8") for p in installed if p.suffix in {".md", ".toml"}]
    joined = "\n".join(texts)
    names = set(re.findall(r"parrot sdd run ([a-z0-9_]+)", joined))
    assert names, "installed markdown invokes no helper through `parrot sdd run`"
    for name in names:
        assert importlib.util.find_spec(f"parrot.sdd.scripts.{name}") is not None, name
    assert "python -m parrot.sdd.scripts." not in joined
    assert "python -m scripts.sdd." not in joined
    assert not re.search(r"scripts/sdd/[a-z_0-9]+\.(py|sh)", joined)


# --------------------------------------------------------------------------
# rev 0.6 C25 — guard-hook rendering
# --------------------------------------------------------------------------

WORKER = ".claude/agents/sdd-worker.md"
CODER = ".claude/agents/sdd-coder.md"


def _hook_of(repo: Path, rel: str = WORKER) -> str:
    """The decoded ``command:`` of the agent's frontmatter hook (parsed as YAML)."""
    import yaml

    front = yaml.safe_load((repo / rel).read_text(encoding="utf-8").split("---", 2)[1])
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("command"), str) and "worktree_environment" in node["command"]:
                found.append(node["command"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(front)
    assert found, front
    return found[0]


@pytest.fixture
def no_launcher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """PATH without any `parrot`, and a PARROT_HOME that holds nothing."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "no-home"))
    return empty


def test_guard_hook_bare_when_managed_launcher_on_path(
    empty_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    shim = home / "bin" / "parrot"
    shim.write_text("#!/bin/sh\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PARROT_HOME", str(home))
    monkeypatch.setenv("PATH", str(home / "bin"))
    assert guard_hook_command(portable=False) == (GUARD_HOOK_LINE, "bare")
    install_sdd_integration(empty_repo)
    assert _hook_of(empty_repo) == GUARD_HOOK_LINE
    assert _hook_of(empty_repo, CODER) == GUARD_HOOK_LINE
    assert sdd_status(empty_repo)["guard_hook"]["form"] == "bare"


def test_guard_hook_baked_when_launcher_absent(empty_repo: Path, no_launcher: Path) -> None:
    hook, form = guard_hook_command(portable=False)
    assert form == "baked"
    install_sdd_integration(empty_repo)
    command = _hook_of(empty_repo)
    assert command == hook
    assert command.startswith(script_path(Path(sys.prefix), "parrot").as_posix())
    assert "python3." not in command and "site-packages" not in command
    report = sdd_status(empty_repo)
    assert report["guard_hook"]["form"] == "baked" and report["guard_hook"]["targets"]
    assert report["hosts"]["claude"]["outdated"] == [] and report["hosts"]["claude"]["edited"] == []


def test_guard_hook_portable_flag_forces_bare(empty_repo: Path, no_launcher: Path) -> None:
    assert guard_hook_command(portable=True) == (GUARD_HOOK_LINE, "bare")
    actions = install_sdd_integration(empty_repo, portable=True)
    assert _hook_of(empty_repo) == GUARD_HOOK_LINE
    assert not any("baked" in a for a in actions)


def test_guard_hook_quoting_space_and_quote(
    empty_repo: Path, tmp_path: Path, no_launcher: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A venv path with a space and a `'` survives the YAML scalar and `sh -c`."""
    venv = tmp_path / "my venv's"
    (venv / "bin").mkdir(parents=True)
    fake = venv / "bin" / "parrot"
    fake.write_text('#!/bin/sh\necho "ran:$*"\n')
    fake.chmod(0o755)
    monkeypatch.setattr(sys, "prefix", str(venv))
    install_sdd_integration(empty_repo)
    command = _hook_of(empty_repo)
    out = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "ran:sdd run worktree_environment --hook"
    assert sdd_status(empty_repo)["guard_hook"]["resolvable"] is True


def test_guard_hook_mode_change_is_outdated_not_edited(empty_repo: Path, no_launcher: Path) -> None:
    install_sdd_integration(empty_repo)  # baked
    assert _hook_of(empty_repo) != GUARD_HOOK_LINE
    actions = install_sdd_integration(empty_repo, portable=True)  # → bare, no --force
    assert any(a.endswith("upgraded") and WORKER in a for a in actions), actions
    assert _hook_of(empty_repo) == GUARD_HOOK_LINE
    report = sdd_status(empty_repo)
    assert WORKER in report["hosts"]["claude"]["current"] and report["hosts"]["claude"]["edited"] == []
    path = empty_repo / WORKER
    path.write_text(path.read_text(encoding="utf-8") + "\n<!-- team edit -->\n", encoding="utf-8")
    assert WORKER in sdd_status(empty_repo)["hosts"]["claude"]["edited"]


def test_guard_hook_status_flags_hand_patched_foreign(empty_repo: Path, no_launcher: Path) -> None:
    agent = empty_repo / WORKER
    agent.parent.mkdir(parents=True)
    agent.write_text(
        "---\nname: sdd-worker\nhooks:\n  PreToolUse:\n    - hooks:\n        - type: command\n"
        "          command: 'python3 /x/site-packages/parrot/sdd/scripts/worktree_environment.py --hook'\n---\nbody\n",
        encoding="utf-8",
    )
    actions = install_sdd_integration(empty_repo, force=True)
    assert any(a.startswith("warning:") and WORKER in a for a in actions)  # foreign: never overwritten
    guard = sdd_status(empty_repo)["guard_hook"]
    assert (guard["form"], guard["resolvable"]) == ("other", False)
    assert WORKER in guard["targets"]
    assert sdd_status(empty_repo)["hosts"]["claude"]["foreign"].count(WORKER) == 1


def test_guard_hook_absent_is_resolvable(tmp_path: Path) -> None:
    assert sdd_status(tmp_path)["guard_hook"] == {"form": None, "command": None, "targets": [], "resolvable": True}
