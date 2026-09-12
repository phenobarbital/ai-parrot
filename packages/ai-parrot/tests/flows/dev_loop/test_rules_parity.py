"""Three-way byte parity for the coder rule files (FEAT-553, spec AC-2/AC-3, mirrors test_subagent_parity.py)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import pytest

from parrot.flows.conventions import CODER_RULE_NAMES


def _repo_rules_dir(sub: str) -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / sub / "rules"
        if candidate.is_dir():
            return candidate
    return None


@pytest.mark.parametrize("name", CODER_RULE_NAMES)
def test_claude_rules_twin_is_identical(name: str) -> None:
    """Compare .claude/rules/<name>.md with .agent/rules/<name>.md."""
    repo_rules = _repo_rules_dir(".claude")
    agent_rules = _repo_rules_dir(".agent")
    if repo_rules is None or agent_rules is None:
        pytest.skip(
            "`.claude/rules/` or `.agent/rules/` not found relative to this test file — "
            "running against an installed package, not the repo checkout."
        )

    claude_copy = repo_rules / f"{name}.md"
    agent_copy = agent_rules / f"{name}.md"
    assert claude_copy.is_file(), f"Missing .claude/rules/{name}.md"
    assert agent_copy.is_file(), f"Missing .agent/rules/{name}.md"
    assert (
        claude_copy.read_bytes() == agent_copy.read_bytes()
    ), f".claude/rules/{name}.md differs from .agent/rules/{name}.md"


@pytest.mark.parametrize("name", CODER_RULE_NAMES)
def test_package_rules_copy_is_identical(name: str) -> None:
    """Compare package copy _rules_data/<name>.md with .agent/rules/<name>.md."""
    agent_rules = _repo_rules_dir(".agent")
    if agent_rules is None:
        pytest.skip(
            "`.agent/rules/` not found relative to this test file — "
            "running against an installed package, not the repo checkout."
        )

    pkg_copy = resources.files("parrot.flows") / "_rules_data" / f"{name}.md"
    agent_copy = agent_rules / f"{name}.md"
    assert agent_copy.is_file(), f"Missing .agent/rules/{name}.md"
    assert (
        pkg_copy.read_bytes() == agent_copy.read_bytes()
    ), f"Package _rules_data/{name}.md differs from .agent/rules/{name}.md"


def test_coder_rules_fit_the_prompt_budget() -> None:
    """Total size of all rule files must fit within the prompt budget."""
    total = sum(
        len((resources.files("parrot.flows") / "_rules_data" / f"{n}.md").read_bytes()) for n in CODER_RULE_NAMES
    )
    assert total <= 8_000, total
