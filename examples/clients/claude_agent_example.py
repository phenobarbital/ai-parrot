"""Example: dispatching a task to a Claude Code agent via ``ClaudeAgentClient``.

This demonstrates how an ai-parrot Agent can delegate file-aware,
bash-capable, tool-using work to a Claude Code sub-agent.

Prerequisites
-------------
1. Install the dedicated extra::

       uv pip install "ai-parrot[claude-agent]"

   The ``claude-agent-sdk`` package bundles the ``claude`` CLI binary it
   needs at runtime — no separate CLI install is required.

2. Authenticate the bundled CLI **once** with ``claude auth`` *or* set
   ``ANTHROPIC_API_KEY`` in your environment. ``claude-agent-sdk`` honours
   either path.

Why use ``ClaudeAgentClient`` instead of ``AnthropicClient``?

* ``AnthropicClient`` calls the Anthropic Messages API over HTTP. Use it
  for completion / vision / batch / streaming.
* ``ClaudeAgentClient`` runs a full Claude Code agent as a subprocess.
  Use it when you want to delegate a *task* (file-aware, bash-capable,
  tool-using) to a sub-agent — for example "list all Python files in the
  current directory and summarise their purpose".

Both clients coexist: install both extras
(``ai-parrot[anthropic]`` and ``ai-parrot[claude-agent]``) when you need
both surfaces.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import sys

from parrot.clients.claude_agent import ClaudeAgentRunOptions
from parrot.clients.factory import LLMFactory


def _check_prereqs() -> None:
    """Fail fast with an actionable message if the CLI / auth are missing."""
    if shutil.which("claude") is None:
        # claude-agent-sdk usually bundles the CLI, but minimal Docker
        # images may strip it. Surface a clear hint either way.
        print(
            "ERROR: the 'claude' CLI was not found on PATH.\n"
            "       Install with: pip install 'ai-parrot[claude-agent]'\n"
            "       (the bundled CLI ships with claude-agent-sdk).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        # Not strictly required — the CLI may already be authenticated via
        # ``claude auth``. We just print a heads-up instead of exiting.
        print(
            "NOTE: ANTHROPIC_API_KEY is not set. The bundled claude CLI will "
            "use whatever auth flow you previously configured (run "
            "`claude auth` once, or export ANTHROPIC_API_KEY)."
        )


async def main() -> int:
    _check_prereqs()

    # 1) Build the client via the standard ai-parrot factory. Any code that
    #    today says ``LLMFactory.create("anthropic:claude-sonnet-4-5")`` can
    #    swap to ``LLMFactory.create("claude-agent:claude-sonnet-4-6")`` to
    #    delegate to a Claude Code sub-agent instead of the API client.
    client = LLMFactory.create("claude-agent:claude-sonnet-4-6")

    # 2) Constrain the sub-agent to a small allowlist of tools and a
    #    specific working directory. ``permission_mode="default"`` is the
    #    safest production choice; bump to ``"acceptEdits"`` when you want
    #    the agent to make edits without prompting.
    run_options = ClaudeAgentRunOptions(
        allowed_tools=["Read", "Bash"],
        permission_mode="default",
        cwd=".",
    )

    # 3) Dispatch a task. The result is the same ``AIMessage`` shape every
    #    other ai-parrot client returns — agent code that consumed
    #    ``AnthropicClient.ask`` does not need to learn a new contract.
    result = await client.ask(
        "List the Python files in the current directory and summarise "
        "what each one is for in two sentences. Use the Bash and Read "
        "tools when needed.",
        run_options=run_options,
    )

    print("=== Output ===")
    print(result.output)
    print()
    print(f"Model:        {result.model}")
    print(f"Provider:     {result.provider}")
    print(f"Stop reason:  {result.stop_reason}")
    print(f"Tool calls:   {len(result.tool_calls)}")
    if result.usage.estimated_cost is not None:
        print(f"Estimated cost: ${result.usage.estimated_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
