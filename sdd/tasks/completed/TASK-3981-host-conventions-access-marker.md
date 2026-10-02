# TASK-3981: Host conventions — read_tools, routing_meta access, strict marking of host writes, effective_access (M6)

**Feature**: FEAT-622 — Agent Studio — Host Toolkits
**Spec**: `sdd/specs/agentstudio-host-toolkits.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3975, TASK-3976
**Assigned-to**: unassigned
**Wave**: 2 (spec §9) · **Module**: M6 host-conventions

---

## Context

Spec G5 and §2 "Read/write marker": a host toolkit declares `read_tools`; effective access is `"read"` for a
method in `read_tools`, otherwise `"write"` for **host** toolkits (fail-safe) and `None` for built-ins (Q7:
unchanged behaviour). It goes to `routing_meta["access"]` and the catalogue. §2 "Host-write confirmation":
a host write tool is strictly marked — `requires_confirmation=True`, `confirmation_enforced=True`,
`confirm_window_seconds=0`. Enforcement of that marking is TASK-3982 (M8); **no build may resolve host write
tools without M8**, so the two tasks land in the same Wave 2 release.

---

## Scope

- `AbstractToolkit`: add `read_tools: ClassVar[frozenset[str]] = frozenset()`.
- `AbstractTool`: add `access: ClassVar[Optional[str]] = None` (values `ToolAccess` or `None`) (standalone host tools declare it; a host
  standalone tool with `access=None` is treated as `"write"`).
- `_create_tool_from_method`: compute effective access; write `routing_meta["access"]`; for a host toolkit's
  write tool set `requires_confirmation`, `confirmation_enforced`, `confirm_window_seconds=0`.
- "Is host" = the toolkit class is the resolved class of a resolver entry with `source="host"` (helper
  `_is_host_class(cls)` in `toolkit.py` using `get_toolkit_resolver()` lazily; never mutate the class).
- Expose `effective_access(cls, method_name)` (module-level in `toolkit.py`) so TASK-3984 can publish `access` in
  the catalogue without instantiating toolkits.
- Extend the core probe (`_host_probe.py`): `read_tools = frozenset({"whoami"})`.
- Test `test_host_write_tool_strict_marking_and_access_meta`.

**NOT in scope**: the approval token and its enforcement (TASK-3982); prefix rules (done in the resolver,
TASK-3975); the catalogue `access` field (TASK-3984); the guide page (TASK-3993); return-type / row-cap
enforcement (Q8: documented only).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/toolkit.py` | MODIFY | read_tools ClassVar; effective access + strict marking in _create_tool_from_method |
| `packages/ai-parrot/src/parrot/tools/abstract.py` | MODIFY | `access` ClassVar on AbstractTool |
| `packages/ai-parrot/tests/tools/_host_probe.py` | MODIFY | ProbeToolkit.read_tools = {whoami} |
| `packages/ai-parrot/tests/tools/test_host_conventions.py` | CREATE | test_host_write_tool_strict_marking_and_access_meta |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (ai-parrot `dev` @ `32b1a45d4`). The implementing agent MUST use these exact imports, class names,
> and method signatures. **DO NOT** invent, guess, or assume any import, attribute, or method not
> listed here. If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.tools.scope import ToolAccess  # TASK-3976
from parrot.tools.resolver import get_toolkit_resolver  # TASK-3975 (import lazily inside the helper)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
    confirming_tools: frozenset = frozenset()  # :272
    tenant_bound: ClassVar[bool] = False       # added by TASK-3976 after :327
    def _create_tool_from_method(self, name: str, bound_method: callable) -> ToolkitTool:  # :647
        method_name = getattr(bound_method, "__name__", name)  # :695
        if method_name in self.confirming_tools:  # :696 ← anchor (occurrences: 1)
            ...tool.routing_meta["requires_confirmation"] = True  # :697-699
        return tool  # :701
# packages/ai-parrot/src/parrot/tools/abstract.py
    routing_meta: Dict = None  # :300; per-instance dict set in __init__ :382
    tenant_bound: ClassVar[bool] = False  # added by TASK-3976 after :342
# packages/ai-parrot/src/parrot/mcp/agent_tools.py:47 read_only_hint — mirrored semantics
```

### Does NOT Exist
- ~~a read/write marker on parrot tools~~ — none today; only MCP's `read_only_hint` (`mcp/agent_tools.py:47`).
- ~~`routing_meta["confirmation_enforced"]` / `["confirm_window_seconds"]` consumers~~ — TASK-3982 adds the consumer.
- ~~an `is_host` attribute stamped on classes by the resolver~~ — never mutate classes or registries; compute from entries.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/tools/toolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/tools/abstract.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/_host_probe.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/tools/test_host_conventions.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit._create_tool_from_method",
    "sym:packages/ai-parrot/src/parrot/tools/abstract.py#AbstractTool"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
- Keep FEAT-235 marking intact for built-ins (`confirming_tools` still sets only `requires_confirmation`).
- `_is_host_class` must not import the resolver at module top (`resolver.py` imports `discovery.py`, which
  imports `toolkit.py`): import inside the function.

### Spec ambiguity (record in Completion Note)
- The spec does not say how a toolkit learns it is a *host* toolkit. This task derives it from resolver
  entries (`source="host"`) — no new public resolver API.

### Cross-feature ordering
- Core files only: no per-file wait.
- Release: **lands together with TASK-3982** — no build that resolves host write tools may ship without M8
  (X16 "TOOLKITS Wave 2 lands M6 together with M8").

### Key Constraints
- Async throughout; no blocking I/O in async paths; `self.logger` (or the module `logger`) — never `print`.
- Pydantic models for every new data structure; Google-style docstrings and strict type hints.
- Core (`packages/ai-parrot`) never imports `ai-parrot-server` (spec §7).
- ARCHITECTURE R4: no new/modified function above cyclomatic complexity 10 or 60 lines; run `flake8` on changed files.
- **Spec §4 test rule (applies to every test in this task):** build requests with `aiohttp.test_utils.make_mocked_request` and install the session the way `navigator_session` does (`request[SESSION_OBJECT] = ...`), or use `aiohttp_client` over a real app. Never a `Mock` / `SimpleNamespace` with hand-set `.session` / `.app`. Side-effect **counters** prove refusals, not mocks. Mutation-check every new assertion (revert the code, see RED) and record the evidence in the Completion Note.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. Never change a signature,
> class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the two ClassVars — *why*: G5 declaration surface.
2. Compute effective access and strict marking after the FEAT-235 block — *why*: host writes default to `"write"` (fail-safe).
3. Expose `effective_access(cls, method_name)` for the catalogue (TASK-3984) — *why*: one source of truth.
4. Extend the probe and write the test; mutation: default host access to `None` ⇒ RED.

### `packages/ai-parrot/src/parrot/tools/toolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'tenant_bound: ClassVar\[bool\] = False' toolkit.py — line added by TASK-3976)
# AFTER — insert below `    tenant_bound: ClassVar[bool] = False`
    #: FEAT-622 — method names (pre-prefix) that are read-only. Host toolkit methods not listed are
    #: treated as writes and require an approval token (strict confirmation).
    read_tools: ClassVar[frozenset[str]] = frozenset()
```
```python
# FILL IN: disambiguate — insert after the FEAT-235 block, i.e. below these verified lines (toolkit.py:696-699):
#         if method_name in self.confirming_tools:
#             if tool.routing_meta is None:
#                 tool.routing_meta = {}
#             tool.routing_meta["requires_confirmation"] = True
        access = effective_access(type(self), method_name)
        if tool.routing_meta is None:
            tool.routing_meta = {}
        tool.routing_meta["access"] = access
        if access == "write" and _is_host_class(type(self)):
            tool.routing_meta["requires_confirmation"] = True
            tool.routing_meta["confirmation_enforced"] = True
            tool.routing_meta["confirm_window_seconds"] = 0
# FILL IN: module-level effective_access(cls, method_name) -> ToolAccess | None ("read" if in cls.read_tools;
#   "write" if _is_host_class(cls); else None) — public: TASK-3984 imports it for the catalogue
# FILL IN: module-level _is_host_class(cls) — lazy get_toolkit_resolver(); True iff some entry with source == "host"
#   resolves to cls
```

### `packages/ai-parrot/src/parrot/tools/abstract.py` (MODIFY)
```python
# AFTER — insert below `    tenant_bound: ClassVar[bool] = False` (added by TASK-3976)
    # FEAT-622: "read" | "write" | None (unknown). Host standalone tools with None are treated as "write".
    access: ClassVar[Optional[str]] = None
```

### FILL IN checklist
- [ ] `toolkit.py::effective_access`, `_is_host_class` — bounded by spec §2 "Read/write marker" and Q7.

---

## Acceptance Criteria

- [ ] Host write tool: `requires_confirmation`, `confirmation_enforced`, `confirm_window_seconds == 0`, `access == "write"`.
- [ ] Host read tool (`whoami`): `access == "read"`, not strictly marked.
- [ ] Built-in toolkit tools: `access is None`; FEAT-235 `confirming_tools` behaviour unchanged (`pytest packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py -q`).
- [ ] `effective_access(cls, method_name)` is importable from `parrot.tools.toolkit`.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/tools/test_host_conventions.py -q`
- `pytest packages/ai-parrot/tests/tools/test_tooldefinition_enforcement.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/tools/test_host_conventions.py
from ._host_probe import host_plugins  # noqa: F401


def test_host_write_tool_strict_marking_and_access_meta(host_plugins):
    """write → requires_confirmation, confirmation_enforced, window 0, access="write"; read → "read"; built-in → None."""
    # FILL IN: instantiate the probe class via importlib (not the resolver: rule 5 hides tenant-bound host entries),
    #   get_tools(); assert routing_meta per tool; a built-in toolkit's tools have access None
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-host-toolkits --feature-id FEAT-622`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/agentstudio-host-toolkits.json`, and every "Cross-feature ordering"
   line in Implementation Notes must be satisfied on `origin/dev`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/agentstudio-host-toolkits.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-id> agentstudio-host-toolkits verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below (including mutation-check evidence), then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (Sonnet 5.5)
**Date**: 2026-10-01
**Notes**: Added `read_tools` (AbstractToolkit), `access` (AbstractTool), module-level `_is_host_class` / `effective_access`
in toolkit.py, strict marking in `_create_tool_from_method`. "Is host" derived from resolver entries (source="host") by
importing the entry's dotted path and comparing identity; no new resolver API. Landing with TASK-3982 is a release
constraint: TASK-3982 not implemented here (blocked, see worker summary).
**Mutation evidence**: `effective_access` host→None ⇒ test_host_write_tool_strict_marking_and_access_meta RED;
strict-marking block disabled (`if False`) ⇒ same test RED. Restored; 2 passed.

**Deviations from spec**: none
