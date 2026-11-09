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
    "git fetch --prune origin",
    "git commit -m 'sdd: line one\n\nline two'",
    "git commit -m \"$(cat <<'EOF'\nsdd: brief\n\nbody\nEOF\n)\"",
    "rg --pretty 'x' packages/",
    "git log --oneline origin/dev..HEAD",
    "git branch --contains HEAD",
    "git merge --ff-only origin/dev",
    "git switch -c fix-y",
    "date +%Y-%m-%d",
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
    # adversarial review findings (codex + Claude subagent), each reproduced before the fix
    ("git branch -Df feature", "git branch -Df"),
    ("git branch -vd feat-x", "git branch -vd"),
    ("git switch -Cfeature HEAD~1", "git switch -Cfeature"),
    ("git switch -fc newb", "git switch -fc"),
    ("git push -df origin feature", "not a plain push"),
    ("git push -fu origin feat-x", "not a plain push"),
    ("git push --del origin feat-x", "not a plain push"),
    ("git push origin 'refs/heads/*:refs/heads/*'", "pushes a pattern"),
    ("git push https://example.com/x.git HEAD", "pushes to a URL"),
    ("git commit --amen --no-edit", "--amen"),
    ("git commit --no-verif -m x", "--no-verif"),
    ("git commit -F /etc/passwd", "outside the workspace"),
    ("git remote -v add evil https://example.com/x.git", "git remote"),
    ("git config --global --list", "git config"),
    ("git diff --no-index /etc/passwd /etc/hosts", "--no-index"),
    ("git blame --contents /etc/passwd README.md", "--contents"),
    ("git grep -Osh x", "git grep -Osh"),
    ("git grep --open-files-in-pager=sh x", "--open-files-in-pager"),
    ("git pull --rebase origin dev", "git pull --rebase"),
    ("git merge --abort", "not a plain merge"),
    ("git add -f .env", "adds ignored files"),
    ("git fetch --prune-tags origin", "git fetch --prune-tags"),
    ("git -C $OTHER commit -m x", "shell variable"),
    ("git -C $(pwd)/../../../../../../../.. add -A", "outside the workspace"),
    ("gh api -XDELETE repos/o/r/git/refs/heads/feature", "method DELETE"),
    ("gh pr create --title t --body-file /etc/passwd", "outside the workspace"),
    ("cat <<EOF\n$(find . -name victim -delete)\nEOF", "unquoted heredoc body"),
    ("echo '<<X'\ngit push -f origin feat-x", "not a plain push"),
    ("echo '<<X'\nsed -i s/a/b/ README.md", "sed -i"),
    ("cat {/etc/passwd,x}", "brace expansion"),
    ('cat "$(git rev-parse --show-toplevel)/../../../../../../../../../../../../etc/passwd"', "outside the workspace"),
    ("cat $(pwd)/../../../../../../../../../etc/passwd", "outside the workspace"),
    ("find -L /etc -type f", "outside the workspace"),
    ("grep -f/etc/passwd .gitignore", "outside the workspace"),
    ("grep -eroot /etc/passwd", "outside the workspace"),
    ("rg --file=/etc/passwd .gitignore", "outside the workspace"),
    ("rg --files /etc", "outside the workspace"),
    ("rg --hostname-bin=/tmp/evil x README.md", "runs a program"),
    ("jq -f /etc/passwd README.md", "outside the workspace"),
    ("date -f /etc/passwd", "outside the workspace"),
    ("sort --compress-program=sh x", "runs a program"),
    ("sort -ro out.txt in.txt", "sort -ro"),
    ("sort --out=out.txt in.txt", "sort --out"),
    ("tree -ofile .", "tree -ofile"),
    ("printf '{}' > .agents/hooks.json", "hook or git configuration"),
    ("echo x > .git/hooks/pre-commit", "hook or git configuration"),
    ("pytest packages/a/test_a.py --junitxml /tmp/x.xml", "writes output files"),
    ("pytest --basetemp=packages packages/a/test_a.py", "writes output files"),
    ("PYTHONPATH=/tmp/evil pytest packages/a/test_a.py", "PYTHONPATH entry"),
    ("GIT_PAGER='sh -c id' git log", "environment override GIT_PAGER"),
    ("parrot sdd docs migrate-index", "not on the SDD auto-approve list"),
    ("wikitoolkit export -o /tmp/x", "not on the SDD auto-approve list"),
    # second review round
    ("printf '{}' | sort -o.agents/hooks.json", "sort -o.agents/hooks.json"),
    ("sort -oREADME.md AGENTS.md", "sort -oREADME.md"),
    ("git commit -F/etc/passwd", "outside the workspace"),
    ("git grep -f/etc/passwd", "outside the workspace"),
    ("pytest -c/tmp/pytest.ini packages/a/test_a.py", "outside the workspace"),
    ("pytest -olog_file=/tmp/x.log packages/a/test_a.py", "overrides the test configuration"),
    ("pytest -oaddopts=--basetemp=/tmp/victim packages/a/test_a.py", "overrides the test configuration"),
    ("git config --list", "add --local"),
    ("git config -l", "add --local"),
    ("git config --get-regexp url", "add --local"),
    ("git fetch /tmp/other-repo", "fetches from a URL or path"),
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
    ("git push origin HEAD:heads/main", "push to main"),
    ("echo '<<X'\ngit push origin HEAD:main", "push to main"),
]


def test_symlink_out_of_the_workspace_is_confirmed(ws: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "link").symlink_to(outside)
    decision = _decide("cat link/secret.txt", ws)
    assert decision.decision == "force_ask"
    assert "symlink" in decision.reason


def test_bare_symlink_and_globs_are_followed(ws: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("x", encoding="utf-8")
    (ws / "outside").symlink_to(secret)
    assert _decide("cat outside", ws).decision == "force_ask"
    etc = tmp_path / "etc"
    etc.mkdir()
    (etc / "passwd").write_text("x", encoding="utf-8")
    (ws / "etcdir").symlink_to(etc)
    assert _decide("cat */passwd", ws).decision == "force_ask"
    (ws / "notes.md").write_text("x", encoding="utf-8")
    assert _decide("cat notes.md *.md", ws).decision == "ask"


def test_config_scoped_listing_is_neutral(ws: Path) -> None:
    assert _decide("git config --local --list", ws).decision == "ask"
    assert _decide("git config --get user.email", ws).decision == "ask"


def _git_config(ws: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(ws), "config", *args], check=True)


def test_bare_push_follows_the_configured_upstream(ws: Path) -> None:
    _git_config(ws, "push.default", "upstream")
    _git_config(ws, "branch.fix-x.remote", "origin")
    _git_config(ws, "branch.fix-x.merge", "refs/heads/main")
    assert _decide("git push", ws).decision == "deny"
    _git_config(ws, "branch.fix-x.merge", "refs/heads/fix-x")
    assert _decide("git push", ws).decision == "ask"


def test_bare_push_with_configured_refspecs_is_confirmed(ws: Path) -> None:
    _git_config(ws, "remote.origin.url", "https://example.com/x.git")
    _git_config(ws, "remote.origin.push", "+HEAD:refs/heads/feature")
    decision = _decide("git push origin", ws)
    assert decision.decision == "force_ask"
    assert "refspecs configured" in decision.reason
    assert _decide("git push origin fix-x", ws).decision == "ask"


def test_matching_push_default_is_confirmed(ws: Path) -> None:
    _git_config(ws, "push.default", "matching")
    assert _decide("git push", ws).decision == "force_ask"


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
def test_main_fails_to_force_ask(stdin: str) -> None:
    """A failure must not answer neutral: the broad agy rules would then apply without narrowing."""
    proc = _run_hook(stdin)
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["decision"] == "force_ask"
    assert "checks failed" in out["reason"]


def test_cli_verb_serves_the_hook(ws: Path) -> None:
    from parrot.cli import cli

    result = CliRunner().invoke(
        cli, ["sdd", "hooks", "agy-permissions", "--hook"], input=json.dumps(_payload("find . -delete", ws))
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output.strip().splitlines()[-1])["decision"] == "force_ask"


REPO_ROOT = Path(__file__).resolve().parents[4]
LAUNCHER = REPO_ROOT / "scripts" / "sdd" / "agy_hook.sh"


def test_tracked_hooks_json_runs_the_repository_launcher() -> None:
    data = json.loads((REPO_ROOT / ".agents" / "hooks.json").read_text(encoding="utf-8"))
    (entry,) = data["parrot-sdd-permissions"]["PreToolUse"]
    assert entry["matcher"] == "run_command|write_file|edit_file"
    # agy runs the command from the folder holding hooks.json
    assert entry["hooks"][0]["command"] == "sh ../scripts/sdd/agy_hook.sh"
    assert LAUNCHER.is_file()


def test_launcher_serves_this_checkout(ws: Path) -> None:
    if not (REPO_ROOT.parent / ".git").exists() and not (REPO_ROOT / ".git").exists():
        pytest.skip("not running from a git checkout")
    proc = subprocess.run(
        ["sh", "../scripts/sdd/agy_hook.sh"],
        cwd=REPO_ROOT / ".agents",
        input=json.dumps(_payload("find . -name x -delete", ws)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    if "unavailable" in out.get("reason", ""):
        pytest.skip(f"main checkout has no usable .venv here: {out['reason']}")
    assert out["decision"] == "force_ask"
    assert "find -delete" in out["reason"]


def test_launcher_judges_write_file(ws: Path) -> None:
    """The tracked launcher denies a write_file whose Path escapes the workspace."""
    if not (REPO_ROOT.parent / ".git").exists() and not (REPO_ROOT / ".git").exists():
        pytest.skip("not running from a git checkout")
    payload = {
        "toolCall": {"name": "write_file", "args": {"Path": "/tmp/escape.txt"}},
        "workspacePaths": [str(ws)],
        "conversationId": "c",
        "stepIdx": 1,
    }
    proc = subprocess.run(
        ["sh", "../scripts/sdd/agy_hook.sh"],
        cwd=REPO_ROOT / ".agents",
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    if "unavailable" in out.get("reason", ""):
        pytest.skip(f"main checkout has no usable .venv here: {out['reason']}")
    assert out["decision"] == "deny"
    assert "outside" in out["reason"].lower()


def test_launcher_outside_a_checkout_asks_for_every_command(tmp_path: Path) -> None:
    script = tmp_path / "agy_hook.sh"
    script.write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)
    proc = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, input="{}", capture_output=True, text=True, env=env, check=False
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["decision"] == "force_ask"
    assert "not a git checkout" in out["reason"]


@pytest.fixture
def unattended(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable the non-interactive AGY permission mode."""
    monkeypatch.setenv(agy_permissions.UNATTENDED_ENV, "1")


def test_agy_permissions_unattended_force_ask_is_deny(
    ws: Path, unattended: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agy_permissions.worktree_environment.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setenv("PARROT_SDD_SANDBOX_BACKEND", "bubblewrap")
    decision = _decide("cat 'unterminated", ws)
    assert decision.decision == "deny"
    assert decision.reason.startswith("unattended:")


def test_agy_permissions_merge_and_overwrite(ws: Path) -> None:
    (ws / "packages" / "core" / "src").mkdir(parents=True)

    routine = _decide("git status", ws)
    assert routine.decision == "ask"
    assert routine.overwrite is not None
    assert routine.overwrite["CommandLine"].startswith("PYTHONPATH=")

    denied = _decide("uv sync", ws)
    assert denied.decision == "deny"
    assert denied.overwrite is None

    confirmed = _decide("find . -name x -delete", ws)
    assert confirmed.decision == "force_ask"
    assert confirmed.overwrite is not None
    assert confirmed.overwrite["CommandLine"].startswith("PYTHONPATH=")
    assert confirmed.overwrite["CommandLine"].endswith("find . -name x -delete")
    assert "overwrite" not in agy_permissions._render(Decision("deny", overwrite=routine.overwrite))


def test_agy_permissions_file_tools(ws: Path, tmp_path: Path) -> None:
    inside = {
        "toolCall": {"name": "write_file", "args": {"Path": "notes.txt", "Content": "x", "Overwrite": True}},
        "workspacePaths": [str(ws)],
    }
    assert evaluate(inside, root=ws).decision == "ask"

    for path in (str(tmp_path / "outside.txt"), "../outside.txt"):
        payload = {"toolCall": {"name": "write_file", "args": {"Path": path}}, "workspacePaths": [str(ws)]}
        assert evaluate(payload, root=ws).decision == "deny"

    outside = tmp_path / "outside"
    outside.mkdir()
    (ws / "link").symlink_to(outside)
    escaped = {"toolCall": {"name": "write_file", "args": {"Path": "link/escape.txt"}}, "workspacePaths": [str(ws)]}
    assert evaluate(escaped, root=ws).decision == "deny"

    shared = ws / ".venv"
    shared.mkdir()
    (shared / "pyvenv.cfg").write_text("home = /tmp", encoding="utf-8")
    protected = {"toolCall": {"name": "write_file", "args": {"Path": ".venv/file"}}, "workspacePaths": [str(ws)]}
    assert evaluate(protected, root=ws).decision == "deny"

    missing = {"toolCall": {"name": "edit_file", "args": {}}, "workspacePaths": [str(ws)]}
    assert evaluate(missing, root=ws).decision == "deny"
    assert evaluate(inside, root=None).decision == "deny"


def test_agy_permissions_unattended_wraps_and_requires_bubblewrap(
    ws: Path, unattended: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    (ws / "packages" / "core" / "src").mkdir(parents=True)
    monkeypatch.setattr(agy_permissions.worktree_environment.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setenv("PARROT_SDD_SANDBOX_BACKEND", "bubblewrap")
    wrapped = _decide("git status", ws)
    assert wrapped.decision == "ask"
    assert wrapped.overwrite is not None
    assert "bwrap" in wrapped.overwrite["CommandLine"]

    monkeypatch.setattr(agy_permissions.worktree_environment.shutil, "which", lambda _: None)
    assert _decide("git status", ws).decision == "deny"


def test_main_unattended_failure_is_deny(unattended: None) -> None:
    proc = _run_hook("not json")
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["decision"] == "deny"
    assert out["reason"].startswith("unattended:")


def test_agy_hook_sh_unattended_fallback(tmp_path: Path) -> None:
    script = tmp_path / "agy_hook.sh"
    script.write_text(LAUNCHER.read_text(encoding="utf-8"), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)
    env[agy_permissions.UNATTENDED_ENV] = "1"
    proc = subprocess.run(
        ["sh", str(script)], cwd=tmp_path, input="{}", capture_output=True, text=True, env=env, check=False
    )
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["decision"] == "deny"
    assert out["reason"].startswith("unattended:")
