# TASK-4016: ADR + memory packs: superseded-active, supersedes-broken, conflict, dangling, stale-memory

**Feature**: FEAT-625 — wikitoolkit lint
**Spec**: `sdd/specs/wikitoolkit-lint.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-4009
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 — deterministic contradiction rules + ADR status conflicts.

---

## Scope

- `adr.py`: load records via `DecisionRepository(store).inventory()` (cache in `ctx.extras['adr']`; on `DecisionError` → one `adr-inventory-unavailable` info finding).
- `AdrSupersededActiveRule` (warning): record accepted (`source_status=='accepted'`) while another record links to it with `relation=='supersedes'`.
- `AdrSupersedesBrokenRule` (error): a `supersedes` link whose `target_id` is not a known decision id / page id.
- `AdrConflictRule` (warning): two accepted records sharing an `explains` target where neither supersedes the other.
- `memory.py`: `MemoryDanglingLinkRule` (error) — outgoing edge from a memory page to a non-existent page; `StaleMemoryRule` (**warning**) — linked page `updated_at` > memory `updated_at` (content changed after the memory).

**NOT in scope**: LLM contradiction (TASK-4017).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/adr.py` | CREATE | ADR rules |
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/memory.py` | CREATE | Memory rules |
| `packages/ai-parrot/tests/knowledge/lint/test_adr_memory_packs.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ 350d206f0 (2026-10-03). Re-verify before coding.

### Verified Imports
```python
from parrot.knowledge.lint.models import Finding, FixResult, LintOptions, LintReport, Severity  # created by TASK-4009
from parrot.knowledge.lint.rule import LintRule, make_fingerprint  # created by TASK-4009
from parrot.knowledge.lint.context import LintContext  # created by TASK-4009
from parrot.knowledge.wiki.decisions.repository import DecisionRepository  # verified: wiki/decisions/repository.py:26
from parrot.knowledge.wiki.decisions.models import DecisionRecord, DecisionLink  # verified: wiki/decisions/models.py:143, :111
```

### Existing Signatures to Use
```python
# wiki/decisions/repository.py
class DecisionRepository:                                  # :26
    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None  # :29
    async def inventory(self) -> list[DecisionRecord]      # :63  raises DecisionError ADR_INVENTORY_LIMIT on overflow
# wiki/decisions/models.py
class DecisionLink(_Strict):     # :111  target_id: str; relation: Literal["explains","supported_by","supersedes"]; provenance
class DecisionRecord(_Strict):   # :143  decision_id; title; source_status: Literal["unknown","proposed","accepted","rejected","deprecated","superseded"]; links: list[DecisionLink]
# memory pages: store.list_pages(origin=["memory"]) (wiki/store.py:2038) via LintContext.memories() (TASK-4009)
```

### Does NOT Exist
- ~~`DecisionRecord.supersedes` field~~ — supersession is `links[].relation == 'supersedes'`
- ~~memories table~~
- ~~a check that superseded ADRs have a supersedes edge~~ — introduced here

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/adr.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/lint/packs/memory.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/lint/test_adr_memory_packs.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionRecord",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionLink"
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
1. FILL IN-verify where `DecisionError` is defined (`grep -rn 'class DecisionError' wiki/decisions`) before importing it — *why*: not in the verified contract.
2. Stale-memory uses `updated_at` comparison (ISO strings compare lexicographically) — *why*: memory rows carry no snapshot of the target hash; spec says 'content_hash changed after updated_at', which `updated_at` of the target captures.

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/adr.py` (CREATE)
```python
"""ADR rule pack — decision status consistency (FEAT-625)."""
from __future__ import annotations

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult
from parrot.knowledge.lint.rule import make_fingerprint
from parrot.knowledge.wiki.decisions.models import DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository


async def _records(ctx: LintContext) -> list[DecisionRecord] | None:
    """Inventory cached on ctx.extras['adr']; None when unavailable."""
    if "adr" not in ctx.extras:
        try:
            ctx.extras["adr"] = await DecisionRepository(ctx.store).inventory()
        except Exception as exc:  # FILL IN: narrow to DecisionError once its import is verified
            ctx.logger.warning("ADR inventory unavailable: %s", exc)
            ctx.extras["adr"] = None
    return ctx.extras["adr"]


class _AdrRule:
    pack = "adr"

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        return None


class AdrSupersededActiveRule(_AdrRule):
    rule_id, default_severity = "adr-superseded-active", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: superseded = {l.target_id for r in records for l in r.links if l.relation == "supersedes"};
        #          finding per record with source_status == "accepted" and decision_id (or its page id) in superseded
        raise NotImplementedError


class AdrSupersedesBrokenRule(_AdrRule):
    rule_id, default_severity = "adr-supersedes-broken", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: supersedes target_id not in {decision ids} | await ctx.page_ids()
        raise NotImplementedError


class AdrConflictRule(_AdrRule):
    rule_id, default_severity = "adr-conflict", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: group accepted records by explains target; pairs where neither supersedes the other
        raise NotImplementedError


ADR_RULES = [AdrSupersededActiveRule, AdrSupersedesBrokenRule, AdrConflictRule]
```

### `packages/ai-parrot/src/parrot/knowledge/lint/packs/memory.py` (CREATE)
```python
"""Memory rule pack — dangling and stale agent memories (FEAT-625)."""
from __future__ import annotations

from parrot.knowledge.lint.context import LintContext
from parrot.knowledge.lint.models import Finding, FixResult
from parrot.knowledge.lint.rule import make_fingerprint


class _MemoryRule:
    pack = "memory"

    async def fix(self, ctx: LintContext, finding: Finding) -> FixResult | None:
        return None


class MemoryDanglingLinkRule(_MemoryRule):
    rule_id, default_severity = "memory-dangling-link", "error"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: memory ids from await ctx.memories(); edges with src in them and dst not in await ctx.page_ids()
        raise NotImplementedError


class StaleMemoryRule(_MemoryRule):
    """A linked page changed after the memory was written (resolved: warning)."""

    rule_id, default_severity = "stale-memory", "warning"

    async def check(self, ctx: LintContext) -> list[Finding]:
        # FILL IN: for each memory edge to an existing page, target.updated_at > memory.updated_at -> warning finding
        raise NotImplementedError


MEMORY_RULES = [MemoryDanglingLinkRule, StaleMemoryRule]
```

**Why this shape**: Severities follow spec §2 and the resolved decision stale-memory = warning (AC6). ADR data is read only through `DecisionRepository.inventory()`, the bounded loader the decision plane already uses.

### FILL IN checklist
- [ ] `DecisionError` import
- [ ] three ADR checks
- [ ] two memory checks

---

## Acceptance Criteria

- [ ] Accepted-but-superseded ADR flagged
- [ ] Broken supersedes → error
- [ ] Stale memory → warning (AC6)
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/lint/test_adr_memory_packs.py -v`
- [ ] No lint errors: `ruff check` on the touched files

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/lint/test_adr_memory_packs.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/lint/test_adr_memory_packs.py
async def test_adr_superseded_active(tmp_path): ...
async def test_adr_supersedes_broken(tmp_path): ...
async def test_stale_memory_warning(tmp_path): ...
async def test_memory_dangling_link(tmp_path): ...
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug wikitoolkit-lint --feature-id FEAT-625`), never on `dev`.
2. Check every Depends-on task is `done` in `sdd/tasks/index/wikitoolkit-lint.json`.
3. Verify the Codebase Contract; fix it first if stale.
4. Implement from the blueprint; complete every `# FILL IN:`; never change fixed signatures/paths.
5. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
6. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-4016 wikitoolkit-lint verified`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
