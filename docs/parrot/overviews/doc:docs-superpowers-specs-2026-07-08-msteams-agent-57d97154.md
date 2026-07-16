---
type: Wiki Overview
title: MS Teams Agent Commands
id: doc:docs-superpowers-specs-2026-07-08-msteams-agent-commands-design-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The MS Teams wrapper (`MSTeamsAgentWrapper`) has no way to invoke agent methods
  directly. All user messages go through `agent.ask()` via the `FormOrchestrator`.
  The Telegram wrapper exposes `/function`, `/tool`, `/skill`, and other commands
  that allow direct method invocation, to
relates_to:
- concept: mod:parrot.integrations.utils
  rel: mentions
---

# MS Teams Agent Commands

**Date:** 2026-07-08
**Status:** Approved
**Scope:** Port core agent commands from Telegram to MS Teams wrapper; activate the dead `config.commands` field; extract shared `parse_kwargs` utility.

---

## Problem

The MS Teams wrapper (`MSTeamsAgentWrapper`) has no way to invoke agent methods directly. All user messages go through `agent.ask()` via the `FormOrchestrator`. The Telegram wrapper exposes `/function`, `/tool`, `/skill`, and other commands that allow direct method invocation, tool usage, and skill activation — none of which exist in Teams.

The `MSTeamsAgentConfig.commands` field (`Dict[str, str]`) accepts a command-to-method mapping in configuration but is never read or registered at runtime.

Additionally, the Telegram `_parse_kwargs` method splits on whitespace without respecting quoted strings, breaking multi-word argument values (e.g., `report="Read this loudly"`). This was already fixed with `shlex.split` but the fix should live in a shared module.

## Approach

**Enfoque B — `AgentCommandHandler` class with injected dependencies.**

A new class `AgentCommandHandler` in `msteams/commands/agent_commands.py` receives `agent` + `wrapper` in its constructor. Its methods are the command handlers. A `register(router)` method wires them into the existing `MSTeamsCommandRouter`. The router is created unconditionally in the wrapper (currently gated on `oauth_manager`).

## Commands to Port

| Command | Purpose | Invocation pattern |
|---------|---------|-------------------|
| `/function` | Invoke agent method with kwargs | `/function speech_report report="hello" max_lines=2` |
| `/call` | Invoke agent method with positional args (legacy) | `/call speech_report "hello" 2` |
| `/tool` | Use a specific tool via LLM | `/tool get_weather New York` |
| `/skill` | Activate a skill and query the agent | `/skill data_analysis summarize sales` |
| `/question` | Ask the LLM without tools | `/question what is machine learning?` |
| `/commands` | List all commands, tools, skills, agent methods | `/commands` |
| `/help` | Show help text with usage examples | `/help` |
| `/whoami` | Show agent info and user identity | `/whoami` |
| `/clear` | Clear conversation history | `/clear` |
| Custom | Map config command names to agent methods | `/report report="..."` (from `commands: {report: speech_report}`) |

## Architecture

### New Files

#### `parrot/integrations/utils.py`

Shared utilities for all integration wrappers. Contains `parse_kwargs(text) -> dict` using `shlex.split` to respect quoted values. Falls back to `str.split()` on parse errors.

#### `msteams/commands/agent_commands.py`

```
class AgentCommandHandler:
    __init__(agent, wrapper)
    register(router: MSTeamsCommandRouter)
    
    # Command handlers (all: async (TurnContext) -> None)
    handle_function(turn_context)
    handle_call(turn_context)
    handle_tool(turn_context)
    handle_skill(turn_context)
    handle_question(turn_context)
    handle_commands(turn_context)
    handle_help(turn_context)
    handle_whoami(turn_context)
    handle_clear(turn_context)
    
    # Custom command support
    _register_custom_commands(router)
    _make_custom_handler(method_name) -> handler
    
    # Internal helpers
    _extract_text(turn_context) -> str       # strips bot mentions
    _send_result(turn_context, result, prefix)  # parse + Adaptive Card
    _send_text(turn_context, text)           # plain text reply
    _list_tools() -> str                     # bullet-formatted tool list
    _list_skills() -> str                    # bullet-formatted skill list
    _list_callable_methods() -> str          # public agent methods
    _resolve_skill(name) -> SkillDefinition  # resolve by name or trigger
```

### Modified Files

#### `msteams/wrapper.py`

- The command router is created **unconditionally** (currently gated on `oauth_manager is not None`).
- `AgentCommandHandler` is instantiated and registered on the router.
- Jira commands are registered only if `oauth_manager` is provided (unchanged).

```python
# Always create router
self._command_router = MSTeamsCommandRouter()
agent_handler = AgentCommandHandler(agent, self)
agent_handler.register(self._command_router)
if oauth_manager is not None:
    register_jira_commands(self._command_router, oauth_manager)
```

#### `telegram/wrapper.py`

- `_parse_kwargs` static method delegates to `parrot.integrations.utils.parse_kwargs`.
- The `import shlex` added earlier in this session stays; the method body is replaced with a one-line delegation.

### Unchanged Files

- `msteams/commands/__init__.py` — `MSTeamsCommandRouter` is sufficient as-is.
- `msteams/models.py` — `commands: Dict[str, str]` field already exists.
- `msteams/handler.py` — `send_text`, `send_card` are used via `self.wrapper`.

## Handler Behavior Details

### `/function` and `/call`

- Validate method exists on `self.agent` and is callable.
- `/function` parses `key=val` pairs via `parse_kwargs`; `/call` splits positionally.
- Send typing indicator before execution.
- Handle both async and sync methods.
- Errors are caught and sent as text messages.

### `/tool`

- Without args: lists available tools (up to 20, with truncated descriptions).
- With args: validates tool exists in `agent.tool_manager`, then calls `agent.ask()` with a directive prompt: `"Use the tool X with the following input: Y"`.
- The LLM handles actual tool invocation (same pattern as Telegram).

### `/skill`

- Without args: lists skills from file-based and DB-backed registries (up to 15).
- With args: resolves skill by name or trigger from both registries. Sets `agent._active_skill` for the duration of the `agent.ask()` call, then clears it in a `finally` block.

### `/clear`

- Clears agent conversation memory if `agent.conversations[conversation_id]` exists.
- Clears Bot Framework `ConversationState` and saves changes.

### Custom commands

- Read from `self.wrapper.config.commands` dict during `register()`.
- Each entry maps a command name to an agent method name.
- A closure-based handler is created via `_make_custom_handler(method_name)`.
- Custom handlers use `parse_kwargs` for argument parsing (same as `/function`).
- Methods not found on the agent are logged as warnings and skipped.

## Response Pipeline

All handlers use the wrapper's existing response infrastructure:

1. `wrapper._parse_response(result)` — detects Adaptive Card JSON or parses into `ParsedResponse`.
2. `wrapper._send_parsed_response(parsed, turn_context)` — builds Adaptive Card with text, tables, charts, code blocks.
3. `wrapper.send_text(text, turn_context)` — for simple text replies (help, errors, listings).
4. `wrapper.send_card(card, turn_context)` — for raw Adaptive Card dicts.

## File Structure

```
parrot/integrations/
├── utils.py                   # NEW — parse_kwargs
├── parser.py                  # existing, unchanged
├── msteams/
│   ├── commands/
│   │   ├── __init__.py        # MSTeamsCommandRouter (unchanged)
│   │   ├── jira_commands.py   # existing (unchanged)
│   │   └── agent_commands.py  # NEW — AgentCommandHandler
│   ├── wrapper.py             # MODIFIED — unconditional router + agent commands
│   └── models.py              # unchanged (commands field already exists)
└── telegram/
    └── wrapper.py             # MODIFIED — _parse_kwargs delegates to utils
```

## Testing

- Unit tests for `parse_kwargs` with quoted strings, nested quotes, edge cases.
- Unit tests for `AgentCommandHandler` with mocked agent and wrapper.
- Integration test: verify custom commands from config are registered and dispatch correctly.

## Out of Scope

- Operator commands (`/health`, `/status`, `/context`, `/memory`, `/model`, `/thread`) — future work.
- `/login`/`/logout` — Teams uses Azure AD at the adapter level.
- `/start` — Teams has its own onboarding flow via welcome cards.
- Shared command mixin between Telegram and Teams (Approach C) — deferred.
