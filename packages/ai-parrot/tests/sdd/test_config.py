"""Tests for parrot.sdd.config and the sdd_meta / brief_meta CLIs (TASK-4299)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from parrot.sdd.config import (
    SddConfig,
    SddConfigError,
    default_sdd_config,
    find_repo_root,
    load_sdd_config,
    write_default_config,
)
from parrot.sdd.scripts import brief_meta, sdd_meta


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


def test_brief_cli_plan_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert brief_meta.main(["plan", "--slug", "crew-guards", "--key", "NAV-1", "--base-branch", "main"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "name": "hotfix-NAV-1-crew-guards",
        "path": ".claude/worktrees/hotfix-NAV-1-crew-guards",
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
