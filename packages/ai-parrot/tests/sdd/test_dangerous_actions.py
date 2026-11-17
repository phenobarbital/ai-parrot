"""C32 — the portable dangerous-actions guard (TASK-5110): rule table, quoting, escape hatch, config, parity."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.sdd.scripts.dangerous_actions import _render, evaluate, protected_branches

FAKE_GHP = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "."}


def _write(path: str, tool: str = "Write") -> dict:
    return {"tool_name": tool, "tool_input": {"file_path": path}, "cwd": "."}


DENIED = [
    "git reset --hard origin/dev",
    "git clean -fdx",
    "git push --force origin dev",
    "git push -f origin main",
    # FEAT-792 / issue:047c5435b564 — a leading "+" on a refspec forces the update like --force
    "git push origin +dev",
    "git push origin +HEAD:main",
    "git push origin +refs/heads/main",
    "git push -u origin +main",
    "git -C repo push origin +staging",
    "git push --force-with-lease origin +dev",
    "git checkout .",
    "git restore .",
    "git branch -D dev",
    # FEAT-839 / issue:a682edf559a5 — protected names still match as whole tokens
    "git branch -d main",
    "git branch -D refs/heads/main",
    "git push -f origin HEAD:main",
    "git push --force origin dev:dev",
    "git worktree remove --force /tmp/x",
    "rm -rf ~",
    "rm -rf /",
    "rm -rf $HOME",
    "rm -rf .venv",
    "rm -rf .git",
    "mkfs.ext4 /dev/sda1",
    "Remove-Item -Recurse -Force C:\\",
    "Remove-Item C:\\ -r",
    "remove-item -recurse ~",
    "rd /s /q C:\\",
    "del /s /q D:\\",
    "format D:",
    "diskutil eraseDisk APFS X disk2",
    'psql -c "DROP ' + 'TABLE x"',
    "twine upload dist/*",
    "uv publish",
    "npm publish",
    f"curl -H 'Authorization: {FAKE_GHP}' https://api.github.com",
    'bash -c "git reset --hard"',
    'pwsh -Command "Remove-Item -Recurse C:\\"',
    'cmd /c "rd /s /q C:\\"',
    'ssh host "rm -rf ~"',
]

ALLOWED = [
    'echo "git reset --hard"',
    "git push --force-with-lease origin feat-x",
    "git push --force origin feat-x",
    "git push origin +feat-x",
    "git push origin +HEAD:feat-x",
    "git push origin +feat-x:feat-x",
    "git push origin dev",
    'echo "git push origin +dev"',
    # FEAT-839 / issue:a682edf559a5 — a protected name inside a longer branch name is not that branch
    "git branch -d feat-FEAT-837-dev-loop-feature-launcher-fixes",
    "git branch -D fix-main-menu",
    "git branch -d feat/dev",
    "git branch -d staging.old",
    "git push -f origin feat-x-dev-loop",
    "git push --force origin fix-main-menu",
    "git reset --soft HEAD~1",
    "rm -rf build/",
    "rm -rf /tmp/build",
    'git commit -m "never run rm -rf ~"',
    'curl --token "$GH_TOKEN" https://x',
    "export K=AKIAIOSFODNN7EXAMPLE",
    "Remove-Item -Recurse build",
    "Remove-Item -Recurse C:\\Users\\me\\build",
    "rd /s /q build",
    "ls -la",
    "git status",
    "pip install requests",  # no uv.lock in tmp_path
]


@pytest.mark.parametrize("cmd", DENIED)
def test_denied(cmd: str, tmp_path: Path) -> None:
    verdict = evaluate(_bash(cmd), root=tmp_path)
    assert verdict.decision == "deny", cmd
    assert "PARROT_ALLOW_DANGEROUS=1" in verdict.reason


@pytest.mark.parametrize("cmd", ALLOWED)
def test_allowed(cmd: str, tmp_path: Path) -> None:
    assert evaluate(_bash(cmd), root=tmp_path).decision == "allow", cmd


@pytest.mark.parametrize(
    "cmd",
    [
        "rm -rf .claude/worktrees/x",
        "rm -rf .parrot/worktrees/x",
        "Remove-Item -Recurse .parrot\\worktrees\\x",
    ],
)
def test_dangerous_rm_both_roots(cmd: str, tmp_path: Path) -> None:
    assert evaluate(_bash(cmd), root=tmp_path).decision == "deny", cmd


def test_merge_guard_uses_resolved_worktree_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    custom_root = tmp_path / "custom-workers"
    custom_root.mkdir()
    monkeypatch.setenv("WORKTREE_BASE_PATH", str(custom_root))
    monkeypatch.setattr("parrot.sdd.scripts.dangerous_actions._live_worker", lambda: True)

    assert evaluate(_bash("git pull"), root=tmp_path).decision == "warn"


def test_merge_guard_falls_back_when_resolver_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fallback_root = tmp_path / ".parrot" / "worktrees"
    fallback_root.mkdir(parents=True)

    def broken_worktree_root(repo_root: Path, override: str | None = None) -> Path:
        del repo_root, override
        raise RuntimeError("resolver unavailable")

    monkeypatch.setattr("parrot.sdd.config.worktree_root", broken_worktree_root)
    monkeypatch.setattr("parrot.sdd.scripts.dangerous_actions._live_worker", lambda: True)

    assert evaluate(_bash("git merge feat-x"), root=tmp_path).decision == "warn"


def test_messages_name_only_portable_fixes(tmp_path: Path) -> None:
    for cmd in DENIED:
        reason = evaluate(_bash(cmd), root=tmp_path).reason
        assert "scripts/" not in reason and "make " not in reason and "/release" not in reason, cmd


def test_protected_branches_follow_sdd_config(tmp_path: Path) -> None:
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sdd/config.json").write_text(json.dumps({"base_branch": "trunk"}))
    assert evaluate(_bash("git push --force origin trunk"), root=tmp_path).decision == "deny"
    assert evaluate(_bash("git push --force origin feat-x"), root=tmp_path).decision == "allow"


def test_default_branches_stay_protected_with_custom_base(tmp_path: Path) -> None:
    """FEAT-792 D2 / issue:47b61e69475b: the config adds lanes, it never removes the defaults."""
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sdd/config.json").write_text(json.dumps({"base_branch": "trunk", "hotfix_base": "release"}))
    assert set(protected_branches(tmp_path)) == {"trunk", "release", "dev", "main", "master", "staging"}
    for branch in ("trunk", "release", "dev", "staging", "main", "master"):
        assert evaluate(_bash(f"git push origin +{branch}"), root=tmp_path).decision == "deny", branch
    assert evaluate(_bash("git push origin +feat-x"), root=tmp_path).decision == "allow"


def test_invalid_config_falls_back_to_defaults(tmp_path: Path) -> None:
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sdd/config.json").write_text("{nope")
    assert evaluate(_bash("git push --force origin main"), root=tmp_path).decision == "deny"


def test_escape_hatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PARROT_ALLOW_DANGEROUS", "1")
    assert evaluate(_bash("git reset --hard"), root=tmp_path).decision == "allow"
    assert evaluate(_write(".env"), root=tmp_path).decision == "allow"


def test_pip_rule_only_in_uv_repos(tmp_path: Path) -> None:
    assert evaluate(_bash("pip install x"), root=tmp_path).decision == "allow"
    (tmp_path / "uv.lock").write_text("")
    assert evaluate(_bash("pip install x"), root=tmp_path).decision == "deny"
    assert evaluate(_bash("uv pip install x"), root=tmp_path).decision == "allow"


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "/repo/.env.local",
        "C:\\repo\\credentials.json",
        "/home/u/.ssh/config",
        "a/server.pem",
        "x/.venv/lib/a.py",
        "a/node_modules/b.js",
        "/r/.git/objects/ab/cd",
        "id_rsa",
        ".npmrc",
    ],
)
def test_write_to_secret_or_generated_path_denied(path: str, tmp_path: Path) -> None:
    assert evaluate(_write(path), root=tmp_path).decision == "deny"


@pytest.mark.parametrize("path", ["env/.env.example", ".env.sample", "src/app.py", "docs/env.md"])
def test_template_and_normal_files_allowed(path: str, tmp_path: Path) -> None:
    assert evaluate(_write(path, "Edit"), root=tmp_path).decision == "allow"


def test_unknown_tool_and_empty_input_allowed(tmp_path: Path) -> None:
    assert evaluate({"tool_name": "Read", "tool_input": {"file_path": ".env"}}, root=tmp_path).decision == "allow"
    assert evaluate({"tool_name": "Bash", "tool_input": {}}, root=tmp_path).decision == "allow"


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "PARROT_ALLOW_DANGEROUS"}


def _run_hook(
    stdin: str, *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    hook_env = _clean_env() if env is None else dict(env)
    hook_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    return subprocess.run(
        [sys.executable, "-m", "parrot.sdd.scripts.dangerous_actions", "--hook"],
        input=stdin,
        capture_output=True,
        text=True,
        env=hook_env,
        cwd=cwd,
        check=False,
    )


def test_main_deny_shape_and_exit_zero() -> None:
    proc = _run_hook(json.dumps(_bash("git reset --hard")))
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert len(proc.stdout.strip().splitlines()) == 1


def test_main_allow_is_empty_object() -> None:
    proc = _run_hook(json.dumps(_bash("ls")))
    assert proc.returncode == 0 and json.loads(proc.stdout) == {}


def test_main_malformed_stdin_allows_with_system_message() -> None:
    proc = _run_hook("not json")
    assert proc.returncode == 0
    assert "systemMessage" in json.loads(proc.stdout)


def test_hook_main_does_not_import_parrot_cli() -> None:
    code = (
        "import sys, io, json\n"
        "sys.stdin = io.StringIO(json.dumps({'tool_name':'Bash','tool_input':{'command':'ls'}}))\n"
        "from parrot.sdd.scripts.dangerous_actions import main\n"
        "main(['--hook'])\n"
        "sys.stderr.write('CLI=' + str('parrot.cli' in sys.modules))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert "CLI=False" in proc.stderr, proc.stderr


def _plane_repo(tmp_path: Path) -> Path:
    """Create a repository with a hand-written mandatory procedure plane."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/feat-FEAT-1-demo\n")

    source = repo / "sdd" / "procedures" / "x.yaml"
    source.parent.mkdir(parents=True)
    source.write_text("name: x\n")
    index = {
        "schema_version": 1,
        "generation": "test",
        "sources": [{"path": "sdd/procedures/x.yaml", "sha1": hashlib.sha1(source.read_bytes()).hexdigest()}],
        "procedures": {
            "sdd:task-close": {
                "mode": "mandatory",
                "use_instead": "parrot sdd task close",
                "preconditions": [],
            }
        },
        "guards": [
            {
                "procedure": "sdd:task-close",
                "kind": "bypass",
                "executable": "git",
                "argv_prefix": ["mv"],
                "path_globs": ["sdd/tasks/active/*"],
                "scope": {},
            }
        ],
    }
    plane = repo / ".parrot" / "procedure"
    plane.mkdir(parents=True)
    (plane / "procedures.json").write_text(json.dumps(index))
    return repo


def test_dangerous_guard_unchanged_without_plane(tmp_path: Path) -> None:
    """Without an index, allowed and denied output stays byte-identical to today's behavior."""
    allowed_payload = _bash("ls")
    allowed_payload["cwd"] = str(tmp_path)
    allowed = _run_hook(json.dumps(allowed_payload), cwd=tmp_path)
    assert allowed.stdout == "{}\n"

    denied_payload = _bash("git reset --hard")
    denied_payload["cwd"] = str(tmp_path)
    denied = _run_hook(json.dumps(denied_payload), cwd=tmp_path)
    assert denied.stdout == json.dumps(_render(evaluate(denied_payload, root=tmp_path))) + "\n"


def test_dangerous_guard_denies_bypass(tmp_path: Path) -> None:
    """A guarded task move is denied and names the prescribed command."""
    repo = _plane_repo(tmp_path)
    payload = _bash("git mv sdd/tasks/active/TASK-1-x.md moved.md")
    payload["cwd"] = str(repo)
    proc = _run_hook(json.dumps(payload), cwd=repo)
    output = json.loads(proc.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "deny"
    assert "parrot sdd task close" in hook_output["permissionDecisionReason"]


def test_dangerous_guard_existing_deny_wins(tmp_path: Path) -> None:
    """An original destructive-action denial wins and carries no procedure text."""
    repo = _plane_repo(tmp_path)
    payload = _bash("git reset --hard && git mv sdd/tasks/active/TASK-1-x.md moved.md")
    payload["cwd"] = str(repo)
    proc = _run_hook(json.dumps(payload), cwd=repo)
    output = json.loads(proc.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "deny"
    assert hook_output["permissionDecisionReason"].startswith("BLOCKED:")
    assert "Procedure" not in hook_output["permissionDecisionReason"]
    assert "additionalContext" not in hook_output


def test_dangerous_guard_escape_turns_deny_into_context(tmp_path: Path) -> None:
    """The procedure escape hatch turns a bypass denial into additional context."""
    repo = _plane_repo(tmp_path)
    payload = _bash("git mv sdd/tasks/active/TASK-1-x.md moved.md")
    payload["cwd"] = str(repo)
    environment = _clean_env()
    environment["PARROT_ALLOW_PROCEDURE"] = "1"
    proc = _run_hook(json.dumps(payload), cwd=repo, env=environment)
    output = json.loads(proc.stdout)
    hook_output = output["hookSpecificOutput"]
    assert hook_output["hookEventName"] == "PreToolUse"
    assert "parrot sdd task close" in hook_output["additionalContext"]
    assert "updatedInput" not in output


def _bash_hook() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".claude" / "hooks" / "dangerous-actions-blocker.sh"
        if candidate.is_file():
            return candidate
    return None


PARITY = [
    "git reset --hard origin/dev",
    "git clean -fdx",
    "git push --force origin dev",
    "git push --force-with-lease origin feat-x",
    "git push origin +dev",
    "git push origin +HEAD:main",
    "git push origin +feat-x",
    "git checkout .",
    "git branch -D main",
    "git branch -d dev",
    "git branch -D refs/heads/main",
    "git push -f origin HEAD:main",
    "git push --force origin dev:dev",
    "git branch -d feat-FEAT-837-dev-loop-feature-launcher-fixes",
    "git branch -D fix-main-menu",
    "git branch -d feat/dev",
    "git push -f origin feat-x-dev-loop",
    "git push --force origin fix-main-menu",
    "git worktree remove --force /tmp/x",
    "rm -rf ~",
    "rm -rf build/",
    "rm -rf .venv",
    'echo "git reset --hard"',
    'bash -c "git reset --hard"',
    'psql -c "DROP ' + 'TABLE x"',
    "twine upload dist/*",
    f"curl {FAKE_GHP}",
    "export K=AKIAIOSFODNN7EXAMPLE",
    "ls -la",
]


@pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("jq") and _bash_hook()), reason="needs bash, jq and the repo hook"
)
@pytest.mark.parametrize("cmd", PARITY)
def test_parity_with_bash_blocker(cmd: str, tmp_path: Path) -> None:
    hook = _bash_hook()
    assert hook is not None
    proc = subprocess.run(
        ["bash", str(hook)],
        input=json.dumps(_bash(cmd)),
        capture_output=True,
        text=True,
        env=_clean_env(),
        cwd=tmp_path,
        check=False,
    )
    assert (evaluate(_bash(cmd), root=tmp_path).decision == "deny") == (proc.returncode == 2), cmd
