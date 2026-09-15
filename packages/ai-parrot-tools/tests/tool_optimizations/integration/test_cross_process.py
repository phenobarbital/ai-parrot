"""Two-process contention on the same worktree (TASK-3091, FEAT-543).

These are genuine OS processes, not threads: the worktree lock is
`fcntl.flock`, which is per-open-file-description, so only real process
separation exercises it.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit

from ..fixtures import GOOD_PATCH, make_repo_with_target, make_valid_task
from ..test_writer import FakeClient
from .conftest import git, record_json, worker_env

PREPARE_WORKER = textwrap.dedent("""
    import asyncio, json, sys, time
    from pathlib import Path
    from parrot_tools.tool_optimizations.git import LocalGitToolkit

    repo, path, barrier = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    while not barrier.exists():
        time.sleep(0.01)
    result = asyncio.run(LocalGitToolkit(repo_root=repo).git_prepare_files([path]))
    print(json.dumps({"status": result.status, "code": result.error.code if result.error else None}))
    """)

APPLY_WORKER = textwrap.dedent("""
    import asyncio, json, sys, time
    from pathlib import Path
    from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit

    repo, artifact_id, sha, barrier = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
    while not barrier.exists():
        time.sleep(0.01)
    result = asyncio.run(TargetedWriterToolkit(repo_root=repo).writer_apply(artifact_id, sha))
    print(json.dumps({
        "status": result.status,
        "code": result.error.code if result.error else None,
        "already": bool(result.data.get("already_applied")),
    }))
    """)


def _run_pair(script, arg_sets, barrier):
    """Start two workers, release the barrier, and collect their verdicts."""
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=worker_env(),
        )
        for args in arg_sets
    ]
    barrier.write_text("go\n")
    results = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=120)
        assert process.returncode == 0, f"worker crashed: {stderr[-2000:]}"
        results.append(json.loads(stdout.strip().splitlines()[-1]))
    return results


def test_two_processes_staging_different_files_lose_nothing(tmp_path):
    """Concurrent staging is serialized; neither update is lost."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "seed.py").write_text("seed = 1\n")
    git(repo, "add", "seed.py")
    git(repo, "commit", "-q", "-m", "base")

    (repo / "one.py").write_text("one = 1\n")
    (repo / "two.py").write_text("two = 2\n")
    barrier = tmp_path / "barrier"

    results = _run_pair(
        PREPARE_WORKER,
        [[str(repo), "one.py", str(barrier)], [str(repo), "two.py", str(barrier)]],
        barrier,
    )

    # The lock file is created and, crucially, never deleted by either process.
    lock = repo / ".git" / "parrot-tool-optimizations.lock"
    assert lock.exists(), "the advisory lock file must survive both processes"
    # No stray git index lock is left behind either.
    assert not (repo / ".git" / "index.lock").exists()

    staged = [item for item in git(repo, "diff", "--cached", "--name-only", "-z").stdout.split("\0") if item]
    outcomes = [result["status"] for result in results]

    record_json(
        "TASK-3091-cross-process-prepare.json",
        {"results": results, "staged": staged, "lock_present": lock.exists()},
    )

    # Each worker either won outright or was refused by a *policy* rule
    # (the other's staging is "unrelated" to its own selection). What must
    # never happen is a corrupt index or a silent lost update.
    assert all(outcome in {"ok", "error"} for outcome in outcomes)
    winners = [name for name, result in zip(("one.py", "two.py"), results) if result["status"] == "ok"]
    assert winners, f"at least one worker must succeed: {results}"
    for winner in winners:
        assert winner in staged, f"{winner} reported ok but is not staged — lost update"

    # The index is still a valid git index.
    assert git(repo, "status", "--porcelain=v2", check=True).returncode == 0


def test_two_processes_applying_the_same_artifact(tmp_path):
    """Concurrent applies never corrupt a file; the loser reports cleanly."""
    import asyncio

    repo = make_repo_with_target(tmp_path)
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    task = make_valid_task(repo)

    writer = TargetedWriterToolkit(repo_root=repo, llm_client=FakeClient([GOOD_PATCH]))
    generated = asyncio.run(writer.writer_generate(task.relative_to(repo).as_posix()))
    assert generated.status == "ok", generated.error
    artifact_id = generated.data["artifact_id"]
    sha = generated.data["patch_sha256"]

    barrier = tmp_path / "apply-barrier"
    results = _run_pair(
        APPLY_WORKER,
        [[str(repo), artifact_id, sha, str(barrier)], [str(repo), artifact_id, sha, str(barrier)]],
        barrier,
    )
    record_json("TASK-3091-cross-process-apply.json", {"results": results})

    statuses = [result["status"] for result in results]
    assert "ok" in statuses, f"one apply must succeed: {results}"

    for result in results:
        if result["status"] != "ok":
            assert result["code"] in {"worktree_busy", "target_changed", "create_collision", "recovery_pending"}, result

    # Exactly one applied write; the file content is correct and not doubled.
    greeter = (repo / "pkg" / "greeter.py").read_text()
    assert greeter == 'def greet(name: str) -> str:\n    """Return a greeting."""\n    return f"hello {name}"\n'
    init_text = (repo / "pkg" / "__init__.py").read_text()
    assert init_text.count("from .greeter import greet") == 1, "the modify hunk was applied twice"
