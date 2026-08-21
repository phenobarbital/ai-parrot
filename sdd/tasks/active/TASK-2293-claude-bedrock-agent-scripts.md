# TASK-2293: Create Claude Bedrock Agent Scripts (Opus 5, Fable 5, Haiku 4.5)

**Feature**: FEAT-437 — AWS Bedrock Sample Agents
**Spec**: `sdd/specs/claude-bedrock-sample-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the first and foundational task for FEAT-437. It creates the
`examples/agents/aws/` directory and implements the three Claude-family
agent scripts. All three scripts use `bedrock-converse` (native Converse
API via boto3/SigV4) as the primary client, with `bedrock` (Anthropic
native with bedrock backend) as a commented-out alternative.

Each script is self-contained: tool definitions (PythonREPL + 3 `@tool`
functions), agent creation, and a CLI input loop are all inline — there
is no shared module.

Implements spec Modules 2, 3, 4 (Module 1 — shared tool definitions —
is inline in each script).

---

## Scope

- Create directory `examples/agents/aws/` (if not present)
- Write `examples/agents/aws/agent_claude_opus5.py` — Claude Opus 5 via
  `bedrock-converse:anthropic.claude-opus-5`
- Write `examples/agents/aws/agent_claude_fable5.py` — Claude Fable 5 via
  `bedrock-converse:anthropic.claude-fable-5`
- Write `examples/agents/aws/agent_claude_haiku45.py` — Claude Haiku 4.5 via
  `bedrock-converse:anthropic.claude-haiku-4-5`
- Each script MUST include:
  - `PythonREPLTool()` instance
  - `@tool calculator(expression: str) -> str` with docstring
  - `@tool current_datetime() -> str` with docstring
  - `@tool system_info() -> str` with docstring
  - `async def main()` with `await agent.configure()` in try/except
  - CLI loop exiting on `EXIT_WORDS = ["exit", "quit", "bye"]`
  - `asyncio.run(main())` entry point
  - Commented-out `llm="bedrock:<model-id>"` alternative line
- Force-add files with `git add -f` (examples/ is gitignored per `.gitignore` line 21)

**NOT in scope**: README, Deepseek script, MiniMax script (TASK-2294 and TASK-2295).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/agents/aws/agent_claude_opus5.py` | CREATE | Claude Opus 5 interactive CLI agent |
| `examples/agents/aws/agent_claude_fable5.py` | CREATE | Claude Fable 5 interactive CLI agent |
| `examples/agents/aws/agent_claude_haiku45.py` | CREATE | Claude Haiku 4.5 interactive CLI agent |

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
        name: str = "Agent",           # line 62
        llm: str = None,               # ← specify LLM as "client:model-id"
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        **kwargs,
    ): ...
    async def configure(self, app=None) -> None: ...  # line 143
    async def invoke(self, question: str, **kwargs): ...  # inherited base.py:595

# packages/ai-parrot/src/parrot/tools/pythonrepl.py:77
class PythonREPLTool(AbstractTool):
    name = "python_repl"   # line 92 — attribute is `name`, NOT `tool_name`

# packages/ai-parrot/src/parrot/tools/decorators.py:55
def tool(_func=None, *, name=None, description=None, ...): ...
# Usage: @tool decorator on a function with docstring → docstring is the tool description
```

### Model-Specific `llm=` Strings (Claude Scripts)

```python
# agent_claude_opus5.py
llm="bedrock-converse:anthropic.claude-opus-5"
# llm="bedrock:anthropic.claude-opus-5"  # ← commented-out alternative

# agent_claude_fable5.py
llm="bedrock-converse:anthropic.claude-fable-5"
# llm="bedrock:anthropic.claude-fable-5"

# agent_claude_haiku45.py
llm="bedrock-converse:anthropic.claude-haiku-4-5"
# llm="bedrock:anthropic.claude-haiku-4-5"
```

### Client Factory Registrations

```python
# packages/ai-parrot/src/parrot/clients/factory.py — SUPPORTED_CLIENTS (line 107)
"bedrock-converse"  → BedrockConverseClient                         # line 116
"bedrock"           → AnthropicClient (PROVIDER_BACKEND="bedrock")  # line 112
```

### Does NOT Exist

- ~~`PythonREPLTool.tool_name`~~ — attribute is `name`, not `tool_name` (line 92)
- ~~`BasicAgent(Agent)`~~ — `BasicAgent` inherits from `Chatbot, NotificationMixin`, NOT `Agent`
- ~~`BedrockMantleClient` for Claude~~ — do NOT use `bedrock-mantle` for Claude models
- ~~`examples/agents/aws/`~~ — does not exist yet; must be created
- ~~`parrot.models.bedrock_models.ClaudeModels`~~ — no enum; use raw string model IDs

---

## Implementation Notes

### Script Template (follow exactly)

```python
"""AWS Bedrock Agent Example — <Model Name>

Interactive CLI agent using <Model Name> on AWS Bedrock via bedrock-converse.
Demonstrates tool calling with PythonREPL, calculator, datetime, and system info.

Usage:
    python examples/agents/aws/agent_<slug>.py

Environment Variables:
    AWS_ACCESS_KEY_ID        — AWS credentials
    AWS_SECRET_ACCESS_KEY    — AWS credentials
    AWS_DEFAULT_REGION       — e.g. us-east-1 (Claude Opus 5 / Haiku 4.5)
                               or us-west-2 (Claude Fable 5 uses global prefix)

See examples/agents/aws/README.md for full setup instructions.
"""
import asyncio
import ast
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
    Use this for arithmetic calculations. Example: calculator('2 ** 100')
    """
    try:
        # Restrict globals for safety
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
        llm="bedrock-converse:<model-id>",
        # llm="bedrock:<model-id>",  # Alternative: Anthropic native with Bedrock backend
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

    print(f"🤖 AWS Bedrock Agent — <Model Name> (bedrock-converse)")
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

- The `calculator` tool MUST NOT use unrestricted `eval` — pass `{"__builtins__": {}}` as globals
- Each script's module docstring MUST list the environment variables for that client
- The commented-out `bedrock:` alternative MUST appear immediately after the primary `llm=` line
- Use `asyncio.run(main())` NOT the manual `loop = asyncio.get_event_loop()` pattern
- Wrap `agent.configure()` in try/except — catch `Exception` and print helpful message
- Handle `EOFError` and `KeyboardInterrupt` in the input loop

### Force-add Due to .gitignore

```bash
# examples/ is gitignored (.gitignore line 21) — MUST use -f flag:
git add -f examples/agents/aws/agent_claude_opus5.py
git add -f examples/agents/aws/agent_claude_fable5.py
git add -f examples/agents/aws/agent_claude_haiku45.py
```

### References in Codebase

- `examples/test_agent.py` — CLI loop reference pattern (lines 44-end)
- `packages/ai-parrot/src/parrot/bots/agent.py` — `BasicAgent` implementation
- `packages/ai-parrot/src/parrot/tools/pythonrepl.py` — `PythonREPLTool`

---

## Acceptance Criteria

- [ ] `examples/agents/aws/` directory exists
- [ ] `agent_claude_opus5.py`, `agent_claude_fable5.py`, `agent_claude_haiku45.py` exist
- [ ] All 3 scripts parse without syntax errors: `python -m py_compile examples/agents/aws/agent_claude_*.py`
- [ ] All 3 scripts use `BasicAgent` from `parrot.bots.agent`
- [ ] Claude scripts use `llm="bedrock-converse:<model-id>"` with commented-out `"bedrock:<model-id>"` alternative
- [ ] Each script has `PythonREPLTool()` + 3 `@tool`-decorated functions with docstrings and type hints
- [ ] Each script has CLI loop with exit on EXIT_WORDS
- [ ] Each script wraps `agent.configure()` in try/except
- [ ] All files added via `git add -f`

---

## Test Specification

No formal unit tests (example scripts). Verify manually:

```bash
# Syntax check (no AWS credentials needed)
source .venv/bin/activate
python -m py_compile examples/agents/aws/agent_claude_opus5.py
python -m py_compile examples/agents/aws/agent_claude_fable5.py
python -m py_compile examples/agents/aws/agent_claude_haiku45.py
echo "All syntax checks passed"

# Import check (no AWS credentials needed)
python -c "
import ast, importlib
for f in ['examples/agents/aws/agent_claude_opus5.py',
          'examples/agents/aws/agent_claude_fable5.py',
          'examples/agents/aws/agent_claude_haiku45.py']:
    ast.parse(open(f).read())
print('Import structure OK')
"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/claude-bedrock-sample-agents.spec.md` for full context
2. **Check dependencies** — none (this is the first task)
3. **Verify the Codebase Contract** — grep for `BasicAgent` in `parrot/bots/agent.py` and
   `PythonREPLTool` in `parrot/tools/pythonrepl.py` to confirm line numbers haven't shifted
4. **Create `examples/agents/aws/` directory** with `mkdir -p`
5. **Write the 3 Claude scripts** following the template exactly (different model IDs/names per script)
6. **Verify syntax**: `python -m py_compile` each file
7. **Force-add** with `git add -f` — required because `examples/` is in `.gitignore`
8. **Commit** with message: `feat(FEAT-437): add Claude Bedrock agent scripts (Opus 5, Fable 5, Haiku 4.5)`
9. **Move this file** to `sdd/tasks/completed/TASK-2293-claude-bedrock-agent-scripts.md`
10. **Update index** at `sdd/tasks/index/claude-bedrock-sample-agents.json` → `"done"`
11. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
