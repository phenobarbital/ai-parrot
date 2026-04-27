"""Code toolkit for spec-driven coding tasks.

The toolkit exposes high-level coding operations through ``AbstractToolkit``
while keeping execution behind provider classes. The Codex SDK integration is
lazy because the SDK is experimental and optional.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from parrot.clients.nvidia import NvidiaClient
from parrot.models.nvidia import NvidiaModel

from .decorators import tool_schema
from .toolkit import AbstractToolkit


@dataclass
class CodingTask:
    """Artifact describing a coding task to execute against a repository."""

    repo_path: Path
    spec_path: Path
    objective: str
    branch_name: str | None = None
    test_command: str | None = None
    files_in_scope: list[str] | None = None
    constraints: list[str] = field(default_factory=list)


@dataclass
class CodingTaskResult:
    """Structured result returned by coding providers."""

    success: bool
    summary: str
    changed_files: list[str]
    diff: str | None
    tests_run: list[str]
    test_output: str | None
    remaining_risks: list[str]


class CodingProvider(Protocol):
    """Provider protocol implemented by coding backends."""

    async def run_task(
        self,
        task: CodingTask,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Run a coding task and return a structured result."""


class CodingTaskInput(BaseModel):
    """Shared input fields for code toolkit tools."""

    spec_file: str = Field(description="Path to the specification file.")
    repo_path: str = Field(description="Path to the repository to work on.")
    test_command: str | None = Field(
        default=None,
        description="Optional command the provider should run to validate the change.",
    )
    model: str | None = Field(
        default=None,
        description="Optional provider-specific model override.",
    )


class ExplainPatchInput(BaseModel):
    """Input for explaining an existing patch or diff."""

    patch_file: str = Field(description="Path to a patch or diff file.")
    repo_path: str = Field(description="Path to the repository the patch applies to.")
    model: str | None = Field(
        default=None,
        description="Optional provider-specific model override.",
    )


class CodexProvider:
    """Coding provider backed by the experimental OpenAI Codex SDK."""

    def __init__(self, skip_git_repo_check: bool = False) -> None:
        self.skip_git_repo_check = skip_git_repo_check

    async def run_task(
        self,
        task: CodingTask,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Run a coding task with the OpenAI Codex SDK."""

        spec = await asyncio.to_thread(task.spec_path.read_text)
        prompt = self.build_prompt(task, spec)
        before_diff = await _git_diff(task.repo_path)

        try:
            from openai_codex_sdk import Codex
        except ImportError as exc:
            raise RuntimeError(
                "openai-codex-sdk is not installed. Run `make install-codex-sdk-editable` "
                "from an active virtual environment first."
            ) from exc

        codex_options: dict[str, Any] = {
            "working_directory": str(task.repo_path),
            "skip_git_repo_check": self.skip_git_repo_check,
        }
        codex = Codex(codex_options)
        thread = codex.start_thread()

        run_options: dict[str, Any] = {}
        if model:
            run_options["model"] = model

        if run_options:
            result = await thread.run(prompt, run_options)
        else:
            result = await thread.run(prompt)

        after_diff = await _git_diff(task.repo_path)
        changed_files = await _git_changed_files(task.repo_path)
        test_output = _extract_text(result)
        summary = self._extract_summary(test_output)

        return CodingTaskResult(
            success=bool(after_diff and after_diff != before_diff),
            summary=summary,
            changed_files=changed_files,
            diff=after_diff or None,
            tests_run=[task.test_command] if task.test_command else [],
            test_output=test_output,
            remaining_risks=self._extract_risks(test_output),
        )

    def build_prompt(self, task: CodingTask, spec: str) -> str:
        """Build a Codex prompt from a coding task and specification text."""

        frontmatter = parse_frontmatter(spec)
        test_command = task.test_command or frontmatter.get("test_command")
        files_in_scope = task.files_in_scope or _as_list(frontmatter.get("files_in_scope"))
        definition_of_done = _as_list(frontmatter.get("definition_of_done"))
        constraints = [*task.constraints, *_as_list(frontmatter.get("constraints"))]

        sections = [
            "You are implementing a repository change from a specification.",
            f"Repository path: {task.repo_path}",
            f"Specification path: {task.spec_path}",
            f"Objective: {task.objective}",
        ]
        if branch_name := task.branch_name:
            sections.append(f"Target branch name: {branch_name}")
        if test_command:
            sections.append(f"Validation command: {test_command}")
        if files_in_scope:
            sections.append("Files in scope:\n" + "\n".join(f"- {item}" for item in files_in_scope))
        if definition_of_done:
            sections.append("Definition of done:\n" + "\n".join(f"- {item}" for item in definition_of_done))
        if constraints:
            sections.append("Constraints:\n" + "\n".join(f"- {item}" for item in constraints))

        sections.append(
            "Return a concise final response with summary, changed files, tests run, "
            "test output, and remaining risks."
        )
        sections.append("Specification:\n" + spec)
        return "\n\n".join(sections)

    @staticmethod
    def parse_result(result: Any) -> CodingTaskResult:
        """Parse a Codex SDK result object without repository diff context."""

        text = _extract_text(result)
        parsed = _parse_json_result(text)
        if parsed:
            return _result_from_mapping(parsed, fallback_text=text)
        return CodingTaskResult(
            success=False,
            summary=text.strip() or "Codex task completed without a structured summary.",
            changed_files=[],
            diff=None,
            tests_run=[],
            test_output=text,
            remaining_risks=[],
        )

    @staticmethod
    def _extract_summary(text: str) -> str:
        if not text.strip():
            return "Codex task completed."
        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return first_line[:500] or "Codex task completed."

    @staticmethod
    def _extract_risks(text: str) -> list[str]:
        parsed = _parse_json_result(text)
        if parsed:
            return _as_list(parsed.get("remaining_risks"))
        return []


class MinimaxProvider:
    """Coding provider backed by Nvidia-hosted Minimax-compatible models."""

    def __init__(
        self,
        client: NvidiaClient | None = None,
        default_model: str = NvidiaModel.KIMI_K2_INSTRUCT_0905.value,
    ) -> None:
        self.client = client or NvidiaClient(model=default_model)
        self.default_model = default_model

    async def run_task(
        self,
        task: CodingTask,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Ask the Nvidia client to produce a structured coding plan/result."""

        spec = await asyncio.to_thread(task.spec_path.read_text)
        prompt = self.build_prompt(task, spec)
        response = await self.client.ask(
            prompt,
            model=model or self.default_model,
            temperature=0,
            enable_web_search=False,
        )
        text = _extract_text(response)
        parsed = _parse_json_result(text)
        if parsed:
            return _result_from_mapping(parsed, fallback_text=text)
        return CodingTaskResult(
            success=False,
            summary=text.strip() or "Minimax provider returned no summary.",
            changed_files=[],
            diff=None,
            tests_run=[task.test_command] if task.test_command else [],
            test_output=text,
            remaining_risks=["MinimaxProvider returns model-generated guidance and does not apply repository patches."],
        )

    def build_prompt(self, task: CodingTask, spec: str) -> str:
        """Build a structured-output prompt for Minimax-compatible models."""

        return (
            "Analyze this coding specification and return only JSON matching this shape: "
            '{"success": false, "summary": string, "changed_files": [], "diff": null, '
            '"tests_run": [], "test_output": string|null, "remaining_risks": []}.\n\n'
            f"Repository path: {task.repo_path}\n"
            f"Specification path: {task.spec_path}\n"
            f"Objective: {task.objective}\n"
            f"Test command: {task.test_command or 'none'}\n\n"
            f"Specification:\n{spec}"
        )


class CodeToolkit(AbstractToolkit):
    """Toolkit for delegating coding tasks to Codex-compatible providers."""

    tool_prefix = "code"
    prefix_separator = "."

    def __init__(
        self,
        provider: CodingProvider,
        default_model: str | None = None,
    ) -> None:
        super().__init__()
        self.provider = provider
        self.default_model = default_model

    @tool_schema(CodingTaskInput)
    async def implement_spec(
        self,
        spec_file: str,
        repo_path: str,
        test_command: str | None = None,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Implement the bugfix or feature described in a specification file."""

        task = CodingTask(
            repo_path=Path(repo_path),
            spec_path=Path(spec_file),
            objective="Implement the bugfix described in the specification file.",
            test_command=test_command,
        )

        return await self.provider.run_task(
            task=task,
            model=model or self.default_model,
        )

    @tool_schema(CodingTaskInput)
    async def fix_bug(
        self,
        spec_file: str,
        repo_path: str,
        test_command: str | None = None,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Fix the bug described in a specification file."""

        task = CodingTask(
            repo_path=Path(repo_path),
            spec_path=Path(spec_file),
            objective="Fix the bug described in the specification file.",
            test_command=test_command,
        )
        return await self.provider.run_task(task=task, model=model or self.default_model)

    @tool_schema(CodingTaskInput)
    async def review_diff(
        self,
        spec_file: str,
        repo_path: str,
        test_command: str | None = None,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Review the repository diff against the specification file."""

        task = CodingTask(
            repo_path=Path(repo_path),
            spec_path=Path(spec_file),
            objective="Review the current repository diff against the specification file.",
            test_command=test_command,
        )
        return await self.provider.run_task(task=task, model=model or self.default_model)

    @tool_schema(CodingTaskInput)
    async def generate_tests(
        self,
        spec_file: str,
        repo_path: str,
        test_command: str | None = None,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Generate or update tests required by a specification file."""

        task = CodingTask(
            repo_path=Path(repo_path),
            spec_path=Path(spec_file),
            objective="Generate or update tests required by the specification file.",
            test_command=test_command,
        )
        return await self.provider.run_task(task=task, model=model or self.default_model)

    @tool_schema(ExplainPatchInput)
    async def explain_patch(
        self,
        patch_file: str,
        repo_path: str,
        model: str | None = None,
    ) -> CodingTaskResult:
        """Explain an existing patch in the context of a repository."""

        task = CodingTask(
            repo_path=Path(repo_path),
            spec_path=Path(patch_file),
            objective="Explain the patch, its intent, test implications, and remaining risks.",
        )
        return await self.provider.run_task(task=task, model=model or self.default_model)


def parse_frontmatter(text: str) -> dict[str, Any]:
    """Parse a small YAML-like frontmatter block without adding dependencies."""

    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\n(.*?)\n---", text, flags=re.DOTALL)
    if not match:
        return {}

    data: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in match.group(1).splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_key:
            data.setdefault(current_key, [])
            if isinstance(data[current_key], list):
                data[current_key].append(line.lstrip()[2:].strip())
            continue
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            data[current_key] = value if value else []
    return data


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


async def _git_diff(repo_path: Path) -> str:
    return await _run_git(repo_path, "diff", "--")


async def _git_changed_files(repo_path: Path) -> list[str]:
    output = await _run_git(repo_path, "diff", "--name-only", "--")
    return [line.strip() for line in output.splitlines() if line.strip()]


async def _run_git(repo_path: Path, *args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=repo_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _stderr = await process.communicate()
    return stdout.decode("utf-8", errors="replace")


def _extract_text(result: Any) -> str:
    if result is None:
        return ""
    for attr in ("final_response", "response", "output", "text"):
        value = getattr(result, attr, None)
        if isinstance(value, str):
            return value
        if value is not None and not isinstance(value, (dict, list, tuple)):
            return str(value)
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result)
    return str(result)


def _parse_json_result(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    candidate = fenced.group(1) if fenced else stripped
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _result_from_mapping(data: dict[str, Any], fallback_text: str) -> CodingTaskResult:
    return CodingTaskResult(
        success=bool(data.get("success")),
        summary=str(data.get("summary") or fallback_text or ""),
        changed_files=_as_list(data.get("changed_files")),
        diff=data.get("diff") if isinstance(data.get("diff"), str) else None,
        tests_run=_as_list(data.get("tests_run")),
        test_output=data.get("test_output") if isinstance(data.get("test_output"), str) else None,
        remaining_risks=_as_list(data.get("remaining_risks")),
    )
