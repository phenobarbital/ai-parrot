# TASK-4385: Backend-neutral TraversalSpec, compiler registry and the built-in AQL compiler

**Feature**: FEAT-670 — HelixDB graph provider
**Spec**: `sdd/specs/helixdb-provider.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8a (resolves §8 Q1, option a; goal G10; AC25). Today a `TraversalPattern` can only run
where an AQL `query_template` exists. This task adds the backend-neutral `TraversalSpec` vocabulary
(start / hops / conditions / ordering / projection), a per-dialect compiler registry with the built-in
`"aql"` compiler, and the `TraversalPattern` validator that **materialises** compiled text into
`query_templates[<dialect>]` so FEAT-540's plain dialect lookup (`ArangoOntologyGraphStore.execute_pattern`,
`OntologyIntentResolver._pattern_query`) needs no change. TASK-4386 registers the `"helix"` compiler against this
registry; TASK-4388 consumes it lazily from `HelixOntologyGraphStore.execute_pattern`.

**Security relevance**: traversal patterns drive the ontology fast path and the declarative
authorization rules; the AQL compiler produces query text executed against tenant databases. The
vocabulary admits **no raw expressions**: every identifier is regex-checked, every value is a bind
parameter or a JSON-encoded scalar literal, every collection is a `@@` bind. This task requires an
adversarial `/sdd-codereview`.

---

## Scope

- Create `ontology/traversal_spec.py`: `ParamRef`, `Condition`, `StartSpec`, `HopSpec`, `OrderSpec`,
  `ReturnSpec`, `TraversalSpec`, `CompiledTraversal`, `TraversalSpecUnsupported`,
  `register_traversal_compiler`, `traversal_compiler_dialects`, `compile_traversal_spec`, `compile_aql`
  (registered as `"aql"` at import).
- Modify `TraversalPattern` in `ontology/schema.py`: `query_template: str | None = None`,
  `traversal_spec: TraversalSpec | None = None`, and a `model_validator(mode="after")`
  `_materialise_templates`.
- Create the fixture ontology `tests/knowledge/ontology/fixtures/portable.ontology.yaml` (two
  spec-only patterns: `find_team`-shaped and `authoritative_doc_for_topic`-shaped).
- Write `tests/knowledge/ontology/test_traversal_spec.py` (vocabulary, AQL golden, registry, materialisation,
  bundled defaults still load).

**NOT in scope**:
- The `"helix"` compiler (TASK-4386) and any HelixDB code.
- Rewriting `ontology/defaults/*.yaml` patterns as `traversal_spec` (spec Non-Goal).
- Editing `ontology/graph_store.py`, `intent.py`, `merger.py`, `schema_overlay/validator.py`,
  `authorization.py`, `entity_resolver.py`, `mixin.py` (AC16/AC25 — see Drift for the two known gaps).
- The live AQL-vs-Helix parity test (TASK-4397).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/traversal_spec.py` | CREATE | Vocabulary models, compiler registry, built-in AQL compiler |
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | MODIFY | `TraversalPattern`: optional `query_template`, `traversal_spec`, materialising validator |
| `packages/ai-parrot/tests/knowledge/ontology/fixtures/portable.ontology.yaml` | CREATE | Fixture ontology with spec-only patterns |
| `packages/ai-parrot/tests/knowledge/ontology/test_traversal_spec.py` | CREATE | Unit tests (vocabulary, golden AQL, materialisation) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator  # verified: ontology/schema.py:13
from parrot.knowledge.ontology.exceptions import OntologyError                       # verified: ontology/exceptions.py:4
from parrot.knowledge.ontology.validators import validate_query                      # verified: ontology/validators.py:120 (async)
from parrot.knowledge.ontology.schema import TraversalPattern                        # verified: ontology/schema.py:261
from parrot.knowledge.ontology.parser import OntologyParser                          # verified: ontology/parser.py:19 (staticmethods load :29, load_from_dict :65, load_default_base :80)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/ontology/schema.py
class TraversalPattern(BaseModel):                       # :261
    description: str                                     # :287
    trigger_intents: list[str] = Field(default_factory=list)   # :288
    query_template: str                                  # :289  ← becomes `str | None = None`
    query_templates: dict[str, str] = Field(default_factory=dict)  # :290 (FEAT-540 M8, merged)
    post_action: Literal["vector_search", "tool_call", "none"] = "none"  # :291
    ...
    tool_call: ToolCallSpec | None = None                # :295
    model_config = ConfigDict(extra="forbid")            # :297

# packages/ai-parrot/src/parrot/knowledge/ontology/validators.py
async def validate_aql(aql: str, max_depth: int | None = None) -> str       # :36 — rejects INSERT/UPDATE/REMOVE/REPLACE/UPSERT words, _system etc., APPLY/CALL/V8(, any `N..M` with M > max_depth (default ONTOLOGY_MAX_TRAVERSAL_DEPTH = 4, conf.py:163)
async def validate_query(dialect: str, text: str, max_depth: int | None = None) -> str  # :120
register_query_validator("aql", validate_aql)                               # :144

# packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py
_ATTRIBUTE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")                  # :42 (do NOT import — cycle; replicate)
async def execute_pattern(...):                                             # :465 — `templates.get(self.dialect) or getattr(pattern, "query_template", None)` :488-489
#   _execute_aql merges collection_binds keyed "@<name>" into bind_vars       # :304-308

# packages/ai-parrot/src/parrot/knowledge/ontology/intent.py
def _pattern_query(self, pattern) -> str:   # :256 — `(pattern.query_templates or {}).get(self._dialect) or pattern.query_template` :265
def _build_collection_binds(self) -> dict[str, str]:  # :267 — keys f"@{collection}" → collection

# packages/ai-parrot/src/parrot/knowledge/ontology/contracts.py:11 imports schema (TraversalPattern) → traversal_spec.py must NOT import contracts.py / graph_store.py
# packages/ai-parrot/src/parrot/knowledge/ontology/tenant.py:363 — overlays load as TraversalPattern(**row.definition)
# packages/ai-parrot/src/parrot/knowledge/ontology/defaults/base.ontology.yaml:138 find_team (query_template :144); knowledge.ontology.yaml:192 authoritative_doc_for_topic
```

### Does NOT Exist
- ~~`parrot.knowledge.ontology.traversal_spec`~~ — created by this task.
- ~~`TraversalPattern.traversal_spec`~~, ~~`TraversalPattern._materialise_templates`~~ — created by this task.
- ~~`parrot.knowledge.helix.traversal` / `compile_helix_traversal`~~ — TASK-4386.
- ~~a `"helix"` entry in `validators._VALIDATORS`~~ — never registered by FEAT-670 (fail-closed rule).
- ~~`Condition.expr`, raw AQL fragments, nested attribute paths (`a.b`)~~ — deliberately absent from the vocabulary.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/traversal_spec.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/ontology/schema.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/fixtures/portable.ontology.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/knowledge/ontology/test_traversal_spec.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TraversalPattern",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/exceptions.py#OntologyError",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/validators.py#validate_query",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/validators.py#validate_aql",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/graph_store.py#ArangoOntologyGraphStore.execute_pattern",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/intent.py#OntologyIntentResolver._pattern_query"
  ]
}
```

---

## Implementation Notes

### Key constraints (security)
- **Identifiers**: every `Condition.field`, `OrderSpec.field`, `ReturnSpec.fields[*]`, `HopSpec.edge_collection`,
  `StartSpec.collection`, `ParamRef.name` must match `^[A-Za-z_][A-Za-z0-9_]*$` (validated at model build —
  a bad YAML pattern fails to load, it never reaches the compiler). `_id` / `_key` match the regex and are the
  backend-neutral aliases.
- **Values**: a `ParamRef` renders as `@name`; a literal renders as `json.dumps(value, allow_nan=False)`
  and literals are restricted to `str | int | float | bool | None` or a list of those (validated). JSON string
  escaping is a subset of AQL string-literal escaping, so a literal can never terminate the string.
  A YAML string starting with `$` is always a `ParamRef` (there is no literal-`$` escape — document it).
- **Collections**: only `@@<logical>` binds; `CompiledTraversal.collections` lists the logical names; callers
  resolve them via `collection_binds` keyed `"@<logical>"` (intent.py:267 format).
- **Variables** in the generated AQL are fixed (`s0`, `v1..vN`, `e1..eN`, `hits`, `d`) — never user-derived.
- **Depth**: `HopSpec` keeps the spec bounds (`min_depth` 0..10, `max_depth` 1..10, `min_depth <= max_depth`).
  Generated `min..max` ranges are what `validate_aql`'s depth check inspects.
- **Fail closed in materialisation**: a compiler raising `TraversalSpecUnsupported` for a dialect (e.g. the
  helix compiler on `edge_where`) must NOT fail the pattern — skip that dialect with a `logger.warning`;
  `execute_pattern` on that backend then raises `TraversalPatternUnavailable`. Any other exception propagates
  (pattern invalid).
- **Explicit entries win**: never overwrite a `query_templates[d]` given by the author. **`query_template`
  counts as an explicit `"aql"` entry**: when it is set, do NOT materialise `"aql"` — `intent._pattern_query`
  and `ArangoOntologyGraphStore.execute_pattern` both prefer `query_templates["aql"]` over `query_template`,
  so materialising would silently shadow the author's AQL.

### Drift vs spec
- Spec §6 cited `schema.py:286-296`; real lines are `:287-297` (`query_template` :289, `query_templates` :290,
  `model_config` :297). FEAT-540's `query_templates` edit is already merged.
- `validate_aql` caps depth at `ONTOLOGY_MAX_TRAVERSAL_DEPTH` (default **4**, conf.py:163) while the spec allows
  `max_depth` ≤ 10. Pattern execution (`ArangoOntologyGraphStore.execute_pattern`) does not validate, so this is
  only relevant to the golden test: keep fixture depths ≤ 4 (`0..3` mirrors `authoritative_doc_for_topic`).
- **Known gaps outside this task's files** (record in the Completion Note and open ledger issues, do not fix):
  (1) `merger.py:392` `_merge_patterns` only overrides `query_template`, not `traversal_spec`/`query_templates`;
  an overlay overriding a spec-based base pattern keeps stale materialised templates.
  (2) `schema_overlay/validator.py:125-126,258-262` dry-run requires `query_template`, so a tenant overlay
  pattern with only `traversal_spec` fails its dry run. (3) `intent.py:265` falls back to `query_template`
  for any dialect (only cosmetic for the pattern path — execution goes through `execute_pattern`, mixin.py:530).

### Generated AQL shape (decided — golden tests pin it)
```
LET hits = (
FOR s0 IN TO_ARRAY(@user_id)                       ← ids start   | FOR s0 IN @@coll  + FILTERs on s0 (scan start)
FOR v1 IN 1..1 OUTBOUND s0 @@member_of_team        ← hop i: FOR vi[, ei] IN min..max DIR v(i-1) @@edge
FOR v2 IN 1..1 INBOUND v1 @@member_of_team
FILTER v2._id != s0                                ← exclude_start (scan start: != s0._id); hop/final FILTERs
RETURN v2
)
FOR d IN UNIQUE(hits)                              ← `hits` when returns.distinct is false
RETURN d                                           ← SORT d.f ASC|DESC / LIMIT n before; fields → {"f": d.f}; ids → d._id
```
`count` → `RETURN LENGTH(UNIQUE(hits))` (order_by/limit rejected for `count` by the model validator).
A spec with zero hops uses `s0` itself as the final frontier: for ids start emit
`FOR s0 IN TO_ARRAY(@p) LET v0 = DOCUMENT(s0) FILTER v0 != null` and use `v0`.

---

## Implementation Blueprint

### Steps (in order)
1. Create `traversal_spec.py` models + registry + `compile_aql` — *why*: schema.py imports it.
2. Edit `TraversalPattern` (optional `query_template`, `traversal_spec`, validator) — *why*: materialisation at load.
3. Write the fixture YAML and the tests; run them; confirm `ontology/defaults/*.yaml` still load.

### `packages/ai-parrot/src/parrot/knowledge/ontology/traversal_spec.py` (CREATE)
```python
"""Backend-neutral traversal patterns compiled per query dialect (FEAT-670 M8a).

Imports nothing from ``ontology/schema.py`` / ``contracts.py`` / ``graph_store.py`` (schema.py imports this).
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .exceptions import OntologyError

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SCALARS = (str, int, float, bool, type(None))
Direction = Literal["outbound", "inbound", "any"]
ConditionOp = Literal["eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "contains", "is_null", "not_null"]


def _ident(value: str) -> str:
    if not isinstance(value, str) or not _IDENT.match(value):
        raise ValueError(f"{value!r} is not a plain identifier")
    return value


class ParamRef(BaseModel):
    """A bind parameter. YAML strings starting with ``$`` become ParamRef (never literals)."""
    name: str
    model_config = ConfigDict(extra="forbid", frozen=True)

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        return _ident(value)


def _coerce_param(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return ParamRef(name=value[1:])
    return value


class Condition(BaseModel):
    field: str
    op: ConditionOp = "eq"
    value: Any = None
    model_config = ConfigDict(extra="forbid")
    # FILL IN: field_validator("field") → _ident; field_validator("value", mode="before") → _coerce_param;
    #   model_validator(after): is_null/not_null require value None; in/not_in require a list or ParamRef;
    #   literal must be a _SCALARS instance or a list of them, and json.dumps(value, allow_nan=False) must succeed
    #   — bounded by "values are never interpolated" (spec §2) and AC25 validate_query pass


class StartSpec(BaseModel):
    """Exactly one of ``ids`` (a ``$param``) or ``collection`` + ``match``."""
    ids: ParamRef | None = None
    collection: str | None = None
    match: list[Condition] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")
    # FILL IN: before-validator on ids (_coerce_param; a non-$ literal is rejected), _ident on collection,
    #   model_validator: exactly one of ids / collection; match only with collection — bounded by test_traversal_spec_vocabulary


class HopSpec(BaseModel):
    edge_collection: str
    direction: Direction = "outbound"
    min_depth: int = Field(default=1, ge=0, le=10)
    max_depth: int = Field(default=1, ge=1, le=10)
    edge_where: list[Condition] = Field(default_factory=list)
    where: list[Condition] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")
    # FILL IN: _ident(edge_collection); min_depth <= max_depth


class OrderSpec(BaseModel):
    field: str
    desc: bool = False
    model_config = ConfigDict(extra="forbid")
    # FILL IN: _ident(field)


class ReturnSpec(BaseModel):
    kind: Literal["vertex", "fields", "ids", "count"] = "vertex"
    fields: list[str] = Field(default_factory=list)
    distinct: bool = True
    model_config = ConfigDict(extra="forbid")
    # FILL IN: every field _ident; kind=="fields" requires non-empty fields, other kinds require empty


class TraversalSpec(BaseModel):
    """Backend-neutral declaration of a traversal pattern, compiled per dialect."""
    start: StartSpec
    hops: list[HopSpec] = Field(default_factory=list)
    where: list[Condition] = Field(default_factory=list)
    exclude_start: bool = False
    order_by: list[OrderSpec] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=800)
    returns: ReturnSpec = Field(default_factory=ReturnSpec)
    model_config = ConfigDict(extra="forbid")
    # FILL IN: model_validator — returns.kind == "count" forbids order_by/limit; exclude_start requires ≥1 hop

    def param_names(self) -> tuple[str, ...]:
        """Every ParamRef name, in first-appearance order (start, match, hops, where)."""
        # FILL IN: walk start.ids, start.match, hops[*].edge_where/where, where; dedupe preserving order
        raise NotImplementedError


class CompiledTraversal(BaseModel):
    dialect: str
    text: str
    params: tuple[str, ...]
    collections: tuple[str, ...]


class TraversalSpecUnsupported(OntologyError):
    """No compiler registered for the dialect, or the compiler cannot express the spec."""


_COMPILERS: dict[str, Callable[[TraversalSpec], CompiledTraversal]] = {}


def register_traversal_compiler(dialect: str, compiler: Callable[[TraversalSpec], CompiledTraversal]) -> None:
    """Register or replace the compiler for ``dialect``."""
    _COMPILERS[dialect] = compiler


def traversal_compiler_dialects() -> tuple[str, ...]:
    return tuple(_COMPILERS)


def compile_traversal_spec(spec: TraversalSpec, dialect: str) -> CompiledTraversal:
    """Dispatch to the registered compiler; TraversalSpecUnsupported otherwise."""
    compiler = _COMPILERS.get(dialect)
    if compiler is None:
        raise TraversalSpecUnsupported(f"No traversal compiler registered for dialect {dialect!r}")
    return compiler(spec)
```
(`compile_aql` + its helpers go below in the same file — next block.)

### `traversal_spec.py` — AQL compiler (same file, continued)
```python
_AQL_OPS = {"eq": "==", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _aql_value(value: Any) -> str:
    if isinstance(value, ParamRef):
        return f"@{value.name}"
    return json.dumps(value, allow_nan=False)   # scalars / lists of scalars only (validated)


def _aql_condition(var: str, cond: Condition) -> str:
    ref = f"{var}.{cond.field}"
    if cond.op in _AQL_OPS:
        return f"FILTER {ref} {_AQL_OPS[cond.op]} {_aql_value(cond.value)}"
    if cond.op == "in":
        return f"FILTER {ref} IN TO_ARRAY({_aql_value(cond.value)})"
    if cond.op == "not_in":
        return f"FILTER {ref} NOT IN TO_ARRAY({_aql_value(cond.value)})"
    if cond.op == "contains":
        return f"FILTER CONTAINS({ref}, {_aql_value(cond.value)})"
    return f"FILTER {ref} == null" if cond.op == "is_null" else f"FILTER {ref} != null"


def compile_aql(spec: TraversalSpec) -> CompiledTraversal:
    """Built-in AQL compiler (see Implementation Notes for the exact shape)."""
    lines: list[str] = ["LET hits = ("]
    collections: list[str] = []
    if spec.start.ids is not None:
        lines.append(f"FOR s0 IN TO_ARRAY(@{spec.start.ids.name})")
        start_id = "s0"
    else:
        collections.append(spec.start.collection)
        lines.append(f"FOR s0 IN @@{spec.start.collection}")
        lines += [_aql_condition("s0", c) for c in spec.start.match]
        start_id = "s0._id"
    prev = "s0"
    # FILL IN: zero-hop ids start → LET v0 = DOCUMENT(s0) / FILTER v0 != null, prev = "v0";
    #   per hop i (1-based): `FOR vi, ei IN min..max DIR prev @@edge` (`, ei` only when edge_where),
    #   DIR = OUTBOUND|INBOUND|ANY, append edge_where on ei and where on vi, collections += edge (dedupe), prev = vi
    #   — bounded by the golden shape in Implementation Notes
    if spec.exclude_start:
        lines.append(f"FILTER {prev}._id != {start_id}")
    lines += [_aql_condition(prev, c) for c in spec.where]
    lines += [f"RETURN {prev}", ")"]
    source = "UNIQUE(hits)" if spec.returns.distinct else "hits"
    # FILL IN: count → "RETURN LENGTH(<source>)"; else FOR d IN <source>, SORT d.f ASC|DESC (comma-joined),
    #   LIMIT n, RETURN d | {"f": d.f, ...} | d._id — bounded by test_traversal_spec_compile_aql_golden
    return CompiledTraversal(
        dialect="aql", text="\n".join(lines), params=spec.param_names(), collections=tuple(collections)
    )


register_traversal_compiler("aql", compile_aql)
```
**Why this shape**: one uniform `LET hits = (...)` + post-processing block keeps DISTINCT/SORT/LIMIT
semantics deterministic and identical for every start form; all user-controlled parts reach the text only
through `_ident`-checked names, `@`/`@@` binds or `json.dumps` literals. Do not add raw-expression escape
hatches.

### `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -F 'from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator' schema.py)
# AFTER — insert below that import (schema.py:13). schema.py has NO logger today (verified: grep -n '^logger\|^import logging' → 0):
#   also add `import logging` beside `import re` (:9) and `logger = logging.getLogger(__name__)` after the imports.
from .traversal_spec import TraversalSpec, TraversalSpecUnsupported, compile_traversal_spec, traversal_compiler_dialects

# occurrences: 1 (verified: grep -c -F '    query_template: str' schema.py → 1; `query_templates:` is a different line)
# REPLACE schema.py:289
    query_template: str | None = None
# AFTER schema.py:290 `    query_templates: dict[str, str] = Field(default_factory=dict)` (occurrences: 1)
    traversal_spec: TraversalSpec | None = None

# AFTER `    model_config = ConfigDict(extra="forbid")` at :297 — occurrences: MANY (every model);
#   `    tool_call: ToolCallSpec | None = None` occurs 2× (:295 TraversalPattern, :582 another model) — anchor on the
#   3-line context unique to TraversalPattern:
#       authorization: AuthorizationSpec | None = None
#       tool_call: ToolCallSpec | None = None
#       <blank>
#       model_config = ConfigDict(extra="forbid")      ← first occurrence after `class TraversalPattern` (:261)
    @model_validator(mode="after")
    def _materialise_templates(self) -> "TraversalPattern":
        """Require a template source; compile traversal_spec into missing dialect entries."""
        if not (self.query_template or self.query_templates or self.traversal_spec):
            raise ValueError("TraversalPattern needs query_template, query_templates or traversal_spec")
        if self.traversal_spec is None:
            return self
        for dialect in traversal_compiler_dialects():
            if dialect in self.query_templates or (dialect == "aql" and self.query_template):
                continue
            try:
                self.query_templates[dialect] = compile_traversal_spec(self.traversal_spec, dialect).text
            except TraversalSpecUnsupported as exc:
                logger.warning("traversal_spec not compilable for %s: %s", dialect, exc)
        return self
```
Also update the class docstring `Args:` (query_template now optional AQL escape hatch; new `traversal_spec`).
**Why**: materialising at load keeps every existing executor untouched; the `aql`/`query_template` rule
prevents shadowing hand-written AQL.

### `packages/ai-parrot/tests/knowledge/ontology/fixtures/portable.ontology.yaml` (CREATE)
```yaml
name: portable_fixture
version: "1.0"
# FILL IN: minimal entities (Employee, Team, Concept, Document) and relations (member_of_team, concept_is_a,
#   doc_covers_concept) so OntologyDefinition validates — copy the key structure from defaults/base.ontology.yaml
traversal_patterns:
  find_team:
    description: Teammates of the current user
    trigger_intents: [what is my team working on]
    traversal_spec:
      start: {ids: $user_id}
      hops:
        - {edge_collection: member_of_team, direction: outbound}
        - {edge_collection: member_of_team, direction: inbound}
      exclude_start: true
  authoritative_doc_for_topic:
    description: Current documents covering a concept family
    traversal_spec:
      start: {ids: $topic_ids}
      hops:
        - {edge_collection: concept_is_a, direction: inbound, min_depth: 0, max_depth: 3}
        - {edge_collection: doc_covers_concept, direction: inbound, where: [{field: is_current, value: true}]}
      order_by: [{field: authority_score, desc: true}]
      limit: 3
      returns: {kind: fields, fields: [document_id, title, version]}
```

### FILL IN checklist
- [ ] `Condition` / `StartSpec` / `HopSpec` / `OrderSpec` / `ReturnSpec` / `TraversalSpec` validators — bounded by test_traversal_spec_vocabulary
- [ ] `TraversalSpec.param_names` — order-preserving dedupe
- [ ] `compile_aql` hop loop + projection block — bounded by the golden strings
- [ ] fixture entities/relations — must load through the parser

---

## Acceptance Criteria

- [ ] AC25 (part): `TraversalPattern` accepts `traversal_spec` with no `query_template`; `query_templates["aql"]`
      is materialised; explicit `query_templates[d]` and an explicit `query_template` are never shadowed.
- [ ] AC25 (part): fixture patterns compile to the golden AQL and pass `await validate_query("aql", text)`.
- [ ] A pattern with none of the three sources fails validation; unknown dialect → `TraversalSpecUnsupported`.
- [ ] `limit > 800`, `max_depth > 10`, `min_depth > max_depth`, `start` with both `ids` and `collection`,
      non-identifier field/collection/param names, dict literals and NaN literals are all rejected.
- [ ] Every bundled `ontology/defaults/**/*.yaml` still loads unchanged (AC25).
- [ ] `ruff check` clean on the two source files; `ontology/graph_store.py` not edited (AC16).

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/ontology/test_traversal_spec.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/test_contracts.py -q`
- `pytest packages/ai-parrot/tests/knowledge/ontology/test_arango_store_typed.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/ontology/test_traversal_spec.py
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from parrot.knowledge.ontology.schema import TraversalPattern
from parrot.knowledge.ontology.traversal_spec import (
    ParamRef, TraversalSpec, TraversalSpecUnsupported, compile_aql, compile_traversal_spec,
)
from parrot.knowledge.ontology.validators import validate_query

FIXTURE = Path(__file__).parent / "fixtures" / "portable.ontology.yaml"
PATTERNS = yaml.safe_load(FIXTURE.read_text())["traversal_patterns"]

FIND_TEAM_AQL = "\n".join([
    "LET hits = (",
    "FOR s0 IN TO_ARRAY(@user_id)",
    "FOR v1 IN 1..1 OUTBOUND s0 @@member_of_team",
    "FOR v2 IN 1..1 INBOUND v1 @@member_of_team",
    "FILTER v2._id != s0",
    "RETURN v2",
    ")",
    "FOR d IN UNIQUE(hits)",
    "RETURN d",
])


def test_traversal_spec_vocabulary() -> None:
    spec = TraversalSpec(**PATTERNS["find_team"]["traversal_spec"])
    assert spec.start.ids == ParamRef(name="user_id")
    for bad in (
        {"start": {"ids": "$u"}, "limit": 801},
        {"start": {"ids": "$u"}, "hops": [{"edge_collection": "e", "max_depth": 11}]},
        {"start": {"ids": "$u", "collection": "c"}},
        {"start": {"ids": "$u"}, "bogus": 1},
        {"start": {"collection": "c; RETURN 1"}},
        {"start": {"ids": "$u"}, "where": [{"field": "a.b", "value": 1}]},
        {"start": {"ids": "$u"}, "where": [{"field": "a", "value": {"x": 1}}]},
        {"start": {"ids": "$bad-name"}},
    ):
        with pytest.raises(ValidationError):
            TraversalSpec(**bad)


@pytest.mark.asyncio
async def test_traversal_spec_compile_aql_golden() -> None:
    compiled = compile_aql(TraversalSpec(**PATTERNS["find_team"]["traversal_spec"]))
    assert compiled.text == FIND_TEAM_AQL
    assert compiled.params == ("user_id",) and compiled.collections == ("member_of_team",)
    for name in PATTERNS:
        text = compile_aql(TraversalSpec(**PATTERNS[name]["traversal_spec"])).text
        assert await validate_query("aql", text) == text
    with pytest.raises(TraversalSpecUnsupported):
        compile_traversal_spec(TraversalSpec(start={"ids": "$u"}), "cypher")


def test_literal_injection_is_quoted() -> None:
    spec = TraversalSpec(start={"ids": "$u"}, hops=[{"edge_collection": "e"}],
                         where=[{"field": "name", "value": '" || true || "'}])
    assert 'FILTER v1.name == "\\" || true || \\""' in compile_aql(spec).text


def test_traversal_pattern_materialises_templates() -> None:
    p = TraversalPattern(description="d", traversal_spec=PATTERNS["find_team"]["traversal_spec"])
    assert p.query_templates["aql"] == FIND_TEAM_AQL and p.query_template is None
    kept = TraversalPattern(description="d", query_template="FOR x IN c RETURN x",
                            traversal_spec=PATTERNS["find_team"]["traversal_spec"])
    assert "aql" not in kept.query_templates
    explicit = TraversalPattern(description="d", query_templates={"aql": "X"},
                                traversal_spec=PATTERNS["find_team"]["traversal_spec"])
    assert explicit.query_templates["aql"] == "X"
    with pytest.raises(ValidationError):
        TraversalPattern(description="d")


def test_bundled_defaults_still_load() -> None:
    # FILL IN: load every defaults/**/*.ontology.yaml through the ontology parser; assert no error
    ...
```

---

## Agent Instructions

1. **Work in the feature worktree** `feat-FEAT-670-helixdb-provider`
   (`python -m scripts.sdd.ensure_worktree --slug helixdb-provider --feature-id FEAT-670`), never on `dev`.
2. Read spec §2 "Backend-neutral traversal spec", §3 Module 8 (M8a), §4 rows `test_traversal_spec_*`, AC25.
3. Check `Depends-on` in `sdd/tasks/index/helixdb-provider.json` (none).
4. Re-verify the Codebase Contract: `grep -n 'query_template' packages/ai-parrot/src/parrot/knowledge/ontology/schema.py`,
   `grep -n -F '    tool_call: ToolCallSpec | None = None' .../schema.py` (2 hits: :295 is TraversalPattern, :582 is not).
5. Mark `in-progress` in the per-spec index; commit only that file.
6. Implement from the blueprint; complete every `# FILL IN:`; never add a raw-expression field.
7. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`; `ruff check --fix` the new/changed files.
8. **Security review is mandatory**: this task touches ontology authorization inputs and generates AQL.
   Run `/sdd-codereview TASK-4385` (adversarial, with the codex second opinion) before closing; triage every
   finding CONFIRM / REJECT / ESCALATE in the Completion Note. Focus: identifier/literal escaping,
   bind-parameter completeness, depth bounds, materialisation precedence.
9. Commit only the listed files: `feat(helixdb-provider): TASK-4385 — backend-neutral TraversalSpec + AQL compiler`.
10. Open ledger issues for the merger / overlay-validator gaps (Drift section), then
    `scripts/sdd/close_task.sh TASK-4385 helixdb-provider verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
