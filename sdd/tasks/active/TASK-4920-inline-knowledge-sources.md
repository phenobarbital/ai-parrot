# TASK-4920: Inline knowledge sources — bundled, workspace, ADR

**Feature**: FEAT-778 — Domain Experts
**Spec**: `sdd/specs/domain-experts.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4919
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (inline adapters), G2, G6, §8 Q5, codex S6. Three adapters that produce INLINE layers:

- `BundledSource` — Tier 1: `tier1_expert` from `bundle.knowledge_files`; `tier1_shared` from an optional shared
  directory (none ships in this feature — the registry passes `None`).
- `WorkspaceSource` — Tier 2: `tier2_expert` from `<bundle.root>/tenants/<bundle.tenant>/knowledge/*.md` when the
  bundle carries a tenant; `tier2_shared` from an optional shared dir (the registry passes `AGENTS_DIR/knowledge`
  when it exists — that is why `knowledge` becomes a reserved tenant name in TASK-4925).
  Tier 2 shadows Tier 1 **by file name** unless the manifest is `global_only` (AC7, SkillView semantics).
- `ADRSource` — accepted ADRs through `DecisionService.why()`.

**Task-time contract correction (verified at `9d5a6476b8`)**: the spec says the ADR layer's revision is
`record.content_fingerprint`, but `DecisionService.why()` returns a `DecisionDossier` whose entries are
`DecisionHit`s — they carry `decision_id` and an integer `revision`, not `content_fingerprint`. Use
`revision = sha256_revision(f"{hit.decision_id}:{hit.revision}".encode())`. The link filter reads
`hit.applicability` (a list of `DecisionLink` with `target_id`), not `record.links`.

---

## Scope

- Create `sources/bundled.py`, `sources/workspace.py`, `sources/adr.py`.
- Write `test_sources_inline.py` (uses a stub `DecisionService`; no real ADR store).

**NOT in scope**: wiki (TASK-4921), bookstore/graphindex/kb (TASK-4922), proposing ADRs (TASK-4927).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/bundled.py` | CREATE | Tier-1 adapter |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/workspace.py` | CREATE | Tier-2 adapter |
| `packages/ai-parrot/src/parrot/experts/knowledge/sources/adr.py` | CREATE | Accepted-ADR adapter |
| `packages/ai-parrot/tests/experts/test_sources_inline.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.service import DecisionService   # verified: decisions/service.py:96
from parrot.knowledge.wiki.decisions.models import DecisionHit, DecisionDossier   # verified: decisions/models.py:224,240
from parrot.experts.knowledge.budget import sha256_revision           # TASK-4919
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)               # TASK-4914
from parrot.memory.compaction.tokens import TokenCounter              # verified: tokens.py:30
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py
class DecisionService:                                                       # line 96
    async def why(self, question: str, *, include_history: bool = False,
                  limit: int = 10, budget_tokens: int = 3000) -> DecisionDossier   # line 276
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py
class DecisionHit(_Strict):            # line 224
    decision_id: str; revision: int; title: str = ""; origin: Literal["documented", "inferred"]
    source_status: str = "unknown"; review_status: Literal["unreviewed", "accepted", "rejected"] = "unreviewed"
    decision: str = ""; applicability: list[DecisionLink] = []
class DecisionDossier(_Strict):        # line 240
    status: Literal["ok", "empty", "ambiguous", "partial", "error"]; documented: list[DecisionHit]; candidates: list[DecisionHit]
class DecisionLink(_Strict):           # line 140
    target_id: str; relation: Literal["explains", "supported_by", "supersedes"]
```

### Does NOT Exist
- ~~`DecisionHit.content_fingerprint`~~ / ~~`DecisionHit.links`~~ — only `DecisionRecord` has those; `why()` never returns records.
- ~~`DecisionRecord.tags`~~ — no tags field exists (spec S6); filter only by status and links.
- ~~`DecisionService.get` / `DecisionService.show`~~ — no single-record getter exists on the service.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/bundled.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/workspace.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/experts/knowledge/sources/adr.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/experts/test_sources_inline.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/service.py#DecisionService.why",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionHit",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionDossier"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- File order: sort `*.md` by name — determinism (AC4). `revision = sha256_revision(path.read_bytes())`.
- Layer `source` string: the path relative to the bundle root (Tier 1) or to the shared dir — never absolute, so
  the serialized context is machine-independent.
- ADR: keep hits whose `source_status` is in `spec.filter.get("status", ["accepted"])` and `review_status !=
  "rejected"`; when `spec.filter.get("links")` is set, require at least one `applicability[i].target_id` in it.
  Consider both `dossier.documented` and `dossier.candidates`. `budget_tokens=3000`, `limit=10` (§8 Q5).

---

## Implementation Blueprint

### Steps (in order)
1. `bundled.py` and `workspace.py` (shared helper inline in each — two short files, no shared module).
2. `adr.py` with a stub-friendly constructor (`service` is injected).

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/bundled.py` (CREATE)
```python
"""Tier-1 knowledge: files shipped with the bundle (FEAT-778 M5)."""
from __future__ import annotations

from pathlib import Path

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)
from parrot.memory.compaction.tokens import TokenCounter


class BundledSource:
    """tier1_shared from `shared_dir` (optional) and tier1_expert from the bundle's knowledge files."""

    kind = KnowledgeSourceKind.BUNDLED

    def __init__(self, shared_dir: Path | None = None) -> None:
        self.shared_dir = shared_dir

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """Inline Tier-1 layers; a tenant file with the same name shadows a Tier-1 file unless global_only (AC7)."""
        shadowed: set[str] = set()
        if bundle.tenant and not bundle.manifest.global_only:
            tenant_dir = bundle.root / "tenants" / bundle.tenant / "knowledge"
            shadowed = {p.name for p in tenant_dir.glob("*.md")} if tenant_dir.is_dir() else set()
        # FILL IN: build tier1_shared layers (sorted) then tier1_expert layers from bundle.knowledge_files (sorted,
        # skipping names in `shadowed`); content=text, tokens=counter.count(text), revision=sha256_revision(bytes),
        # source=relative path — bounded by AC4, AC6, AC7
        return []
```

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/workspace.py` (CREATE)
```python
"""Tier-2 knowledge: workspace and tenant files (FEAT-778 M5)."""
from __future__ import annotations

from pathlib import Path

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)
from parrot.memory.compaction.tokens import TokenCounter


class WorkspaceSource:
    """tier2_shared from `shared_dir` (optional) and tier2_expert from <root>/tenants/<tenant>/knowledge."""

    kind = KnowledgeSourceKind.WORKSPACE

    def __init__(self, shared_dir: Path | None = None) -> None:
        self.shared_dir = shared_dir

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """Inline Tier-2 layers; nothing for the tenant part when bundle.tenant is None."""
        # FILL IN: same layer construction as BundledSource with layer names tier2_shared / tier2_expert;
        # skip tenant files entirely when bundle.manifest.global_only (they were dropped by the view) — AC7
        return []
```

### `packages/ai-parrot/src/parrot/experts/knowledge/sources/adr.py` (CREATE)
```python
"""Accepted ADRs as inline knowledge (FEAT-778 M5, consumer side)."""
from __future__ import annotations

from pathlib import Path

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.models import (ExpertBundle, KnowledgeLayer, KnowledgeMode, KnowledgeSourceKind,
                                   KnowledgeSourceSpec)
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.memory.compaction.tokens import TokenCounter

ADR_BUDGET_TOKENS = 3000
ADR_LIMIT = 10


class ADRSource:
    """Inline 'adr' layers from DecisionService.why(); accepted and not rejected only (AC9)."""

    kind = KnowledgeSourceKind.ADR

    def __init__(self, service: DecisionService) -> None:
        self.service = service

    async def layers(self, spec: KnowledgeSourceSpec, bundle: ExpertBundle, *, workspace: Path | None,
                     counter: TokenCounter) -> list[KnowledgeLayer]:
        """One layer per kept hit; content = '### <title>\\n<decision>'; revision from decision_id:revision."""
        dossier = await self.service.why(bundle.manifest.description, limit=ADR_LIMIT,
                                         budget_tokens=ADR_BUDGET_TOKENS)
        hits = [*dossier.documented, *dossier.candidates]
        # FILL IN: filters per Key Constraints; layer source = f"adr:{hit.decision_id}";
        # revision = sha256_revision(f"{hit.decision_id}:{hit.revision}".encode()) — bounded by AC9, AC6
        return []
```

### FILL IN checklist
- [ ] `BundledSource.layers` — shared then expert layers, shadowing; AC7.
- [ ] `WorkspaceSource.layers` — tenant layers, global_only skip; AC7.
- [ ] `ADRSource.layers` — status/review/link filters; AC9.

---

## Acceptance Criteria

- [ ] AC7 — a tenant file shadows the Tier-1 file of the same name; with `global_only: true` it does not.
- [ ] AC9 (consumer part) — proposed, rejected and superseded hits never produce a layer.
- [ ] AC6 — every layer has `tokens` from the counter and a sha256 `revision`.
- [ ] `ruff check` passes.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_sources_inline.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/experts/test_sources_inline.py — expert_bundle fixture (TASK-4914) + stub service
def test_bundled_source_emits_tier1_with_revisions(expert_bundle): ...   # FILL IN
def test_tenant_file_shadows_tier1(expert_bundle): ...                    # FILL IN
def test_global_only_blocks_shadowing(expert_bundle): ...                 # FILL IN
def test_workspace_source_without_tenant_is_empty(expert_bundle): ...     # FILL IN
def test_adr_source_filters_accepted_only(): ...                          # FILL IN: stub why() returning 4 hits
def test_adr_source_links_filter(): ...                                   # FILL IN
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug domain-experts --feature-id FEAT-778`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/domain-experts.json`
4. **Verify the Codebase Contract** — before writing ANY code, confirm every import and signature still exists;
   if anything changed, update the contract FIRST. Never reference a name not in the contract without verifying it.
5. **Update status** in `sdd/tasks/index/domain-experts.json` → `"in-progress"` (set `started_at`) and commit only that file
6. **Implement** — start from the Implementation Blueprint, complete every `# FILL IN:` marker, never change a
   signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src`
   (add `packages/ai-parrot-server/src` when the task touches the server) and `ruff check` the files you changed
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4920 domain-experts verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
