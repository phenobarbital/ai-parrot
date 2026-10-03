# TASK-4015: Export pack: frontmatter-schema, export-drift, dangling relates_to

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-4009
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 — linting the exported markdown wiki (`docs/wiki` by default).

---

## Scope

- `ExportFrontmatter` Pydantic model with the keys `page_frontmatter` writes.
- `FrontmatterSchemaRule` (error): parse each `*.md` under the export dir except `index.md`; validate.
- `ExportDriftRule` (warning, fixable): plane ids vs exported ids, and `timestamp` != `updated_at`. Fix = `export_okf_bundle(store, export_dir, wiki_name)`.
- `ExportDanglingRelatesToRule` (error): `relates_to[].concept` not a page id.
- If `ctx.options.export_dir` is None or missing → a single `export-missing` info finding, other export rules return [].
- File reads via `asyncio.to_thread` — *no blocking in async*.

**NOT in scope**: Changing export.py output.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/export.py` | CREATE | Export rules |
| `packages/ai-parrot/tests/knowledge/lint/test_export_pack.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.wiki.export import page_frontmatter, export_okf_bundle  # verified: wiki/export.py:86, :125
```

### Existing Signatures to Use
```python
# wiki/export.py:86
def page_frontmatter(page: dict[str, Any], relates_to: list[dict[str, str]]) -> str
#   keys in order: type, title, id, tags=[category], timestamp=updated_at, summary? , relates_to? ([{concept, rel}])
# wiki/export.py:125
async def export_okf_bundle(store, output_dir, wiki_name)  # writes <out>/index.md + <category>s/<id>.md
```

### Does NOT Exist
- ~~`related:` frontmatter key~~ — export writes `relates_to` only
- ~~an existing frontmatter validator~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/export.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_export_pack.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#page_frontmatter",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/export.py#export_okf_bundle"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Async throughout; never block the event loop (file I/O via `asyncio.to_thread`).
- Pydantic v2; `self.logger` / `logging.getLogger(__name__)`; Google docstrings; 120 cols.
- Writes only through store/export APIs — never raw SQL from a rule; never delete pages or edges (spec AC2).

### References in Codebase
- Spec `sdd/specs/wikitoolkit-lint.spec.md` §2–§7 (rule ids, severities, decisions are fixed there).

---

## Implementation Blueprint

### Steps (in order)
1. Load + parse the export once into `ctx.extras['export']` — *why*: three rules share it.
2. Use `yaml.safe_load` on the block between the first two `---` lines — *why*: mirrors `page_frontmatter` rendering.

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/export.py` (CREATE)
```python
"""Export rule pack — lint the exported markdown/OKF wiki (FEAT-625)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.wiki.export import export_okf_bundle


class ExportFrontmatter(BaseModel):
    """Schema of the frontmatter written by ``wiki.export.page_frontmatter``."""

    type: str
    title: str
    id: str
    tags: list[str]
    timestamp: str
    summary: str | None = None
    relates_to: list[dict[str, str]] | None = None


def _read_export(export_dir: Path) -> dict[str, dict[str, Any]]:
    """Return ``{path: {"meta": dict|None, "error": str|None}}`` for every page file (sync; run in a thread)."""
    # FILL IN: glob **/*.md excluding index.md; split frontmatter; yaml.safe_load; capture parse errors
    raise NotImplementedError


async def _export(ctx: LintContext) -> dict[str, dict[str, Any]] | None:
    export_dir = ctx.options.export_dir
    if export_dir is None or not Path(export_dir).is_dir():
        return None
    if "export" not in ctx.extras:
        ctx.extras["export"] = await asyncio.to_thread(_read_export, Path(export_dir))
    return ctx.extras["export"]


class FrontmatterSchemaRule:
    rule_id, pack, default_severity = "frontmatter-schema", "export", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: None export -> [Finding(rule_id="export-missing", severity="info", ...)];
        #          else validate each meta with ExportFrontmatter.model_validate, ValidationError -> error finding
        raise NotImplementedError

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        return None


class ExportDriftRule:
    rule_id, pack, default_severity = "export-drift", "export", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: compare {meta.id} with await ctx.page_ids() both ways, and meta.timestamp vs page updated_at; fixable=True
        raise NotImplementedError

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        # FILL IN: run export_okf_bundle ONCE per run (guard with ctx.extras["export_refreshed"]), then ctx.extras.pop("export")
        raise NotImplementedError


class ExportDanglingRelatesToRule:
    rule_id, pack, default_severity = "export-dangling-relates-to", "export", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: relates_to[].concept not in await ctx.page_ids()
        raise NotImplementedError

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        return None


EXPORT_RULES = [FrontmatterSchemaRule, ExportDriftRule, ExportDanglingRelatesToRule]
```

**Why this shape**: Frontmatter schema mirrors `page_frontmatter` exactly (spec M5). Drift fix re-exports through the real exporter, never by editing files directly (spec §7: writes via store/export APIs).

### FILL IN checklist
- [ ] `_read_export`
- [ ] three check bodies
- [ ] single re-export guard

---

## Acceptance Criteria

- [ ] Missing `id` → `frontmatter-schema` error
- [ ] Drift fixed by re-export, re-check clean
- [ ] No export dir → only `export-missing` info
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_export_pack.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_export_pack.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_export_pack.py
async def test_frontmatter_schema_invalid(tmp_path): ...
async def test_export_drift_fix(tmp_path): ...
async def test_no_export_dir_is_info(tmp_path): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4015 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
