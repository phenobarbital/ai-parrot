---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: AWS Bedrock Sample Agents

**Date**: 2026-08-21
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AI-Parrot now supports three Bedrock-related client backends — `BedrockConverseClient`
(FEAT-302), `NovaClient` (FEAT-315), and `BedrockMantleClient` (FEAT-407) — but
there are **no example agent scripts** that demonstrate how to use these clients to
build interactive, tool-using agents. Existing examples in `examples/clients/aws.py`
only show raw client calls (text completion, streaming, voice), not the full Agent
experience with tools and a CLI prompt loop.

Developers evaluating AI-Parrot for AWS-centric deployments need concrete, runnable
examples showing:
- How to wire Bedrock-hosted models (Claude, Deepseek, MiniMax) into AI-Parrot agents.
- How tool calling works across different model vendors on Bedrock.
- Which client backend (`bedrock-mantle` vs `bedrock-converse`) to use for each model family.

**Who is affected**: Developers adopting AI-Parrot with AWS Bedrock as their LLM provider.

## Constraints & Requirements

- Each example must be a **self-contained, standalone script** runnable with
  `python examples/agents/aws/<script>.py`.
- Must use the existing `BasicAgent` / `Agent` abstractions — no raw client calls.
- Must include **PythonREPLTool** plus 2-3 additional `@tool`-decorated functions
  to demonstrate tool-calling breadth.
- Must provide a **CLI input loop** (`input()` prompt) for interactive conversation.
- All scripts share a **README.md** with prerequisites, env vars, and usage instructions.
- No new library dependencies — only existing `parrot.*` imports and stdlib.
- `examples/**/*.py` is gitignored (line 21) — new files need `git add -f`.

---

## Options Explored

### Option A: Dual-Client Showcase (bedrock-mantle + bedrock-converse)

Use `bedrock-mantle` (OpenAI-compatible endpoint) for vendors that expose the
Chat Completions API (Deepseek, MiniMax), and `bedrock-converse` (native Converse
API via boto3) for Anthropic Claude models whose Mantle endpoint uses the
Anthropic Messages API path (`/anthropic/v1/messages`) instead of the
OpenAI-compatible `/v1`.

Each Claude sample shows **both** `bedrock-converse` and `bedrock` (Anthropic native)
client paths, controlled by a commented-out alternative `llm=` line so the user can
switch with a one-line edit.

**5 scripts total**: one per model.

✅ **Pros:**
- Demonstrates the correct client for each model family — no silent API-shape mismatch.
- Claude examples show both paths, educating users on the difference.
- Each script is self-contained and copy-pasteable.
- Follows the existing pattern in `examples/test_agent.py` and `examples/agents/`.

❌ **Cons:**
- Two different `llm=` strings across the folder (e.g., `bedrock-converse:anthropic.claude-opus-5`
  vs `bedrock-mantle:deepseek.v3.2`) — could confuse beginners unfamiliar with the split.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.bots.agent.BasicAgent` | Agent abstraction | Already in core |
| `parrot.tools.pythonrepl.PythonREPLTool` | Python code execution tool | Core tool |
| `parrot.tools.decorators.tool` | `@tool` decorator for custom tools | Core decorator |
| `parrot.clients.bedrock.BedrockConverseClient` | Native Converse API client | FEAT-302, boto3-based |
| `parrot.clients.nova.mantle.BedrockMantleClient` | OpenAI-compatible Mantle client | FEAT-407 |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/agent.py` — `BasicAgent` class
- `packages/ai-parrot/src/parrot/tools/pythonrepl.py` — `PythonREPLTool`
- `packages/ai-parrot/src/parrot/tools/decorators.py` — `@tool` decorator
- `packages/ai-parrot/src/parrot/models/bedrock_models.py` — `PUBLIC_TO_BEDROCK` mapping
- `examples/test_agent.py` — CLI loop pattern
- `examples/clients/aws.py` — NovaClient usage pattern

---

### Option B: Mantle-Only (force all models through bedrock-mantle)

Use `bedrock-mantle` for every model, including Claude. This would require either:
(a) extending `BedrockMantleClient` to detect Anthropic model IDs and switch to the
`/anthropic/v1/messages` base path, or (b) expecting users to manually configure
`base_url` to the Anthropic-specific Mantle endpoint.

✅ **Pros:**
- Uniform `llm="bedrock-mantle:<model-id>"` across all examples — simpler to explain.
- Single client path — less cognitive load.

❌ **Cons:**
- `BedrockMantleClient` currently inherits from `OpenAIClient` and targets the
  OpenAI-compatible `/v1` endpoint. Claude on Mantle uses `/anthropic/v1/messages`
  (Anthropic Messages API shape), which is incompatible.
- Would require **code changes to the client** (not just examples) — violates the
  constraint of no new library work.
- Fragile: Claude model IDs on Mantle lack the `-vN:0` suffix, adding detection complexity.

📊 **Effort:** Medium–High (client changes required)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.clients.nova.mantle.BedrockMantleClient` | Would need modification | FEAT-407 |

🔗 **Existing Code to Reuse:**
- Same as Option A, minus `BedrockConverseClient`.

---

### Option C: Converse-Only (route everything through bedrock-converse)

Use `bedrock-converse` for all five models. The Converse API is the most universal
Bedrock endpoint and supports all model families.

✅ **Pros:**
- Single client path — `llm="bedrock-converse:<model-id>"` everywhere.
- Converse API supports tool calling natively via `toolConfig`.
- No API-shape mismatch concerns.

❌ **Cons:**
- Requires **boto3 + SigV4 signing** — heavier credential setup than Mantle's bearer
  key. Less accessible for quick demos.
- Doesn't showcase `BedrockMantleClient` at all, which is the newer, lighter option
  (FEAT-407) and the recommended path for models that support it.
- Misses the opportunity to demonstrate the framework's multi-client versatility.
- Deepseek/MiniMax model IDs on Converse may need validation (untested path).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.clients.bedrock.BedrockConverseClient` | Native Converse API client | FEAT-302 |
| `boto3` | AWS SDK, SigV4 auth | Already a dependency |

🔗 **Existing Code to Reuse:**
- Same as Option A, minus `BedrockMantleClient`.

---

## Recommendation

**Option A** is recommended because:

- It correctly matches each model to its natural Bedrock client, avoiding silent
  API-shape mismatches that would frustrate users.
- The Claude examples showing both `bedrock-converse` and `bedrock` paths are
  educational — developers learn *why* the split exists, not just *how* to copy-paste.
- It showcases AI-Parrot's multi-client architecture, which is a key differentiator.
- No client code changes required — examples-only scope keeps this low effort.

The tradeoff is slightly more complexity in the README (explaining two client types),
but this is documentation, not code complexity.

---

## Feature Description

### User-Facing Behavior

The developer creates `examples/agents/aws/` containing 5 standalone Python scripts
and a README:

```
examples/agents/aws/
├── README.md
├── agent_claude_opus5.py
├── agent_claude_fable5.py
├── agent_claude_haiku45.py
├── agent_deepseek_v32.py
└── agent_minimax_m25.py
```

Each script:
1. Imports `BasicAgent`, `PythonREPLTool`, and 2-3 `@tool`-decorated functions.
2. Configures the agent with the correct `llm=` string for the target model.
3. Starts an interactive CLI loop: `You > ` prompt, agent responds, loop until `exit`.
4. The agent can use all registered tools (PythonREPL, calculator, datetime, shell info).

Example session:
```
$ python examples/agents/aws/agent_claude_opus5.py
🤖 AWS Bedrock Agent — Claude Opus 5 (bedrock-converse)
   Tools: python_repl, calculator, current_datetime, system_info
   Type 'exit' to quit.

You > What is 2**100?
Agent > I'll calculate that for you using Python.
[Tool: python_repl] 2**100
→ 1267650600228229401496703205376

You > What time is it?
Agent > [Tool: current_datetime]
→ It's 2026-08-21 15:42:03 UTC.
```

### Internal Behavior

**Script structure** (each file follows the same pattern):

1. **Tool definitions** — `PythonREPLTool()` instance + 2-3 `@tool`-decorated functions:
   - `calculator(expression: str) -> str` — evaluates safe math expressions.
   - `current_datetime() -> str` — returns current UTC datetime.
   - `system_info() -> str` — returns Python version, platform, working directory.

2. **Agent creation** — `BasicAgent(name=..., llm=..., tools=[...])` with:
   - Claude scripts: `llm="bedrock-converse:anthropic.claude-opus-5"` (primary),
     with a commented-out `llm="bedrock:anthropic.claude-opus-5"` alternative.
   - Deepseek/MiniMax scripts: `llm="bedrock-mantle:deepseek.v3.2"` or
     `llm="bedrock-mantle:minimax.minimax-m2.5"`.

3. **CLI loop** — `while True` with `input("You > ")`, `agent.invoke(query)`,
   print response. Exit on `exit`/`quit`/`bye`.

4. **Async wrapper** — `asyncio.run(main())` at `__main__`.

**README.md** covers:
- Prerequisites (AWS account, Bedrock API key or IAM credentials).
- Environment variables per client type:
  - `bedrock-converse`: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION_NAME`
    (or `AWS_BEARER_TOKEN_BEDROCK` for API key auth).
  - `bedrock-mantle`: `BEDROCK_MANTLE_API_KEY` (or `AWS_NOVA_API_KEY`), `BEDROCK_AWS_REGION`.
- Model access: which models need to be enabled in the Bedrock console.
- How to run each script.
- Explanation of the client split (mantle vs converse vs bedrock-native).

### Edge Cases & Error Handling

- **Missing credentials**: Each script wraps agent creation in try/except, printing
  a clear message pointing to the README if auth fails.
- **Model not enabled**: Bedrock returns a specific error when a model isn't enabled
  in the console — the README explains this and links to the Bedrock model access page.
- **PythonREPL safety**: `PythonREPLTool` already has the sandbox/sanitizer gate
  (FEAT-380). No additional safety work needed.
- **Tool calling not supported**: Deepseek V3.2 and MiniMax M2.5 support client-side
  tool calling on both Mantle and Converse endpoints — confirmed from AWS docs.
  If a model fails tool calling, the agent falls back to text-only response.

---

## Capabilities

### New Capabilities
- `aws-bedrock-agent-examples`: Standalone example scripts demonstrating AWS Bedrock
  agent creation with tool support across Claude, Deepseek, and MiniMax model families.

### Modified Capabilities
- None — these are pure example files with no library changes.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `examples/agents/aws/` | new directory | 5 scripts + README |
| `examples/agents/` | extends | New `aws/` subdirectory |
| No library code | — | Examples only; no core changes |

---

## Code Context

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/bots/agent.py
class BasicAgent(Agent):
    # Agent with basic configuration, inherits from Agent
    # Usage: BasicAgent(name=..., llm=..., tools=[...])
    # Methods: configure(), invoke(query), ask(query)

# From packages/ai-parrot/src/parrot/tools/pythonrepl.py:77
class PythonREPLTool(AbstractTool):
    tool_name: str = "python_repl"  # line 92
    args_schema = PythonREPLArgs  # line 70: code: str, debug: bool

# From packages/ai-parrot/src/parrot/clients/factory.py:116
# Factory key: "bedrock-converse" → BedrockConverseClient
# Factory key: "bedrock-mantle" / "mantle" → BedrockMantleClient (lines 125-126)
# Factory key: "bedrock" → AnthropicClient with backend="bedrock" (line 112)

# From packages/ai-parrot/src/parrot/models/bedrock_models.py:71-123
# PUBLIC_TO_BEDROCK mappings:
#   "claude-opus-5" → "anthropic.claude-opus-5"
#   "claude-fable-5" → "anthropic.claude-fable-5"
#   "claude-haiku-4-5" → "anthropic.claude-haiku-4-5-20251001-v1:0"
# Vendor-namespaced IDs pass through verbatim:
#   _VENDOR_NAMESPACES = ("minimax.", "zai.", "moonshotai.") — line 47
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.bots.agent import BasicAgent          # core agent
from parrot.tools.pythonrepl import PythonREPLTool # or from parrot.tools import PythonREPLTool
from parrot.tools import tool                      # @tool decorator (decorators.py:55)
```

#### Key Attributes & Constants
- `BedrockConverseClient._default_model` → `"claude-sonnet-4-5"` (bedrock.py:1406)
- `BedrockConverseClient._fallback_model` → `"claude-haiku-4-5"` (bedrock.py:1407)
- `BedrockMantleClient._default_model` → `"openai.gpt-oss-120b"` (nova/mantle.py:81)
- `BedrockMantleClient._fallback_model` → `"google.gemma-4-26b-a4b"` (nova/mantle.py:82)

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.models.bedrock_models.DeepseekModels`~~ — no Deepseek enum in bedrock models; use raw string `"deepseek.v3.2"`
- ~~`parrot.models.bedrock_models.MiniMaxModels`~~ — no MiniMax enum; use raw string `"minimax.minimax-m2.5"` (passes through via `_VENDOR_NAMESPACES`)
- ~~`BedrockMantleClient` for Claude models~~ — Mantle's OpenAI-compatible path (`/v1`) does NOT work for Claude; Claude on Mantle uses `/anthropic/v1/messages`
- ~~`examples/agents/aws/`~~ — directory does not exist yet; must be created

---

## Parallelism Assessment

- **Internal parallelism**: Yes — each of the 5 scripts is completely independent.
  The README and the shared `@tool` definitions could be extracted as a shared module,
  but given the "one script per model" decision, each script is self-contained.
  All 5 scripts + README could be written in parallel.
- **Cross-feature independence**: No conflicts with in-flight specs. No shared
  mutable library code.
- **Recommended isolation**: `per-spec` — all tasks sequential in one worktree
  (or even directly on `dev` given these are examples with no code conflicts).
- **Rationale**: Pure example files with no library changes. No risk of merge
  conflicts with other features. Sequential is fine given the low total effort.

---

## Open Questions

- [x] Which Bedrock client for Claude vs third-party models? — *Owner: Jesus Lara*: Use `bedrock-converse` for Claude, `bedrock-mantle` for Deepseek/MiniMax. Claude examples also show `bedrock` (Anthropic native) as a commented-out alternative.
- [x] Which tools beyond PythonREPL? — *Owner: Jesus Lara*: Small toolkit of 3-4 tools: PythonREPL + calculator + current_datetime + system_info, using `@tool` decorator.
- [x] One script per model or a dispatcher? — *Owner: Jesus Lara*: One self-contained script per model.
- [x] README or docstrings only? — *Owner: Jesus Lara*: Shared README.md in the `aws/` directory.
- [ ] Should we add Deepseek V3.2 and MiniMax M2.5 to `PUBLIC_TO_BEDROCK` in `bedrock_models.py`? — *Owner: Jesus Lara*: Currently they pass through as vendor-namespaced raw strings. Adding them would provide friendly aliases (`deepseek-v3.2` → `deepseek.v3.2`). Low priority — can be a follow-up.
