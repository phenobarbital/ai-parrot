"""Tests for parrot.sdd.config and the sdd_meta / brief_meta CLIs (TASK-4299)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from navconfig import BASE_DIR
from pydantic import ValidationError

from parrot import conf
from parrot.sdd.config import (
    DEFAULT_WORKTREE_ROOT,
    LEGACY_WORKTREE_ROOT,
    SddConfig,
    SddConfigError,
    default_sdd_config,
    find_repo_root,
    legacy_migration_recipe,
    legacy_worktrees,
    ledger_destination,
    load_sdd_config,
    worktree_root,
    worktree_root_setting,
    write_default_config,
)
from parrot.sdd.scripts import brief_meta, sdd_meta, worktree_root as worktree_root_script


def _repo(tmp_path: Path, config: dict | str | None = None) -> Path:
    (tmp_path / ".git").mkdir()
    if config is not None:
        (tmp_path / "sdd").mkdir()
        text = config if isinstance(config, str) else json.dumps(config)
        (tmp_path / "sdd" / "config.json").write_text(text, encoding="utf-8")
    return tmp_path


def test_defaults_match_today() -> None:
    cfg = SddConfig()
    assert (cfg.base_branch, cfg.hotfix_base, cfg.staging_branch) == ("dev", "main", None)
    assert cfg.issue_tracker == "none" and cfg.reviewer == "none"
    assert cfg.test_command is None and cfg.projects is None
    assert default_sdd_config() == cfg


def test_extra_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        SddConfig(nope=1)


def test_base_equals_hotfix_rejected() -> None:
    with pytest.raises(ValidationError, match="must differ"):
        SddConfig(base_branch="main", hotfix_base="main")


def test_staging_collides_rejected() -> None:
    with pytest.raises(ValidationError):
        SddConfig(staging_branch="dev")
    with pytest.raises(ValidationError):
        SddConfig(staging_branch="main")


def test_jira_requires_host() -> None:
    with pytest.raises(ValidationError, match="jira_host"):
        SddConfig(issue_tracker="jira")


def test_jira_host_bare_hostname() -> None:
    with pytest.raises(ValidationError):
        SddConfig(issue_tracker="jira", jira_host="https://x.atlassian.net")
    assert SddConfig(issue_tracker="jira", jira_host="X.atlassian.net").jira_host == "x.atlassian.net"


@pytest.mark.parametrize("bad", ["", "  ", "a b", "origin/dev"])
def test_branch_blank_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        SddConfig(base_branch=bad)


@pytest.mark.parametrize("bad", ["", "   "])
def test_test_command_blank_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        SddConfig(test_command=bad)


def test_test_command_kept_verbatim() -> None:
    assert SddConfig(test_command="make test && echo ok").test_command == "make test && echo ok"


def test_projects_default_none_and_list() -> None:
    assert SddConfig().projects is None
    assert SddConfig(projects=["billing"]).projects == ["billing"]


def test_load_absent_is_default(tmp_path: Path) -> None:
    assert load_sdd_config(_repo(tmp_path)) == SddConfig()


def test_load_valid(tmp_path: Path) -> None:
    cfg = load_sdd_config(_repo(tmp_path, {"base_branch": "develop"}))
    assert cfg.base_branch == "develop"


def test_load_invalid_json_raises(tmp_path: Path) -> None:
    root = _repo(tmp_path, "{not json")
    with pytest.raises(SddConfigError, match="config.json"):
        load_sdd_config(root)


def test_load_validation_error_raises(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"base_branch": "main"})
    with pytest.raises(SddConfigError, match="config.json"):
        load_sdd_config(root)


def test_find_repo_root_git_dir(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert find_repo_root(sub) == tmp_path.resolve()


def test_find_repo_root_git_file(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
    assert find_repo_root(tmp_path) == tmp_path.resolve()


def test_find_repo_root_none(tmp_path: Path) -> None:
    if find_repo_root(tmp_path) is not None:
        pytest.skip("tmp_path lives inside a git repository")
    assert find_repo_root(tmp_path) is None


def test_write_default_config_refuses_overwrite(tmp_path: Path) -> None:
    path = write_default_config(tmp_path)
    assert path.read_text(encoding="utf-8").endswith("}\n")
    assert load_sdd_config(tmp_path) == SddConfig()
    with pytest.raises(FileExistsError):
        write_default_config(tmp_path)


SPEC = Path("sdd/specs/parrot-installer.spec.md")


def test_cli_parse_prints_type_and_base(capsys: pytest.CaptureFixture[str]) -> None:
    assert sdd_meta.main(["parse", str(SPEC)]) == 0
    assert capsys.readouterr().out.strip() == "feature dev"


def test_cli_taxonomy_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert sdd_meta.main(["taxonomy", str(SPEC)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"projects", "tags"} and "ai-parrot" in data["projects"]


def test_cli_resolve_flow_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert sdd_meta.main(["resolve-flow", "--kind", "bug"]) == 0
    assert json.loads(capsys.readouterr().out) == {"type": "hotfix", "base_branch": "main"}


def test_cli_unknown_subcommand_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        sdd_meta.main(["bogus"])
    assert exc.value.code == 2


def test_brief_cli_plan_json(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    assert brief_meta.main(["plan", "--slug", "crew-guards", "--key", "NAV-1", "--base-branch", "main"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "name": "hotfix-NAV-1-crew-guards",
        "path": ".parrot/worktrees/hotfix-NAV-1-crew-guards",
        "base_ref": "origin/main",
    }


def test_brief_cli_write_index_writes_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    brief = tmp_path / "x.brief.md"
    brief.write_text(
        "---\nkind: brief\nslug: crew-guards\nkey: NAV-1\nbase_branch: main\n"
        "source:\n  type: text\n  ref: demo\ncreated: '2026-10-26T00:00:00Z'\n---\n# Brief\n",
        encoding="utf-8",
    )
    tasks = tmp_path / "tasks.json"
    tasks.write_text(
        json.dumps([{"id": "HOTFIX-NAV-1-1", "slug": "t", "title": "T", "file": "f.md"}]), encoding="utf-8"
    )
    out_root = tmp_path / "wt"
    assert brief_meta.main(["write-index", str(brief), "--tasks", str(tasks), "--worktree-root", str(out_root)]) == 0
    written = Path(capsys.readouterr().out.strip())
    assert written.is_file() and written.name == "crew-guards.index.json"


def test_brief_cli_unknown_subcommand_exits_2() -> None:
    with pytest.raises(SystemExit) as exc:
        brief_meta.main(["bogus"])
    assert exc.value.code == 2


def test_ledger_destination_follows_base_branch_unless_set() -> None:
    """FEAT-758 outbox: ``ledger_branch`` wins, else ``base_branch``; the default stays ``dev``."""
    assert ledger_destination(default_sdd_config()) == "dev"
    assert ledger_destination(SddConfig(base_branch="develop")) == "develop"
    assert ledger_destination(SddConfig(base_branch="develop", ledger_branch="ledger")) == "ledger"
    with pytest.raises(ValidationError):
        SddConfig(ledger_branch="origin/dev")


def _git_repo(tmp_path: Path) -> Path:
    """Create a real repository with one commit for worktree tests."""
    repo = tmp_path / "repo with spaces"
    subprocess.run(["git", "init", "-q", "-b", "dev", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "seed",
        ],
        check=True,
    )
    return repo


def _add_worktree(repo: Path, relative_path: str, branch: str) -> Path:
    """Create and return a registered worktree rooted at ``relative_path``."""
    path = repo / relative_path
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q", "-b", branch, str(path), "dev"],
        check=True,
    )
    return path


def test_worktree_root_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The default resolver root lives beneath ``.parrot``."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    assert worktree_root_setting() == DEFAULT_WORKTREE_ROOT
    assert worktree_root(tmp_path) == tmp_path / ".parrot" / "worktrees"


def test_worktree_root_env_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Relative environment settings remain repository-relative."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    monkeypatch.setenv("WORKTREE_BASE_PATH", "./wt//x/")
    assert worktree_root_setting() == "wt/x"
    assert worktree_root(tmp_path) == tmp_path / "wt" / "x"


def test_worktree_root_env_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absolute settings are normalized and blank settings are ignored."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    configured = os.path.join(str(tmp_path), "absolute", ".", "child", "..", "worktrees")
    monkeypatch.setenv("WORKTREE_BASE_PATH", configured)
    assert worktree_root_setting() == os.path.normpath(configured)
    assert worktree_root(tmp_path) == Path(os.path.normpath(configured))
    monkeypatch.setenv("WORKTREE_BASE_PATH", "  ")
    assert worktree_root_setting() == DEFAULT_WORKTREE_ROOT


def test_worktree_root_override_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit setting supersedes the environment."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    monkeypatch.setenv("WORKTREE_BASE_PATH", "from-environment")
    assert worktree_root_setting("from-override/") == "from-override"
    assert worktree_root(tmp_path, "from-override") == tmp_path / "from-override"


@pytest.mark.parametrize("env", [None, "wt dir/x", "/abs/with space/wt"])
def test_worktree_root_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], env: str | None
) -> None:
    """The read-only root CLI matches the resolver without loading application configuration."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    if env is not None:
        monkeypatch.setenv("WORKTREE_BASE_PATH", env)

    assert worktree_root_script.main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == f"{worktree_root(tmp_path)}\n"
    assert not (tmp_path / ".parrot").exists()

    fresh_process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import parrot.sdd.scripts.worktree_root; assert 'parrot.conf' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert fresh_process.returncode == 0, fresh_process.stderr

    with pytest.raises(SystemExit) as exc:
        worktree_root_script.main([])
    assert exc.value.code == 2


def test_conf_worktree_base_path_derives() -> None:
    """The default configuration shares the resolver's worktree root."""
    if conf.config.get("WORKTREE_BASE_PATH", fallback=None) is not None:
        pytest.skip("WORKTREE_BASE_PATH is overridden by navconfig")
    assert conf.WORKTREE_BASE_PATH == str(worktree_root(BASE_DIR))


def test_legacy_worktrees_detects_registered(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only registered worktrees below the legacy root are returned."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    repo = _git_repo(tmp_path)
    worktree = _add_worktree(repo, ".claude/worktrees/feat-FEAT-1-x", "feat-1")
    (repo / LEGACY_WORKTREE_ROOT / "plain").mkdir()
    assert legacy_worktrees(repo) == [worktree.resolve()]


def test_legacy_worktrees_no_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-repository has no registered legacy worktrees."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    assert legacy_worktrees(tmp_path) == []


def test_legacy_migration_recipe_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The recipe preflights before moving only registered top-level paths."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    repo = _git_repo(tmp_path)
    parent = _add_worktree(repo, ".claude/worktrees/feature--pool", "feature-pool")
    child = _add_worktree(repo, ".claude/worktrees/feature--pool/w1", "feature-worker")
    recipe = legacy_migration_recipe(repo, [child, parent])
    moves = [line for line in recipe if line.startswith("mv ")]
    checks = [line for line in recipe if line.startswith("[ ! -e ")]
    repair = [line for line in recipe if " worktree repair " in line]
    assert recipe[:2] == ["(", "set -e"]
    assert len(moves) == 1 and str(parent) in moves[0]
    assert checks and recipe.index(checks[-1]) < recipe.index(moves[0])
    assert len(repair) == 1
    assert str(repo / ".parrot/worktrees/feature--pool") in repair[0]
    assert str(repo / ".parrot/worktrees/feature--pool/w1") in repair[0]
    assert f"'{repo}'" in repair[0]


def test_legacy_migration_refuses_live_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A live process inside a legacy worktree blocks the recipe and is named (issue:1b8289182630)."""
    from parrot.sdd.scripts import remove_worktree

    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    repo = _git_repo(tmp_path)
    worktree = _add_worktree(repo, ".claude/worktrees/hotfix-NAV-1-x", "hotfix-NAV-1-x")
    seen: list[Path] = []

    def fake_live(path: Path, exclude_pids: object = ()) -> list[tuple[int, str]]:
        seen.append(path)
        return [(4242, "claude --agent sdd-worker")] if path == worktree.resolve() else []

    monkeypatch.setattr(remove_worktree, "live_processes_in", fake_live)
    with pytest.raises(ValueError, match="live process") as exc:
        legacy_migration_recipe(repo, [worktree])
    assert str(worktree.resolve()) in str(exc.value)
    assert "4242" in str(exc.value)
    assert seen == [worktree.resolve()]


def test_legacy_migration_recipe_verifies_destinations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every destination is checked with ``rev-parse --git-dir`` after the repair line."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    repo = _git_repo(tmp_path)
    feature = _add_worktree(repo, ".claude/worktrees/feat-FEAT-1-x", "feat-1")
    hotfix = _add_worktree(repo, ".claude/worktrees/hotfix-NAV-1-x", "hotfix-NAV-1-x")
    recipe = legacy_migration_recipe(repo, [feature, hotfix])
    repair_at = next(i for i, line in enumerate(recipe) if " worktree repair " in line)
    checks = [(i, line) for i, line in enumerate(recipe) if "rev-parse --git-dir" in line]
    assert len(checks) == 2
    assert all(i > repair_at for i, _ in checks)
    for name in ("feat-FEAT-1-x", "hotfix-NAV-1-x"):
        destination = str(repo / ".parrot/worktrees" / name)
        assert any(f"git -C {destination} rev-parse" in line or f"git -C '{destination}' rev-parse" in line
                   for _, line in checks)
    assert recipe[-1] == ")"


def test_legacy_migration_collisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Generation and execution collision checks preserve the old worktree."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    repo = _git_repo(tmp_path)
    old_path = _add_worktree(repo, ".claude/worktrees/feature", "feature")
    destination = repo / ".parrot/worktrees/feature"
    destination.parent.mkdir(parents=True)
    destination.mkdir()
    with pytest.raises(ValueError, match="already exists"):
        legacy_migration_recipe(repo, [old_path])
    destination.rmdir()
    destination.symlink_to(repo / "missing")
    with pytest.raises(ValueError, match="already exists"):
        legacy_migration_recipe(repo, [old_path])
    destination.unlink()
    with pytest.raises(ValueError, match="duplicate"):
        legacy_migration_recipe(repo, [old_path, old_path])
    monkeypatch.setenv("WORKTREE_BASE_PATH", ".claude/worktrees/new")
    with pytest.raises(ValueError, match="overlap"):
        legacy_migration_recipe(repo, [old_path])
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    recipe = legacy_migration_recipe(repo, [old_path])
    destination.mkdir()
    completed = subprocess.run(["bash", "-c", "\n".join(recipe)], capture_output=True, text=True, check=False)
    assert completed.returncode != 0
    assert old_path.exists()


def test_legacy_migration_recipe_executes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The recipe preserves nested registrations, branches, and worktree files."""
    monkeypatch.delenv("WORKTREE_BASE_PATH", raising=False)
    repo = _git_repo(tmp_path)
    parent = _add_worktree(repo, ".claude/worktrees/a--pool", "a-pool")
    child = _add_worktree(repo, ".claude/worktrees/a--pool/w1", "a-worker")
    sibling = _add_worktree(repo, ".claude/worktrees/b--pool/w1", "b-worker")
    for worktree in (parent, child, sibling):
        (worktree / "proof.txt").write_text(worktree.name, encoding="utf-8")
    heads = {
        worktree: subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        for worktree in (parent, child, sibling)
    }
    subprocess.run(["bash", "-c", "\n".join(legacy_migration_recipe(repo, [parent, child, sibling]))], check=True)
    new_paths = [
        repo / ".parrot/worktrees/a--pool",
        repo / ".parrot/worktrees/a--pool/w1",
        repo / ".parrot/worktrees/b--pool/w1",
    ]
    assert legacy_worktrees(repo) == []
    for path, head in zip(new_paths, heads.values(), strict=True):
        assert (path / "proof.txt").is_file()
        assert (
            subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
            == head
        )
