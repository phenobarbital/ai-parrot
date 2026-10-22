# TASK-4014: Fixable plane rules: asymmetric-related, fts-index-drift

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4009, TASK-4011
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (fixable rules) — the bidirectional `related` sync and index rebuild the user asked for.

---

## Scope

- Implement `AsymmetricRelatedRule` (warning, fixable): for each edge with rel in `INVERSE_RELATIONS`, if `(dst, src, INVERSE_RELATIONS[rel])` is absent (also accept an existing `related`/`references` reverse edge as satisfying symmetry for symmetric rels), emit a finding. Skip edges whose dst is not a page (broken links are not symmetrized).
- Fix: `store.add_edges([(dst, src, inverse, "asserted")])` — never delete.
- Implement `FtsIndexDriftRule` (warning, fixable) over `store.index_drift()`; fix = `store.rebuild_index()`.
- Export `PLANE_FIX_RULES`.

**NOT in scope**: Audit logging (runner logs LINT_FIX, TASK-4010).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/plane_fix.py` | CREATE | Fixable plane rules |
| `packages/ai-parrot/tests/knowledge/lint/test_plane_fix.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                              # :525
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...  # :544
    async def add_edges(self, edges: list[tuple]) -> int: ...          # :547  (src, dst, rel, provenance)
    async def get_page(self, concept_id: str, include_body: bool = True) -> Optional[dict[str, Any]]: ...  # :565
    async def list_pages(self, category=None, limit: int = 100, origin: Optional[list[str]] = None) -> list[dict[str, Any]]: ...  # :568
    async def dump_pages(self) -> list[dict[str, Any]]: ...            # :590  keys: concept_id,node_id,title,category,summary,body,source_id,token_count,created_at,updated_at,content_hash
    async def dump_edges(self) -> list[dict[str, Any]]: ...            # :593  keys: src,dst,rel
    async def orphan_sources(self) -> list[str]: ...                   # :600
    async def broken_edges(self) -> list[dict[str, Any]]: ...          # :603  keys: src,dst,rel
    async def missing_bodies(self) -> list[str]: ...                   # :606
# added by TASK-4011 on BaseWikiStore:
async def rebuild_index(self) -> dict[str, Any]: ...
async def index_drift(self) -> dict[str, int]: ...
```

### Does NOT Exist
- ~~`provenance` in `dump_edges()` rows~~ — SQLite `dump_edges` returns only `src, dst, rel` (`wiki/store.py:2222-2226`)
- ~~a `related` relation in use today~~ — this task introduces it
- ~~edge deletion~~ — forbidden (AC2)

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/plane_fix.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_plane_fix.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore.add_edges"
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
1. Define `INVERSE_RELATIONS` exactly as spec §3 M3 — *why*: resolved decision `references` ⇒ symmetric `related`; `contains` etc. excluded.
2. Build a set of `(src, dst, rel)` once from `ctx.edges()` — *why*: O(E) symmetry check.
3. Make fix idempotent: re-check presence before `add_edges` — *why*: runner may re-run (spec §7).

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/plane_fix.py` (CREATE)
```python
"""Fixable plane rules: bidirectional related + FTS index drift (FEAT-625)."""
from __future__ import annotations

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult
from parrot.knowledge.lint.rule import make_fingerprint

INVERSE_RELATIONS: dict[str, str] = {
    "references": "related",
    "related": "related",
    "supersedes": "superseded_by",
}
SYMMETRIC_RELATIONS = frozenset({"references", "related"})


class AsymmetricRelatedRule:
    """A→B exists (references/related/supersedes) without the inverse B→A."""

    rule_id, pack, default_severity = "asymmetric-related", "plane", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: edges = await ctx.edges(); present = {(e["src"], e["dst"], e["rel"])}; page_ids = await ctx.page_ids()
        #          for each edge with rel in INVERSE_RELATIONS and dst in page_ids and src != dst:
        #            satisfied = (dst, src, INVERSE_RELATIONS[rel]) in present
        #                        or (rel in SYMMETRIC_RELATIONS and any((dst, src, r) in present for r in SYMMETRIC_RELATIONS))
        #            if not satisfied -> Finding(fixable=True, subjects=[src, dst], data={"src", "dst", "rel", "inverse"})
        raise NotImplementedError

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        d = finding.data
        await ctx.store.add_edges([(d["dst"], d["src"], d["inverse"], "asserted")])
        return FixResult(fingerprint=finding.fingerprint, applied=True, detail=f"added {d['dst']} -{d['inverse']}-> {d['src']}")


class FtsIndexDriftRule:
    """Search index row counts differ from content tables."""

    rule_id, pack, default_severity = "fts-index-drift", "plane", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        drift = await ctx.store.index_drift()
        if not drift:
            return []
        subjects = sorted(drift)
        return [Finding(rule_id=self.rule_id, severity="warning", subjects=subjects, message=f"index drift: {drift}",
                        fixable=True, fingerprint=make_fingerprint(self.rule_id, subjects), data={"drift": drift})]

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult:
        result = await ctx.store.rebuild_index()
        return FixResult(fingerprint=finding.fingerprint, applied=bool(result.get("rebuilt")), detail=str(result))


PLANE_FIX_RULES = [AsymmetricRelatedRule, FtsIndexDriftRule]
```

**Why this shape**: Implements AC3 literally (inverse `related`, provenance `asserted`). Provenance cannot be read from `dump_edges` (only src/dst/rel), so the check uses relation names only.

### FILL IN checklist
- [ ] `AsymmetricRelatedRule.check` loop + idempotence

---

## Acceptance Criteria

- [ ] A→B `references` without reverse → fix adds B→A `related` asserted; second run clean (AC3)
- [ ] `contains` never flagged
- [ ] Broken targets never symmetrized
- [ ] FTS drift repaired
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_plane_fix.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_plane_fix.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_plane_fix.py
async def test_asymmetric_references_fix(tmp_path): ...
async def test_contains_not_symmetrized(tmp_path): ...
async def test_fix_idempotent(tmp_path): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4014 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

## Completion Note

Implemented by sonnet (native), 1 attempt. Merged via coder_merge. Verified: lint test package passes in worktree (scoped). Closed via close_task.sh.
