# TASK-4329: TraversalPattern.query_templates, ResolvedIntent query/dialect, mixin uses the contract

**Feature**: FEAT-540 — GraphIndex Core Seams
**Spec**: `sdd/specs/graphindex-core-seams.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4328, TASK-4327
**Assigned-to**: unassigned

---

## Context

Spec §3 M8. `ResolvedIntent.aql` (schema.py:571) and `IntentDecision.aql` (intent.py:42) carry AQL; the mixin runs it via `execute_traversal` (mixin.py:337/359/379).

---

## Scope

- `TraversalPattern.query_templates: dict[str, str]` (additive).
- `ResolvedIntent`: `aql` → `query` + `dialect` (hard cut); `IntentDecision.aql` → `query`.
- `OntologyIntentResolver(..., dialect='aql')`: prompt names the dialect; dynamic path calls `validate_query(dialect, ...)`; unregistered dialect ⇒ `vector_only`.
- Mixin: patterns via `execute_pattern`, dynamic via `execute_query(DynamicQuery(...))`; constructor typed `OntologyTraversalStore`.
- Update tests: test_ontology_intent.py, test_ontology_intent_demotion.py, test_ontology_schema.py, test_ontology_schema_extensions.py, test_ontology_mixin.py, test_degradation_chain.py, parrot_tools procedures/test_service.py.

**NOT in scope**: authorization/entity_resolver (TASK-4330); parrot_tools callers (TASK-4331).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` | MODIFY | query_templates; query/dialect |
| `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py` | MODIFY | dialect-aware resolver |
| `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` | MODIFY | contract calls |
| `packages/ai-parrot/tests/knowledge/test_ontology_intent.py` | MODIFY | field rename |
| `packages/ai-parrot/tests/knowledge/test_ontology_intent_demotion.py` | MODIFY | field rename |
| `packages/ai-parrot/tests/knowledge/test_ontology_schema.py` | MODIFY | field rename |
| `packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py` | MODIFY | field rename |
| `packages/ai-parrot/tests/knowledge/test_ontology_mixin.py` | MODIFY | contract mocks |
| `packages/ai-parrot/tests/knowledge/test_degradation_chain.py` | MODIFY | contract mocks |
| `packages/ai-parrot-tools/tests/procedures/test_service.py` | MODIFY | field rename |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `cf6316096` on 2026-10-14. Re-verify before writing code.

### Verified Imports
```python
from parrot.knowledge.ontology.contracts import DynamicQuery, OntologyTraversalStore  # TASK-4327
from parrot.knowledge.ontology.validators import validate_query  # TASK-4327
```

### Existing Signatures to Use
```python
# schema.py: TraversalPattern :261 (query_template :288); ResolvedIntent :547 (aql :571)
# intent.py: IntentDecision.aql :42; __init__ :79; aql=pattern.query_template :150, :212; validate_aql :222; prompt :275
# mixin.py: graph_store import :70; kwarg :120; execute_traversal :337, :359, :379
```

### Does NOT Exist
- ~~`ResolvedIntent.query` / `.dialect` today~~
- ~~`TraversalPattern.query_templates` today~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/schema.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/intent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_intent.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_intent_demotion.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_schema.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_ontology_mixin.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/test_degradation_chain.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/procedures/test_service.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#TraversalPattern",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/schema.py#ResolvedIntent",
    "sym:packages/ai-parrot/src/parrot/knowledge/ontology/intent.py#OntologyIntentResolver"
  ]
}
```

---

## Implementation Notes

Pattern intents must call `execute_pattern(ctx, pattern, params, collection_binds)` so non-Arango stores pick their template; only dynamic LLM queries use `execute_query`.

### Key Constraints
- Async-first; Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; strict type hints; 120 cols.
- Never import `requests`/`httpx`/`langchain`; no `print`. Hard cuts for renamed internals (no external consumers).
- Touch only the files listed above.

---

## Implementation Blueprint

### Steps (in order)
1. Schema fields.
2. Intent resolver.
3. Mixin.
4. Tests.

### `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'query_template: str' parrot/knowledge/ontology/schema.py)
# AFTER/AT — anchor `query_template: str` (verified: schema.py:288)
# ADD below:
    query_templates: dict[str, str] = Field(default_factory=dict)
```
**Why**: Additive; YAML keeps working.

### `packages/ai-parrot/src/parrot/knowledge/ontology/schema.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'aql: str | None = None' parrot/knowledge/ontology/schema.py)
# AFTER/AT — anchor `aql: str | None = None` (verified: schema.py:571)
# REPLACE with:
    query: str | None = None
    dialect: str = "aql"
# FILL IN: update the docstring Args
```
**Why**: Hard cut.

### `packages/ai-parrot/src/parrot/knowledge/ontology/intent.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'validated = await validate_aql(decision.aql)' parrot/knowledge/ontology/intent.py)
# AFTER/AT — anchor `validated = await validate_aql(decision.aql)` (verified: intent.py:222)
# REPLACE with:
                    validated = await validate_query(self._dialect, decision.query)
# FILL IN: IntentDecision.aql -> query; resolver dialect kwarg; prompt key; QueryValidationError -> vector_only
```
**Why**: Dialect-aware dynamic path.

### `packages/ai-parrot/src/parrot/knowledge/ontology/mixin.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .graph_store import OntologyGraphStore' parrot/knowledge/ontology/mixin.py)
# AFTER/AT — anchor `from .graph_store import OntologyGraphStore` (verified: mixin.py:70)
# REPLACE with TYPE_CHECKING import of OntologyTraversalStore; graph_store kwarg typed to it
# FILL IN: the three execute_traversal calls -> execute_pattern (pattern intents) / execute_query(DynamicQuery(...)) (dynamic)
```
**Why**: Mixin talks to the contract.

### `packages/ai-parrot/tests/knowledge/test_ontology_intent.py` (MODIFY)
```python
# occurrences: n/a — re-grep `aql` in this file
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: .aql -> .query / aql= -> query=
```
**Why**: Follow hard cut.

### `packages/ai-parrot/tests/knowledge/test_ontology_intent_demotion.py` (MODIFY)
```python
# occurrences: n/a — re-grep `aql`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: same
```
**Why**: Same.

### `packages/ai-parrot/tests/knowledge/test_ontology_schema.py` (MODIFY)
```python
# occurrences: n/a — re-grep `aql`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: same
```
**Why**: Same.

### `packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py` (MODIFY)
```python
# occurrences: n/a — re-grep `aql`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: same
```
**Why**: Same.

### `packages/ai-parrot/tests/knowledge/test_ontology_mixin.py` (MODIFY)
```python
# occurrences: n/a — re-grep `execute_traversal`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: mocks of execute_traversal -> execute_pattern/execute_query
```
**Why**: Same.

### `packages/ai-parrot/tests/knowledge/test_degradation_chain.py` (MODIFY)
```python
# occurrences: n/a — re-grep `execute_traversal`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: same
```
**Why**: Same.

### `packages/ai-parrot-tools/tests/procedures/test_service.py` (MODIFY)
```python
# occurrences: n/a — re-grep `aql`
# FILL IN: re-verify with grep -c once the file exists; quote the anchor before editing
# FILL IN: aql field rename
```
**Why**: Same.

### FILL IN checklist
- [ ] resolver dialect + prompt
- [ ] mixin call sites
- [ ] seven test files

---

## Acceptance Criteria

- [ ] no `ResolvedIntent.aql`/`IntentDecision.aql` left
- [ ] pattern intents use execute_pattern; dynamic use execute_query
- [ ] listed tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/test_ontology_intent.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_intent_demotion.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_schema.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_schema_extensions.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_ontology_mixin.py -q`
- `pytest packages/ai-parrot/tests/knowledge/test_degradation_chain.py -q`
- `pytest packages/ai-parrot-tools/tests/procedures/test_service.py -q`

---

## Test Specification

```python
# existing tests updated
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug graphindex-core-seams --feature-id FEAT-540 --spec sdd/specs/graphindex-core-seams.spec.md --index sdd/tasks/index/graphindex-core-seams.json`)
2. **Read the spec** (`sdd/specs/graphindex-core-seams.spec.md`) — at least §2 and the module this task implements
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/graphindex-core-seams.json`
4. **Verify the Codebase Contract** — re-run `grep -c` for every anchor in the blueprint; a changed count means the
   anchor moved: re-locate it and fix the blueprint line before editing. A count of 0 means drift — stop and report.
5. **Update status** → `"in-progress"` (`started_at`) and commit only the index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:`; never change a fixed signature or path
7. **Validate** — `ruff check --fix <changed files>` and the Validation Commands with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src` (worktrees: the shared venv points at the main checkout)
8. **Commit code** — stage only the files listed above (never `git add .` / `-A`)
9. **Close** with `scripts/sdd/close_task.sh TASK-4329 graphindex-core-seams verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
