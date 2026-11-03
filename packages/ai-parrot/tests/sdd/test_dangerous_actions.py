"""C32 — the portable dangerous-actions guard (TASK-5110): rule table, quoting, escape hatch, config, parity."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from parrot.sdd.scripts.dangerous_actions import evaluate

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
    "git checkout .",
    "git restore .",
    "git branch -D dev",
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


def test_messages_name_only_portable_fixes(tmp_path: Path) -> None:
    for cmd in DENIED:
        reason = evaluate(_bash(cmd), root=tmp_path).reason
        assert "scripts/" not in reason and "make " not in reason and "/release" not in reason, cmd


def test_protected_branches_follow_sdd_config(tmp_path: Path) -> None:
    (tmp_path / "sdd").mkdir()
    (tmp_path / "sdd/config.json").write_text(json.dumps({"base_branch": "trunk"}))
    assert evaluate(_bash("git push --force origin trunk"), root=tmp_path).decision == "deny"
    assert evaluate(_bash("git push --force origin feat-x"), root=tmp_path).decision == "allow"


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


def _run_hook(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "parrot.sdd.scripts.dangerous_actions", "--hook"],
        input=stdin,
        capture_output=True,
        text=True,
        env=_clean_env(),
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
    "git checkout .",
    "git branch -D main",
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
