# TASK-4058: Dedupe DDL foreign keys, surface local annotations in schema lookup, cover AC4/AC7

**Feature**: FEAT-628 — Schema-plane producer & annotation fixes
**Spec**: `sdd/specs/producers-ddl-fixes.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Resolves ledger issues `issue:5ebd43788504` (FK duplication in `fold_ddl`) and
`issue:7aee524c981c` (AC7 broken + untested, AC4 untested). See spec §1 for the re-derivation.

## Scope

- `ddl.py`: add `_append_fk(meta, entry)` that appends only when `entry not in meta.foreign_keys`;
  `_add_inline_fk` and `_add_fk` call it.
- `service.py`: `lookup(ref, *, annotation_store=None)`; when set, merge
  `await annotation_store.neighbors(table_id)` rows with `rel == "about"` whose
  namespace-stripped `concept_id` is not already annotated.
- `tools.py`: `WikiSchemaLookupTool(service, annotation_store=None)` forwards it;
  `create_schema_tools` passes `store`.
- Tests listed in spec §4.

**NOT in scope**: CLI `schema lookup`; implicit-PK `REFERENCES t`; composite-FK convention.

## Files to Create / Modify

| File | Action |
|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/producers/ddl.py` | MODIFY |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/service.py` | MODIFY |
| `packages/ai-parrot/src/parrot/knowledge/wiki/schema/tools.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_ddl_producer.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_service.py` | MODIFY |
| `packages/ai-parrot/tests/knowledge/wiki/schema/test_store.py` | MODIFY |

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.context import split_namespaced_id
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.mcp_server import create_wiki_mcp_server
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config
from parrot.knowledge.wiki.schema.store import SchemaStore
```

### Existing Signatures to Use
```python
# schema/service.py:256
async def lookup(self, ref: str) -> LookupResult | list[str]
# schema/tools.py:124
def create_schema_tools(store, root, config, service=None) -> list[AbstractTool]
# schema/store.py:171
async def replace_schema_slice(self, origin, pages, columns, edges: list[tuple[str, str, str, str]]) -> dict
# store neighbors rows: {"concept_id", "rel", "provenance", "title", ..., "direction", "namespace"}
```

### Does NOT Exist
- No `annotations` merge anywhere in `schema/tools.py` today; `create_schema_tools` ignores `store`.

## Acceptance Criteria
Spec §5 AC1–AC5.

## Validation Commands
```bash
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/knowledge/wiki/schema/ -q
ruff check packages/ai-parrot/src/parrot/knowledge/wiki/schema/ packages/ai-parrot/tests/knowledge/wiki/schema/
```

## Completion Note
_(filled on close)_
