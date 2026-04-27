from pathlib import Path

import pytest

from parrot_tools.code_toolkit import (
    CodeToolkit,
    CodexProvider,
    CodingTask,
    CodingTaskResult,
    parse_frontmatter,
)


class FakeProvider:
    def __init__(self) -> None:
        self.task: CodingTask | None = None
        self.model: str | None = None

    async def run_task(
        self,
        task: CodingTask,
        model: str | None = None,
    ) -> CodingTaskResult:
        self.task = task
        self.model = model
        return CodingTaskResult(
            success=True,
            summary="done",
            changed_files=["example.py"],
            diff="diff --git a/example.py b/example.py",
            tests_run=[task.test_command] if task.test_command else [],
            test_output="passed",
            remaining_risks=[],
        )


def test_toolkit_exposes_dotted_code_tools() -> None:
    toolkit = CodeToolkit(provider=FakeProvider())

    assert set(toolkit.list_tool_names()) == {
        "code.explain_patch",
        "code.fix_bug",
        "code.generate_tests",
        "code.implement_spec",
        "code.review_diff",
    }


@pytest.mark.asyncio
async def test_implement_spec_builds_coding_task(tmp_path: Path) -> None:
    spec = tmp_path / "spec.md"
    spec.write_text("Fix the timeout bug.")
    provider = FakeProvider()
    toolkit = CodeToolkit(provider=provider, default_model="codex-test")

    result = await toolkit.implement_spec(
        spec_file=str(spec),
        repo_path=str(tmp_path),
        test_command="pytest tests/auth -q",
    )

    assert result.success is True
    assert provider.model == "codex-test"
    assert provider.task is not None
    assert provider.task.repo_path == tmp_path
    assert provider.task.spec_path == spec
    assert provider.task.test_command == "pytest tests/auth -q"
    assert provider.task.objective == "Implement the bugfix described in the specification file."


def test_parse_frontmatter_lists_and_scalars() -> None:
    frontmatter = parse_frontmatter("""---
type: bugfix
repo: ai-parrot
test_command: pytest tests/ -q
files_in_scope:
  - ai_parrot/agents/
  - tests/
definition_of_done:
  - failing test added
  - bug fixed
---
# Body
""")

    assert frontmatter["type"] == "bugfix"
    assert frontmatter["repo"] == "ai-parrot"
    assert frontmatter["test_command"] == "pytest tests/ -q"
    assert frontmatter["files_in_scope"] == ["ai_parrot/agents/", "tests/"]
    assert frontmatter["definition_of_done"] == ["failing test added", "bug fixed"]


def test_codex_prompt_uses_frontmatter(tmp_path: Path) -> None:
    provider = CodexProvider()
    task = CodingTask(
        repo_path=tmp_path,
        spec_path=tmp_path / "spec.md",
        objective="Fix the issue.",
    )

    prompt = provider.build_prompt(
        task,
        """---
test_command: pytest tests/ -q
files_in_scope:
  - parrot/tools/
definition_of_done:
  - tests passing
---
Fix it.
""",
    )

    assert "Validation command: pytest tests/ -q" in prompt
    assert "- parrot/tools/" in prompt
    assert "- tests passing" in prompt
    assert "Specification:\n---" in prompt
