"""C15 SDD readiness checks + C14 scopes (FEAT-633 rev 0.2/0.3, TASK-4080).

The parrot.sdd.* modules may not exist when this task lands (TASK-4091/4299 come later): every
test here must pass BOTH with them absent (checks report 'unavailable' as informational) and present.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from parrot.cli import cli
from parrot.self_ import doctor


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@x", *args], check=True, capture_output=True)


@pytest.fixture
def ready_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo satisfying EVERY C15 + rev 0.5 C23 prerequisite: bare origin with 'dev', tracked ledger, ignored
    worktrees, config, the `.gitattributes` ledger lines and the four ledger hooks."""
    from parrot.knowledge.wiki.claude_code.installer import _install_ledger_hooks  # verified: installer.py:973

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "dev", str(origin)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "-C", str(origin), "config", "receive.denyDeleteCurrent", "ignore"], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True)
    (repo / "sdd/tasks").mkdir(parents=True)
    (repo / "sdd/tasks/.id_ledger.json").write_text('{"task": 0, "feature": 0}\n')
    (repo / "sdd/config.json").write_text(json.dumps({"base_branch": "dev", "hotfix_base": "main"}) + "\n")
    (repo / ".gitignore").write_text(".claude/worktrees/\n")
    # FILL IN: wrap in TASK-4091's marker lines if review requires the marker (see the C23 note in _check_sdd)
    (repo / ".gitattributes").write_text("sdd/ledger/events.jsonl merge=union\nsdd/ledger/archive/*.jsonl merge=union\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    _git(repo, "push", "-q", "-u", "origin", "dev")
    _install_ledger_hooks(repo)  # after the seed commit, so the pre-commit ledger hook never fires here
    monkeypatch.setattr(doctor.shutil, "which", lambda name: f"/usr/bin/{name}")  # gh, jq, claude present
    monkeypatch.setattr(doctor.subprocess, "run", _gh_ok(doctor.subprocess.run))
    return repo


def _gh_ok(real_run):
    """Pass-through for git; fake `gh auth status` → exit 0."""
    def run(cmd, *a, **k):
        if cmd[:3] == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *a, **k)
    return run


def test_ready_repo_has_no_sdd_failures(ready_repo: Path) -> None:
    checks = doctor._check_sdd(ready_repo)
    assert checks and not doctor.failed(checks), [c.model_dump() for c in doctor.failed(checks)]


@pytest.mark.parametrize(
    "break_it, check_name, fix_fragment",
    [
        (lambda r: _git(r, "remote", "remove", "origin"), "sdd: origin remote", "git remote add origin"),
        (lambda r: subprocess.run(["git", "-C", str(r), "push", "-q", "origin", "--delete", "dev"], check=True), "sdd: base branch on origin", "git push -u origin dev"),
        (lambda r: (_git(r, "rm", "-q", "--cached", "sdd/tasks/.id_ledger.json"), _git(r, "commit", "-q", "--no-verify", "-m", "untrack")), "sdd: id ledger tracked", "git add sdd/tasks/.id_ledger.json"),
        (lambda r: (r / ".gitignore").write_text(""), "sdd: worktrees ignored", "parrot sdd install"),
        (lambda r: (r / ".gitattributes").write_text(""), "sdd: ledger merge=union", "parrot sdd install"),  # rev 0.5 C23
        (lambda r: (r / ".git" / "hooks" / "post-merge").unlink(), "sdd: ledger hooks", "parrot sdd install"),  # rev 0.5 C23
    ],
)
def test_each_missing_prerequisite_fails_its_check_with_a_fix(ready_repo: Path, break_it, check_name: str, fix_fragment: str) -> None:
    """C15 'done when': a fixture repo missing each prerequisite gets the matching check failing, with its fix."""
    break_it(ready_repo)
    bad = {c.name: c for c in doctor.failed(doctor._check_sdd(ready_repo))}
    assert check_name in bad and fix_fragment in bad[check_name].fix


def test_gh_unauthenticated_fails_non_informational(ready_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_run = subprocess.run

    def run(cmd, *a, **k):
        if cmd[:3] == ["gh", "auth", "status"]:
            return subprocess.CompletedProcess(cmd, 1, "", "not logged in")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(doctor.subprocess, "run", run)
    bad = {c.name: c for c in doctor.failed(doctor._check_sdd(ready_repo))}
    assert "sdd: gh" in bad and "gh auth login" in bad["sdd: gh"].fix


def test_host_cli_missing_is_informational_only(ready_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    status = {"hosts": {"claude": {"current": [".claude/commands/sdd-start.md"]}}}
    monkeypatch.setattr(doctor, "_sdd_status", lambda root: status)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None if name == "claude" else f"/usr/bin/{name}")
    checks = doctor._check_sdd(ready_repo)
    host = [c for c in checks if c.name == "sdd: host cli claude"]
    assert host and not host[0].ok and host[0].informational
    assert host[0] not in doctor.failed(checks)


def test_sdd_modules_absent_degrade_to_informational(ready_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ImportError for parrot.sdd.config / installer / audit must yield informational checks, never raise."""
    import builtins
    real_import = builtins.__import__

    def no_sdd(name, *a, **k):
        if name.startswith("parrot.sdd"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_sdd)
    checks = doctor._check_sdd(ready_repo)
    assert not doctor.failed([c for c in checks if "config" in c.name or "files current" in c.name])


def _guard_status(**guard):
    return {"hosts": {}, "guard_hook": guard}


def test_guard_hook_unresolvable_fails_with_fix() -> None:
    check = doctor._check_guard_hook(_guard_status(form="baked", command="/gone/python x.py", targets=["a"], resolvable=False))
    assert not check.ok and not check.informational and "parrot sdd install" in check.fix and "--portable" in check.fix


def test_guard_hook_hand_patched_is_other() -> None:
    check = doctor._check_guard_hook(
        _guard_status(form="other", command="/site-packages/x/worktree_environment.py", targets=["a"], resolvable=True)
    )
    assert not check.ok and "site-packages" in check.detail and "hand-copied" in check.fix


def test_guard_hook_absent_is_informational() -> None:
    for status in (None, {"hosts": {}}, _guard_status(form=None)):
        check = doctor._check_guard_hook(status)
        assert check.ok and check.informational
    ok = doctor._check_guard_hook(_guard_status(form="bare", command="parrot", targets=["a"], resolvable=True))
    assert ok.ok and not ok.informational and "PATH" in ok.detail


def test_scope_runtime_only_excludes_repo_host_and_component_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C14: a broken repo / host config / toolkit must NOT surface under --runtime-only."""
    repo = tmp_path / "repo"
    (repo / "sdd").mkdir(parents=True)  # no git at all → every SDD check would fail in "full"
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"wikitoolkit": {"command": "/nope/wikitoolkit"}}}))
    names = {c.name for c in doctor.run_doctor(repo, scope="runtime-only")}
    assert names == {"uv", "python", "runtime entry points", "PATH", "parrot_tools.wiki"} or all(
        not n.startswith("sdd:") and "mcp" not in n.lower() and "toolkit" not in n.lower() for n in names
    )
    assert any(c.name.startswith("sdd:") for c in doctor.run_doctor(repo, scope="full"))
    assert any(c.name.startswith("sdd:") for c in doctor.run_doctor(tmp_path / "no-sdd-dir", scope="sdd"))
    assert not any(c.name.startswith("sdd:") for c in doctor.run_doctor(tmp_path / "no-sdd-dir", scope="full"))


def test_cli_flags_mutually_exclusive_and_exit_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    result = CliRunner().invoke(cli, ["self", "doctor", "--sdd", "--runtime-only"])
    assert result.exit_code == 2 and "mutually exclusive" in result.output
    informational_fail = [doctor.DoctorCheck(name="sdd: host cli claude", ok=False, informational=True)]
    with mock.patch("parrot.self_.doctor.run_doctor", return_value=informational_fail):
        assert CliRunner().invoke(cli, ["self", "doctor"]).exit_code == 0
    real_fail = [doctor.DoctorCheck(name="sdd: gh", ok=False, fix="gh auth login")]
    with mock.patch("parrot.self_.doctor.run_doctor", return_value=real_fail):
        result = CliRunner().invoke(cli, ["self", "doctor", "--sdd"])
        assert result.exit_code == 1 and "gh auth login" in result.output


def test_hung_ls_remote_times_out_as_informational(ready_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`git ls-remote` that never answers must not hang the doctor: it degrades to an informational check."""
    import os
    import shutil

    real_git = shutil.which("git")
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "git").write_text(
        f'#!/bin/sh\ncase "$*" in *ls-remote*) sleep 30;; esac\nexec {real_git} "$@"\n', encoding="utf-8"
    )
    (shim / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(doctor, "GIT_TIMEOUT_S", 0.5)
    import time

    started = time.monotonic()
    result = doctor._check_sdd_git(ready_repo, "dev")
    assert time.monotonic() - started < 10
    origin_check = next(c for c in result if c.name == "sdd: base branch on origin")
    assert origin_check.informational and "timed out" in origin_check.detail
