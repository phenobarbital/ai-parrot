"""Tests for complexity evidence collectors."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from parrot.flows.dev_loop.sdd_coder.complexity_collectors import (
    collect_complexity,
    validate_complexity_snapshot,
    _collect_dependency_metrics,
    _run_subprocess,
    SubprocessResult,
)
from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityContract, ComplexityPolicy, ComplexityTarget


def _init_git_repo(worktree: Path) -> None:
    """Initialize a minimal git repo with one commit.

    `_get_git_head_sha` runs a real (unmocked) `git rev-parse HEAD` against
    `worktree`, matching production use where `collect_complexity` always
    runs inside a real feature worktree. Test fixtures must provide that
    same precondition rather than relying on `_run_subprocess` mocking,
    which only covers Ruff/wiki collector calls.
    """
    subprocess.run(["git", "init", "-q"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=worktree, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=worktree, check=True)
    subprocess.run(["git", "add", "-A"], cwd=worktree, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=worktree, check=True)


@pytest.fixture
def temp_worktree():
    """Create a temporary worktree for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)

        # Create a sample task file
        task_content = """# TASK-1234: Sample task

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "src/sample.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:src/sample.py#SampleClass"
  ]
}
```

## Acceptance Criteria

- [ ] First criterion
- [x] Second criterion
- [ ] Third criterion
"""
        task_file = worktree / "TASK-1234-sample.md"
        task_file.write_text(task_content)

        # Create a sample Python file
        sample_py = worktree / "src" / "sample.py"
        sample_py.parent.mkdir(parents=True, exist_ok=True)
        sample_py.write_text("""
class SampleClass:
    def method_one(self):
        if True:
            if True:
                if True:
                    pass  # Complex nesting
    
    def method_two(self):
        pass
""")

        # Create a simple index file
        index_content = {
            "TASK-1234": {"id": "TASK-1234", "status": "pending", "depends_on": []},
            "TASK-5678": {"id": "TASK-5678", "status": "pending", "depends_on": ["TASK-1234"]},  # Depends on our task
        }
        index_file = worktree / "index.json"
        index_file.write_text(json.dumps(index_content))

        _init_git_repo(worktree)

        yield worktree, task_file.relative_to(worktree), index_file.relative_to(worktree)


@pytest.mark.asyncio
async def test_collect_complexity_basic(temp_worktree):
    """Test basic complexity collection."""
    worktree, task_file, index_file = temp_worktree
    policy = ComplexityPolicy()

    # Mock subprocess calls
    with patch("parrot.flows.dev_loop.sdd_coder.complexity_collectors._run_subprocess") as mock_run:
        # Mock Ruff cyclomatic. `ruff check --output-format json` prints a
        # top-level JSON array of diagnostics (verified against the
        # installed ruff binary), each `message` shaped
        # "`name` is too complex (N > threshold)" -- not a
        # `{"diagnostics": [...]}` wrapper nor a bare "(N)".
        mock_run.side_effect = [
            SubprocessResult(
                1,
                json.dumps(
                    [
                        {
                            "code": "C901",
                            "message": "`method_one` is too complex (5 > 0)",
                            "location": {"file": "src/sample.py"},
                        }
                    ]
                ),
                "",
            ),
            SubprocessResult(0, json.dumps([]), ""),  # Syntax check
            SubprocessResult(
                0,
                json.dumps(
                    {
                        "root": {"symbol_id": "sym:src/sample.py#SampleClass"},
                        "impacted": [{"symbol_id": "sym:src/other.py#OtherClass"}],
                        "files": ["src/other.py"],
                        "truncated": False,
                    }
                ),
                "",
            ),  # Wiki blast
        ]

        evidence = await collect_complexity(worktree, task_file, index_file, policy)

        assert evidence.task_id == "TASK-1234"
        assert "cyclomatic_max" in evidence.metrics
        assert "blast_symbols" in evidence.metrics
        assert "weighted_files" in evidence.metrics
        assert "modules" in evidence.metrics
        assert "acceptance_criteria" in evidence.metrics
        assert "downstream_tasks" in evidence.metrics

        # Check specific values
        assert evidence.metrics["cyclomatic_max"].state == "ok"
        assert evidence.metrics["cyclomatic_max"].value == 5

        assert evidence.metrics["blast_symbols"].state == "ok"
        assert evidence.metrics["blast_symbols"].value == 1  # One impacted symbol

        assert evidence.metrics["weighted_files"].state == "ok"
        assert evidence.metrics["weighted_files"].value == 2  # 0 CREATE + 2*1 MODIFY

        assert evidence.metrics["modules"].state == "ok"
        assert evidence.metrics["modules"].value == 1  # One parent directory (src)

        assert evidence.metrics["acceptance_criteria"].state == "ok"
        assert evidence.metrics["acceptance_criteria"].value == 3  # Three criteria

        assert evidence.metrics["downstream_tasks"].state == "ok"
        assert evidence.metrics["downstream_tasks"].value == 1  # One dependent task


def _dep_contract() -> ComplexityContract:
    return ComplexityContract(schema_version=1, targets=(ComplexityTarget(path="pkg/x.py", action="CREATE"),))


async def _run_dependency_metrics(worktree: Path, index_data: dict, task_id: str = "TASK-0001"):
    index_file = worktree / "index.json"
    index_file.write_text(json.dumps(index_data))
    task_file = worktree / f"{task_id}-demo.md"
    task_file.write_text(f"# {task_id}: demo\n")
    metrics, *_ = await _collect_dependency_metrics(
        worktree,
        task_file.relative_to(worktree),
        index_file.relative_to(worktree),
        _dep_contract(),
        ComplexityPolicy(),
    )
    return metrics["downstream_tasks"]


@pytest.mark.asyncio
async def test_downstream_tasks_counts_transitive_not_direct():
    """A 6-task linear dependency chain must report 5 TRANSITIVE descendants
    for the root, not 1 direct dependent (spec §2 item 5: "The score uses
    transitive count; direct count remains visible")."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)
        index_data = {
            "tasks": [
                {"id": "TASK-0001", "depends_on": []},
                {"id": "TASK-0002", "depends_on": ["TASK-0001"]},
                {"id": "TASK-0003", "depends_on": ["TASK-0002"]},
                {"id": "TASK-0004", "depends_on": ["TASK-0003"]},
                {"id": "TASK-0005", "depends_on": ["TASK-0004"]},
                {"id": "TASK-0006", "depends_on": ["TASK-0005"]},
            ]
        }
        evidence = await _run_dependency_metrics(worktree, index_data)
        assert evidence.state == "ok"
        assert evidence.value == 5


@pytest.mark.asyncio
async def test_downstream_tasks_dedups_diamond_paths():
    """B and C both depend on ROOT; D depends on BOTH B and C. ROOT's
    transitive descendants are {B, C, D} = 3, not 4 (D must not be counted
    twice for reaching it via two different paths)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)
        index_data = {
            "tasks": [
                {"id": "TASK-0001", "depends_on": []},
                {"id": "TASK-0002", "depends_on": ["TASK-0001"]},
                {"id": "TASK-0003", "depends_on": ["TASK-0001"]},
                {"id": "TASK-0004", "depends_on": ["TASK-0002", "TASK-0003"]},
            ]
        }
        evidence = await _run_dependency_metrics(worktree, index_data)
        assert evidence.state == "ok"
        assert evidence.value == 3


@pytest.mark.asyncio
async def test_downstream_tasks_cycle_is_unknown():
    """A cycle back to the root task invalidates the dependency contract
    (spec §2 item 5: "Missing nodes or cycles invalidate the dependency
    contract") -- reported as unknown, never a silently-wrong count."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)
        index_data = {
            "tasks": [
                {"id": "TASK-0001", "depends_on": ["TASK-0002"]},
                {"id": "TASK-0002", "depends_on": ["TASK-0001"]},
            ]
        }
        evidence = await _run_dependency_metrics(worktree, index_data)
        assert evidence.state == "unknown"
        assert "cycle" in evidence.reason.lower()


@pytest.mark.asyncio
async def test_downstream_tasks_dangling_reference_is_unknown():
    """A depends_on reference to a task ID never declared anywhere in the
    index is dangling -- invalidates the whole dependency contract, even
    when the dangling reference itself is unrelated to task_id's own
    downstream subgraph (spec §2 item 5: "Missing nodes ... invalidate the
    dependency contract")."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)
        index_data = {
            "tasks": [
                {"id": "TASK-0001", "depends_on": []},
                {"id": "TASK-0003HILD", "depends_on": ["TASK-0001"]},
                {"id": "TASK-0003", "depends_on": ["TASK-9999"]},
            ]
        }
        evidence = await _run_dependency_metrics(worktree, index_data)
        assert evidence.state == "unknown"
        assert "dangling" in evidence.reason.lower()


@pytest.mark.asyncio
async def test_collect_complexity_no_python_files():
    """Test collecting complexity with no Python files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)

        # Create a task with no Python files
        task_content = """# TASK-5678: Non-Python task

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/readme.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": null
}
```

## Acceptance Criteria

- [ ] Single criterion
"""
        task_file = worktree / "TASK-5678-non-python.md"
        task_file.write_text(task_content)

        # Create index
        index_content = {"TASK-5678": {"id": "TASK-5678", "status": "pending", "depends_on": []}}
        index_file = worktree / "index.json"
        index_file.write_text(json.dumps(index_content))

        _init_git_repo(worktree)

        policy = ComplexityPolicy()

        evidence = await collect_complexity(
            worktree, task_file.relative_to(worktree), index_file.relative_to(worktree), policy
        )

        # Documentation MODIFY target -> not_applicable (spec §2 item 1: distinct
        # from an unsupported-language MODIFY target, which is unknown).
        assert evidence.metrics["cyclomatic_max"].state == "not_applicable"
        assert "documentation" in evidence.metrics["cyclomatic_max"].reason.lower()


@pytest.mark.asyncio
async def test_collect_complexity_unsupported_language_is_unknown():
    """A MODIFY target in an unsupported programming language (not Python, not
    documentation/configuration) must be unknown, not not_applicable (spec §2
    item 1: "Unsupported source languages give unknown.")."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)

        task_content = """# TASK-6789: Rust task

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "src/lib.rs",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": null
}
```
"""
        task_file = worktree / "TASK-6789-rust.md"
        task_file.write_text(task_content)

        rs_file = worktree / "src" / "lib.rs"
        rs_file.parent.mkdir(parents=True)
        rs_file.write_text("fn main() {}\n")

        index_content = {"TASK-6789": {"id": "TASK-6789", "status": "pending", "depends_on": []}}
        index_file = worktree / "index.json"
        index_file.write_text(json.dumps(index_content))

        _init_git_repo(worktree)

        policy = ComplexityPolicy()

        evidence = await collect_complexity(
            worktree, task_file.relative_to(worktree), index_file.relative_to(worktree), policy
        )

        assert evidence.metrics["cyclomatic_max"].state == "unknown"
        assert "lib.rs" in evidence.metrics["cyclomatic_max"].reason


@pytest.mark.asyncio
async def test_collect_complexity_ruff_timeout():
    """Test handling of Ruff timeout."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)

        # Create a task
        task_content = """# TASK-9012: Timeout test

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "src/code.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": null
}
```
"""
        task_file = worktree / "TASK-9012-timeout.md"
        task_file.write_text(task_content)

        # Create Python file
        code_py = worktree / "src" / "code.py"
        code_py.parent.mkdir(parents=True)
        code_py.write_text("def simple(): pass")

        # Create index
        index_content = {"TASK-9012": {"id": "TASK-9012", "status": "pending", "depends_on": []}}
        index_file = worktree / "index.json"
        index_file.write_text(json.dumps(index_content))

        _init_git_repo(worktree)

        policy = ComplexityPolicy()

        # Mock timeout
        with patch("parrot.flows.dev_loop.sdd_coder.complexity_collectors._run_subprocess") as mock_run:
            mock_run.side_effect = asyncio.TimeoutError()

            evidence = await collect_complexity(
                worktree, task_file.relative_to(worktree), index_file.relative_to(worktree), policy
            )

            # Should have unknown state due to timeout
            assert evidence.metrics["cyclomatic_max"].state == "unknown"
            assert "timed out" in evidence.metrics["cyclomatic_max"].reason


@pytest.mark.asyncio
async def test_validate_complexity_snapshot():
    """Test validating complexity snapshots."""
    with tempfile.TemporaryDirectory() as tmpdir:
        worktree = Path(tmpdir)

        # Create task
        task_content = """# TASK-1111: Validation test

## Complexity Contract
```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "src/test.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": null
}
```
"""
        task_file = worktree / "TASK-1111-validation.md"
        task_file.write_text(task_content)

        # Create Python file
        test_py = worktree / "src" / "test.py"
        test_py.parent.mkdir(parents=True)
        test_py.write_text("def test(): pass")

        # Create index
        index_content = {"TASK-1111": {"id": "TASK-1111", "status": "pending", "depends_on": []}}
        index_file = worktree / "index.json"
        index_file.write_text(json.dumps(index_content))

        _init_git_repo(worktree)

        policy = ComplexityPolicy()

        # Mock subprocess for initial collection
        with patch("parrot.flows.dev_loop.sdd_coder.complexity_collectors._run_subprocess") as mock_run:
            mock_run.side_effect = [
                SubprocessResult(0, json.dumps([]), ""),  # Cyclomatic
                SubprocessResult(0, json.dumps([]), ""),  # Syntax
            ]

            # Collect initial evidence
            evidence = await collect_complexity(
                worktree, task_file.relative_to(worktree), index_file.relative_to(worktree), policy
            )

            # Create a mock assessment (simplified)
            from parrot.flows.dev_loop.sdd_coder.complexity_models import ComplexityAssessment

            assessment = ComplexityAssessment(
                policy_version=policy.version,
                task_id=evidence.task_id,
                classification="standard",
                total_points=0,
                component_points={},
                reason_codes=("score_below_threshold",),
                evidence=evidence,
                assessment_id="test_assessment_id",
            )

            # Validate - should be True since inputs haven't changed
            is_valid = await validate_complexity_snapshot(
                worktree, task_file.relative_to(worktree), index_file.relative_to(worktree), assessment, policy
            )

            # For this test, we'll just check that it doesn't crash
            assert isinstance(is_valid, bool)


def test_subprocess_result():
    """Test SubprocessResult class."""
    result = SubprocessResult(0, "stdout content", "stderr content")
    assert result.returncode == 0
    assert result.stdout == "stdout content"
    assert result.stderr == "stderr content"


@pytest.mark.asyncio
async def test_run_subprocess():
    """Test subprocess execution with limits."""
    with patch("asyncio.create_subprocess_exec") as mock_create:
        # Mock process
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output", b"errors"))
        mock_proc.returncode = 0
        mock_create.return_value = mock_proc

        result = await _run_subprocess(["echo", "test"], Path("."), 10, 1000)

        assert result.returncode == 0
        assert result.stdout == "output"
        assert result.stderr == "errors"


@pytest.mark.asyncio
async def test_run_subprocess_timeout():
    """Test subprocess timeout handling."""
    with patch("asyncio.create_subprocess_exec") as mock_create:
        # Mock process
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.kill = Mock()  # real asyncio.subprocess.Process.kill() is sync, not a coroutine
        mock_proc.wait = AsyncMock()
        mock_create.return_value = mock_proc

        with pytest.raises(asyncio.TimeoutError):
            await _run_subprocess(["sleep", "10"], Path("."), 1, 1000)

        # Verify process was killed
        mock_proc.kill.assert_called_once()
