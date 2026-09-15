"""Full writer lifecycle with a real acceptance run (TASK-3091, FEAT-543).

generate -> bounded hunk review -> apply -> **the test harness runs the
packet's real acceptance command**. The model's own claims are never
treated as evidence: the pytest exit code is recorded separately from the
manifest.
"""

import hashlib
import json
import subprocess
import sys

from parrot_tools.tool_optimizations.reader import BoundedSourceToolkit
from parrot_tools.tool_optimizations.writer import TargetedWriterToolkit

from ..fixtures import GOOD_PATCH, make_repo_with_target, make_valid_task
from ..test_writer import FakeClient
from .conftest import git, record_json, worker_env


def _prepare_repo(tmp_path):
    """Build the fixture repo plus a real acceptance test for the packet."""
    repo = make_repo_with_target(tmp_path)
    git(repo, "init", "-q", "-b", "dev")
    git(repo, "config", "commit.gpgsign", "false")

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_greeter.py").write_text(
        "from pkg.greeter import greet\n\n\ndef test_greet():\n    assert greet('world') == 'hello world'\n"
    )
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "base")
    task = make_valid_task(repo)
    return repo, task


async def test_writer_lifecycle_ends_in_a_real_acceptance_run(tmp_path):
    """The whole delegated path, ending in an executed pytest run."""
    repo, task = _prepare_repo(tmp_path)
    task_path = task.relative_to(repo).as_posix()

    # 1. Generate.
    writer = TargetedWriterToolkit(repo_root=repo, llm_client=FakeClient([GOOD_PATCH]))
    generated = await writer.writer_generate(task_path)
    assert generated.status == "ok", generated.error
    artifact_id = generated.data["artifact_id"]
    patch_path = generated.data["patch_path"]

    # Generation must not have touched the worktree.
    assert not (repo / "pkg" / "greeter.py").exists()

    # 2. Review every hunk through the bounded reader, as the workflow requires.
    reader = BoundedSourceToolkit(repo_root=repo)
    info = await reader.source_info(patch_path)
    assert info.size_bytes > 0

    reviewed = ""
    cursor = 1
    while cursor is not None:
        chunk = await reader.source_read(patch_path, cursor, cursor + 349, expected_sha256=info.sha256)
        assert chunk.status if hasattr(chunk, "status") else True
        reviewed += chunk.content
        cursor = chunk.next_line
    assert "+def greet(name: str) -> str:" in reviewed
    assert "+from .greeter import greet" in reviewed

    # 3. The reviewed hash must equal the stored patch's digest.
    on_disk = (repo / patch_path).read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == generated.data["patch_sha256"]
    assert reviewed.encode() == on_disk, "the review must cover the whole patch"

    # 4. Apply.
    applied = await writer.writer_apply(artifact_id, generated.data["patch_sha256"])
    assert applied.status == "ok", applied.error
    assert (repo / "pkg" / "greeter.py").exists()

    # Applying never stages or commits.
    assert git(repo, "diff", "--cached", "--name-only").stdout == ""

    # 5. The HARNESS runs the packet's acceptance command. The writer never
    #    runs tests, and its manifest is not evidence that they passed.
    manifest = json.loads((repo / "artifacts" / "tool-optimizations" / artifact_id / "manifest.json").read_text())
    packet = json.loads((repo / "artifacts" / "tool-optimizations" / artifact_id / "packet.json").read_text())
    command = packet["validation_commands"][0]
    assert command[0] == "pytest"

    completed = subprocess.run(
        [sys.executable, "-m", *command],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
        env=worker_env(),
    )

    record_json(
        "TASK-3091-writer-lifecycle.json",
        {
            "artifact_id": artifact_id,
            "manifest_validation_state": manifest["validation_state"],
            "manifest_repairs": manifest["repairs"],
            "acceptance_command": command,
            "acceptance_exit_code": completed.returncode,
            "acceptance_tail": completed.stdout[-800:],
        },
    )

    # Recorded separately, and asserted independently of the manifest.
    assert manifest["validation_state"] == "validated"
    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]


async def test_apply_is_refused_when_the_review_hash_is_wrong(tmp_path):
    """Review gating holds in the integrated path, not just in unit tests."""
    repo, task = _prepare_repo(tmp_path)
    writer = TargetedWriterToolkit(repo_root=repo, llm_client=FakeClient([GOOD_PATCH]))
    generated = await writer.writer_generate(task.relative_to(repo).as_posix())

    refused = await writer.writer_apply(generated.data["artifact_id"], "0" * 64)
    assert refused.error.code == "review_hash_mismatch"
    assert not (repo / "pkg" / "greeter.py").exists()
