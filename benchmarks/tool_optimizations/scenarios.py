"""Benchmark scenarios: the same work, done the baseline and optimized way.

Each scenario names a task a coding host actually performs, and supplies two
recipes for it:

* ``baseline`` — what a host does *without* these tools (the shell lines
  from the spec's user-provided code, a whole-file read, a hand-written
  implementation prompt).
* ``optimized`` — the equivalent tool calls.

Both sides run against the same fixtures at the same repository revision, so
the comparison is like-for-like.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "SCENARIOS",
    "Scenario",
    "ScenarioKind",
    "build_decided_task_repo",
    "build_git_repo",
    "build_large_file_repo",
)

ScenarioKind = Literal["git_fetch_preflight_prepare", "targeted_read_large_file", "decided_create_modify_task"]


class Scenario(BaseModel):
    """One benchmarked unit of work.

    Attributes:
        name: Stable identifier used in reports.
        kind: Which workflow this exercises.
        description: What a host is trying to achieve.
        baseline_recipe: The commands/reads a host issues without the tools.
        optimized_recipe: The equivalent tool calls.
        has_acceptance: Whether a real acceptance test can be executed.
        implementation_functions: For task scenarios, how many functions the
            decided implementation contains. This is the only variable
            distinguishing the small and large task rows, so the pair
            brackets the cost crossover rather than confounding it.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ScenarioKind
    description: str
    baseline_recipe: list[str] = Field(default_factory=list)
    optimized_recipe: list[str] = Field(default_factory=list)
    has_acceptance: bool = False
    implementation_functions: int = 1


#: The three fixed scenarios (spec §4 Measurement Protocol).
SCENARIOS: list[Scenario] = [
    Scenario(
        name="git_prepare",
        kind="git_fetch_preflight_prepare",
        description="Fetch the branch, inspect the tree, and stage exactly one file.",
        # The user-provided commands preserved in spec §6.
        baseline_recipe=[
            "git fetch origin dev",
            "git status --short && git diff --check && git diff --cached --name-only",
            "git reset HEAD && git add -- {filename} && git diff --cached --name-only && git diff --cached --check",
        ],
        optimized_recipe=["git_fetch", "git_preflight", "git_prepare_files"],
        has_acceptance=False,
    ),
    Scenario(
        name="targeted_read",
        kind="targeted_read_large_file",
        description="Read the region of interest from a 2,000-line module.",
        baseline_recipe=["Read(file_path=big_module.py)  # whole file into context"],
        optimized_recipe=["source_info", "source_read(start_line, end_line)"],
        has_acceptance=False,
    ),
    Scenario(
        name="decided_task",
        kind="decided_create_modify_task",
        description="Implement a SMALL already-decided TASK (~10 lines): one file created, one modified.",
        baseline_recipe=["primary model writes both files from the TASK description"],
        optimized_recipe=["writer_generate", "source_read(patch)", "writer_apply", "pytest"],
        has_acceptance=True,
        implementation_functions=2,
    ),
    Scenario(
        name="decided_task_large",
        kind="decided_create_modify_task",
        description="Implement a REALISTIC already-decided TASK (~150 lines): one file created, one modified.",
        baseline_recipe=["primary model writes both files from the TASK description"],
        optimized_recipe=["writer_generate", "source_read(patch)", "writer_apply", "pytest"],
        has_acceptance=True,
        implementation_functions=37,
    ),
]


def build_git_repo(workdir: Path, git_run) -> tuple[Path, Path]:
    """Create a repo with a bare remote for the Git scenario.

    Args:
        workdir: Directory to build in.
        git_run: A callable running git in a given cwd.

    Returns:
        A ``(repo, remote)`` tuple.
    """
    repo = workdir / "git_repo"
    repo.mkdir(parents=True)
    git_run(repo, "init", "-q", "-b", "dev")
    git_run(repo, "config", "commit.gpgsign", "false")
    (repo / "a.py").write_text("print('a')\n")
    git_run(repo, "add", "a.py")
    git_run(repo, "commit", "-q", "-m", "base")

    remote = workdir / "remote.git"
    git_run(workdir, "init", "-q", "--bare", str(remote))
    git_run(repo, "remote", "add", "origin", str(remote))
    git_run(repo, "push", "-q", "-u", "origin", "dev")
    (repo / "feature.py").write_text("value = 1\n")
    return repo, remote


def build_large_file_repo(workdir: Path, lines: int = 2000) -> Path:
    """Create a repo containing one large module.

    Args:
        workdir: Directory to build in.
        lines: How many lines the module should have.

    Returns:
        The repository root.
    """
    repo = workdir / "read_repo"
    repo.mkdir(parents=True)
    body = "".join(f"def function_{index}():\n    return {index}\n\n" for index in range(1, lines // 3 + 1))
    (repo / "big_module.py").write_text(body)
    return repo


#: The package init both task scenarios modify. Kept tiny and fixed so the
#: only variable between the small and large rows is the generated module.
_INIT_SOURCE = '"""Package."""\n\n__all__ = []\n'


def _generated_module(functions: int) -> str:
    """Render a deterministic module of ``functions`` simple functions.

    Deliberately free of anything the contract validator treats as an
    unresolved placeholder (``...``, TODO/FIXME/XXX, angle brackets,
    NotImplementedError) — this stands in for code whose design is already
    decided, not for a sketch.

    Args:
        functions: How many functions to emit (4 lines each).

    Returns:
        The module source.
    """
    lines = ['"""Decided calculations module."""', ""]
    for index in range(1, functions + 1):
        lines += [
            f"def compute_{index}(value: int) -> int:",
            f'    """Return value scaled by {index}."""',
            f"    return value * {index}",
            "",
        ]
    return "\n".join(lines)


def build_decided_task_repo(workdir: Path, functions: int) -> tuple[Path, str, str]:
    """Build a repo, an eligible TASK and the patch that satisfies it.

    Everything is generated together so the packet's hashes, the
    implementation block and the unified diff are consistent by
    construction — a hand-maintained fixture would silently rot as soon as
    the module changed.

    Args:
        workdir: Directory to build in.
        functions: Size of the decided implementation.

    Returns:
        A ``(repo, task_relative_path, patch_text)`` tuple.
    """
    repo = workdir / "task_repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "sdd" / "tasks" / "active").mkdir(parents=True)
    (repo / "tests").mkdir()

    init_path = repo / "pkg" / "__init__.py"
    init_path.write_text(_INIT_SOURCE)
    init_sha = hashlib.sha256(init_path.read_bytes()).hexdigest()

    module = _generated_module(functions)
    module_lines = module.split("\n")

    (repo / "tests" / "test_calculations.py").write_text(
        f"from pkg.calculations import compute_1, compute_{functions}\n\n\n"
        f"def test_compute():\n"
        f"    assert compute_1(2) == 2\n"
        f"    assert compute_{functions}(2) == {2 * functions}\n"
    )

    packet = {
        "schema_version": 1,
        "task_id": "TASK-9998",
        "spec_path": "sdd/specs/example.spec.md",
        "design_complete": True,
        "targets": [
            {
                "path": "pkg/calculations.py",
                "action": "create",
                "expected_sha256": None,
                "planned_changes": f"New module with {functions} decided compute functions",
                "blocks": ["impl-calculations"],
            },
            {
                "path": "pkg/__init__.py",
                "action": "modify",
                "expected_sha256": init_sha,
                "planned_changes": "Export compute_1",
                "blocks": ["impl-init"],
            },
        ],
        "references": [
            {
                "path": "pkg/__init__.py",
                "sha256": init_sha,
                "start_line": 1,
                "end_line": 3,
                "purpose": "existing exports",
            }
        ],
        "implementation_blocks": ["impl-calculations", "impl-init"],
        "acceptance_criteria": ["pytest tests/test_calculations.py passes"],
        "validation_commands": [["pytest", "tests/test_calculations.py", "-q"]],
    }

    task = repo / "sdd" / "tasks" / "active" / "TASK-9998-calculations.md"
    task.write_text(f"""# TASK-9998: Decided calculations module

## Delegation Contract

```json
{json.dumps(packet, indent=2)}
```

## Implementation

```python id=impl-calculations path=pkg/calculations.py
{module}
```

```python id=impl-init
# Apply to pkg/__init__.py: export the first calculation
from .calculations import compute_1

__all__ = [*__all__, "compute_1"]
```
""")

    # The patch the delegate is expected to produce, byte-consistent with the
    # module above and with the init file's exact current contents.
    created = "\n".join(f"+{line}" for line in module_lines)
    patch = (
        "--- a/pkg/__init__.py\n"
        "+++ b/pkg/__init__.py\n"
        "@@ -1,3 +1,5 @@\n"
        ' """Package."""\n'
        " \n"
        "+from .calculations import compute_1\n"
        "+\n"
        " __all__ = []\n"
        "--- /dev/null\n"
        "+++ b/pkg/calculations.py\n"
        f"@@ -0,0 +1,{len(module_lines)} @@\n"
        f"{created}\n"
    )
    return repo, task.relative_to(repo).as_posix(), patch
