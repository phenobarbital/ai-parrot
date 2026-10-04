"""Process-boundary tests for `.claude/hooks/e2e-teardown.sh` (FEAT-581, TASK-3544).

This hook is a `SubagentStop`/`Stop` defense-in-depth safety net for the two
M8 exploration agents (`e2e-api-tester`, `e2e-ui-tester`): it must clean up
ONLY runs owned by the matching fixed identity (`explore-<agent_type>`)
inside the resolved worktree, never a global/machine-wide kill, and it must
never crash or block on a malformed hook payload or a missing prerequisite
(`parrot` not installed).

The real bash script is invoked via `subprocess.run` (a genuine
process-boundary acceptance test, per this task's own instructions: "any
process-boundary acceptance test must use real subprocesses"). Its one real
collaborator, the `parrot` CLI, is faked with a small recording stub placed
on a fully-controlled `PATH` — this keeps the test hermetic (no
`ai-parrot-server` install or real E2E state required) while still proving
exactly what the hook invokes, with what arguments, from what working
directory, and that it tolerates that collaborator's own failure.

`PATH`/`HOME`/`CLAUDE_PROJECT_DIR` are built from scratch for every
invocation (never `os.environ.copy()`) so this suite is immune to whatever
Claude Code / Codex environment variables happen to be set in the
surrounding session (this repo's own real `.venv/bin/parrot` must never
leak in through an inherited `PATH` or `CLAUDE_PROJECT_DIR`).
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path
from typing import Any, Optional

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".claude" / "hooks" / "e2e-teardown.sh"

_API_OWNER = "explore-e2e-api-tester"
_UI_OWNER = "explore-e2e-ui-tester"


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """A minimal real git repo standing in for a resolved worktree root."""
    root = tmp_path / "repo"
    root.mkdir()
    _git("init", cwd=root)
    (root / "README.md").write_text("demo\n", encoding="utf-8")
    _git("add", ".", cwd=root)
    _git("commit", "-m", "initial", cwd=root)
    return root


@pytest.fixture
def isolated_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


def _install_parrot_stub(bin_dir: Path, *, log_path: Path, exit_code: int = 0) -> None:
    """Install a recording `parrot` stub: appends one JSON line per invocation.

    Records argv and the stub's own working directory so tests can assert
    exactly what the hook invoked and from where, without any real
    `ai-parrot-server`/E2E state. Pure bash/`printf` (no python3 dependency,
    no f-string/heredoc brace-escaping fragility) — every argument this
    suite ever passes through is a plain safe-slug/flag with no quotes or
    backslashes, so naive `"%s"` quoting is sufficient JSON string escaping.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "parrot"
    script = textwrap.dedent("""\
        #!/usr/bin/env bash
        {
            printf '{"argv":['
            first=1
            for arg in "$@"; do
                [[ $first -eq 0 ]] && printf ','
                first=0
                printf '"%s"' "$arg"
            done
            printf '],"cwd":"%s"}\\n' "$PWD"
        } >> "__LOG_PATH__"
        exit __EXIT_CODE__
        """)
    script = script.replace("__LOG_PATH__", str(log_path)).replace("__EXIT_CODE__", str(exit_code))
    stub.write_text(script, encoding="utf-8")
    stub.chmod(0o755)


def _run_hook(
    payload: Optional[dict[str, Any]],
    *,
    home: Path,
    extra_path_dirs: tuple[Path, ...] = (),
    raw_stdin: Optional[str] = None,
    env_overrides: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    """Invoke the real hook script with a from-scratch, hermetic environment."""
    path_entries = [str(p) for p in extra_path_dirs] + ["/usr/bin", "/bin"]
    env = {
        "PATH": ":".join(path_entries),
        "HOME": str(home),
        # Deliberately absent unless a test opts in: CLAUDE_PROJECT_DIR must
        # never leak this session's real repo (which has a real
        # `.venv/bin/parrot`) into the hook's own candidate-resolution list.
    }
    if env_overrides:
        env.update(env_overrides)

    stdin_text = raw_stdin if raw_stdin is not None else json.dumps(payload or {})
    return subprocess.run(
        ["bash", str(_HOOK_PATH)],
        input=stdin_text,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Success: owner/worktree-scoped immediate down
# ---------------------------------------------------------------------------


def test_teardown_invokes_scoped_down_for_api_tester(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook(
        {"agent_type": "e2e-api-tester", "cwd": str(worktree)},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
    )

    assert result.returncode == 0, result.stderr
    assert log_path.exists(), f"parrot stub was never invoked; stderr={result.stderr!r}"
    invocations = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(invocations) == 1
    argv = invocations[0]["argv"]
    assert argv == ["e2e", "down", "--all", "--owner-id", _API_OWNER]
    # Worktree-scoped: the stub's own cwd is the resolved worktree root, not
    # some arbitrary or unresolved path.
    assert Path(invocations[0]["cwd"]).resolve() == worktree.resolve()


def test_teardown_invokes_scoped_down_for_ui_tester(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook(
        {"agent_type": "e2e-ui-tester", "cwd": str(worktree)},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
    )

    assert result.returncode == 0, result.stderr
    invocations = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(invocations) == 1
    assert invocations[0]["argv"] == ["e2e", "down", "--all", "--owner-id", _UI_OWNER]


def test_teardown_never_uses_stale_flag(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    """Immediate hook cleanup is always `--all`, never `--stale` (spec §2: never a global stale kill)."""
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    _run_hook(
        {"agent_type": "e2e-api-tester", "cwd": str(worktree)},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
    )

    invocations = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert "--stale" not in invocations[0]["argv"]
    assert "--all" in invocations[0]["argv"]


def test_teardown_scoped_to_each_worktrees_own_cwd(tmp_path: Path, isolated_home: Path) -> None:
    """Two sibling worktrees each get their own scoped invocation; neither call touches the other's cwd."""
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    worktree_a = tmp_path / "repo-a"
    worktree_b = tmp_path / "repo-b"
    for repo in (worktree_a, worktree_b):
        repo.mkdir()
        _git("init", cwd=repo)
        (repo / "README.md").write_text("demo\n", encoding="utf-8")
        _git("add", ".", cwd=repo)
        _git("commit", "-m", "initial", cwd=repo)

    _run_hook({"agent_type": "e2e-api-tester", "cwd": str(worktree_a)}, home=isolated_home, extra_path_dirs=(stub_bin,))
    _run_hook({"agent_type": "e2e-api-tester", "cwd": str(worktree_b)}, home=isolated_home, extra_path_dirs=(stub_bin,))

    invocations = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(invocations) == 2
    seen_cwds = {Path(entry["cwd"]).resolve() for entry in invocations}
    assert seen_cwds == {worktree_a.resolve(), worktree_b.resolve()}


def test_teardown_exits_zero_even_when_down_fails(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    """A failing/already-clean `parrot e2e down` is not a hook error (defense in depth, never blocks)."""
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path, exit_code=1)

    result = _run_hook(
        {"agent_type": "e2e-ui-tester", "cwd": str(worktree)},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
    )

    assert result.returncode == 0, result.stderr
    assert log_path.exists()


# ---------------------------------------------------------------------------
# Malformed/irrelevant payload handling — always a silent, successful no-op
# ---------------------------------------------------------------------------


def test_teardown_noop_for_unrelated_agent_type(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook(
        {"agent_type": "sdd-worker", "cwd": str(worktree)},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
    )

    assert result.returncode == 0, result.stderr
    assert not log_path.exists(), "an unrelated agent_type must never trigger a teardown"


def test_teardown_noop_for_malformed_json(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook(
        None,
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
        raw_stdin="{not valid json at all",
    )

    assert result.returncode == 0, result.stderr
    assert not log_path.exists()


def test_teardown_noop_for_empty_stdin(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook(None, home=isolated_home, extra_path_dirs=(stub_bin,), raw_stdin="")

    assert result.returncode == 0, result.stderr
    assert not log_path.exists()


def test_teardown_noop_for_missing_agent_type_field(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook({"cwd": str(worktree)}, home=isolated_home, extra_path_dirs=(stub_bin,))

    assert result.returncode == 0, result.stderr
    assert not log_path.exists()


def test_teardown_noop_for_missing_cwd(isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook({"agent_type": "e2e-api-tester"}, home=isolated_home, extra_path_dirs=(stub_bin,))

    assert result.returncode == 0, result.stderr
    assert not log_path.exists()


def test_teardown_noop_for_nonexistent_cwd(isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook(
        {"agent_type": "e2e-api-tester", "cwd": str(tmp_path / "does-not-exist")},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
    )

    assert result.returncode == 0, result.stderr
    assert not log_path.exists()


def test_teardown_noop_when_cwd_is_not_a_git_worktree(isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()

    result = _run_hook(
        {"agent_type": "e2e-ui-tester", "cwd": str(plain_dir)},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
    )

    assert result.returncode == 0, result.stderr
    assert not log_path.exists()


def test_teardown_skipped_via_env_flag(worktree: Path, isolated_home: Path, tmp_path: Path) -> None:
    stub_bin = tmp_path / "stub-bin"
    log_path = tmp_path / "invocations.jsonl"
    _install_parrot_stub(stub_bin, log_path=log_path)

    result = _run_hook(
        {"agent_type": "e2e-api-tester", "cwd": str(worktree)},
        home=isolated_home,
        extra_path_dirs=(stub_bin,),
        env_overrides={"PARROT_SKIP_E2E_TEARDOWN": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert not log_path.exists()


# ---------------------------------------------------------------------------
# Prerequisite failure: `parrot` not installed
# ---------------------------------------------------------------------------


def test_teardown_noop_when_parrot_cli_missing(worktree: Path, isolated_home: Path) -> None:
    """No `parrot` on PATH (ai-parrot-server not installed) never crashes the hook."""
    result = _run_hook({"agent_type": "e2e-api-tester", "cwd": str(worktree)}, home=isolated_home)

    assert result.returncode == 0, result.stderr
    assert "parrot CLI not found" in result.stderr


def test_teardown_ignores_leaked_claude_project_dir_without_venv(
    worktree: Path, isolated_home: Path, tmp_path: Path
) -> None:
    """A CLAUDE_PROJECT_DIR pointing at a directory with no `.venv/bin/parrot` still no-ops safely."""
    fake_project_dir = tmp_path / "fake-project"
    fake_project_dir.mkdir()

    result = _run_hook(
        {"agent_type": "e2e-api-tester", "cwd": str(worktree)},
        home=isolated_home,
        env_overrides={"CLAUDE_PROJECT_DIR": str(fake_project_dir)},
    )

    assert result.returncode == 0, result.stderr
    assert "parrot CLI not found" in result.stderr
