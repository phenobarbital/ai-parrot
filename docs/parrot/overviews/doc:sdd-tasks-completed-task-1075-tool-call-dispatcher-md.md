---
type: Wiki Overview
title: 'TASK-1075: Implement ToolCallDispatcher with Jinja2 templating and per-user
  credential plumbing'
id: doc:sdd-tasks-completed-task-1075-tool-call-dispatcher-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 New Public Interfaces, §3 Module 4, §6 Codebase Contract. `ToolCallDispatcher`
  is the bridge between graph results and real tool invocation. It renders `ToolCallSpec.parameters`
  via Jinja2 with safety filters, resolves the tool via `ToolManager.get_tool`, and
  forwards `_p
relates_to:
- concept: mod:parrot.auth.exceptions
  rel: mentions
- concept: mod:parrot.knowledge.ontology.schema
  rel: mentions
- concept: mod:parrot.knowledge.ontology.tool_dispatcher
  rel: mentions
- concept: mod:parrot.tools
  rel: mentions
- concept: mod:parrot.tools.manager
  rel: mentions
---

# TASK-1075: Implement ToolCallDispatcher with Jinja2 templating and per-user credential plumbing

**Feature**: FEAT-158 — Ontology Entity Extraction & Tool-Call Dispatch
**Spec**: `sdd/specs/ontology-entity-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1071
**Assigned-to**: unassigned

---

## Context

Spec §2 New Public Interfaces, §3 Module 4, §6 Codebase Contract. `ToolCallDispatcher` is the bridge between graph results and real tool invocation. It renders `ToolCallSpec.parameters` via Jinja2 with safety filters, resolves the tool via `ToolManager.get_tool`, and forwards `_permission_context` so the toolkit's own `_pre_execute` resolves user-scoped OAuth.

**Critical design refinement vs. brainstorm**: the dispatcher does NOT call `CredentialResolver.resolve` directly. Toolkits already own their resolver (e.g., `JiraToolkit._pre_execute` at `jiratoolkit.py:866-902`). The dispatcher's only credential responsibility is forwarding `_permission_context`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/knowledge/ontology/tool_dispatcher.py` with `class ToolCallDispatcher`.
- Async method `dispatch(spec, graph_result, user_context, extras=None) -> dict[str, Any]` returning `{spec.result_binding: tool_output}`.
- **Empty-team gate** runs BEFORE rendering: dispatch on `spec.empty_team_behavior`:
  - `short_circuit`: return `{spec.result_binding: {"empty": True, "items": []}}` without invoking the tool.
  - `call_anyway`: proceed.
  - `fail`: raise `ValueError("empty graph result, empty_team_behavior=fail")`.
- **Jinja2 environment** (single instance per dispatcher):
  - `StrictUndefined` so missing bindings raise instead of producing `"None"`.
  - `autoescape=False` — outputs are non-HTML query strings; safety is per-filter.
  - Register custom filters: `jql_quote`, `jira_accounts`, `join_ids`, `map_attr`, `json`. See "Pattern to Follow" below.
- **Render `parameters`** with namespaces:
  - `graph`: the `graph_result` list. Also expose `graph.team` as an alias for `graph` (semantic shortcut used in YAML examples).
  - `ctx`: `user_context` plus `ctx.original_query`.
  - `extras`: caller-supplied extras (or `{}`).
- **Tool invocation**:
  - `tool = await tool_manager.get_tool(f"{spec.toolkit}.{spec.method}")`.
  - If `tool is None`, raise `ValueError(f"tool {toolkit}.{method} not registered")`.
  - Build a `PermissionContext` from `user_context`. Pass `_permission_context=perm_ctx` via the tool's `.execute(**rendered, _permission_context=perm_ctx)` call.
  - Surface `AuthorizationRequired` unchanged — the Mixin (TASK-1076) translates it.
- **Render-error translation**: catch `jinja2.exceptions.UndefinedError` and re-raise as a domain exception `RenderError(template_field, message)` for the Mixin to translate.

**NOT in scope**:
- Calling the resolver directly (toolkits handle that).
- Translating `AuthorizationRequired` to `ContextEnvelope` — that is the Mixin's job (TASK-1076).
- The `PermissionContext` class location — see Open Question §8 in the spec; identify the existing class via grep and use it. If genuinely absent, wrap `user_context` in `types.SimpleNamespace` with `user_id` and `channel` attributes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/tool_dispatcher.py` | CREATE | `ToolCallDispatcher` + custom Jinja2 filters + `RenderError`. |
| `packages/ai-parrot/tests/knowledge/test_tool_dispatcher.py` | CREATE | Unit tests, including adversarial JQL inputs. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.knowledge.ontology.schema import ToolCallSpec        # NEW from TASK-1071
from parrot.tools.manager import ToolManager                     # tools/manager.py:203
from parrot.auth.exceptions import AuthorizationRequired         # auth/exceptions.py:12
# PermissionContext: grep for the existing class before importing.
# As of spec drafting, it is referenced by JiraToolkit._pre_execute at
# jiratoolkit.py:891-892 (attributes: user_id, channel).
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/manager.py:203
class ToolManager:
    async def get_tool(self, tool_name: str) -> Optional[Any]: ...    # lines 822-832
    # Returns the registered tool object or None. tool.execute(**kwargs) is the call.

# packages/ai-parrot/src/parrot/auth/exceptions.py:12
class AuthorizationRequired(Exception):
    def __init__(
        self, tool_name: str, message: str,
        auth_url: Optional[str] = None,
        provider: str = "unknown",
        scopes: Optional[List[str]] = None,
    ) -> None: ...

# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:866
# (Read this to understand how _pre_execute consumes _permission_context.)
class JiraToolkit:
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        # Reads kwargs.get("_permission_context")               # line 878
        # Reads perm_ctx.user_id, perm_ctx.channel              # lines 891-892
        # Calls self.credential_resolver.resolve(channel, user_id)  # line 902
        # Raises AuthorizationRequired with auth_url on miss
```

### Does NOT Exist
- ~~A `parrot.tools.dispatcher` module~~ — this task creates a new one specific to the ontology package, not a global dispatcher.
- ~~`ToolManager.invoke(tool_name, ...)`~~ — `ToolManager.get_tool` returns a tool object; you call `.execute(**kwargs)` on it.
- ~~`CredentialResolver` consumed by the dispatcher~~ — the dispatcher does NOT touch `CredentialResolver`. Toolkits own theirs.

---

## Implementation Notes

### Pattern to Follow

Filter implementations (all defense-in-depth escapers):

```python
def jql_quote(value: str) -> str:
    """Escape a single value for safe inclusion as a JQL string literal.
    Wraps in double quotes and escapes embedded double quotes + backslashes."""
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'

def jira_accounts(team: list[dict]) -> str:
    """Render a comma-separated list of accountIds for a JQL `assignee in (...)`
    clause. Validates each element looks like an account id."""
    ids = []
    for member in team:
        acc = member.get("jira_account_id")
        if not acc or not isinstance(acc, str):
            continue
        if not re.fullmatch(r"[A-Za-z0-9:_\-]+", acc):
            raise ValueError(f"invalid jira accountId shape: {acc!r}")
        ids.append(acc)
    return ", ".join(jql_quote(a) for a in ids)

def join_ids(items: list[dict], key: str = "_id", sep: str = ",") -> str:
    return sep.join(str(item[key]) for item in items if key in item)

def map_attr(items: list[dict], key: str) -> list[Any]:
    return [item.get(key) for item in items]
```

Dispatcher skeleton:

```python
class RenderError(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message


class ToolCallDispatcher:
    def __init__(self, tool_manager: ToolManager) -> None:
        self._tool_manager = tool_manager
        self.logger = logging.getLogger(__name__)
        self._env = Environment(
            undefined=StrictUndefined,
            autoescape=False,
            keep_trailing_newline=False,
        )
        self._env.filters["jql_quote"] = jql_quote
        self._env.filters["jira_accounts"] = jira_accounts
        self._env.filters["join_ids"] = join_ids
        self._env.filters["map_attr"] = map_attr
        self._env.filters["json"] = lambda v: json.dumps(v)

    async def dispatch(
        self, spec: ToolCallSpec,
        graph_result: list[dict[str, Any]],
        user_context: dict[str, Any],
        extras: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # 1. Empty-team gate
        if not graph_result:
            if spec.empty_team_behavior == "short_circuit":
                return {spec.result_binding: {"empty": True, "items": []}}
            if spec.empty_team_behavior == "fail":
                raise ValueError("empty graph result, empty_team_behavior=fail")
            # fall through for "call_anyway"

        # 2. Render parameters
        ns = {
            "graph": _GraphNamespace(graph_result),
            "ctx": {**user_context, "original_query": user_context.get("original_query")},
            "extras": extras or {},
        }
        rendered: dict[str, Any] = {}
        for field, template_value in spec.parameters.items():
            try:
                rendered[field] = self._render(template_value, ns)
            except UndefinedError as exc:
                raise RenderError(field=field, message=str(exc)) from exc

        # 3. Resolve tool
        tool = await self._tool_manager.get_tool(f"{spec.toolkit}.{spec.method}")
        if tool is None:
            raise ValueError(f"tool {spec.toolkit}.{spec.method} not registered")

        # 4. Build PermissionContext and invoke (AuthorizationRequired propagates)
        perm_ctx = _build_permission_context(user_context)
        result = await tool.execute(**rendered, _permission_context=perm_ctx)
        return {spec.result_binding: result}
```

### Key Constraints

- `autoescape=False` is INTENTIONAL — never enable it; safety lives in per-filter escapers.
- Strings, lists, and dicts in `spec.parameters` must all be rendered: scalars via single `env.from_string(s).render(**ns)`; lists/dicts recursively. Non-string scalars (`int`, `bool`) pass through unchanged.
- The `_GraphNamespace` helper exposes the result list as `graph.rows` AND `graph.team` (alias). Both point to the same list.
- All async logging via `self.logger.info(...)`; no `print`.
- The PermissionContext class location is an unresolved spec question (§8) — start by grepping `class PermissionContext` across `packages/ai-parrot/`; reuse the existing one. If none is found, use a `SimpleNamespace(user_id=..., channel=...)` adapter and document in the module docstring.

### References in Codebase

- `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py:866-915` — example of `_pre_execute` consuming `_permission_context`.
- `packages/ai-parrot/src/parrot/auth/exceptions.py:12` — `AuthorizationRequired` shape.
- `packages/ai-parrot/src/parrot/tools/manager.py:822-832` — `get_tool` usage.

---

## Acceptance Criteria

- [ ] `test_dispatcher_renders_basic` passes.
- [ ] `test_dispatcher_strict_undefined_raises` passes — missing binding triggers `RenderError`.
- [ ] `test_dispatcher_jql_quote_escapes_quotes` passes — input `Jesús" OR project="OTHER` is safely escaped.
- [ ] `test_dispatcher_jira_accounts_validates_shape` passes — malformed account ID raises before tool call.
- [ ] `test_dispatcher_empty_team_short_circuit` passes — no tool call; result has `empty=True`.
- [ ] `test_dispatcher_forwards_permission_context` passes — assert via spy that `tool.execute` was called with `_permission_context` whose `.user_id` matches `user_context["user_id"]`.
- [ ] `test_dispatcher_propagates_authorization_required` passes — when the spied toolkit raises `AuthorizationRequired`, the dispatcher re-raises unchanged (does NOT swallow).
- [ ] All unit tests pass: `pytest packages/ai-parrot/tests/knowledge/test_tool_dispatcher.py -v`.

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/test_tool_dispatcher.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from parrot.knowledge.ontology.tool_dispatcher import ToolCallDispatcher, RenderError
from parrot.knowledge.ontology.schema import ToolCallSpec
from parrot.auth.exceptions import AuthorizationRequired


@pytest.fixture
def tool():
    t = MagicMock()
    t.execute = AsyncMock(return_value={"issues": [{"key": "T-1"}]})
    return t


@pytest.fixture
def tool_manager(tool):
    tm = MagicMock()
    tm.get_tool = AsyncMock(return_value=tool)
    return tm


@pytest.fixture
def dispatcher(tool_manager):
    return ToolCallDispatcher(tool_manager=tool_manager)


def _spec(**overrides) -> ToolCallSpec:
    base = dict(
        toolkit="JiraToolkit", method="jira_search_issues",
        parameters={"jql": "assignee in ({{ graph.team | jira_accounts }})"},
        result_binding="issues",
        empty_team_behavior="short_circuit",
    )
    base.update(overrides)
    return ToolCallSpec(**base)


class TestDispatcher:
    async def test_renders_basic_jql(self, dispatcher, tool):
        spec = _spec()
        graph = [{"jira_account_id": "557058:abc"}, {"jira_account_id": "557058:def"}]
        out = await dispatcher.dispatch(spec, graph,
                                        user_context={"user_id": "u1", "channel": "telegram"})
        tool.execute.assert_awaited_once()
        kwargs = tool.execute.await_args.kwargs
        assert '"557058:abc"' in kwargs["jql"]
        assert '"557058:def"' in kwargs["jql"]

    async def test_strict_undefined_raises_render_error(self, dispatcher):
        spec = _spec(parameters={"jql": "assignee = {{ ctx.unknown_var }}"})
        with pytest.raises(RenderError):
            await dispatcher.dispatch(spec, [{"a": 1}], user_context={"user_id": "u1"})

    async def test_jql_quote_escapes_adversarial_input(self, dispatcher, tool):
        spec = _spec(parameters={"jql": 'assignee = {{ ctx.name | jql_quote }}'})
        adversarial = 'Jesús" OR project="OTHER'
        await dispatcher.dispatch(spec, [{"x": 1}],
                                  user_context={"user_id": "u1", "name": adversarial})
        jql = tool.execute.await_args.kwargs["jql"]
        # The opening of the OTHER literal must be neutralized.
        assert '" OR project="OTHER' not in jql
        assert '\\"' in jql or '\\\\"' in jql

    async def test_jira_accounts_rejects_bad_shape(self, dispatcher):
        spec = _spec()
        bad_graph = [{"jira_account_id": "id; DROP TABLE users--"}]
        with pytest.raises(ValueError, match="invalid jira accountId"):
            await dispatcher.dispatch(spec, bad_graph, user_context={"user_id": "u1"})

    async def test_empty_team_short_circuit(self, dispatcher, tool):
        spec = _spec(empty_team_behavior="short_circuit")
        out = await dispatcher.dispatch(spec, [], user_context={"user_id": "u1"})
        tool.execute.assert_not_awaited()
        assert out["issues"]["empty"] is True

    async def test_forwards_permission_context(self, dispatcher, tool):
        spec = _spec(parameters={"jql": "project = TROC"})
        await dispatcher.dispatch(
            spec, [{"x": 1}],
            user_context={"user_id": "alice@corp", "channel": "telegram"},
        )
        kwargs = tool.execute.await_args.kwargs
        assert "_permission_context" in kwargs
        assert kwargs["_permission_context"].user_id == "alice@corp"
        assert kwargs["_permission_context"].channel == "telegram"

    async def test_propagates_authorization_required(self, dispatcher, tool):
        tool.execute.side_effect = AuthorizationRequired(
            tool_name="jira_search_issues",
            message="please reauth",
            auth_url="https://auth/url",
            provider="jira",
            scopes=["read:jira-work"],
        )
        spec = _spec(parameters={"jql": "project = TROC"})
        with pytest.raises(AuthorizationRequired) as exc:
            await dispatcher.dispatch(spec, [{"x": 1}],
                                      user_context={"user_id": "u1", "channel": "telegram"})
        assert exc.value.auth_url == "https://auth/url"
```

---

## Agent Instructions

1. Read the spec at the path above, especially §6 Codebase Contract and §7 Implementation Notes.
2. **Critical pre-implementation step**: grep `class PermissionContext` across `packages/ai-parrot/` to identify the existing class. Use it. Document the choice (existing import OR `SimpleNamespace` adapter) in the module docstring.
3. Re-read `jiratoolkit.py:866-915` to confirm the `_permission_context` kwarg convention is still in force.
4. Implement following the pattern and constraints.
5. Verify all acceptance criteria.
6. Move this file to `sdd/tasks/completed/`.
7. Update the per-spec index → `"done"`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session>
**Date**: YYYY-MM-DD
**Notes**: ...
**Deviations from spec**: none | describe if any
