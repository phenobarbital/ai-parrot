"""Brief agy-permission-hook, task 1 — the Antigravity (agy) PreToolUse permission policy.

agy auto-approves only through ``permissions.allow`` rules; the hook narrows the managed rules with
``deny`` / ``force_ask`` and answers ``ask`` (neutral) otherwise. These tests pin the rule list, agy's
matching facts verified live (env prefix and ``cd`` ignored, ``git -C`` needs its own rule), the risk
table and the hook's I/O contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.sdd.scripts import agy_permissions
from parrot.sdd.scripts.agy_permissions import (
    GIT_SUBCOMMANDS,
    SDD_ALLOW_RULES,
    Decision,
    evaluate,
    rule_covers,
    workspace_roots,
)


@pytest.fixture(autouse=True)
def _no_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARROT_ALLOW_DANGEROUS", raising=False)


def _repo(path: Path, branch: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True)
    return path


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """A workspace checked out on a feature branch."""
    return _repo(tmp_path / "ws", "fix-x")


def _payload(command: str, workspace: Path, **args: str) -> dict:
    return {
        "toolCall": {"name": "run_command", "args": {"CommandLine": command, **args}},
        "workspacePaths": [str(workspace)],
        "conversationId": "c",
        "stepIdx": 1,
    }


def _decide(command: str, workspace: Path, **args: str) -> Decision:
    return evaluate(_payload(command, workspace, **args), root=workspace)


# --------------------------------------------------------------------------
# managed rules and agy matching
# --------------------------------------------------------------------------


def test_rules_are_unique_command_rules() -> None:
    assert len(SDD_ALLOW_RULES) == len(set(SDD_ALLOW_RULES))
    assert all(rule.startswith("command(") and rule.endswith(")") for rule in SDD_ALLOW_RULES)
    for needed in (
        "command(find)",
        "command(git -C)",
        "command(parrot sdd)",
        "command(wikitoolkit)",
        "command(pytest)",
    ):
        assert needed in SDD_ALLOW_RULES


def test_rules_never_cover_destructive_binaries() -> None:
    for words in (["rm", "-rf", "x"], ["git", "reset", "--hard"], ["curl", "x"], ["python", "-c", "x"], ["uv", "sync"]):
        assert not rule_covers(words)


def test_rule_covers_ignores_leading_assignments() -> None:
    """Verified live: `FOO=bar find …` runs with only `command(find)`."""
    assert rule_covers(["FOO=bar", "find", ".", "-name", "*.txt"])
    assert rule_covers(["PYTHONPATH=packages/ai-parrot/src", "pytest", "t.py"])


def test_git_dash_c_needs_its_own_rule() -> None:
    """Verified live: `git -C . status` does not match `command(git status)`."""
    assert ("git", "-C") in {tuple(r[len("command(") : -1].split()) for r in SDD_ALLOW_RULES}
    assert rule_covers(["git", "-C", ".", "status"])
    assert rule_covers(["git", "status"])


def test_git_subcommands_cover_the_git_rules() -> None:
    git_rules = {r[len("command(git ") : -1].split()[0] for r in SDD_ALLOW_RULES if r.startswith("command(git ")}
    assert git_rules - {"-C"} <= GIT_SUBCOMMANDS


# --------------------------------------------------------------------------
# decisions
# --------------------------------------------------------------------------

ASK = [
    'find packages/ -path "*/sdd*" -o -path "*/dev_loop*" 2>/dev/null | head -n 50',
    "sed -n '10,20p' README.md",
    "test -e x && sed -n '3p' x",
    'grep -rn "/api/v1" packages/',
    "rg -n 'def evaluate' packages/ai-parrot/src",
    "cat README.md | wc -l",
    "ls -la packages/",
    "mkdir -p sdd/briefs/x/tasks",
    "git status --short",
    "git -C . status --short",
    "git -C . add sdd/briefs/x.brief.md",
    "git log --oneline -5",
    "git diff --name-only origin/dev...HEAD",
    "git checkout dev",
    "git checkout -b fix-y origin/dev",
    "git switch dev",
    "git commit -m 'sdd: add brief'",
    "git commit -am 'x'",
    "git pull --ff-only origin dev",
    "git pull --no-rebase --no-edit origin dev && git push origin dev",
    "git push -u origin fix-x",
    "git push origin dev",
    "git fetch origin dev",
    "git branch --show-current",
    "git remote get-url origin",
    "git config --get user.email",
    "git worktree list",
    "gh pr create --base dev --title t --body b",
    "gh api repos/o/r/code-scanning/alerts/1",
    "parrot sdd ids reserve --kind task --count 1 --base-branch dev --label x",
    "parrot sdd worktree ensure --json --slug s --brief-key k --base-branch dev",
    "parrot sdd task graph sdd/briefs/s.index.json",
    "wikitoolkit query 'agy permissions'",
    "wikitoolkit ledger claim abc --actor agent:sdd-fix",
    "PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_x.py -q",
    "python -m pytest packages/ai-parrot/tests/sdd/test_x.py::test_a",
    "ruff check --fix packages/ai-parrot/src/parrot/sdd/cli.py",
    "black packages/ai-parrot/src/parrot/sdd/cli.py",
    "source .venv/bin/activate && parrot sdd tests select --tier merge",
    'cat "$(git rev-parse --show-toplevel)/README.md"',
    "cat <<'EOF' > notes.md\nhello 'unbalanced\nEOF",
    "echo done > /dev/null 2>&1",
    "rm -rf build",  # not covered by a managed rule: agy prompts by itself, the hook stays neutral
    "npm test",
]


@pytest.mark.parametrize("command", ASK)
def test_neutral(command: str, ws: Path) -> None:
    decision = _decide(command, ws)
    assert decision.decision == "ask", decision.reason


FORCE_ASK = [
    ("find . -name x -delete", "find -delete"),
    ("find . -name '*.py' -exec rm {} +", "find -exec"),
    ("find / -name passwd", "outside the workspace"),
    ("sed -i s/a/b/ f", "sed -i"),
    ("sed -ni '1p' f", "sed -i"),
    ("sed -n '1e rm -rf /' f", "print-only"),
    ("sed 's/a/b/w out' f", "print-only"),
    ("sed -f script.sed f", "sed -f"),
    ("cat ~/.ssh/id_rsa", "outside the workspace"),
    ("cat $HOME/.aws/credentials", "outside the workspace"),
    ("cat $SECRET_FILE", "shell variable"),
    ("ls $(echo /etc)", "command substitution"),
    ("ls -la /", "outside the workspace"),
    ("cat ../../outside.txt", "outside the workspace"),
    ("cd /etc && cat passwd", "working directory"),
    ("echo hi > /tmp/x", "outside the workspace"),
    ("sort -o out.txt in.txt", "sort -o"),
    ("uniq in.txt out.txt", "uniq"),
    ("rg --pre cat x", "rg --pre"),
    ("git -C . reset --soft HEAD~1", "not on the SDD auto-approve list"),
    ("git -C . stash", "not on the SDD auto-approve list"),
    ("git -C /etc status", "outside the workspace"),
    ("git -C . -c core.pager=sh status", "overrides repository settings"),
    ("git push --force origin fix-x", "git push --force"),
    ("git push --force-with-lease origin fix-x", "git push --force-with-lease"),
    ("git push origin :old-branch", "deletes a branch"),
    ("git push origin +fix-x", "forces the update"),
    ("git commit --amend --no-edit", "--amend"),
    ("git commit -n -m x", "skips hooks"),
    ("git checkout file.py", "git checkout"),
    ("git checkout -- .gitignore", "git checkout"),
    ("git checkout -B dev", "git checkout"),
    ("git switch --discard-changes dev", "git switch"),
    ("git branch -D fix-old", "git branch -D"),
    ("git remote add x url", "git remote"),
    ("git config user.email a@b.c", "git config"),
    ("git -C . worktree add ../x", "git worktree"),
    ("git fetch origin +dev:dev", "refspec"),
    ("git log --output=/tmp/log", "writes a file"),
    ("gh api repos/o/r/pulls -X POST", "changes GitHub state"),
    ("gh api repos/o/r/issues -f title=x", "write request"),
    ("parrot sdd install --host google", "parrot sdd install"),
    ("parrot sdd launch worker FEAT-1", "parrot sdd launch"),
    ("parrot sdd worktree remove x", "worktree remove"),
    ("wikitoolkit mcp", "wikitoolkit mcp"),
    ("pytest", "without an explicit path"),
    ("pytest -k foo", "without an explicit path"),
    ("ruff check --fix", "without an explicit path"),
    ("LD_PRELOAD=/x.so pytest packages/a/test_a.py", "environment override"),
    ("timeout 5 find . -delete", "find -delete"),
]


@pytest.mark.parametrize(("command", "why"), FORCE_ASK)
def test_force_ask(command: str, why: str, ws: Path) -> None:
    decision = _decide(command, ws)
    assert decision.decision == "force_ask", command
    assert why in decision.reason


DENY = [
    ("git push origin main", "push to main"),
    ("git push origin HEAD:main", "push to main"),
    ("git -C . push origin master", "push to master"),
    ("git reset --hard", "git reset --hard"),
    ("git push --force origin dev", "Force-push"),
    ("echo x > .env", "secrets file"),
    ("uv publish", "publication"),
]


@pytest.mark.parametrize(("command", "why"), DENY)
def test_deny(command: str, why: str, ws: Path) -> None:
    decision = _decide(command, ws)
    assert decision.decision == "deny", command
    assert why in decision.reason


def test_bare_push_on_main_is_denied(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "on-main", "main")
    assert _decide("git push", repo).decision == "deny"
    assert _decide("git push origin", repo).decision == "deny"
    feature = _repo(tmp_path / "on-feature", "fix-y")
    assert _decide("git push", feature).decision == "ask"


def test_configured_hotfix_branch_is_denied(ws: Path) -> None:
    (ws / "sdd").mkdir()
    (ws / "sdd" / "config.json").write_text(json.dumps({"hotfix_base": "release"}), encoding="utf-8")
    assert _decide("git push origin release", ws).decision == "deny"


def test_cwd_argument_outside_workspace(ws: Path, tmp_path: Path) -> None:
    assert _decide("ls", ws, Cwd=str(tmp_path)).decision == "force_ask"
    (ws / "sub").mkdir()
    assert _decide("ls", ws, Cwd="sub").decision == "ask"


def test_worktree_includes_main_checkout(tmp_path: Path) -> None:
    main = _repo(tmp_path / "main", "dev")
    subprocess.run(["git", "-C", str(main), "commit", "-q", "--allow-empty", "-m", "init"], check=True,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t"})  # fmt: skip
    wt = tmp_path / "elsewhere" / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "fix-z", str(wt)], check=True)
    assert workspace_roots([str(wt)], None) == [wt, main]
    assert _decide(f"cat {main}/README.md", wt).decision == "ask"


def test_escape_hatch(ws: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARROT_ALLOW_DANGEROUS", "1")
    assert _decide("git push origin main", ws).decision == "ask"
    assert _decide("find . -delete", ws).decision == "ask"


def test_unparseable_command_is_confirmed(ws: Path) -> None:
    decision = _decide("cat 'unterminated", ws)
    assert decision.decision == "force_ask"
    assert "could not parse" in decision.reason


@pytest.mark.parametrize(
    "payload",
    [
        {"toolCall": {"name": "view_file", "args": {"AbsolutePath": "/etc/passwd"}}},
        {"toolCall": {"name": "run_command", "args": {}}},
        {"toolCall": "nope"},
        {},
    ],
)
def test_other_payloads_are_neutral(payload: dict) -> None:
    assert evaluate(payload, root=None).decision == "ask"


# --------------------------------------------------------------------------
# hook I/O
# --------------------------------------------------------------------------


def _run_hook(stdin: str) -> subprocess.CompletedProcess[str]:
    # `import parrot` may chdir to another checkout, so a relative PYTHONPATH would import the wrong tree.
    src = str(Path(agy_permissions.__file__).resolve().parents[3])
    env = {k: v for k, v in os.environ.items() if k != "PARROT_ALLOW_DANGEROUS"}
    env["PYTHONPATH"] = os.pathsep.join(p for p in (src, env.get("PYTHONPATH", "")) if p)
    return subprocess.run(
        [sys.executable, "-m", "parrot.sdd.scripts.agy_permissions", "--hook"],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_main_writes_one_json_object(ws: Path) -> None:
    proc = _run_hook(json.dumps(_payload("git push origin main", ws)))
    assert proc.returncode == 0
    lines = proc.stdout.strip().splitlines()
    assert len(lines) == 1
    out = json.loads(lines[0])
    assert out["decision"] == "deny"
    assert "main" in out["reason"]


def test_main_omits_empty_reason(ws: Path) -> None:
    out = json.loads(_run_hook(json.dumps(_payload("git status", ws))).stdout)
    assert out == {"decision": "ask"}


@pytest.mark.parametrize("stdin", ["not json", "[1, 2]", ""])
def test_main_fails_neutral(stdin: str) -> None:
    proc = _run_hook(stdin)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["decision"] == "ask"
    assert "checks skipped" in out["reason"]


def test_cli_verb_serves_the_hook(ws: Path) -> None:
    from parrot.cli import cli

    result = CliRunner().invoke(
        cli, ["sdd", "hooks", "agy-permissions", "--hook"], input=json.dumps(_payload("find . -delete", ws))
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output.strip().splitlines()[-1])["decision"] == "force_ask"


def test_tracked_hooks_json_uses_the_bare_command() -> None:
    root = Path(__file__).resolve().parents[4]
    data = json.loads((root / ".agents" / "hooks.json").read_text(encoding="utf-8"))
    (entry,) = data["parrot-sdd-permissions"]["PreToolUse"]
    assert entry["matcher"] == "run_command"
    assert entry["hooks"][0]["command"] == "parrot sdd hooks agy-permissions --hook"
