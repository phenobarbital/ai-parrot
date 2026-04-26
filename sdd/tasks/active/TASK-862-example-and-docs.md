# TASK-862: Example & Documentation for ClaudeAgentClient

**Feature**: FEAT-124 — Claude SDK Migration & ClaudeAgentClient
**Spec**: `sdd/specs/claude-sdk-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-858, TASK-859
**Assigned-to**: unassigned

---

## Context

> Spec Module 8. Users need a runnable example demonstrating how to dispatch a task
> to a Claude Code agent via `ClaudeAgentClient`, plus README documentation covering
> both extras: `pip install ai-parrot[anthropic]` (API) and
> `pip install ai-parrot[claude-agent]` (CLI dispatch).

---

## Scope

- Create `examples/clients/claude_agent_example.py` demonstrating:
  - Importing `ClaudeAgentClient` via `LLMFactory.create("claude-agent")`
  - Setting `ClaudeAgentRunOptions(allowed_tools=["Read", "Bash"], cwd="...")`
  - Running `ask()` with a task prompt
  - Handling the `AIMessage` response
  - Including a CLI-availability check before running
- Add a short "Optional extras" section in the package README
  (`packages/ai-parrot/README.md`) documenting both install paths.

**NOT in scope**: implementation code, test code, pyproject changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/claude_agent_example.py` | CREATE | Runnable example |
| `packages/ai-parrot/README.md` | MODIFY | Add "Optional extras" section |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase.

### Verified Imports
```python
from parrot.clients.factory import LLMFactory                    # factory.py:38
from parrot.clients.claude_agent import ClaudeAgentRunOptions     # TASK-858 creates
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
LLMFactory.create("claude-agent:claude-sonnet-4-6")  # → ClaudeAgentClient

# packages/ai-parrot/src/parrot/clients/claude_agent.py (TASK-858)
class ClaudeAgentRunOptions(BaseModel):
    allowed_tools: Optional[List[str]] = None
    disallowed_tools: Optional[List[str]] = None
    permission_mode: Optional[str] = None
    cwd: Optional[str] = None
    cli_path: Optional[str] = None
    system_prompt: Optional[str] = None

class ClaudeAgentClient(AbstractClient):
    async def ask(self, prompt, *, run_options=None, **kwargs) -> AIMessage: ...
```

### Does NOT Exist
- ~~`from parrot.clients import ClaudeAgentClient`~~ — NOT re-exported from `__init__` (lazy import)
- ~~`claude_agent_sdk.ClaudeClient`~~ — class is `ClaudeSDKClient`

---

## Implementation Notes

### Pattern to Follow
```python
# examples/clients/claude_agent_example.py
"""
Example: Dispatching a task to a Claude Code agent via ClaudeAgentClient.

Prerequisites:
    pip install ai-parrot[claude-agent]
    # Ensure `claude` CLI is available (bundled with claude-agent-sdk)
"""
import asyncio
import shutil
import sys

from parrot.clients.factory import LLMFactory
from parrot.clients.claude_agent import ClaudeAgentRunOptions


async def main():
    # Check CLI availability
    if not shutil.which("claude"):
        print("Error: 'claude' CLI not found. Install with: pip install ai-parrot[claude-agent]")
        sys.exit(1)

    client = LLMFactory.create("claude-agent:claude-sonnet-4-6")
    options = ClaudeAgentRunOptions(
        allowed_tools=["Read", "Bash"],
        cwd=".",
    )
    result = await client.ask(
        "List all Python files in the current directory and summarize their purpose.",
        run_options=options,
    )
    print(f"Output: {result.output}")
    print(f"Model: {result.model}")
    print(f"Usage: {result.usage}")


if __name__ == "__main__":
    asyncio.run(main())
```

### Key Constraints
- Example must include a CLI-availability check (`shutil.which("claude")`)
- Example must be fully runnable with clear error messages
- README section must document both install paths and clarify they are independent
- Do NOT add excessive documentation — keep it concise
- Mention that `AnthropicClient` is for API access, `ClaudeAgentClient` for CLI dispatch

### References in Codebase
- Check `examples/` directory for existing example patterns
- `packages/ai-parrot/README.md` for existing README structure

---

## Acceptance Criteria

- [ ] `examples/clients/claude_agent_example.py` exists and is syntactically valid
- [ ] Example includes CLI-availability check
- [ ] Example demonstrates `LLMFactory.create`, `ClaudeAgentRunOptions`, `ask()`
- [ ] `packages/ai-parrot/README.md` has "Optional extras" section
- [ ] README documents `pip install ai-parrot[anthropic]` and `pip install ai-parrot[claude-agent]`
- [ ] Example runs end-to-end when `claude` CLI is available

---

## Test Specification

```bash
# Syntax check
python -c "import ast; ast.parse(open('examples/clients/claude_agent_example.py').read())"

# If claude CLI is available, run the example
python examples/clients/claude_agent_example.py
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-858, TASK-859 are in `tasks/completed/`
3. **Check existing examples** in `examples/` directory for patterns
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** the example and README section
6. **Verify** syntax and acceptance criteria
7. **Move this file** to `tasks/completed/TASK-862-example-and-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
