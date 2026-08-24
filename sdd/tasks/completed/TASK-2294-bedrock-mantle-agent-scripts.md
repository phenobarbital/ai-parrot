# TASK-2294: Create Bedrock-Mantle Agent Scripts (Deepseek V3.2, MiniMax M2.5)

**Feature**: FEAT-437 — AWS Bedrock Sample Agents
**Spec**: `sdd/specs/claude-bedrock-sample-agents.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2293
**Assigned-to**: unassigned

---

## Context

This task implements the two third-party vendor agent scripts for FEAT-437.
Deepseek V3.2 and MiniMax M2.5 are accessed via `BedrockMantleClient` — the
OpenAI-compatible endpoint that Bedrock exposes for non-Anthropic models — as
opposed to the `BedrockConverseClient` used for Claude.

Key difference from TASK-2293: no commented-out alternative client (Mantle is
the only supported path for these vendors). There is also NO entry in
`PUBLIC_TO_BEDROCK` for these models — their IDs are passed verbatim.

Implements spec Modules 5 and 6.

---

## Scope

- Write `examples/agents/aws/agent_deepseek_v32.py` — Deepseek V3.2 via
  `bedrock-mantle:deepseek.v3.2`
- Write `examples/agents/aws/agent_minimax_m25.py` — MiniMax M2.5 via
  `bedrock-mantle:minimax.minimax-m2.5`
- Each script MUST include (same toolkit as TASK-2293):
  - `PythonREPLTool()` instance
  - `@tool calculator(expression: str) -> str` with docstring
  - `@tool current_datetime() -> str` with docstring
  - `@tool system_info() -> str` with docstring
  - `async def main()` with `await agent.configure()` in try/except
  - CLI loop exiting on `EXIT_WORDS = ["exit", "quit", "bye"]`
  - `asyncio.run(main())` entry point
  - **No** commented-out alternative client (unlike Claude scripts)
- Force-add files with `git add -f` (examples/ is gitignored)
- Verify `deepseek.v3.2` passes through `BedrockMantleClient` correctly
  (see gotcha note in spec §7 — "deepseek." is NOT in `_VENDOR_NAMESPACES`)

**NOT in scope**: Claude scripts (TASK-2293), README (TASK-2295).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/aws/agent_deepseek_v32.py` | CREATE | Deepseek V3.2 interactive CLI agent |
| `examples/agents/aws/agent_minimax_m25.py` | CREATE | MiniMax M2.5 interactive CLI agent |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports and signatures. DO NOT invent alternatives.

### Verified Imports

```python
from parrot.bots.agent import BasicAgent           # verified: parrot/bots/agent.py:28
from parrot.tools.pythonrepl import PythonREPLTool # verified: parrot/tools/pythonrepl.py:77
from parrot.tools import tool                       # verified: parrot/tools/__init__.py:144
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/agent.py:28
class BasicAgent(Chatbot, NotificationMixin):
    def __init__(
        self,
        name: str = "Agent",
        llm: str = None,               # ← "bedrock-mantle:<model-id>"
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        **kwargs,
    ): ...
    async def configure(self, app=None) -> None: ...
    async def invoke(self, question: str, **kwargs): ...
```

### Model-Specific `llm=` Strings (Mantle Scripts)

```python
# agent_deepseek_v32.py — vendor-namespaced ID passed verbatim
llm="bedrock-mantle:deepseek.v3.2"
# No alternative — bedrock-converse does NOT support Deepseek

# agent_minimax_m25.py — vendor-namespaced; "minimax." IS in _VENDOR_NAMESPACES
llm="bedrock-mantle:minimax.minimax-m2.5"
# No alternative — bedrock-converse does NOT support MiniMax
```

### Client Factory Registrations

```python
# packages/ai-parrot/src/parrot/clients/factory.py — SUPPORTED_CLIENTS (line 107)
"bedrock-mantle"  → BedrockMantleClient  # line 125
"mantle"          → BedrockMantleClient  # line 126 (alias)
```

### Vendor Namespace Notes

```python
# packages/ai-parrot/src/parrot/models/bedrock_models.py

# _VENDOR_NAMESPACES (line 47):
_VENDOR_NAMESPACES = ("minimax.", "zai.", "moonshotai.")
# "minimax.minimax-m2.5" → passes through verbatim (prefix matches)

# NOTE: "deepseek." is NOT in _VENDOR_NAMESPACES.
# "deepseek.v3.2" is passed as a raw Bedrock model ID to BedrockMantleClient.
# BedrockMantleClient handles this at the API level directly.
# If this fails at runtime, open a follow-up to add "deepseek." to _VENDOR_NAMESPACES.
```

### Does NOT Exist

- ~~`parrot.models.bedrock_models.DeepseekModels`~~ — no enum; use raw string `"deepseek.v3.2"`
- ~~`parrot.models.bedrock_models.MiniMaxModels`~~ — no enum; use raw string `"minimax.minimax-m2.5"`
- ~~`PythonREPLTool.tool_name`~~ — attribute is `name`, not `tool_name`
- ~~`BedrockMantleClient` for Claude~~ — do NOT use `bedrock-mantle` for Claude models
- ~~Commented-out `bedrock:` alternative~~ — Mantle-only scripts have no alternative client

---

## Implementation Notes

### Script Template for Mantle-Based Scripts

```python
"""AWS Bedrock Agent Example — <Model Name>

Interactive CLI agent using <Model Name> on AWS Bedrock via bedrock-mantle
(OpenAI-compatible endpoint for third-party models).
Demonstrates tool calling with PythonREPL, calculator, datetime, and system info.

Usage:
    python examples/agents/aws/agent_<slug>.py

Environment Variables:
    BEDROCK_ENDPOINT_URL     — Bedrock Mantle endpoint URL (optional; defaults to regional)
    AWS_ACCESS_KEY_ID        — AWS credentials
    AWS_SECRET_ACCESS_KEY    — AWS credentials
    AWS_DEFAULT_REGION       — AWS region (e.g. us-east-1)

See examples/agents/aws/README.md for full setup instructions.
"""
import asyncio
import os
import platform
from datetime import datetime, timezone

from parrot.bots.agent import BasicAgent
from parrot.tools.pythonrepl import PythonREPLTool
from parrot.tools import tool

EXIT_WORDS = ["exit", "quit", "bye"]

# --- Tool definitions ---

python_repl = PythonREPLTool()

@tool
def calculator(expression: str) -> str:
    """Evaluate a mathematical expression safely and return the result as a string.
    Use this for arithmetic calculations. Example: calculator('2 + 2')
    """
    try:
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {e}"

@tool
def current_datetime() -> str:
    """Get the current date and time in UTC. Returns an ISO-8601 formatted string."""
    return datetime.now(timezone.utc).isoformat()

@tool
def system_info() -> str:
    """Get system information: Python version, platform name, and current working directory."""
    return (
        f"Python: {platform.python_version()}, "
        f"Platform: {platform.system()} {platform.release()}, "
        f"CWD: {os.getcwd()}"
    )

# --- Agent ---

async def main() -> None:
    agent = BasicAgent(
        name="<AgentName>",
        llm="bedrock-mantle:<vendor-model-id>",
        tools=[python_repl, calculator, current_datetime, system_info],
        system_prompt=(
            "You are a helpful AI assistant running on AWS Bedrock. "
            "You have access to tools: a Python REPL, a calculator, "
            "the current datetime, and system info. Use them when helpful."
        ),
    )
    try:
        await agent.configure()
    except Exception as e:
        print(f"❌ Failed to configure agent: {e}")
        print("   See examples/agents/aws/README.md for setup instructions.")
        return

    print(f"🤖 AWS Bedrock Agent — <Model Name> (bedrock-mantle)")
    print("   Tools: python_repl, calculator, current_datetime, system_info")
    print("   Type 'exit' to quit.\n")

    while True:
        try:
            query = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if not query or query.lower() in EXIT_WORDS:
            print("Goodbye!")
            break
        response = await agent.invoke(query)
        print(f"Agent > {response}\n")

if __name__ == "__main__":
    asyncio.run(main())
```

### Key Constraints

- **No commented-out alternative** for Mantle scripts (unlike Claude scripts)
- The `calculator` tool MUST NOT use unrestricted `eval` — pass `{"__builtins__": {}}` as globals
- Wrap `agent.configure()` in try/except; catch `Exception`
- Handle `EOFError` and `KeyboardInterrupt` in the input loop
- `BEDROCK_ENDPOINT_URL` environment variable note in the docstring (some Mantle setups need it)

### Deepseek Gotcha

The `"deepseek."` prefix is NOT in `_VENDOR_NAMESPACES`
(`packages/ai-parrot/src/parrot/models/bedrock_models.py` line 47 — only
`minimax.`, `zai.`, `moonshotai.` are listed). The raw Bedrock model ID
`"deepseek.v3.2"` is passed directly through to `BedrockMantleClient`.
If configure fails with a model resolution error, grep `bedrock_models.py`
for `_VENDOR_NAMESPACES` and add `"deepseek."` as a follow-up fix.

### Force-add Due to .gitignore

```bash
# examples/ is gitignored (.gitignore line 21) — MUST use -f flag:
git add -f examples/agents/aws/agent_deepseek_v32.py
git add -f examples/agents/aws/agent_minimax_m25.py
```

### References in Codebase

- `examples/agents/aws/agent_claude_opus5.py` — reference pattern (created by TASK-2293)
- `packages/ai-parrot/src/parrot/clients/bedrock_mantle_client.py` — `BedrockMantleClient`
- `packages/ai-parrot/src/parrot/models/bedrock_models.py` — vendor namespaces

---

## Acceptance Criteria

- [ ] `agent_deepseek_v32.py` and `agent_minimax_m25.py` exist in `examples/agents/aws/`
- [ ] Both scripts parse without syntax errors: `python -m py_compile examples/agents/aws/agent_deepseek_v32.py examples/agents/aws/agent_minimax_m25.py`
- [ ] Both scripts use `BasicAgent` from `parrot.bots.agent`
- [ ] Deepseek script uses `llm="bedrock-mantle:deepseek.v3.2"`
- [ ] MiniMax script uses `llm="bedrock-mantle:minimax.minimax-m2.5"`
- [ ] Each script has `PythonREPLTool()` + 3 `@tool`-decorated functions with docstrings and type hints
- [ ] Each script has CLI loop with exit on EXIT_WORDS
- [ ] Each script wraps `agent.configure()` in try/except
- [ ] **No** `bedrock:` commented-out alternative (Mantle-only scripts)
- [ ] Both files added via `git add -f`

---

## Test Specification

No formal unit tests (example scripts). Verify manually:

```bash
# Syntax check (no AWS credentials needed)
source .venv/bin/activate
python -m py_compile examples/agents/aws/agent_deepseek_v32.py
python -m py_compile examples/agents/aws/agent_minimax_m25.py
echo "All syntax checks passed"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/claude-bedrock-sample-agents.spec.md`
2. **Check dependencies** — TASK-2293 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — grep `bedrock_models.py` for `_VENDOR_NAMESPACES`
   to confirm current list; note if `"deepseek."` was added since the spec was written
4. **Reference the Claude scripts** from TASK-2293 as a structural template
5. **Write the 2 Mantle scripts** following the template (no commented alternative)
6. **Verify syntax**: `python -m py_compile` each file
7. **Force-add** with `git add -f` — required because `examples/` is in `.gitignore`
8. **Commit** with message: `feat(FEAT-437): add Bedrock-Mantle agent scripts (Deepseek V3.2, MiniMax M2.5)`
9. **Move this file** to `sdd/tasks/completed/TASK-2294-bedrock-mantle-agent-scripts.md`
10. **Update index** at `sdd/tasks/index/claude-bedrock-sample-agents.json` → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: not recorded at completion time
**Date**: not recorded (index marked `done`; task file was never updated)
**Notes**: Reconciled retroactively on 2026-08-24 during an `sdd/tasks/active/`
cleanup. The task index (`sdd/tasks/index/claude-bedrock-sample-agents.json`)
already carried status `done`, but this file was left in `active/` as an
unfilled template. Declared deliverables were verified present on disk:

- `examples/agents/aws/agent_deepseek_v32.py` — present
- `examples/agents/aws/agent_minimax_m25.py` — present

No original completion note exists, so the implementation details, deviations,
and test evidence for this task were never captured and are not reconstructed
here.

**Deviations from spec**: unknown — not recorded at completion time.
