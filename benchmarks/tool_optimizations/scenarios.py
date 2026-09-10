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

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ("SCENARIOS", "Scenario", "ScenarioKind", "build_git_repo", "build_large_file_repo")

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
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    kind: ScenarioKind
    description: str
    baseline_recipe: list[str] = Field(default_factory=list)
    optimized_recipe: list[str] = Field(default_factory=list)
    has_acceptance: bool = False


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
        description="Implement an already-decided TASK: one file created, one modified.",
        baseline_recipe=["primary model writes both files from the TASK description"],
        optimized_recipe=["writer_generate", "source_read(patch)", "writer_apply", "pytest"],
        has_acceptance=True,
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
