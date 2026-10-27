# TASK-4753: Origin and component extraction for turn materialization (pure)

**Feature**: FEAT-757 — Materialize a chat turn as a linked widget
**Spec**: `sdd/specs/materialize-turn-linked-widget.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. `materialize_widget` (TASK-4754) must decide, **without an LLM and without I/O**, (a) which
`qs_execute_slug` call produced the rows a chat turn showed, and (b) which component (Chart / DataTable / KPICard)
to relink. This task implements both decisions as pure functions plus the shared models and the closed
reason vocabulary, in core (`parrot.outputs.a2ui.linked`) so the tool in ai-parrot-tools only orchestrates.

Spec decisions this task encodes: last COMPLETED `qs_execute_slug` wins; a trailing linked build means
`already_linked`; more than one distinct `(slug, tenant, request)` means `multi_source`; any invocation outside
`NEUTRAL_TOOLS` (Q3, resolved) or no slug call means `none`.

---

## Scope

- Create `packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py` with: the tool-name constants,
  `NEUTRAL_TOOLS`, `SUPPORTED_ROOTS`, the reason constants, `SlugOrigin`, `OriginOutcome`,
  `MaterializeWidgetResult`, `extract_slug_origin()`, `component_from_envelope()`.
- Write unit tests in `packages/ai-parrot/tests/outputs/a2ui/linked/test_materialize.py`.

**NOT in scope**: the tool, any memory lookup, any call to QuerySource or `publish_surface` (TASK-4754); docs
(TASK-4756); exporting the new names from `parrot/outputs/a2ui/linked/__init__.py` (import them by full module
path — do not edit `__init__.py`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py` | CREATE | Models, constants, pure extraction functions |
| `packages/ai-parrot/tests/outputs/a2ui/linked/test_materialize.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, Field                                   # pydantic v2 (project standard)
from parrot.memory.compaction.models import ToolInvocation, ToolStatus  # verified: compaction/models.py:24 (ToolStatus), :46 (ToolInvocation)
from parrot.memory import ConversationTurn                              # tests only; verified: memory/__init__.py:3
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/compaction/models.py
class ToolStatus(str, Enum):          # line 24
    COMPLETED = "completed"           # line 27
    ERROR = "error"                   # line 28

@dataclass
class ToolInvocation:                 # line 46
    tool_name: str
    input: Dict[str, Any]             # canonical (sorted) args AFTER Stage 0 normalization
    output: Optional[str] = None
    status: ToolStatus = ToolStatus.COMPLETED
    error: Optional[str] = None
    elapsed_ms: Optional[int] = None
    output_chars: Optional[int] = None
    omitted: Dict[str, str] = field(default_factory=dict)   # field name -> content_id when offloaded
    wm_key: Optional[str] = None

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py  (READ ONLY — names this module matches on)
#   tool_prefix = "qs" (line 84); execute_slug(slug, placeholders, filter, fields, ordering, grouping, limit,
#   offset, refresh, tenant) (line 253). Generated names (module docstring, lines 3-5): qs_get_dialect_reference,
#   qs_list_slugs, qs_describe_slug, qs_execute_slug, qs_build_linked_surface, qs_build_linked_dashboard,
#   qs_list_components, qs_validate_pipeline, qs_run_multiquery, qs_save_multiquery.
#   _bind_component (line 680): Chart/DataTable get comp["data"] = {"path": f"/{key}/rows"};
#   KPICard with a str `value` gets comp["value"] = {"path": f"/{key}/rows/0/{value}"}; others -> error.

# Other neutral tool names (verified):
#   read_omitted_content  — memory/compaction/recover.py:27; search_tools — tools/manager.py:270
#   list_skill_commands / load_skill / read_skill_asset — skills/tools.py:436 / :473 / :505 (no tool_prefix)
#   search_skills / read_skill / list_skills             — skills/tools.py:118 / :184 / :218 (no tool_prefix)
```
Envelope dump shape (`CreateSurface.model_dump(by_alias=True)`, `outputs/a2ui/models.py:446`): keys `surfaceId`,
`catalogId`, `components` (list of dicts with `id` and `component`), `dataModel`, `metadata`. An envelope may also
arrive wrapped as `{"createSurface": {...}}` (the same unwrap `has_data_sources` does, `linked/__init__.py:63-66`).

### Does NOT Exist
- ~~`parrot.outputs.a2ui.linked.materialize`~~ — this task creates it.
- ~~`ToolInvocation.args` / `ToolInvocation.name`~~ — the fields are `input` and `tool_name`.
- ~~`ToolStatus.SUCCESS` / `ToolStatus.FAILED`~~ — only `COMPLETED` and `ERROR`.
- ~~`ConversationTurn.a2ui_envelope`~~ — the envelope is not on the turn; it is passed in by the caller.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/outputs/a2ui/linked/test_materialize.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/compaction/models.py#ToolInvocation",
    "sym:packages/ai-parrot/src/parrot/memory/compaction/models.py#ToolStatus"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Pure: no network, no `await`, no imports from `parrot_tools` or server code (core one-way import rule).
- Pydantic v2 models; Google-style docstrings; 120-col lines.
- The reason strings are a closed set used verbatim by TASK-4754 and the docs — never rename them.
- **Deviation note (add to the Completion Note):** `REASON_PIN_FAILED = "pin_failed"` extends the spec's §7
  reason list. It is needed because `publish_surface` can fail after the linked build succeeded, and none of the
  spec's reasons describes that.

---

## Implementation Blueprint

### Steps (in order)
1. Create `materialize.py` from the block below — *why*: fixes every public name TASK-4754 imports.
2. Complete the `FILL IN` markers in `extract_slug_origin` and `component_from_envelope` — *why*: these are the
   two judgement calls; their rules are stated next to each marker.
3. Write the tests from the Test Specification, then run the Validation Commands.

### `packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py` (CREATE)
```python
"""Pure helpers that turn a chat turn into a linked-widget origin (FEAT-757).

No I/O and no LLM: the origin is read from the turn's recorded tool invocations, the component from the
envelope the caller already holds.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from parrot.memory.compaction.models import ToolInvocation, ToolStatus

__all__ = [
    "EXECUTE_TOOL", "LINKED_TOOLS", "NEUTRAL_TOOLS", "SUPPORTED_ROOTS", "REQUEST_KEYS",
    "REASON_TURN_NOT_FOUND", "REASON_NO_SLUG_ORIGIN", "REASON_MULTI_SOURCE_TURN", "REASON_UNSUPPORTED_COMPONENT",
    "REASON_NO_ENVELOPE", "REASON_NO_QUERYSOURCE_TOOLKIT", "REASON_BUILD_FAILED", "REASON_NO_PUBLISH_SURFACE",
    "REASON_PIN_FAILED",
    "SlugOrigin", "OriginOutcome", "MaterializeWidgetResult", "extract_slug_origin", "component_from_envelope",
]

EXECUTE_TOOL = "qs_execute_slug"
LINKED_TOOLS: frozenset[str] = frozenset({"qs_build_linked_surface", "qs_build_linked_dashboard"})
#: Read-only tools tolerated between the query and the answer (spec §8 Q3). Anything else invalidates the origin.
NEUTRAL_TOOLS: frozenset[str] = frozenset({
    "qs_list_slugs", "qs_describe_slug", "qs_get_dialect_reference", "qs_list_components", "qs_validate_pipeline",
    "read_omitted_content", "search_tools",
    "list_skill_commands", "load_skill", "read_skill_asset", "search_skills", "read_skill", "list_skills",
})
SUPPORTED_ROOTS: frozenset[str] = frozenset({"Chart", "DataTable", "KPICard"})
#: qs_execute_slug args carried into build_linked_surface's ``request`` (offset/refresh are dropped on purpose).
REQUEST_KEYS: tuple[str, ...] = ("placeholders", "filter", "fields", "ordering", "grouping", "limit")

REASON_TURN_NOT_FOUND = "turn_not_found"
REASON_NO_SLUG_ORIGIN = "no_slug_origin"
REASON_MULTI_SOURCE_TURN = "multi_source_turn"
REASON_UNSUPPORTED_COMPONENT = "unsupported_component"
REASON_NO_ENVELOPE = "no_envelope"
REASON_NO_QUERYSOURCE_TOOLKIT = "no_querysource_toolkit"
REASON_BUILD_FAILED = "build_failed"
REASON_NO_PUBLISH_SURFACE = "no_publish_surface"
REASON_PIN_FAILED = "pin_failed"


class SlugOrigin(BaseModel):
    """The re-runnable data origin of a turn: one query slug plus its request."""

    slug: str
    tenant: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)


class OriginOutcome(BaseModel):
    """Result of :func:`extract_slug_origin`."""

    kind: Literal["slug", "already_linked", "multi_source", "none"]
    origin: SlugOrigin | None = None


class MaterializeWidgetResult(BaseModel):
    """What ``materialize_widget`` returns (spec §2 Data Models)."""

    status: Literal["materialized", "already_linked", "snapshot_only", "not_materializable"]
    reason: str | None = None
    message: str | None = None
    a2ui_envelope: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    surface_id: str | None = None
    pinned: bool = False
    refreshable: bool = False
    origin: SlugOrigin | None = None


def extract_slug_origin(invocations: Sequence[ToolInvocation]) -> OriginOutcome:
    """Decide a turn's data origin from its recorded tool invocations.

    Rules, in order: ignore invocations whose ``status`` is not ``ToolStatus.COMPLETED``; if any remaining
    invocation is outside ``NEUTRAL_TOOLS | LINKED_TOOLS | {EXECUTE_TOOL}`` -> ``none``; if the last relevant
    invocation is in ``LINKED_TOOLS`` -> ``already_linked``; collect ``qs_execute_slug`` origins — zero -> ``none``,
    more than one distinct origin -> ``multi_source``, otherwise ``slug`` with the last one.
    """
    # FILL IN: implement the rules above — bounded by spec §2 Overview step 2 and §7 "Wrong-widget risk".
    # An execute_slug invocation whose input was offloaded ("input" in inv.omitted) or has no str "slug" is
    # unusable: treat the whole turn as "none" (spec §7 "Offloaded inputs"). Origins compare by
    # (slug, tenant, request) — use _origin_from_input below.
    raise NotImplementedError


def _origin_from_input(data: Mapping[str, Any]) -> SlugOrigin:
    """Build a SlugOrigin from a qs_execute_slug ``input`` dict, keeping only non-empty REQUEST_KEYS."""
    request = {key: data[key] for key in REQUEST_KEYS if data.get(key) not in (None, {}, [])}
    return SlugOrigin(slug=str(data["slug"]), tenant=data.get("tenant") or None, request=request)


def component_from_envelope(envelope: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the envelope's root component without its data binding, or None when it cannot be relinked.

    The root is the component whose ``id`` is ``"root"``, else the first component. Returns None when the
    envelope has no components or the root's ``component`` is not in ``SUPPORTED_ROOTS``.
    """
    payload = envelope.get("createSurface", envelope)
    components = payload.get("components") or []
    if not components:
        return None
    root = next((c for c in components if c.get("id") == "root"), components[0])
    if root.get("component") not in SUPPORTED_ROOTS:
        return None
    comp = dict(root)
    # FILL IN: strip the binding so QuerysourceToolkit._bind_component can re-add it — bounded by the
    # _bind_component contract (toolkit.py:680): Chart/DataTable -> drop "data"; KPICard -> "value" must end
    # as the column-name str: a {"path": ".../rows/0/<col>"} binding becomes "<col>", a str stays, anything
    # else (a baked literal number) -> return None (the column is unknowable). Keep every other prop
    # (type, x, y, title, columns, label, ...) unchanged.
    return comp
```
**Why this shape**: every name TASK-4754 imports is fixed here, so the tool task cannot drift. Keeping the
logic pure is what lets AC7 be checked without a database or an event loop. `REQUEST_KEYS` drops `offset` and
`refresh` because a linked widget pages and refreshes on its own.

### FILL IN checklist
- [ ] `materialize.py::extract_slug_origin` — the ordered rules; bounded by spec §2 step 2, §7, AC3
- [ ] `materialize.py::component_from_envelope` — binding strip per component type; bounded by `_bind_component` (toolkit.py:680)

---

## Acceptance Criteria

- [ ] `extract_slug_origin` / `component_from_envelope` behave as in the Test Specification (spec AC3, AC7)
- [ ] No I/O and no imports from `parrot_tools` / `parrot.handlers` in `materialize.py`
- [ ] `ruff check packages/ai-parrot/src/parrot/outputs/a2ui/linked/materialize.py` is clean

## Validation Commands

- `pytest packages/ai-parrot/tests/outputs/a2ui/linked/test_materialize.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/linked/test_materialize.py
from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.outputs.a2ui.linked.materialize import component_from_envelope, extract_slug_origin


def _exec(slug="flex_hours_query_pbi", **extra):
    return ToolInvocation(tool_name="qs_execute_slug", input={"slug": slug, **extra})


def test_extract_origin_last_completed_wins(): ...           # same slug/request twice -> kind "slug"
def test_extract_origin_ignores_errored(): ...               # trailing status=ERROR call is ignored
def test_extract_origin_already_linked(): ...                # trailing qs_build_linked_surface -> "already_linked"
def test_extract_origin_multi_source(): ...                  # two distinct slugs -> "multi_source"
def test_extract_origin_none(): ...                          # no invocations / pandas-only -> "none"
def test_extract_origin_neutral_tools_tolerated(): ...       # qs_describe_slug + load_skill around it -> "slug"
def test_extract_origin_non_neutral_tool_blocks(): ...       # a python_repl call in the turn -> "none"
def test_extract_origin_offloaded_input_is_none(): ...       # omitted={"input": "om_x"} -> "none"
def test_extract_origin_drops_offset_keeps_tenant(): ...     # offset/refresh dropped, tenant kept
def test_component_strips_bindings_and_rows(): ...           # Chart/DataTable lose "data"; KPICard path -> column str
def test_component_kpicard_literal_value_unsupported(): ...  # value=42 -> None
def test_component_unsupported_root(): ...                   # Infographic root -> None
def test_component_wrapped_envelope(): ...                   # {"createSurface": {...}} is unwrapped
```

---

## Agent Instructions

1. **Work in the feature worktree** (`python -m scripts.sdd.ensure_worktree --slug materialize-turn-linked-widget --feature-id FEAT-757`)
2. **Read the spec** for full context.
3. **Check dependencies**: none.
4. **Verify the Codebase Contract** before writing code; update it first if anything moved.
5. **Update status** in `sdd/tasks/index/materialize-turn-linked-widget.json` → `"in-progress"` (set `started_at`), commit only that file.
6. **Implement** from the blueprint, completing every `# FILL IN:`.
7. **Verify** with the Validation Commands (`PYTHONPATH=packages/ai-parrot/src`).
8. **Commit the code**, staging only the files listed above.
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4753 materialize-turn-linked-widget verified`.
10. **Fill in the Completion Note**, then commit the staged SDD state.

---

## Completion Note


- Task: TASK-4753
- Feature: materialize-turn-linked-widget
- Implementation SHA: e115d1d722e95e4d898f10b46262585530e8d2c9
- Closed at (UTC): 2026-10-27T01:54:49+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 201.9s · Tokens: n/a |
