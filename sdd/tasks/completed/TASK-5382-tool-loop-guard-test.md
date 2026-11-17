# TASK-5382: Guard test — the tool-loop flag matches every provider's resolved ask()

**Feature**: FEAT-848 — Client tool-loop capability flag
**Spec**: `sdd/specs/client-tool-loop-capability.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5379
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (G4, AC-5). The flag must not drift from what providers do. For every installed provider,
the test resolves `ask()` through the MRO (following real `super().ask(...)` calls) plus one hop of
`self.<helper>(...)` calls, parses the source with `ast`, and counts only executable `self.<name>(...)` calls
to a tool-execution method. The flag must equal `runs_loop or cls.__name__ in EXTERNAL_LOOP_CLIENTS`. The two
external-agent clients (Codex, Claude) are allowlisted, and each allowlist entry is backed by a bridge
exposure test: Codex's already exists; this task adds Claude's.

The helpers in the blueprint were prototyped on `dev @ d8832d3fc8` over all 39 installed provider keys
(22 classes): 3 classes `False` (hf, jev, google-live), 2 bridge exceptions, 17 in-process loops, no
unresolved method — the spec §6 audit, reproduced exactly.

---

## Scope

- Append to `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` (created by TASK-5379):
  `TOOL_EXECUTION_METHODS`, `EXTERNAL_LOOP_CLIENTS`, `_installed_classes()`, `_parse_function()`,
  `_self_method_calls()`, `_resolved_ask_calls()`, three synthetic fixture classes, and five tests:
  `test_flag_matches_resolved_ask[provider]`, `test_comment_and_string_markers_do_not_count`,
  `test_executable_marker_counts_through_mro_and_helper`, `test_uncalled_nested_marker_does_not_count`,
  `test_claude_bridge_exposes_registered_tools`.

**NOT in scope**:
- Any source change in `parrot/` (the flags are TASK-5379's; a guard failure means report, not "fix the provider").
- Executing tools through either bridge (FEAT-434's contract). The Codex bridge test already exists — do not duplicate it.
- An `ask_stream()` audit (spec §8: no streaming flag).
- Touching `test_default_is_true` / `test_known_false_classes` (TASK-5379).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` | MODIFY | append the AST guard, synthetic fixtures and the Claude bridge exposure test |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev @ d8832d3fc8` (2026-11-09).

### Verified Imports
```python
import ast, inspect, textwrap                                       # stdlib
from parrot.clients.factory import LLMFactory                        # verified: packages/ai-parrot/tests/clients/test_credential_env.py:9
from parrot.tools.manager import ToolManager                         # verified: packages/ai-parrot-client-openai/tests/unit/test_codex_agent.py:13
# Inside test_claude_bridge_exposes_registered_tools only (optional extra):
#   pytest.importorskip("claude_agent_sdk")                          # installed: claude_agent_sdk 0.2.174
#   from parrot.clients.anthropic.claude_agent import ClaudeAgentClient, ClaudeAgentRunOptions   # claude_agent.py:265, :85
#   from parrot.clients.anthropic.claude_agent_bridge import ClaudeAgentToolBridge               # claude_agent_bridge.py:60
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def supported_clients() -> Dict[str, Any]: ...   # :203 — values are classes or zero-arg entry-point loaders (ep.load, :146-147);
                                                     # only INSTALLED distributions register entries, so a loader raising
                                                     # ModuleNotFoundError = an optional dependency is absent

# packages/ai-parrot/src/parrot/clients/base.py
class AbstractClient:
    def __init_subclass__(cls, **kwargs) -> None: ...   # :324 — wraps each subclass's own ask/ask_stream/resume/invoke
                                                        # with the budget adapter: ALWAYS inspect.unwrap() before getsource
    @property
    def tool_manager(self) -> ToolManager: ...          # :1002 (setter :1007)

# packages/ai-parrot/src/parrot/tools/manager.py
class ToolManager:
    def __init__(self, logger=None, debug: bool = False, include_search_tool: bool = False, resolver=None, execution_policy=None)  # :302
    def register_tool(self, tool=None, name: str = None, description: str = None, input_schema: Dict[str, Any] = None,
                      function: Callable = None) -> None                                                                       # :856

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py
class ClaudeAgentRunOptions(BaseModel):                 # :85 — expose_parrot_tools: bool = True (:213); max_exposed_tools: int = 15 (:220)
class ClaudeAgentClient(AbstractClient):                # :265 — __init__(cli_path=None, cwd=None, permission_mode=None, run_options=None, **kwargs) :291
    # ask() builds the bridge exactly like this (:465-484):
    #   bridge = ClaudeAgentToolBridge(self.tool_manager, tool_timeout=merged.tool_timeout)
    #   selected_tools = bridge.select(prompt or "", merged.max_exposed_tools)
    #   server_map["parrot"] = bridge.build_server(selected_tools, caller_context)
    #   exposed_names = bridge.exposed_names()

# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent_bridge.py
class ClaudeAgentToolBridge:                                           # :60
    def __init__(self, tool_manager, *, namespace: str = "parrot", tool_timeout: float | None = None)   # :74
    def select(self, query: str, limit: int) -> list[AbstractTool]     # :87 — blank query: registration order, no ranking
    def build_server(self, tools, permission_context=None) -> Any       # :148 — needs claude_agent_sdk; sets the exposed names
    def exposed_names(self) -> list[str]                                # :328 — "mcp__<namespace>__<tool>"; EMPTY until build_server() ran

# Codex counterpart (exists, do not duplicate):
# packages/ai-parrot-client-openai/tests/unit/test_codex_agent.py:129 — test_tool_bridge_routes_through_tool_manager
```

### Does NOT Exist
- ~~`exposed_names()` populated by `select()`~~ — **spec §3 M3 drift**: the spec says "select(...) and assert the sentinel is in `bridge.exposed_names()`", but `exposed_names()` is empty until `build_server()` runs, and its entries are `mcp__parrot__<tool>`, not the bare name. Call `build_server(selected)` and assert `"mcp__parrot__<sentinel>"` (prototyped: works with sdk 0.2.174).
- ~~catching every `Exception` in provider enumeration~~ — `test_credential_env.py:17` does; this test must NOT (spec §2): skip only `ModuleNotFoundError`, let other loader errors fail.
- ~~`textwrap.dedent` always yields parseable source~~ — `AnthropicClient._get_deep_research_system_prompt` has column-0 string lines, so dedent leaves it indented and `ast.parse` raises `IndentationError`; retry with a `class _Wrapper:` prefix (blueprint).
- ~~`parrot.clients.protocols.ToolLoopCapable`~~, ~~`supports_stream_tool_loop`~~ — do not exist; not added.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/clients/test_tool_loop_capability.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.supported_clients",
    "sym:packages/ai-parrot/src/parrot/clients/base.py#AbstractClient",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager",
    "sym:packages/ai-parrot/src/parrot/tools/manager.py#ToolManager.register_tool",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py#ClaudeAgentClient",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent.py#ClaudeAgentRunOptions",
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/claude_agent_bridge.py#ClaudeAgentToolBridge"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Only `ast.Call` nodes whose function is `self.<name>` (or `super().<name>`) count. Comments, docstrings, string literals, uncalled attribute references and bodies of nested `def`/`class`/`lambda` never count (spec §2).
- `_resolved_ask_calls(cls)` keeps the spec signature; the optional `unresolved` list only collects diagnostics.
- AC-5: no `xfail`/`skip` on an installed provider; an unresolved method is reported in the assertion message.
- If the guard fails for a real provider, STOP and report in the Completion Note — never change a flag or `TOOL_EXECUTION_METHODS` to make it pass without checking the provider's behaviour (spec §7).
- In a worktree, run with `PYTHONPATH=packages/ai-parrot/src` plus the `src` of every client satellite TASK-5379 changed (`ai-parrot-client-hf`, `-jev`, `-google`).

---

## Implementation Blueprint

### Steps (in order)
1. Extend the imports, then append constants and helpers (Edit 1) — *why*: prototyped code; the parse fallback and `inspect.unwrap` are required for the real providers.
2. Append the synthetic fixtures and the guard tests (Edit 2) — *why*: negative/positive fixtures pin the AST rule (AC-5).
3. Append the Claude bridge exposure test (Edit 3) — *why*: backs the `ClaudeAgentClient` allowlist entry.
4. Run the Validation Command and confirm 39 parametrized provider cases pass with no skip.

### `packages/ai-parrot/tests/clients/test_tool_loop_capability.py` (MODIFY — 3 edits)
```python
# Edit 1 — extend the import block (after `import pytest`, verified: created by TASK-5379), then append after KNOWN_FALSE:
import ast
import inspect
import textwrap

from parrot.clients.factory import LLMFactory
from parrot.tools.manager import ToolManager

TOOL_EXECUTION_METHODS: frozenset[str] = frozenset(
    {"_run_tool_call_loop", "_execute_tool", "_handle_multiturn_function_calls", "_run_tool_loop"}
)
# Registered manager tools are exposed through CodexToolBridge / ClaudeAgentToolBridge; the client drives the
# external agent to completion before ask() returns. Each entry is backed by a bridge exposure test.
EXTERNAL_LOOP_CLIENTS: frozenset[str] = frozenset({"OpenAICodexClient", "ClaudeAgentClient"})


def _installed_classes() -> dict[str, type[AbstractClient]]:
    """Enumerate LLMFactory.supported_clients; skip confirmed absent extras, fail other loader errors."""
    out: dict[str, type[AbstractClient]] = {}
    for provider, value in LLMFactory.supported_clients().items():
        try:
            out[provider] = value() if callable(value) and not isinstance(value, type) else value
        except ModuleNotFoundError:  # an optional dependency of the installed satellite is absent
            continue
    return out


def _parse_function(func: object) -> ast.AST | None:
    """Parse one function's own source; None when no source is available."""
    try:
        source = inspect.getsource(inspect.unwrap(func))
    except (OSError, TypeError):
        return None
    for candidate in (textwrap.dedent(source), "class _Wrapper:\n" + source):
        try:
            node = ast.parse(candidate).body[0]
        except SyntaxError:
            continue
        return node.body[0] if isinstance(node, ast.ClassDef) else node
    return None


def _self_method_calls(func: object, unresolved: list[str]) -> set[str]:
    """Executable self.<name>(...) / super().<name>(...) calls in func's body, outside nested definitions."""
    node = _parse_function(func)
    if node is None:
        unresolved.append(getattr(func, "__qualname__", repr(func)))
        return set()
    calls: set[str] = set()

    def visit(parent: ast.AST) -> None:
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                target = child.func.value
                if isinstance(target, ast.Name) and target.id == "self":
                    calls.add(child.func.attr)
                elif isinstance(target, ast.Call) and isinstance(target.func, ast.Name) and target.func.id == "super":
                    calls.add("super()." + child.func.attr)
            visit(child)

    visit(node)
    return calls


def _resolved_ask_calls(cls: type, unresolved: list[str] | None = None) -> frozenset[str]:
    """Self-method call names from reachable ask bodies (MRO via super().ask) and one-hop helpers."""
    sink: list[str] = unresolved if unresolved is not None else []
    calls: set[str] = set()
    for owner in cls.__mro__:
        if "ask" not in vars(owner):
            continue
        own = _self_method_calls(vars(owner)["ask"], sink)
        calls |= own
        if "super().ask" not in own:
            break
    for name in [c for c in calls if not c.startswith("super().")]:
        helper = getattr(cls, name, None)
        if inspect.isfunction(helper) or inspect.ismethod(helper):
            calls |= _self_method_calls(helper, sink)
    return frozenset(calls)
```
```python
# Edit 2 — append: synthetic fixtures (plain classes, never instantiated) and the guard tests


class _CommentOnly:
    async def ask(self, prompt):
        """Mentions self._execute_tool(prompt) only in a docstring."""
        note = "self._run_tool_call_loop()"  # self._execute_tool(prompt)
        return note


class _HelperBase:
    async def ask(self, prompt):
        return await self._drive(prompt)

    async def _drive(self, prompt):
        return await self._run_tool_call_loop(prompt)


class _InheritsLoop(_HelperBase):
    async def ask(self, prompt):
        return await super().ask(prompt)


class _DeadNested:
    async def ask(self, prompt):
        def _never():
            return self._execute_tool(prompt)

        handle = self._execute_tool  # a reference, not a call
        return handle is None


@pytest.mark.parametrize("provider", sorted(_installed_classes()))
def test_flag_matches_resolved_ask(provider: str) -> None:
    """The declared flag equals AST tool-loop evidence, except for the documented agent bridges."""
    cls = _installed_classes()[provider]
    unresolved: list[str] = []
    runs_loop = bool(_resolved_ask_calls(cls, unresolved) & TOOL_EXECUTION_METHODS)
    # FILL IN: assert cls.supports_tool_loop is (runs_loop or cls.__name__ in EXTERNAL_LOOP_CLIENTS), with a message
    #   naming provider, class, runs_loop, the declared flag and `unresolved` — bounded by AC-5


def test_comment_and_string_markers_do_not_count() -> None:
    # FILL IN: assert not (_resolved_ask_calls(_CommentOnly) & TOOL_EXECUTION_METHODS) — bounded by AC-5


def test_executable_marker_counts_through_mro_and_helper() -> None:
    # FILL IN: assert "_run_tool_call_loop" in _resolved_ask_calls(_InheritsLoop) — bounded by AC-5 (super().ask + one-hop _drive)


def test_uncalled_nested_marker_does_not_count() -> None:
    # FILL IN: assert not (_resolved_ask_calls(_DeadNested) & TOOL_EXECUTION_METHODS) — bounded by AC-5
```
```python
# Edit 3 — append: Claude bridge exposure test (Codex counterpart: test_codex_agent.py:129)


def test_claude_bridge_exposes_registered_tools() -> None:
    """A tool registered in ClaudeAgentClient().tool_manager is exposed by the bridge the way ask() builds it."""
    pytest.importorskip("claude_agent_sdk")
    claude_agent = pytest.importorskip("parrot.clients.anthropic.claude_agent")
    from parrot.clients.anthropic.claude_agent_bridge import ClaudeAgentToolBridge

    client = claude_agent.ClaudeAgentClient()
    client.tool_manager = ToolManager(include_search_tool=False)

    async def feat848_sentinel(value: str) -> str:
        return value

    client.tool_manager.register_tool(
        name="feat848_sentinel",
        description="Echo a value (FEAT-848 sentinel).",
        input_schema={"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        function=feat848_sentinel,
    )
    bridge = ClaudeAgentToolBridge(client.tool_manager, tool_timeout=None)
    selected = bridge.select("", claude_agent.ClaudeAgentRunOptions().max_exposed_tools)
    # FILL IN: assert "feat848_sentinel" in [getattr(t, "name", None) for t in selected]; call bridge.build_server(selected);
    #   assert "mcp__parrot__feat848_sentinel" in bridge.exposed_names() — bounded by AC-5 (no SDK query, no network)
```
**Why this shape**: Edit 1 is the prototyped audit — copy it verbatim; `inspect.unwrap` undoes the budget
adapter `__init_subclass__` installs, and the `class _Wrapper:` retry handles methods `dedent` cannot flatten.
The fixtures are plain classes so `__init_subclass__` never wraps them. The blank `select("")` query uses
registration order (no ranking), the same code path `ask()` takes for an empty prompt.

### FILL IN checklist
- [ ] `test_flag_matches_resolved_ask` — identity assert + diagnostic message; bounded by AC-5
- [ ] three synthetic-fixture tests — one assert each; bounded by AC-5
- [ ] `test_claude_bridge_exposes_registered_tools` — selected name, `build_server`, exposed `mcp__parrot__` name; bounded by AC-5

---

## Acceptance Criteria

- [ ] `test_flag_matches_resolved_ask` passes for every installed provider (39 keys on the dev venv) with `EXTERNAL_LOOP_CLIENTS == {"OpenAICodexClient", "ClaudeAgentClient"}` and no `xfail`/`skip` on an installed provider (spec AC-5).
- [ ] Only AST call evidence counts: the comment/string and nested-definition fixtures stay negative; the MRO/helper fixture is positive (spec AC-5).
- [ ] `test_claude_bridge_exposes_registered_tools` passes with `claude_agent_sdk` installed (spec AC-5).
- [ ] `ruff check` passes on the test file.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/clients/test_tool_loop_capability.py -q`

---

## Test Specification

See the three edit blocks above. Expected run on the dev venv: 39 `test_flag_matches_resolved_ask[...]` cases,
3 synthetic-fixture tests, 1 Claude bridge test, plus TASK-5379's tests — all passing, none skipped except a
known-False class whose satellite is absent.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug client-tool-loop-capability --feature-id FEAT-848`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/client-tool-loop-capability.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/client-tool-loop-capability.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `parrot sdd task close TASK-5382 client-tool-loop-capability verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

Seat: gpt-5.6-terra (codex). tool-loop guard tests (test_tool_loop_capability.py). Merge-tier validation green.

**Completed by**: sdd-worker
**Date**: 2026-11-09
**Notes**: tool-loop guard tests (test_tool_loop_capability.py)

**Deviations from spec**: none
