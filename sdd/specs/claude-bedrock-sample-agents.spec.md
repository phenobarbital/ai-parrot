---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: AWS Bedrock Sample Agents

**Feature ID**: FEAT-437
**Date**: 2026-08-21
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

AI-Parrot now supports three Bedrock-related client backends —
`BedrockConverseClient` (FEAT-302), `NovaClient` (FEAT-315), and
`BedrockMantleClient` (FEAT-407) — but there are **no example agent scripts**
that demonstrate how to use these clients to build interactive, tool-using
agents. The existing `examples/clients/aws.py` only shows raw client calls
(text completion, streaming, voice), not the full Agent experience with tools
and a CLI prompt loop.

Developers evaluating AI-Parrot for AWS-centric deployments need concrete,
runnable examples showing:
- How to wire Bedrock-hosted models (Claude, Deepseek, MiniMax) into
  AI-Parrot agents.
- How tool calling works across different model vendors on Bedrock.
- Which client backend (`bedrock-mantle` vs `bedrock-converse`) to use for
  each model family.

### Goals
- Provide 5 standalone example scripts in `examples/agents/aws/`, one per
  Bedrock-hosted model: Claude Opus 5, Claude Fable 5, Claude Haiku 4.5,
  Deepseek V3.2, MiniMax M2.5.
- Each script uses `BasicAgent` with a CLI input loop and a small toolkit
  (PythonREPL + 3 `@tool`-decorated functions) to demonstrate interactive
  tool-calling.
- Include a shared `README.md` with prerequisites, environment variables,
  model-access instructions, and an explanation of the client split.
- Demonstrate the correct client backend for each model family:
  `bedrock-converse` for Claude, `bedrock-mantle` for Deepseek/MiniMax.

### Non-Goals (explicitly out of scope)
- No new library code or client modifications — examples only.
- No streaming examples (covered separately in `examples/clients/aws.py`).
- No multi-agent or AgentCrew examples — single-agent focus.
- No `BedrockMantleClient` support for Claude models — Mantle's
  OpenAI-compatible path (`/v1`) does NOT work for Claude, whose Mantle
  endpoint uses `/anthropic/v1/messages` (rejected in brainstorm Option B —
  see `sdd/proposals/claude-bedrock-sample-agents.brainstorm.md`).
- No friendly aliases for Deepseek/MiniMax in `PUBLIC_TO_BEDROCK` — deferred
  as a low-priority follow-up (see §8).

---

## 2. Architectural Design

### Overview

**Approach: Dual-Client Showcase** (brainstorm Option A, recommended).

Use `bedrock-converse` (native Converse API via boto3/SigV4) for Anthropic
Claude models, and `bedrock-mantle` (OpenAI-compatible endpoint) for
third-party vendors (Deepseek, MiniMax) that expose the Chat Completions API.

Each Claude script shows **both** client paths — `bedrock-converse` as the
primary `llm=` string, and `bedrock` (Anthropic native with bedrock backend)
as a commented-out one-line alternative — so developers learn both options
and can switch with a single edit.

Every script follows an identical structure:
1. Tool definitions (shared toolkit: PythonREPL + 3 `@tool` functions).
2. `BasicAgent` creation with model-specific `llm=` string.
3. Interactive CLI loop (`input()` → `agent.invoke()` → print).
4. `asyncio.run(main())` entry point.

### Component Diagram

```
examples/agents/aws/
├── README.md                       ← Prerequisites, env vars, client-split explanation
├── agent_claude_opus5.py           ← bedrock-converse:anthropic.claude-opus-5
├── agent_claude_fable5.py          ← bedrock-converse:anthropic.claude-fable-5
├── agent_claude_haiku45.py         ← bedrock-converse:anthropic.claude-haiku-4-5
├── agent_deepseek_v32.py           ← bedrock-mantle:deepseek.v3.2
└── agent_minimax_m25.py            ← bedrock-mantle:minimax.minimax-m2.5

Each script:
┌─────────────────────────────────────────────────┐
│  Tool definitions                               │
│  ├── PythonREPLTool()                           │
│  ├── @tool calculator(expression: str) -> str   │
│  ├── @tool current_datetime() -> str            │
│  └── @tool system_info() -> str                 │
│                                                 │
│  async def main():                              │
│      agent = BasicAgent(                        │
│          name="...",                            │
│          llm="<client>:<model-id>",             │
│          tools=[python_repl, calculator,        │
│                 current_datetime, system_info],  │
│      )                                          │
│      await agent.configure()                    │
│      while True:                                │
│          query = input("You > ")                │
│          if query in EXIT_WORDS: break          │
│          response = await agent.invoke(query)   │
│          print(f"Agent > {response}")           │
│                                                 │
│  asyncio.run(main())                            │
└─────────────────────────────────────────────────┘
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BasicAgent` (Chatbot subclass) | uses | Agent abstraction with tool support |
| `PythonREPLTool` | uses | Bundled code-execution tool |
| `@tool` decorator | uses | Custom tool creation |
| `BedrockConverseClient` | uses (via factory) | Claude models: `llm="bedrock-converse:<model>"` |
| `BedrockMantleClient` | uses (via factory) | Deepseek/MiniMax: `llm="bedrock-mantle:<model>"` |
| `AnthropicClient` (bedrock backend) | uses (via factory) | Claude alternative: `llm="bedrock:<model>"` |
| `PUBLIC_TO_BEDROCK` | transparent | Claude model name → Bedrock model ID mapping |
| `_VENDOR_NAMESPACES` | transparent | Deepseek/MiniMax vendor-prefixed IDs pass through |

### Data Models

No new data models. Scripts use existing `BasicAgent` and tool abstractions.

### New Public Interfaces

No new public interfaces. These are standalone example scripts.

---

## 3. Module Breakdown

### Module 1: Shared Tool Definitions
- **Path**: Inline in each script (no shared module — one-file-per-model decision)
- **Responsibility**: Define 3 `@tool`-decorated utility functions used by all
  example agents:
  - `calculator(expression: str) -> str` — safe math expression evaluator
    (uses `ast.literal_eval` or `eval` with restricted globals).
  - `current_datetime() -> str` — returns current UTC datetime as ISO string.
  - `system_info() -> str` — returns Python version, platform, working directory.
- **Depends on**: `parrot.tools.tool` decorator, stdlib `datetime`, `platform`, `os`

### Module 2: Claude Opus 5 Agent Script
- **Path**: `examples/agents/aws/agent_claude_opus5.py`
- **Responsibility**: Interactive CLI agent using Claude Opus 5 via
  `bedrock-converse:anthropic.claude-opus-5`. Includes commented-out
  `bedrock:anthropic.claude-opus-5` alternative.
- **Depends on**: Module 1 (tool definitions, copy-pasted inline)

### Module 3: Claude Fable 5 Agent Script
- **Path**: `examples/agents/aws/agent_claude_fable5.py`
- **Responsibility**: Interactive CLI agent using Claude Fable 5 via
  `bedrock-converse:anthropic.claude-fable-5`.
- **Depends on**: Module 1

### Module 4: Claude Haiku 4.5 Agent Script
- **Path**: `examples/agents/aws/agent_claude_haiku45.py`
- **Responsibility**: Interactive CLI agent using Claude Haiku 4.5 via
  `bedrock-converse:anthropic.claude-haiku-4-5`.
- **Depends on**: Module 1

### Module 5: Deepseek V3.2 Agent Script
- **Path**: `examples/agents/aws/agent_deepseek_v32.py`
- **Responsibility**: Interactive CLI agent using Deepseek V3.2 via
  `bedrock-mantle:deepseek.v3.2`. Vendor-namespaced ID passes through
  `_VENDOR_NAMESPACES` (no `PUBLIC_TO_BEDROCK` entry needed).
- **Depends on**: Module 1

### Module 6: MiniMax M2.5 Agent Script
- **Path**: `examples/agents/aws/agent_minimax_m25.py`
- **Responsibility**: Interactive CLI agent using MiniMax M2.5 via
  `bedrock-mantle:minimax.minimax-m2.5`. Vendor-namespaced ID passes through
  `_VENDOR_NAMESPACES`.
- **Depends on**: Module 1

### Module 7: README
- **Path**: `examples/agents/aws/README.md`
- **Responsibility**: Documentation covering prerequisites, environment
  variables (per client type), model-access instructions, usage examples,
  and explanation of the bedrock-mantle vs bedrock-converse split.
- **Depends on**: none

---

## 4. Test Specification

These are example scripts, not library code — formal unit tests are not
required. However, each script must be verified to:

### Manual Verification
| Check | Module | Description |
|---|---|---|
| `python_syntax` | All scripts | Each script parses without syntax errors (`python -m py_compile`) |
| `import_resolution` | All scripts | All imports resolve in the project venv |
| `tool_definitions` | All scripts | `@tool`-decorated functions have proper docstrings and type hints |
| `exit_handling` | All scripts | CLI loop exits cleanly on "exit", "quit", "bye" |
| `error_handling` | All scripts | Auth failure produces a helpful error message |

### Smoke Test (optional, requires AWS credentials)
| Test | Description |
|---|---|
| `test_claude_opus5_responds` | Run script, send "hello", verify agent response |
| `test_deepseek_tool_call` | Run Deepseek script, ask "what is 2+2?", verify calculator tool is called |

### Test Data / Fixtures

No fixtures needed — these are standalone CLI scripts.

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] Directory `examples/agents/aws/` exists
- [ ] All 5 agent scripts exist and parse without syntax errors
- [ ] All scripts use `BasicAgent` from `parrot.bots.agent` (not raw clients)
- [ ] Claude scripts use `llm="bedrock-converse:<model-id>"` with a
      commented-out `llm="bedrock:<model-id>"` alternative
- [ ] Deepseek script uses `llm="bedrock-mantle:deepseek.v3.2"`
- [ ] MiniMax script uses `llm="bedrock-mantle:minimax.minimax-m2.5"`
- [ ] Each script includes `PythonREPLTool` + at least 2 `@tool`-decorated functions
- [ ] Each script has a CLI input loop with exit on "exit"/"quit"/"bye"
- [ ] Each script wraps agent creation in try/except for auth failures
- [ ] `examples/agents/aws/README.md` exists with prerequisites, env vars,
      model-access instructions, and client-split explanation
- [ ] All files added via `git add -f` (examples/ is gitignored)
- [ ] No new library dependencies introduced
- [ ] No breaking changes to existing code

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> This section is the single source of truth for what exists in the codebase.
> Implementation agents MUST NOT reference imports, attributes, or methods
> not listed here without first verifying they exist via `grep` or `read`.

### Verified Imports

```python
# All verified 2026-08-21 against current dev branch

from parrot.bots.agent import BasicAgent          # verified: parrot/bots/agent.py:28
from parrot.tools.pythonrepl import PythonREPLTool # verified: parrot/tools/pythonrepl.py:77
from parrot.tools import tool                      # verified: parrot/tools/__init__.py:144 (re-exports from decorators.py:55)

# Also valid (alternative import path for PythonREPLTool):
from parrot.tools import PythonREPLTool            # verified: parrot/tools/__init__.py re-export
```

### Existing Class Signatures

```python
# packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Chatbot, NotificationMixin):  # line 28
    def __init__(
        self,
        name: str = "Agent",                   # line 62
        agent_id: str = "agent",
        use_llm: str = "google",
        llm: str = None,                       # ← THIS is how to specify the LLM provider
        tools: List[AbstractTool] = None,
        system_prompt: str = None,
        human_prompt: str = None,
        use_tools: bool = True,
        instructions: Optional[str] = None,
        dataframes: Optional[Dict[str, pd.DataFrame]] = None,
        **kwargs,
    ): ...
    async def configure(self, app=None) -> None: ...  # line 143
    # invoke() inherited from BaseBot (parrot/bots/base.py:595)
    async def invoke(
        self,
        question: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        use_conversation_history: bool = True,
        memory: Optional[Callable] = None,
        ctx: Optional[RequestContext] = None,
        response_model: Optional[Type[BaseModel]] = None,
        **kwargs
    ): ...  # returns response

# packages/ai-parrot/src/parrot/tools/pythonrepl.py
class PythonREPLTool(AbstractTool):  # line 77
    name = "python_repl"             # line 92 — NOTE: attribute is `name`, NOT `tool_name`
    args_schema = PythonREPLArgs     # line 94 — PythonREPLArgs(code: str, debug: bool = False)

# packages/ai-parrot/src/parrot/tools/decorators.py
def tool(                            # line 55
    _func: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    auto_register: bool = False,
    requires_confirmation: bool = False,
    confirm_template: Optional[str] = None,
    confirm_window_seconds: int = 0,
    allow_edit: bool = False,
): ...
# Usage: @tool decorator on a function with docstring → docstring becomes tool description
```

### Client Factory Registrations

```python
# packages/ai-parrot/src/parrot/clients/factory.py — SUPPORTED_CLIENTS (line 107)

# For Claude models on Bedrock:
"bedrock-converse"  → BedrockConverseClient                         # line 116
"bedrock"           → AnthropicClient (PROVIDER_BACKEND="bedrock")  # line 112
"anthropic-aws"     → AnthropicClient (PROVIDER_BACKEND="aws")      # line 113

# For Deepseek/MiniMax on Bedrock:
"bedrock-mantle"    → BedrockMantleClient                           # line 125
"mantle"            → BedrockMantleClient                           # line 126
```

### Bedrock Model IDs

```python
# packages/ai-parrot/src/parrot/models/bedrock_models.py

# PUBLIC_TO_BEDROCK dict (line 71):
"claude-opus-5"    → "anthropic.claude-opus-5"                 # line 100
"claude-fable-5"   → "anthropic.claude-fable-5"               # line 101
"claude-haiku-4-5" → "anthropic.claude-haiku-4-5-20251001-v1:0"  # line 82

# REQUIRES_REGION_PREFIX dict (line 56):
"claude-opus-5"    → "us"
"claude-fable-5"   → "global"
"claude-haiku-4-5" → "us"

# _VENDOR_NAMESPACES (line 47) — IDs starting with these pass through verbatim:
_VENDOR_NAMESPACES = ("minimax.", "zai.", "moonshotai.")
# NOTE: "deepseek." is NOT in _VENDOR_NAMESPACES — the raw Bedrock model ID
# "deepseek.v3.2" may need to be passed as-is to bedrock-mantle.
```

### CLI Loop Pattern (from examples/test_agent.py)

```python
# examples/test_agent.py — reference pattern for the CLI loop

EXIT_WORDS = ["exit", "quit", "bye"]  # line 44

# Pattern: asyncio event loop → input() → agent.invoke() → print
loop = asyncio.get_event_loop()
agent = BasicAgent(name='...', tools=[...])
loop.run_until_complete(agent.configure())
query = input("Type in your query: \n")
while query not in EXIT_WORDS:
    response = loop.run_until_complete(agent.invoke(query))
    print(response)
    query = input("Type in your query: \n")

# Modern equivalent (recommended for new examples):
async def main():
    agent = BasicAgent(name='...', llm='...', tools=[...])
    await agent.configure()
    while True:
        query = input("You > ")
        if query.lower().strip() in EXIT_WORDS:
            break
        response = await agent.invoke(query)
        print(f"Agent > {response}")

if __name__ == "__main__":
    asyncio.run(main())
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| All scripts | `BasicAgent.__init__()` | `llm=` parameter | `agent.py:62` |
| All scripts | `BasicAgent.configure()` | `await agent.configure()` | `agent.py:143` |
| All scripts | `BaseBot.invoke()` | `await agent.invoke(query)` | `base.py:595` |
| All scripts | `PythonREPLTool` | tool instance in `tools=[]` | `pythonrepl.py:77` |
| All scripts | `@tool` decorator | custom function tools | `decorators.py:55` |
| Claude scripts | `BedrockConverseClient` | `llm="bedrock-converse:..."` | `factory.py:116` |
| Deepseek/MiniMax | `BedrockMantleClient` | `llm="bedrock-mantle:..."` | `factory.py:125` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.models.bedrock_models.DeepseekModels`~~ — no Deepseek enum; use raw string `"deepseek.v3.2"`
- ~~`parrot.models.bedrock_models.MiniMaxModels`~~ — no MiniMax enum; use raw string `"minimax.minimax-m2.5"`
- ~~`PythonREPLTool.tool_name`~~ — the attribute is `name`, not `tool_name` (line 92)
- ~~`BasicAgent(Agent)`~~ — `BasicAgent` inherits from `Chatbot, NotificationMixin`, NOT from `Agent`
- ~~`BedrockMantleClient` for Claude~~ — Mantle's `/v1` path is OpenAI-compatible; Claude on Mantle uses `/anthropic/v1/messages` (incompatible shape)
- ~~`examples/agents/aws/`~~ — directory does not exist; must be created
- ~~`"deepseek."` in `_VENDOR_NAMESPACES`~~ — only `"minimax.", "zai.", "moonshotai."` are listed; Deepseek model IDs are passed as raw Bedrock model IDs to the Mantle client

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Script structure**: follow the pattern in `examples/test_agent.py` (CLI loop
  with `BasicAgent` + `configure()` + `invoke()`), modernized with
  `asyncio.run(main())` instead of manual event-loop management.
- **Tool docstrings**: every `@tool`-decorated function MUST have a docstring —
  it becomes the LLM's tool description (see `decorators.py:55`).
- **Type hints**: all function parameters and return types must be annotated.
- **Error handling**: wrap `agent.configure()` in try/except to catch auth
  failures and print a user-friendly message pointing to the README.

### Script Template

Each of the 5 scripts follows this skeleton:

```python
"""AWS Bedrock Agent Example — <Model Name>

Interactive CLI agent using <Model Name> on AWS Bedrock.
Demonstrates tool calling with PythonREPL, calculator, datetime, and system info.

Usage:
    python examples/agents/aws/agent_<model>.py

Environment Variables:
    <CLIENT-SPECIFIC VARS>

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
    """Evaluate a mathematical expression safely and return the result.
    Use this for arithmetic calculations. Example: calculator("2 ** 100")
    """
    ...

@tool
def current_datetime() -> str:
    """Get the current date and time in UTC. Returns an ISO-8601 string."""
    ...

@tool
def system_info() -> str:
    """Get system information: Python version, platform, and working directory."""
    ...

# --- Agent ---

async def main():
    agent = BasicAgent(
        name="<AgentName>",
        llm="<client>:<model-id>",
        # Alternative: llm="<alt-client>:<model-id>"  # (Claude scripts only)
        tools=[python_repl, calculator, current_datetime, system_info],
        system_prompt="You are a helpful AI assistant with access to tools. ...",
    )
    try:
        await agent.configure()
    except Exception as e:
        print(f"❌ Failed to configure agent: {e}")
        print("   See examples/agents/aws/README.md for setup instructions.")
        return

    print(f"🤖 AWS Bedrock Agent — <Model Name> (<client>)")
    print(f"   Tools: python_repl, calculator, current_datetime, system_info")
    print(f"   Type 'exit' to quit.\n")

    while True:
        try:
            query = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not query or query.lower() in EXIT_WORDS:
            break
        response = await agent.invoke(query)
        print(f"Agent > {response}\n")

if __name__ == "__main__":
    asyncio.run(main())
```

### Model-Specific `llm=` Strings

| Script | Primary `llm=` | Alternative (commented) |
|---|---|---|
| `agent_claude_opus5.py` | `"bedrock-converse:anthropic.claude-opus-5"` | `"bedrock:anthropic.claude-opus-5"` |
| `agent_claude_fable5.py` | `"bedrock-converse:anthropic.claude-fable-5"` | `"bedrock:anthropic.claude-fable-5"` |
| `agent_claude_haiku45.py` | `"bedrock-converse:anthropic.claude-haiku-4-5"` | `"bedrock:anthropic.claude-haiku-4-5"` |
| `agent_deepseek_v32.py` | `"bedrock-mantle:deepseek.v3.2"` | — |
| `agent_minimax_m25.py` | `"bedrock-mantle:minimax.minimax-m2.5"` | — |

### Known Risks / Gotchas

- **`examples/**/*.py` is gitignored** (`.gitignore` line 21): all new `.py`
  files must be added via `git add -f`. The `README.md` is not gitignored.
- **Deepseek `"deepseek."` not in `_VENDOR_NAMESPACES`**: the Deepseek vendor
  prefix is NOT in the pass-through list (only `minimax.`, `zai.`, `moonshotai.`
  are). The raw Bedrock model ID `"deepseek.v3.2"` is passed directly to
  `BedrockMantleClient` which handles model IDs at the API level — verify this
  works during implementation.
- **`REQUIRES_REGION_PREFIX`**: Claude models have region prefix requirements
  (`claude-opus-5` → `"us"`, `claude-fable-5` → `"global"`, `claude-haiku-4-5`
  → `"us"`). The README should mention AWS region requirements.
- **PythonREPLTool sandbox**: the tool already has the sandbox/sanitizer gate
  (FEAT-380). No additional safety work needed.
- **Tool calling support**: Deepseek V3.2 and MiniMax M2.5 support client-side
  tool calling on Bedrock Mantle — confirmed from AWS documentation. If tool
  calling fails at runtime, the agent falls back to text-only response.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `ai-parrot` | current | Core: BasicAgent, @tool, PythonREPLTool |
| `boto3` | `>=1.28` | Required by BedrockConverseClient (SigV4 auth) |
| — | — | No NEW dependencies; all are already in the project |

---

## Worktree Strategy

- **Default isolation**: `per-spec` — all tasks run sequentially in one worktree
  (or directly on `dev`).
- **Rationale**: Pure example files with zero library changes. No risk of merge
  conflicts with other features. The total effort is low enough that sequential
  execution in a single session is optimal.
- **Cross-feature dependencies**: None. No in-flight specs share `examples/agents/aws/`.

---

## 8. Open Questions

- [x] Which Bedrock client for Claude vs third-party models? — *Resolved in
  brainstorm*: Use `bedrock-converse` for Claude, `bedrock-mantle` for
  Deepseek/MiniMax. Claude examples also show `bedrock` (Anthropic native) as
  a commented-out alternative.
- [x] Which tools beyond PythonREPL? — *Resolved in brainstorm*: Small toolkit
  of 3-4 tools: PythonREPL + calculator + current_datetime + system_info, using
  `@tool` decorator.
- [x] One script per model or a dispatcher? — *Resolved in brainstorm*: One
  self-contained script per model.
- [x] README or docstrings only? — *Resolved in brainstorm*: Shared README.md
  in the `aws/` directory.
- [ ] Should Deepseek V3.2 and MiniMax M2.5 be added to `PUBLIC_TO_BEDROCK` in
  `bedrock_models.py`? — *Owner: Jesus Lara*: Currently they pass through as
  vendor-namespaced raw strings (`"deepseek.v3.2"`, `"minimax.minimax-m2.5"`).
  Adding them would provide friendly aliases. Low priority — can be a follow-up
  feature.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-21 | Jesus Lara | Initial draft from brainstorm |
