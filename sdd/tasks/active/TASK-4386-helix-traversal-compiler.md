# TASK-4386: HelixDB traversal compiler (`"helix"` dialect) and read-only op-tree loader

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4374, TASK-4385
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8b (Q1 option a, G10, AC25). TASK-4385 created the backend-neutral `TraversalSpec` and the
compiler registry with the built-in `"aql"` compiler. This task adds the `"helix"` compiler —
`compile_helix_traversal(spec) -> CompiledTraversal` whose `text` is a **DSL op-tree JSON document** — and
registers it on `import parrot.knowledge.helix`. It also owns the *consumer side* of that JSON format:
a strict, read-only parser (`parse_helix_op_tree`) and the lowering to a `helixdb` read traversal
(`build_helix_traversal`). `HelixOntologyGraphStore.execute_pattern` / `execute_query` (TASK-4388) run
**every** helix template — materialised or hand-written in a tenant overlay — through that parser, so the
allowlist here is the only thing standing between tenant-authored JSON and a write on the tenant database.

**Security relevance**: requires adversarial `/sdd-codereview` (see Agent Instructions).

---

## Scope

- Create `helix/traversal.py`:
  - `HELIX_READ_OPS` (frozenset of allowed op names) and `HELIX_PREDICATE_OPS`.
  - Pydantic op-tree models (`HelixPredicate`, `HelixStep`, `HelixOpTree`), `extra="forbid"`, bounded sizes.
  - `compile_helix_traversal(spec: TraversalSpec) -> CompiledTraversal` (pure — no `helixdb` import).
  - `parse_helix_op_tree(text: str) -> HelixOpTree` (rejects unknown ops / write ops / unbound params).
  - `build_helix_traversal(tree, params, collection_binds)` (lazy `helixdb` import; the only SDK-touching function).
- Modify `helix/__init__.py` (created by TASK-4374) to `register_traversal_compiler("helix", compile_helix_traversal)` on import.
- Tests `tests/knowledge/helix/test_traversal_helix.py`.

**NOT in scope**: executing traversals against a database (TASK-4388); a `"helix"` query **validator**
(`register_query_validator` — FEAT-670 registers none, LLM-dynamic stays fail-closed); the ontology backend
registration row (TASK-4392); live parity (TASK-4397).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/helix/traversal.py` | CREATE | helix compiler, op-tree models, read-only parser, lowering |
| `packages/ai-parrot/src/parrot/knowledge/helix/__init__.py` | MODIFY | register the `"helix"` compiler on import |
| `packages/ai-parrot/tests/knowledge/helix/test_traversal_helix.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# created by TASK-4385 (verify on pickup: grep -n '^def \|^class ' packages/ai-parrot/src/parrot/knowledge/ontology/traversal_spec.py)
from parrot.knowledge.ontology.traversal_spec import (
    CompiledTraversal, Condition, HopSpec, ParamRef, TraversalSpec, TraversalSpecUnsupported,
    compile_traversal_spec, register_traversal_compiler, traversal_compiler_dialects,
)
from parrot.knowledge.ontology.exceptions import OntologyError   # verified: ontology/exceptions.py:4
# external, lazily inside build_helix_traversal only — spec §6 "HelixDB SDK surface" (helix-db 0.3.4 wheel):
#   from helixdb import g, Predicate, read_batch, define_params   (dsl.py: g :3054, Predicate :770, read_batch :3410)
#   helixdb is NOT installed in the shared .venv today (verified: `python -c "import helixdb"` → ModuleNotFoundError);
#   TASK-4373 adds the extra + dev group. Verify every DSL method name against the installed wheel before use.
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/helix/__init__.py — CREATED BY TASK-4374 (exports only, no registrations).
#   Verify the file exists and read it before editing; anchor on its last import line.
# ontology/traversal_spec.py (TASK-4385): compile_aql registered as "aql" at import; TraversalSpec.param_names() -> tuple[str, ...]
# ontology/schema.py TraversalPattern._materialise_templates (TASK-4385): compiles every traversal_compiler_dialects()
#   entry missing from query_templates; a TraversalSpecUnsupported from a compiler skips that dialect (logged).
# helixdb DSL op names available per spec §6: n, n_where, n_with_label, out, in_, both, out_e, in_e, where, limit, skip,
#   order_by, dedup, count, value_map, project, repeat, union, shortest_path, group_count — and WRITE ops add_n, add_e,
#   set_property, remove_property, drop, drop_edge, drop_edge_by_id, create_index_if_not_exists, drop_index,
#   create_text_index_nodes, create_vector_index_nodes (must never be reachable from a template).
```

### Does NOT Exist
- ~~`parrot.knowledge.helix.traversal`~~ — created here.
- ~~`register_query_validator("helix", …)`~~ — must NOT be added (spec M8, AC7).
- ~~an edge→vertex DSL op (`to_n`, `out_n`, `in_v`)~~ — not in the spec's verified op list; `edge_where` is therefore
  unsupported unless you find one in the installed wheel (see FILL IN).
- ~~`helixdb.Predicate.in_` / `is_in`~~ — unverified; check the wheel before mapping `in` / `not_in`.
- ~~raw HelixQL / `.hx` queries~~ — legacy, not used (spec §6 Does NOT Exist).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/traversal.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/helix/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/helix/test_traversal_helix.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py#OntologyError"
  ]
}
```
(`traversal_spec.py` and `helix/__init__.py` symbols are created by TASK-4385 / TASK-4374 and are not on dev yet.)

---

## Implementation Notes

### The op-tree JSON format (decided here — TASK-4388 consumes it)
```json
{"version": 1,
 "define_params": ["user_id"],
 "collections": ["member_of_team"],
 "steps": [
   {"op": "n_where", "pred": {"op": "in", "field": "_id", "value": {"$param": "user_id"}}},
   {"op": "out", "label": {"$collection": "member_of_team"}},
   {"op": "in_", "label": {"$collection": "member_of_team"}},
   {"op": "where", "pred": {"op": "not_in", "field": "_id", "value": {"$param": "user_id"}}},
   {"op": "dedup"},
   {"op": "value_map"}
 ]}
```
- Start: ids → `n_where` on `_id` (`in` with the list-valued param; a single id is wrapped to a list at bind time);
  scan → `n_with_label` + one `where` per `match` condition.
- Hop with depth range `min..max` → `{"op": "union", "branches": [[], [out], [out, out], ...]}` for k in
  `min..max` (k = 0 is the empty branch); a fixed `1..1` hop is a single step. `where` conditions follow the hop.
- `exclude_start` → `where not_in _id $start` (ids start) — for a scan start raise `TraversalSpecUnsupported`
  unless you implement it soundly (the scan start set is not a param).
- Final `where`, then `dedup` (when `returns.distinct`), `order_by`, `limit`, then `value_map` (vertex),
  `value_map` with `fields` (fields), `value_map` `["_id"]` (ids) or `count`.
- `_id` / `_key` are ordinary node properties on HelixDB: TASK-4387 stores every ontology document with
  `_key` and `_id = f"{collection}/{key}"` properties, and every edge with `_from` / `_to`.

### Security constraints (non-negotiable)
- `HelixStep.op` is a `Literal` over the read-only allowlist; `parse_helix_op_tree` uses `model_validate_json`
  with `extra="forbid"` everywhere, so a write op (`add_n`, `drop`, `set_property`, …) or any unknown key fails
  **before** any SDK call. Bound the tree: ≤ 64 steps per list, union ≤ 11 branches, nesting depth ≤ 3,
  `limit` ≤ 800.
- Every `{"$param": n}` must be listed in `define_params`, and every `define_params` entry must be referenced;
  every `{"$collection": c}` in `collections`; names match `^[A-Za-z_][A-Za-z0-9_]*$`.
- `build_helix_traversal` binds values as Python objects passed to DSL methods (never string-built), resolves
  labels only through `collection_binds["@<name>"]` (intent.py:267 key format) with `_ident`-checked values, raises
  `ValueError` on a missing param or bind, and invokes DSL methods only via an explicit
  `{op_name: callable}` dispatch dict — **never** `getattr(traversal, step.op)` on arbitrary names.
- It returns a read-only object (a `read_batch()`-built batch or a traversal to be wrapped in one by TASK-4388);
  it must never build a `write_batch()`.

### Drift vs spec
- Spec says the text is "a DSL op-tree JSON document" and the test row says "`define_params` names equal
  `CompiledTraversal.params`": realised as the JSON key `define_params` above; the store maps it to
  `helixdb.define_params` (or binds directly) inside `build_helix_traversal`.
- `edge_where` and scan-start `exclude_start` may be inexpressible with the verified DSL ops; the compiler raises
  `TraversalSpecUnsupported`, which TASK-4385's validator turns into "no helix template" (fail closed) — the
  fixture ontology does not use either, so AC25 parity is unaffected.

---

## Implementation Blueprint

### Steps (in order)
1. Confirm TASK-4374's `helix/__init__.py` and TASK-4385's `traversal_spec.py` exist; install-check `helixdb`.
2. Write the op-tree models + `parse_helix_op_tree` — *why*: the security boundary is the parser, write it first.
3. Write `compile_helix_traversal` (pure) and make its output round-trip through the parser.
4. Write `build_helix_traversal` against the installed wheel's real method names.
5. Register in `helix/__init__.py`; write tests.

### `packages/ai-parrot/src/parrot/knowledge/helix/traversal.py` (CREATE)
```python
"""HelixDB compiler for backend-neutral traversal specs + read-only op-tree loader (FEAT-670 M8b)."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parrot.knowledge.ontology.traversal_spec import (
    CompiledTraversal, Condition, ParamRef, TraversalSpec, TraversalSpecUnsupported,
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ReadOp = Literal["n_where", "n_with_label", "out", "in_", "both", "where", "union", "dedup",
                 "order_by", "limit", "value_map", "count"]
HELIX_READ_OPS: frozenset[str] = frozenset(ReadOp.__args__)
PredOp = Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "is_null", "not_null"]
HELIX_PREDICATE_OPS: frozenset[str] = frozenset(PredOp.__args__)


class HelixPredicate(BaseModel):
    op: PredOp
    field: str = Field(pattern=_IDENT.pattern)
    value: Any = None            # literal scalar/list, or {"$param": name}
    model_config = ConfigDict(extra="forbid")


class HelixStep(BaseModel):
    op: ReadOp
    pred: HelixPredicate | None = None
    label: dict[Literal["$collection"], str] | None = None
    branches: list[list["HelixStep"]] | None = Field(default=None, max_length=11)
    fields: list[str] | None = None
    order: list[tuple[str, bool]] | None = None     # (field, desc)
    n: int | None = Field(default=None, ge=1, le=800)
    model_config = ConfigDict(extra="forbid")
    # FILL IN: model_validator — each op carries exactly its own argument (n_where/where→pred, out/in_/both/
    #   n_with_label→label, union→branches, limit→n, order_by→order, value_map→optional fields, others none);
    #   every identifier _IDENT-checked — bounded by "Security constraints"


class HelixOpTree(BaseModel):
    version: Literal[1] = 1
    define_params: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    steps: list[HelixStep] = Field(max_length=64)
    model_config = ConfigDict(extra="forbid")
    # FILL IN: model_validator — walk steps (recursing into branches, depth ≤ 3); the set of {"$param"} refs must
    #   equal define_params and the set of {"$collection"} refs must equal collections — bounded by AC25 / test row


def parse_helix_op_tree(text: str) -> HelixOpTree:
    """Parse and validate a helix template; raises ``ValueError`` (pydantic) on anything not allowlisted."""
    return HelixOpTree.model_validate_json(text)


def _value(value: Any) -> Any:
    return {"$param": value.name} if isinstance(value, ParamRef) else value


def _pred(cond: Condition) -> dict[str, Any]:
    return {"op": cond.op, "field": cond.field, "value": _value(cond.value)}


def compile_helix_traversal(spec: TraversalSpec) -> CompiledTraversal:
    """Compile ``spec`` into the op-tree JSON (pure; no helixdb import)."""
    steps: list[dict[str, Any]] = []
    collections: list[str] = []
    if spec.start.ids is not None:
        steps.append({"op": "n_where", "pred": {"op": "in", "field": "_id", "value": _value(spec.start.ids)}})
    else:
        # FILL IN: n_with_label {"$collection": start.collection} + where per match; collections += collection
        raise NotImplementedError
    for hop in spec.hops:
        if hop.edge_where:
            raise TraversalSpecUnsupported("helix: edge_where needs an edge→vertex op")   # FILL IN: lift only if the wheel has one
        # FILL IN: op = {"outbound": "out", "inbound": "in_", "any": "both"}[hop.direction]; single step when
        #   min == max == 1, else union of k-length chains for k in min..max; then where per hop.where;
        #   collections += edge (dedupe, order-preserving)
    # FILL IN: exclude_start (ids → where not_in _id; scan → TraversalSpecUnsupported), final where, dedup,
    #   order_by, limit, projection (value_map / value_map fields / value_map ["_id"] / count)
    tree = {"version": 1, "define_params": list(spec.param_names()), "collections": collections, "steps": steps}
    text = json.dumps(tree, sort_keys=True, separators=(",", ":"))
    parse_helix_op_tree(text)   # self-check: the compiler can never emit what the loader refuses
    return CompiledTraversal(dialect="helix", text=text, params=spec.param_names(), collections=tuple(collections))


def build_helix_traversal(tree: HelixOpTree, params: Mapping[str, Any], collection_binds: Mapping[str, str]) -> Any:
    """Lower a validated op-tree to a helixdb read traversal; values are bound as Python objects."""
    # FILL IN: lazy `from helixdb import g, Predicate` (raise HelixExtraMissing from helix/errors.py when absent);
    #   missing param / bind → ValueError; label = collection_binds[f"@{name}"] (_IDENT-checked);
    #   single id param value → [value]; explicit dispatch dict {op: lambda t, step: ...}; union branches built
    #   from g() sub-traversals; predicate mapping to verified Predicate constructors — bounded by Security constraints
    raise NotImplementedError
```
**Why this shape**: the JSON is our own allowlisted format (not a pass-through of SDK JSON), so the read-only
guarantee is a type-level property of `HelixStep.op`; the compiler self-checks against the same parser the store
uses.

### `packages/ai-parrot/src/parrot/knowledge/helix/__init__.py` (MODIFY)
```python
# occurrences: verify on pickup — file is created by TASK-4374 (not on dev when this task was written).
# AFTER — append at the end of the module (after the last import / __all__):
from parrot.knowledge.ontology.traversal_spec import register_traversal_compiler
from parrot.knowledge.helix.traversal import compile_helix_traversal

register_traversal_compiler("helix", compile_helix_traversal)
# and add "compile_helix_traversal" to __all__ if the module defines one
```
**Why**: spec AC25 — the helix compiler is registered on `import parrot.knowledge.helix`; registration stays
SDK-free because `compile_helix_traversal` imports no `helixdb`. TASK-4392 later adds `register_all()` here —
keep this registration at module level, not inside a function.

### FILL IN checklist
- [ ] `HelixStep` / `HelixOpTree` validators — allowlist, bounds, param/collection set equality
- [ ] `compile_helix_traversal` scan start, hops, tail — round-trips through the parser
- [ ] `build_helix_traversal` — verified DSL names only, explicit dispatch dict, ValueError on unbound
- [ ] `edge_where` — lift only if a verified edge→vertex op exists

---

## Acceptance Criteria

- [ ] AC25 (part): `import parrot.knowledge.helix` registers `"helix"` in `traversal_compiler_dialects()`; a
      `TraversalPattern(traversal_spec=…)` built afterwards has `query_templates["helix"]`.
- [ ] Fixture patterns (`tests/knowledge/ontology/fixtures/portable.ontology.yaml`) compile; `define_params`
      equals `CompiledTraversal.params`; output parses with `parse_helix_op_tree`.
- [ ] `parse_helix_op_tree` rejects every write op name listed in the Codebase Contract, unknown keys, unbound
      `$param`, oversize trees, and non-identifier fields/labels.
- [ ] No `register_query_validator("helix", …)` anywhere (AC7).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/helix/test_traversal_helix.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/test_traversal_spec.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/helix/test_traversal_helix.py
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import parrot.knowledge.helix  # noqa: F401  (registers "helix")
from parrot.knowledge.helix.traversal import compile_helix_traversal, parse_helix_op_tree
from parrot.knowledge.ontology.schema import TraversalPattern
from parrot.knowledge.ontology.traversal_spec import TraversalSpec, traversal_compiler_dialects

FIXTURE = Path(__file__).parents[1] / "ontology" / "fixtures" / "portable.ontology.yaml"
PATTERNS = yaml.safe_load(FIXTURE.read_text())["traversal_patterns"]
WRITE_OPS = ["add_n", "add_e", "set_property", "remove_property", "drop", "drop_edge", "drop_edge_by_id",
             "create_index_if_not_exists", "drop_index", "create_text_index_nodes", "create_vector_index_nodes"]


def test_helix_registered_and_materialised() -> None:
    assert "helix" in traversal_compiler_dialects()
    p = TraversalPattern(description="d", traversal_spec=PATTERNS["find_team"]["traversal_spec"])
    assert parse_helix_op_tree(p.query_templates["helix"]).define_params == ["user_id"]


@pytest.mark.parametrize("name", sorted(PATTERNS))
def test_traversal_spec_compile_helix(name: str) -> None:
    compiled = compile_helix_traversal(TraversalSpec(**PATTERNS[name]["traversal_spec"]))
    tree = parse_helix_op_tree(compiled.text)
    assert tuple(tree.define_params) == compiled.params


@pytest.mark.parametrize("op", WRITE_OPS)
def test_write_ops_rejected(op: str) -> None:
    with pytest.raises(ValidationError):
        parse_helix_op_tree(json.dumps({"version": 1, "steps": [{"op": op}]}))


def test_unbound_param_and_extra_keys_rejected() -> None:
    step = {"op": "n_where", "pred": {"op": "eq", "field": "_id", "value": {"$param": "x"}}}
    with pytest.raises(ValidationError):
        parse_helix_op_tree(json.dumps({"version": 1, "steps": [step]}))
    with pytest.raises(ValidationError):
        parse_helix_op_tree(json.dumps({"version": 1, "define_params": [], "steps": [{"op": "dedup", "js": 1}]}))
```

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`
   (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`), never on `dev`.
2. Read spec §2 "Backend-neutral traversal spec", §3 Module 8 (M8b), §6 "HelixDB SDK surface", AC7 / AC25.
3. Check `Depends-on` (TASK-4374, TASK-4385) are `done` in `sdd/tasks/index/helixdb-provider.json`.
4. Re-verify: `traversal_spec.py` symbols, `helix/__init__.py` contents, and the installed `helixdb` DSL names
   (`python -c "import helixdb.dsl as d; print([n for n in dir(d.Traversal) if not n.startswith('_')])"` — adjust to
   the real class name) before writing `build_helix_traversal`.
5. Mark `in-progress` in the per-spec index; commit only that file.
6. Implement from the blueprint; complete every `# FILL IN:`.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; `ruff check --fix` the touched files.
8. **Security review is mandatory**: run `/sdd-codereview TASK-4386` (adversarial, codex second opinion) before
   closing. Focus: can any template reach a write op or an unlisted DSL method; are values ever string-built;
   are labels/params fail-closed when unbound. Triage every finding CONFIRM / REJECT / ESCALATE in the Completion Note.
9. Commit only the listed files: `feat(helixdb-provider): TASK-4386 — helix traversal compiler`.
10. `scripts/sdd/close_task.sh TASK-4386 helixdb-provider verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
