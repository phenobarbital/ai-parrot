# TASK-4013: Plane pack: broken-link, orphans, duplicate-slug, missing-body, stale-source

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M
**Depends-on**: TASK-4009
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (report-only rules). Scope violations are folded into `broken-link` (spec §2, resolved).

---

## Scope

- Implement rules in `lint/packs/plane.py`: `BrokenLinkRule` (error), `OrphanPageRule` (warning), `OrphanSourceRule` (warning), `DuplicateSlugRule` (warning), `MissingBodyRule` (warning), `StaleSourceRule` (warning).
- `broken-link`: use `store.broken_edges()`; on a `FederatedWikiStore` reuse its classification (do not flag resolvable cross-namespace edges).
- `duplicate-slug`: `_slugify(title or concept_id)` per page; group; any slug with ≥2 pages → ONE finding listing all subjects.
- `stale-source`: `SourceCollectionManager.is_stale` — skip (no finding) when `ctx.extras.get('sources')` is absent.
- Export `PLANE_RULES` list.

**NOT in scope**: Fixable rules (TASK-4014).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/plane.py` | CREATE | Report-only plane rules |
| `packages/ai-parrot/tests/knowledge/lint/test_plane_pack.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.pageindex.okf.concept_id import _slugify  # verified: pageindex/okf/concept_id.py:31
from parrot.knowledge.wiki.federation import FederatedWikiStore  # verified: wiki/federation.py:622
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
# wiki/sources.py:532  SourceCollectionManager.is_stale(source_id) -> bool
# wiki/federation.py ~1488-1523  FederatedWikiStore.broken_edges classifies cross-namespace edges
```

### Does NOT Exist
- ~~`provenance` in `dump_edges()` rows~~ — SQLite `dump_edges` returns only `src, dst, rel` (`wiki/store.py:2222-2226`)
- ~~`origin` in `dump_pages()` rows~~ — use `list_pages(origin=[...])` (`wiki/store.py:2038`) to find memory pages
- ~~`memories` / `notes` tables~~ — memories are `pages.origin='memory'`
- ~~`scope-violation` rule~~ — folded into `broken-link` (spec §8 resolved)
- ~~title uniqueness constraint~~

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/plane.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_plane_pack.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/store.py#BaseWikiStore",
    "sym:packages/ai-parrot/src/parrot/knowledge/pageindex/okf/concept_id.py#_slugify",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/federation.py#FederatedWikiStore"
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
1. Write one small class per rule with `rule_id`, `pack='plane'`, `default_severity`, `check`, `fix` returning None — *why*: protocol from TASK-4009.
2. Prefer the store fast-paths (`broken_edges`, `orphan_sources`, `missing_bodies`) — *why*: they already run in the DB on SQLite/Arango (spec §7).
3. Compute orphan pages from `ctx.edges()` (no inbound edge) excluding `adr:`/`issue:`/`spec:` ids — *why*: those are roots by design; FILL IN confirm list.

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/plane.py` (CREATE)
```python
"""Plane rule pack — report-only integrity rules (FEAT-625)."""
from __future__ import annotations

from collections import defaultdict

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.pageindex.okf.concept_id import _slugify


def _finding(rule_id: str, severity: str, subjects: list[str], message: str, **data) -> Finding:
    return Finding(
        rule_id=rule_id, severity=severity, subjects=subjects, message=message,
        fingerprint=make_fingerprint(rule_id, subjects), data=data,
    )


class _ReportOnly:
    pack = "plane"

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        return None


class BrokenLinkRule(_ReportOnly):
    """Edge target does not resolve in this wiki/namespace (also covers scope violations)."""

    rule_id, default_severity = "broken-link", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: await ctx.store.broken_edges(); one finding per (src, dst, rel), subjects=[src, dst]
        raise NotImplementedError


class DuplicateSlugRule(_ReportOnly):
    """Two or more pages whose title slugifies to the same slug."""

    rule_id, default_severity = "duplicate-slug", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        groups: dict[str, list[str]] = defaultdict(list)
        for page in await ctx.pages():
            groups[_slugify(str(page.get("title") or page["concept_id"]))].append(str(page["concept_id"]))
        return [
            _finding(self.rule_id, self.default_severity, sorted(ids), f"slug {slug!r} shared by {len(ids)} pages", slug=slug)
            for slug, ids in sorted(groups.items())
            if len(ids) > 1
        ]


class OrphanPageRule(_ReportOnly):
    rule_id, default_severity = "orphan-page", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: pages with no inbound edge; skip root id prefixes (FILL IN: confirm set)
        raise NotImplementedError


class OrphanSourceRule(_ReportOnly):
    rule_id, default_severity = "orphan-source", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        return [_finding(self.rule_id, "warning", [s], "source produced no pages") for s in await ctx.store.orphan_sources()]


class MissingBodyRule(_ReportOnly):
    rule_id, default_severity = "missing-body", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        return [_finding(self.rule_id, "warning", [c], "page has an empty body") for c in await ctx.store.missing_bodies()]


class StaleSourceRule(_ReportOnly):
    rule_id, default_severity = "stale-source", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        sources = ctx.extras.get("sources")
        if sources is None:
            return []
        # FILL IN: for entry in sources.list_sources(): if sources.is_stale(entry.source_id) -> finding
        raise NotImplementedError


PLANE_RULES = [BrokenLinkRule, OrphanPageRule, OrphanSourceRule, DuplicateSlugRule, MissingBodyRule, StaleSourceRule]
```

**Why this shape**: Rule ids and severities are fixed by spec §2/AC4/AC5. `duplicate-slug` implements the resolved definition literally: compute the slug, look it up among existing slugs. `ctx.extras['sources']` is populated by the CLI adapter (TASK-4020).

### FILL IN checklist
- [ ] broken-link federation handling
- [ ] orphan root-prefix exclusions
- [ ] stale-source loop

---

## Acceptance Criteria

- [ ] `broken-link` severity error (AC4)
- [ ] duplicate slugs detected via `_slugify` (AC5)
- [ ] Rules work on `InMemoryWikiStore`
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_plane_pack.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_plane_pack.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_plane_pack.py
async def test_broken_link_is_error(tmp_path): ...
async def test_duplicate_slug(tmp_path):
    # FILL IN: two pages titled "Foo Bar" and "foo  bar!" -> one finding with both concept_ids
    ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4013 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none

## Completion Note

Implemented by gpt-5.6-terra (codex), 1 attempt. Merged via coder_merge. Verified: lint test package passes in worktree (scoped). Closed via close_task.sh.
