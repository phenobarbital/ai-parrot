"""Bedrock-Mantle pilot seat for the FEAT-580 live evaluation (TASK-3514).

This is one ``SeatSpec.argv`` entry for ALL FIVE arms of the pilot manifest
(``python -m benchmarks.sdd_lsp.seats.bedrock_mantle_seat``) -- it branches
internally on the ``PARROT_LSP_PILOT_ARM``/``PARROT_LSP_PILOT_TOOLS`` env
vars ``benchmarks.sdd_lsp.runner`` sets per attempt, rather than needing
five different seat scripts. It composes only already-existing framework
primitives:

- ``LLMFactory``'s ``"mantle:<model>"`` string -> ``BedrockMantleClient``
  (Bedrock's OpenAI-compatible Project Mantle endpoint).
- ``parrot.bots.Agent`` for the tool-calling loop -- this script never
  reimplements a provider tool-call protocol.
- ``parrot_tools.lsp.toolkit.LSPToolkit`` for the three LSP arms.
- The small local tools in :mod:`benchmarks.sdd_lsp.seats.tools` for the
  ``wiki_ast`` control condition (index-free -- see that module's
  docstring for why the repo's real wiki MCP tools do not apply here).

Never a new LLM client class or CLI dispatcher (TASK-3514's own "NOT in
scope: implementing new host adapters"). See TASK-3514's Completion Note
/ scope-correction section for the full accounting of why this file
exists and the operator-confirmed per-arm tool loadout table.

Seat contract (``benchmarks/sdd_lsp/runner.py``): launched with ``cwd`` =
one already-materialized attempt directory and five env vars
(``PARROT_LSP_PILOT_ATTEMPT_ID``, ``_TASK_ID``, ``_ARM``, ``_REPETITION``,
``_TOOLS``, plus ``_FORCE_UNAVAILABLE=1`` for one fixed task). On exit it
must have written ``answer.json`` (investigation tasks) or edited
``entry_point`` in place (change/fix tasks), plus ``trace.jsonl`` -- one
``ModelUsage``-shaped JSON object per line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

import yaml

from parrot.bots.agent import Agent

from benchmarks.sdd_lsp.models import ModelUsage
from benchmarks.sdd_lsp.seats.tools import build_local_tools

__all__ = ("main",)

logger = logging.getLogger(__name__)

_TASKS_YAML = Path(__file__).resolve().parents[1] / "tasks.yaml"
_DEFAULT_MODEL = "minimax.minimax-m2.5"
_TRACE_FILENAME = "trace.jsonl"
_ANSWER_FILENAME = "answer.json"
_DEFAULT_ENVIRONMENT_ID = "lexotanil"


def _load_task(task_id: str) -> dict[str, Any]:
    """Load one pilot task's reviewed ground truth from ``tasks.yaml``.

    Args:
        task_id: One of the twelve fixed pilot task ids.

    Returns:
        The task's entry (``prompt``, ``entry_point``, etc.).

    Raises:
        KeyError: If ``task_id`` is not one of the fixed twelve.
    """
    data = yaml.safe_load(_TASKS_YAML.read_text(encoding="utf-8"))
    for entry in data["tasks"]:
        if entry["id"] == task_id:
            return entry
    raise KeyError(f"unknown pilot task id: {task_id!r}")


def _build_question(task: dict[str, Any]) -> str:
    """Render the task's reviewed prompt into the agent-facing instruction."""
    prompt = task["prompt"].strip()
    entry_point = task.get("entry_point")
    if entry_point is None:
        return (
            f"{prompt}\n\n"
            "This is a READ-ONLY investigation. Do not edit any file. "
            "When you have determined the answer, call submit_answer(path, line) "
            "exactly once with the repository-relative path and one-based line "
            "number of the true definition. Verify with your tools before answering; "
            "do not guess."
        )
    return (
        f"{prompt}\n\n"
        f"Edit {entry_point} in place using write_file to make the described "
        "change. Do not create new files and do not rename existing ones. "
        "When you believe the change is complete and correct, stop -- do not "
        "run or read check.py yourself."
    )


def _build_lsp_tools(cwd: Path, requested: tuple[str, ...], environment_id: str) -> list[Any]:
    """Construct the subset of LSP tools this attempt's arm may see.

    Args:
        cwd: The attempt's materialized working directory -- also the
            LSP toolkit's ``repo_root`` for this one, short-lived attempt.
        requested: The LSP tool names ``PARROT_LSP_PILOT_TOOLS`` named
            (per ``runner.ARM_TOOL_FILTER``); empty for non-LSP arms.
        environment_id: The pinned environment id, or the toolkit's own
            ``operator-unconfigured`` sentinel to simulate the
            ``fix-unavailable-server`` forced condition (every ``lsp_*``
            call then reports ``status="unavailable"`` before any process
            spawns -- the toolkit's own documented behavior, not new
            simulation logic).

    Returns:
        The matching tool callables from :class:`LSPToolkit`, or an empty
        list when ``requested`` is empty.
    """
    if not requested:
        return []
    from parrot_tools.lsp.models import LSPConfig
    from parrot_tools.lsp.toolkit import LSPToolkit

    config = LSPConfig(repo_root=cwd, environment_id=environment_id)
    toolkit = LSPToolkit(config=config)
    return [t for t in toolkit.get_tools() if getattr(t, "name", None) in requested]


async def _run() -> int:
    """Run exactly one pilot attempt: build tools, ask the agent, write outputs."""
    attempt_id = os.environ["PARROT_LSP_PILOT_ATTEMPT_ID"]
    task_id = os.environ["PARROT_LSP_PILOT_TASK_ID"]
    arm = os.environ["PARROT_LSP_PILOT_ARM"]
    tools_env = os.environ.get("PARROT_LSP_PILOT_TOOLS", "")
    requested_lsp_tools = tuple(t for t in tools_env.split(",") if t)
    force_unavailable = os.environ.get("PARROT_LSP_PILOT_FORCE_UNAVAILABLE") == "1"
    model = os.environ.get("PARROT_LSP_SEAT_MODEL", _DEFAULT_MODEL)
    environment_id = os.environ.get("PARROT_LSP_SEAT_ENVIRONMENT_ID", _DEFAULT_ENVIRONMENT_ID)
    if force_unavailable:
        from parrot_tools.lsp.models import OPERATOR_UNCONFIGURED_ENVIRONMENT_ID

        environment_id = OPERATOR_UNCONFIGURED_ENVIRONMENT_ID

    cwd = Path.cwd().resolve()
    task = _load_task(task_id)

    answer_holder: dict[str, Any] = {}
    local = build_local_tools(cwd, answer_holder)

    agent_tools = list(local.base_tools)
    if arm != "current":
        agent_tools.extend(local.wiki_ast_tools)
    agent_tools.extend(_build_lsp_tools(cwd, requested_lsp_tools, environment_id))

    agent = Agent(
        name="lsp-pilot-seat",
        agent_id=f"lsp-pilot-{arm}",
        llm=f"mantle:{model}",
        tools=agent_tools,
        system_prompt=(
            "You are a bounded coding-investigation seat in a research pilot "
            f"measuring navigation tooling. Your working directory is {cwd}. "
            "Use only the provided tools; never invoke a shell, never read or "
            "write outside your working directory, and never fabricate a result "
            "you have not verified with a tool call."
        ),
        use_tools=True,
    )
    await agent.configure()

    question = _build_question(task)
    failure: Optional[str] = None
    usage_record: ModelUsage
    try:
        response = await agent.ask(question=question, session_id=attempt_id, user_id="lsp-pilot-seat")
        usage = response.usage
        usage_record = ModelUsage(
            attempt_id=attempt_id,
            seat_id=arm,
            request_id=f"{attempt_id}::final",
            model=getattr(response, "model", None) or model,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            source="parrot.bots.Agent accumulated usage (bedrock-mantle)",
        )
    except Exception as exc:  # noqa: BLE001 -- a real, unpredictable live-provider/agent error; recorded, not swallowed
        failure = str(exc)
        usage_record = ModelUsage(
            attempt_id=attempt_id,
            seat_id=arm,
            request_id=f"{attempt_id}::error",
            model=model,
            failed=True,
            source="parrot.bots.Agent accumulated usage (bedrock-mantle)",
        )

    (cwd / _TRACE_FILENAME).write_text(usage_record.model_dump_json() + "\n", encoding="utf-8")

    if task.get("entry_point") is None and answer_holder.get("path") is not None:
        (cwd / _ANSWER_FILENAME).write_text(json.dumps(answer_holder), encoding="utf-8")

    if failure is not None:
        print(f"seat error: {failure}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    """Entry point: run one attempt and return its process exit code."""
    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
