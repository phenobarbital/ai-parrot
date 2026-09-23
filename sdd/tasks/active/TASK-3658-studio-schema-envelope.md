# TASK-3658: Studio GET /toolkits/{slug}/schema returns the JSON Schema envelope (hard cut)

**Feature**: FEAT-593 — Tool Configuration for Agent Studio
**Spec**: `sdd/specs/tool-configuration-agentstudio.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3647
**Assigned-to**: unassigned

---

## Context

Spec §2 Overview (4), design research S8, AC6. Hard cut (no SPA consumer exists): the
`params` map is replaced by one Draft 2020-12 envelope. FEAT-540 overlap: keep the current
`from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig` import (resolved 2026-09-23).

---

## Scope

- `_wiki_schema()` → `build_schema_envelope("wiki", LLMWikiToolkit, server_managed=frozenset({...same 3...}))`
  then embed `WikiConfig.model_json_schema()` as the `config` property's schema (keep `x-server-managed` on the 3 toolkits).
- `_dataset_manager_schema()` → `DatasetManager.config_schema("dataset_manager")`.
- `_infographic_schema()` → envelope with `server_managed=frozenset({"artifact_store"})`.
- Generic branch → `cls.config_schema(slug)` when `issubclass(cls, AbstractToolkit)`, else
  `build_schema_envelope(slug, cls)`.
- Rewrite `TestToolkitSchema` (5 tests) for the new shape; keep all POST tests untouched.

**NOT in scope**: POST assignment (unchanged); new endpoints (TASK-3660).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` | MODIFY | GET returns {slug, class_name, source, schema} |
| `packages/ai-parrot-server/tests/studio/test_toolkits.py` | MODIFY | Update TestToolkitSchema to the envelope contract |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references (dev @ `ce602539c`, 2026-09-23). Use these exact imports,
> names and signatures. Anything not listed here must be verified with `grep`/`read` first.

### Verified Imports
```python
from parrot.tools.config_schema import build_schema_envelope  # created by TASK-3646
from parrot.tools.toolkit import AbstractToolkit  # verified: tests/studio/test_toolkits.py:27 imports it
from parrot.knowledge.wiki import LLMWikiToolkit, WikiConfig  # verified: toolkits.py:27 (keep as-is — FEAT-540)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py
    async def get(self):  # :235 — generic branch builds `schema = {` … `}` at :250-254 ← anchor
    @staticmethod
    def _wiki_schema() -> dict:  # :259 (server_managed pageindex_toolkit/graphindex_toolkit/okf_toolkit; WikiConfig schema :265)
    @staticmethod
    def _dataset_manager_schema() -> dict:  # :269 ← anchor
    @staticmethod
    def _infographic_schema() -> dict:  # :277 (server_managed artifact_store)
# packages/ai-parrot-server/tests/studio/test_toolkits.py
class TestToolkitSchema:  # :82 — 5 tests asserting the OLD params-map shape (rewrite them)
```

### Does NOT Exist
- ~~a `params` key in the new response~~ — replaced by `schema` (hard cut).
- ~~`TOOL_REGISTRY["wiki"]` / `["infographic"]`~~ — keep the explicit slug branches.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_toolkits.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler.get",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler._wiki_schema",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler._dataset_manager_schema",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py#StudioToolkitsHandler._infographic_schema"
  ]
}
```

---

## Implementation Notes

The envelope dicts are `model_dump(by_alias=True)` so the key is `schema`, not `schema_`.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block to its declared path nearly
> verbatim, then complete every `# FILL IN:` marker. Blocks derive from the spec's Interface
> Skeletons (§3) and the §6 Edit Sites table, re-verified at task time. Never change a
> signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Rewrite the three static helpers and the generic branch — *why*: AC6.
2. Update the 5 schema tests — *why*: they assert the old contract.

### `packages/ai-parrot-server/src/parrot/handlers/studio/toolkits.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            schema = {' toolkits.py) — generic branch of get() (:250-254)
# REPLACE the `schema = {"slug": ..., "class_name": ..., "params": _introspect_params(cls)}` literal with:
            if isinstance(cls, type) and issubclass(cls, AbstractToolkit):
                schema = cls.config_schema(slug)
            else:
                schema = build_schema_envelope(slug, cls).model_dump(by_alias=True)

# occurrences: 1 (verified: grep -c '    def _dataset_manager_schema() -> dict:' toolkits.py)
# REPLACE the bodies of the three helpers (:259-282):
    @staticmethod
    def _wiki_schema() -> dict:
        env = build_schema_envelope(
            "wiki", LLMWikiToolkit,
            server_managed=frozenset({"pageindex_toolkit", "graphindex_toolkit", "okf_toolkit"}),
        ).model_dump(by_alias=True)
        # FILL IN: env["schema"]["properties"]["config"] = WikiConfig.model_json_schema() (keep required)
        return env

    @staticmethod
    def _dataset_manager_schema() -> dict:
        return DatasetManager.config_schema("dataset_manager")

    @staticmethod
    def _infographic_schema() -> dict:
        return build_schema_envelope(
            "infographic", InfographicToolkit, server_managed=frozenset({"artifact_store"})
        ).model_dump(by_alias=True)
```

### `packages/ai-parrot-server/tests/studio/test_toolkits.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'class TestToolkitSchema:' test_toolkits.py)
# REPLACE the body of `class TestToolkitSchema:` (verified: test_toolkits.py:82-152) — see Test Specification
```

### FILL IN checklist
- [ ] wiki `config` property embedding; bounded by the old test's storage_dir/wiki_name assertions
- [ ] Remove `_introspect_params` usage from GET only (POST still uses `_missing_required_params`)

---

## Acceptance Criteria

- [ ] All three explicit slugs + generic return `{slug, class_name, source, schema}` (AC6).
- [ ] `dataset_manager` → `source == "model"` with the datasource `oneOf`.
- [ ] `artifact_store` and the 3 wiki toolkits carry `x-server-managed: true`.
- [ ] All POST tests in test_toolkits.py still pass.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot-server/tests/studio/test_toolkits.py -q`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/studio/test_toolkits.py — new TestToolkitSchema
class TestToolkitSchema:
    def test_wiki_envelope(self):
        env = StudioToolkitsHandler._wiki_schema()
        props = env["schema"]["properties"]
        assert env["slug"] == "wiki" and props["pageindex_toolkit"]["x-server-managed"] is True
        assert "storage_dir" in props["config"]["properties"]

    def test_dataset_manager_envelope_is_model(self):
        env = StudioToolkitsHandler._dataset_manager_schema()
        assert env["source"] == "model"
        assert env["schema"]["properties"]["datasources"]["items"]["discriminator"]["propertyName"] == "kind"

    def test_infographic_marks_server_managed(self):
        props = StudioToolkitsHandler._infographic_schema()["schema"]["properties"]
        assert props["artifact_store"]["x-server-managed"] is True

    @pytest.mark.asyncio
    async def test_generic_envelope(self, monkeypatch):
        app = web.Application()
        monkeypatch.setattr(toolkits_module, "_resolve_toolkit_class",
                            lambda slug: _NeedsArgToolkit if slug == "needs_arg" else None)
        handler = _make_handler(app, method="GET", path="/toolkits/needs_arg/schema", match_info={"slug": "needs_arg"})
        body = await _decode(await _unwrap(StudioToolkitsHandler.get)(handler))
        assert body["class_name"] == "_NeedsArgToolkit" and "foo" in body["schema"]["required"]

    # keep test_unknown_generic_slug_404 unchanged
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context (§2 Overview, §3 module, §7 risks).
2. **Check dependencies** — verify every `Depends-on` task is in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — before writing ANY code, confirm every import and
   signature listed still exists (`grep`/`read`). If anything moved, update the contract first.
4. **Update status** in `sdd/tasks/index/tool-configuration-agentstudio.json` → `"in-progress"`.
5. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:`
   marker, and never change a signature or path the blueprint fixes.
6. **Verify** all acceptance criteria; run the Validation Commands (in a worktree prefix with
   `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src:packages/ai-parrot-tools/src`).
7. **Move this file** to `sdd/tasks/completed/` and set the index entry to `"done"`.
8. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
