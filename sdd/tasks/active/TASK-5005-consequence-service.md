# TASK-5005: ConsequenceService — evaluate and governing (M6b)

**Feature**: FEAT-784 — SDD Decision Audit
**Spec**: `sdd/specs/sdd-decision-audit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5004, TASK-4999, TASK-5002
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 — the heart of the feature. `ConsequenceService.evaluate()` turns a spec into a
`ConsequenceReport` (parse → validate taxonomy/targets/links/waivers → snapshot → baseline → impact → judge →
digests); `governing()` builds the complete governing dossier from the same snapshot. The owner marked M6
**not delegation-eligible** (fingerprint canonicalization and baseline/replay semantics need the thinking model),
so this task deliberately leaves the judgement rules as bounded `FILL IN`s. Zero LLM calls (AC1, G3).

---

## Scope

- Append `audit_configured()`, `ConsequenceService.__init__`, `evaluate()`, `governing()` and private helpers
  to `decisions/consequences.py` below the `# --- evaluator (TASK-5005) ---` marker created by TASK-5004.
- Implement the five finding kinds: blocking `contradiction` (only from an explicit unresolved `contradicts`
  reference, either direction — AC4), advisory `potential-conflict`, `possible-supersession`, `blast-radius`,
  `evidence-gap`.
- Implement waiver binding (AC9), the `skipped` portability path (G8, AC19), status precedence (AC11).
- Write `test_consequences.py` with the spec §4 M6 tests.

**NOT in scope**: Markdown rendering/splicing (TASK-5006), publication (TASK-5007), service wiring from a repo
root (`spec_audit.py`, TASK-5008), CLI/MCP/gate surfaces.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py` | MODIFY | Add `audit_configured` and `ConsequenceService` below the TASK-5004 marker |
| `packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences.py` | CREATE | Spec §4 M6 unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord, DecisionDiagnostic, DecisionError  # verified: models.py:63,172,215,47
from parrot.knowledge.wiki.decisions.repository import DecisionRepository        # verified: repository.py:26
from parrot.knowledge.wiki.decisions.evidence import verify_freshness            # verified: evidence.py:226
from parrot.knowledge.wiki.structural.service import StructuralService, BlastRadiusOutput  # verified: structural/service.py:130, :93
from parrot.knowledge.wiki.store import BaseWikiStore                            # verified: store.py (get_page :765)
# Created by earlier FEAT-784 tasks (spec §3 skeletons):
from parrot.knowledge.wiki.decisions.spec_entries import parse_spec_decisions, canonical_block_bytes, entries_to_records  # TASK-4999
from parrot.knowledge.wiki.decisions.taxonomy import Taxonomy                    # TASK-5000
from parrot.knowledge.wiki.decisions.approvals import ApprovalManifest, ApprovalAdapter   # TASK-5001
from parrot.knowledge.wiki.decisions.scope import TargetResolver, ResolvedTarget  # TASK-5002
from parrot.knowledge.wiki.decisions.inventory import InventorySnapshot, RULES_VERSION    # TASK-5003
from parrot.knowledge.wiki.decisions.models import (                              # TASK-4997 constants
    SPEC_BLOCK_MISSING, TARGET_UNRESOLVED, WAIVER_INVALID, SUPERSESSION_INVALID, SNAPSHOT_UNSTABLE,
    SCOPE_INCOMPLETE, AUDIT_NOT_CONFIGURED, ADR_INVENTORY_LIMIT, ADR_SCHEMA_UNSUPPORTED,
)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py
class DecisionRepository:                                         # line 26
    def __init__(self, store: BaseWikiStore, max_records: int = 10_000) -> None   # line 29
    async def inventory(self) -> list[DecisionRecord]             # line 63 — raises DecisionError(ADR_INVENTORY_LIMIT) on overflow; decode failures → self.last_diagnostics

# packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py
async def verify_freshness(root: Path | None, evidence: EvidenceRef) -> tuple[str, DecisionDiagnostic | None]   # line 226

# packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py
_BLAST_RADIUS_NODE_CAP = 500                                      # line 42
class BlastRadiusOutput(BaseModel): root; impacted: list[ImpactedSymbol]; files: list[str]; truncated: bool = False   # line 93
class StructuralService:                                          # line 130
    def __init__(self, store, root: Path, config: WikiProjectConfig, *, read_repair: bool = True)   # line 143
    async def blast_radius(self, symbol: str, *, relations: list[str] | None = None, depth: int = 2,
                           include_inferred: bool = True, include_tests: bool = True) -> BlastRadiusOutput   # line 360
# ImpactedSymbol fields: symbol: SymbolHit, via: str, distance: int, provenance: str   (class at line 84)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
async def page_hashes(self, concept_ids: list[str]) -> dict[str, Optional[str]]   # line 1074 (sqlite override :2362)

# TASK-5004 (same file): Status, EXIT_CODES, CoverageSummary, Finding, GoverningEntry, GoverningDossier,
#   ConsequenceReport, finding_fingerprint, canonicalize_spec, input_digest, evaluation_digest, status_precedence
# TASK-5003: InventorySnapshot.take(repo, taxonomy, approvals, adapter, structural_revision) -> InventorySnapshot
#   .eligible: list[DecisionRecord]; .manifest: SnapshotManifest; .diagnostics; .effective_head(id); .governing(about, scope_ids)
# TASK-5002: TargetResolver(store, root, structural).resolve(target_id) / .ancestors_of(page_id) / .expand_dir(dir_id)
# TASK-4999: parse_spec_decisions(text, *, source_path) -> (SpecDecisionsBlock | None, list[ConflictWaiver], list[DecisionDiagnostic])
```

### Does NOT Exist
- ~~`DecisionService.why()` / `for_symbol()` / `pack_dossier()` as gate inputs~~ — they are budgeted and omit records (audit F02). The evaluator consumes `InventorySnapshot.eligible` ONLY.
- ~~`StructuralService.lookup()` as an id validator~~ — lexical (F05); exact validation is `TargetResolver`.
- ~~multi-record transactions on `BaseWikiStore`~~.
- ~~`ADR_UNSUPPORTED_SCHEMA`~~ — use `ADR_SCHEMA_UNSUPPORTED` (models.py:19).
- ~~`review_status == "accepted"` as an eligibility requirement~~ — F03 double-acceptance trap; eligibility is TASK-5003's `is_eligible`.
- ~~`spec_audit.py` / `open_consequence_service`~~ — TASK-5008; do not build services from a repo root here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/repository.py#DecisionRepository.inventory",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/evidence.py#verify_freshness",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#StructuralService.blast_radius",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/structural/service.py#BlastRadiusOutput",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionConfig",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/models.py#DecisionRecord"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never raise for spec/content faults** — return a report with status `invalid`/`incomplete` and diagnostics.
  Only programmer errors may raise. Precedence via `status_precedence` (TASK-5004); keep ALL diagnostics (spec §4 `test_status_precedence`).
- **`skipped`** only when `audit_configured(...)` is False AND the spec has no `## Decisions` block. A block in an
  unconfigured repo is `invalid` with `AUDIT_NOT_CONFIGURED` (spec §2 portability).
- **Structural snapshot (S6)**: the caller passes a `StructuralService` built with `read_repair=False`. Document
  that in the class docstring; if `structural._read_repair` is True, emit a diagnostic and treat as `incomplete`
  (a rescan during evaluation silently changes the snapshot — §7).
- `BlastRadiusOutput.truncated` ⇒ `coverage.impact_complete = False` ⇒ `incomplete` (S6, AC11). Never read truncation as "no more impact".
- Impact relations: `["calls", "extends", "implements", "uses"]`, `depth=2`, `include_tests=True`; record
  `provenance == "inferred"` impacted symbols separately in the blast-radius finding message (spec M6).
- Impact NEVER propagates applicability: a dependent outside a target's scope gets a `blast-radius` finding only (AC7).
- Blocking is reserved for `contradiction` (AC4). Target/polarity overlap (e.g. forbid httpx + require aiohttp on
  the same file) is `potential-conflict`, `blocking=False`.
- Conflict on the 51st record must still block (AC5): iterate the full `snapshot.eligible`, never a limited list.
- Async throughout; `asyncio.to_thread` for reading the spec file. Logging via `self.logger`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the imports from the Verified Imports block to the top of `consequences.py` (merge with TASK-5004's), plus stdlib `import asyncio`, `import logging`, `from pathlib import Path` — *why*: the blueprint may not introduce symbols outside the contract.
2. Paste block A below the marker, then block B — *why*: keeps `__init__`/`evaluate` (orchestration) separate from the judging helpers so each stays under ~80 lines.
3. Fill the judging `FILL IN`s, bounded by the cited ACs — *why*: these are the owner-reserved design calls.
4. Write the tests with the spec §4 fixtures (`decision_plane`, `spec_with_decisions`), run validation.

### `consequences.py` — block A (MODIFY)
```python
# occurrences: 1 (anchor defined by TASK-5004's blueprint; verify: grep -c '^# --- evaluator (TASK-5005) ---$' packages/ai-parrot/src/parrot/knowledge/wiki/decisions/consequences.py)
# AFTER — insert below `# --- evaluator (TASK-5005) ---` (created by TASK-5004)

_IMPACT_RELATIONS = ["calls", "extends", "implements", "uses"]


def audit_configured(taxonomy_path: Path, approvals_path: Path) -> bool:
    """Decision audit is configured when the taxonomy OR the approvals manifest exists (spec §2 portability)."""
    return taxonomy_path.is_file() or approvals_path.is_file()


class ConsequenceService:
    """Deterministic spec-decision evaluator. Zero LLM calls (AC1).

    ``structural`` MUST be built with ``read_repair=False`` (spec S6) so an
    evaluation never rescans or mutates the plane.
    """

    def __init__(
        self, store: BaseWikiStore, root: Path, config: DecisionConfig, structural: StructuralService,
        *, taxonomy_path: Path, approvals_path: Path, adapter: ApprovalAdapter,
    ) -> None:
        self.store, self.root, self.config, self.structural = store, root, config, structural
        self.taxonomy_path, self.approvals_path, self.adapter = taxonomy_path, approvals_path, adapter
        self.resolver = TargetResolver(store, root, structural)
        self.logger = logging.getLogger(__name__)

    async def evaluate(self, spec_path: Path, *, mode: Literal["preview", "replay"] = "preview") -> ConsequenceReport:
        """Never raises for spec/content faults. Precedence invalid > incomplete > conflict > pass."""
        text = await asyncio.to_thread((self.root / spec_path).read_text, encoding="utf-8")
        rel = spec_path.as_posix()
        block, waivers, diagnostics = parse_spec_decisions(text, source_path=rel)
        has_block = block is not None or any(d.code != SPEC_BLOCK_MISSING for d in diagnostics)
        if not audit_configured(self.taxonomy_path, self.approvals_path):
            if not has_block:
                return ConsequenceReport(status="skipped", exit_code=EXIT_CODES["skipped"])
            diagnostics.append(DecisionDiagnostic(code=AUDIT_NOT_CONFIGURED, message="spec declares decisions but decision audit is not configured", path=rel))
            return self._finish("invalid", text, block, waivers, None, [], diagnostics, CoverageSummary())
        statuses: list[str] = ["invalid"] if any(d.code != SPEC_BLOCK_MISSING for d in diagnostics) else []
        try:
            taxonomy = Taxonomy.load(self.taxonomy_path)
            approvals = ApprovalManifest.load(self.approvals_path)
            snapshot = await InventorySnapshot.take(
                DecisionRepository(self.store, self.config.max_records), taxonomy, approvals, self.adapter,
                await self._structural_revision(),
            )
        except DecisionError as exc:
            diagnostics.append(DecisionDiagnostic(code=exc.code, message=exc.message, path=rel))
            # FILL IN: map exc.code → status: TAXONOMY_INVALID/APPROVAL_MANIFEST_INVALID ⇒ "invalid";
            #   ADR_INVENTORY_LIMIT/SNAPSHOT_UNSTABLE/ADR_SCHEMA_UNSUPPORTED ⇒ "incomplete" — bounded by AC11
            return self._finish("incomplete", text, block, waivers, None, [], diagnostics, CoverageSummary(inventory_complete=False))
        diagnostics.extend(snapshot.diagnostics)
        coverage = CoverageSummary()
        findings: list[Finding] = []
        if block is not None:
            # FILL IN: (1) about ids ∉ taxonomy.ids() ⇒ invalid + closest() suggestions in the message;
            #   (2) resolve every target via self.resolver.resolve — missing/foreign ⇒ invalid (AC7), incomplete scope ⇒ incomplete (SCOPE_INCOMPLETE);
            #   (3) baseline: mode="replay" excludes the spec's own already-approved batch records from the
            #       comparison set so an approved batch never conflicts with itself (spec §4 test_replay_uses_recorded_baseline, AC12);
            #       a revision entry pins previous_revision and compares against the predecessor revision only (AC3);
            #   (4) findings = await self._judge(block, waivers, snapshot, resolved, coverage)
            pass
        # FILL IN: coverage.subsystems = taxonomy.map_projects(frontmatter projects, tags); coverage.unmapped_tags likewise (TASK-5000 API)
        statuses.append("conflict" if any(f.blocking and f.waived_by is None for f in findings) else "pass")
        if not (coverage.impact_complete and coverage.inventory_complete):
            statuses.append("incomplete")
        return self._finish(status_precedence(statuses), text, block, waivers, snapshot.manifest, findings, diagnostics, coverage)
```
**Why**: the order parse → configured check → snapshot → judge is spec §3 M6 verbatim. `skipped` short-circuits
before any store access so unconfigured repos never need a built wiki (G8). `has_block` treats a malformed block
as "declared" — an author who tried to declare decisions must get `invalid`, not `skipped`.

### `consequences.py` — block B (MODIFY, directly after block A, same class)
```python
    def _finish(self, status, text, block, waivers, manifest, findings, diagnostics, coverage) -> ConsequenceReport:
        """Compute digests and assemble the report (pure)."""
        block_bytes = canonical_block_bytes(block) if block is not None else b""
        waiver_bytes = json.dumps([w.model_dump(mode="json") for w in waivers], sort_keys=True, separators=(",", ":")).encode()
        config_digest = _sha256(_canonical(self.config.model_dump(mode="json")))
        idig = input_digest(canonicalize_spec(text), block_bytes, waiver_bytes, config_digest, manifest)
        ordered = sorted(findings, key=lambda f: (f.kind, f.fingerprint))
        return ConsequenceReport(
            status=status, exit_code=EXIT_CODES[status], input_digest=idig,
            evaluation_digest=evaluation_digest(idig, ordered), snapshot=manifest,
            findings=ordered, diagnostics=sorted(diagnostics, key=lambda d: (d.code, d.path or "", d.decision_id or "", d.message)),
            coverage=coverage,
        )

    async def _structural_revision(self) -> str:
        """Content hash of the structural plane as consulted (AC10)."""
        # FILL IN: sha256 over the sorted (concept_id, content_hash) pairs of the structural pages this
        #   evaluation can consult (use self.store.page_hashes, store.py:1074). Must change when a symbol page
        #   or a structural edge changes even if no ADR page changed — bounded by AC10. If the plane exposes no
        #   enumerable revision, return "unknown" AND add a diagnostic so the report is `incomplete`.
        raise NotImplementedError

    async def _judge(self, block, waivers, snapshot, resolved, coverage) -> list[Finding]:
        """Produce findings from the full eligible set; never from a budgeted surface (F02)."""
        findings: list[Finding] = []
        # FILL IN contradiction: for each entry, each `contradicts` ref whose target is an effective head in
        #   snapshot (and, in reverse, each eligible record whose `contradicts` names this entry's id) ⇒
        #   Finding(kind="contradiction", blocking=True) unless resolved by a prospective `supersedes` of that
        #   exact predecessor revision — bounded by AC4, AC5, AC8.
        # FILL IN potential-conflict: same scope (target or ancestor overlap via resolved[*].ancestors) with
        #   opposite normative polarity (forbids vs requires/constrains) ⇒ blocking=False — bounded by AC4.
        # FILL IN possible-supersession: same canonical target set + same about, no explicit link ⇒ advisory.
        # FILL IN blast-radius: for each resolved symbol target, await self.structural.blast_radius(target,
        #   relations=_IMPACT_RELATIONS, depth=2, include_tests=True); truncated ⇒ coverage.impact_complete=False;
        #   inferred-provenance nodes listed separately in the message — bounded by S6, AC7.
        # FILL IN evidence-gap: eligible governing records whose evidence verify_freshness says stale/missing.
        # FILL IN waivers: a waiver applies only if finding_fingerprint matches AND participants equal exactly AND
        #   approval_ref names a verified manifest entry (snapshot/adapter); else WAIVER_INVALID diagnostic and the
        #   finding stays blocking — bounded by AC9. Set waived_by=approval_ref on success.
        # Every Finding: rule_version=RULES_VERSION, fingerprint=finding_fingerprint(kind, RULES_VERSION, participants, scope).
        return findings

    async def governing(self, spec_path: Path, *, budget_tokens: int = 3000) -> GoverningDossier:
        """Full eligible set collected first; ``budget_tokens`` is consumed by the renderer only (G1, AC14)."""
        # FILL IN: parse spec; if not audit_configured ⇒ GoverningDossier(empty_plane=True, searched_subsystems=[]);
        #   else take the snapshot as in evaluate(), about = taxonomy.map_projects(projects, tags) ∪ block about ids,
        #   scope_ids = resolved targets + their ancestors (TargetResolver.ancestors_of) + Codebase Contract ids;
        #   records = snapshot.governing(about, scope_ids); entries sorted by decision_id; missing fields stay ""
        #   (renderer prints "not recorded"); empty_plane = not snapshot.eligible. budget_tokens is NOT applied here.
        raise NotImplementedError
```
**Why**: `_finish` is the single assembly point, so every return path (skipped excluded) gets digests from the same
code — required for render/check byte stability (AC10). Sorting findings and diagnostics makes output order
independent of dict/set iteration.

### FILL IN checklist
- [ ] block A: `DecisionError` code → status mapping; bounded by AC11
- [ ] block A: taxonomy/target validation, baseline selection (preview vs replay), `_judge` call; bounded by AC3, AC7, AC12
- [ ] block A: coverage subsystems/unmapped tags from frontmatter; bounded by G1
- [ ] block B: `_structural_revision`; bounded by AC10
- [ ] block B: five finding kinds + waiver binding in `_judge`; bounded by AC4, AC5, AC7, AC8, AC9, S6
- [ ] block B: `governing()`; bounded by G1, AC14

---

## Acceptance Criteria

- [ ] AC1: `evaluate()`/`governing()` never call `LLMFactory.create` (offline guard test).
- [ ] AC4/AC5: explicit `contradicts` blocks (also as the 51st matching record); polarity overlap is advisory only.
- [ ] AC7: `dir:` rule collected for a descendant symbol target; dependent outside scope ⇒ `blast-radius` only.
- [ ] AC8: supersession faults surface as `invalid` (via TASK-5003 diagnostics), never repaired.
- [ ] AC9: forged/changed waiver ⇒ `WAIVER_INVALID`, contradiction stays blocking.
- [ ] AC11: precedence invalid > incomplete > conflict > pass; truncated impact ⇒ `incomplete`.
- [ ] AC19: unconfigured repo + no block ⇒ `skipped`/0; unconfigured + block ⇒ `invalid`.
- [ ] `ruff check` clean on both files.

---

## Validation Commands
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequence_digests.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/decisions/test_consequences.py
import pytest
from parrot.knowledge.wiki.decisions.consequences import ConsequenceService, audit_configured

# Fixtures (spec §4 Test Data): build in this file or a local helper —
#   decision_plane: adr_store (conftest.py:190) seeded with 2 legacy schema-1 accepted ADRs (one unreviewed),
#     1 rejected, a superseded chain A1 -> A2, and >50 filler records.
#   spec_with_decisions: tmp spec with a valid ## Decisions block (2 entries), one explicit contradicts ref.
#   A fake ApprovalAdapter whose verify() returns (True, []) for listed batches; a stub StructuralService
#   (read_repair=False) whose blast_radius returns a controllable BlastRadiusOutput.

async def test_unconfigured_repo_is_skipped(tmp_path): ...           # FILL IN — AC19
async def test_block_in_unconfigured_repo_is_invalid(tmp_path): ...  # FILL IN — AC19
async def test_explicit_conflict_blocks_beyond_limit(): ...          # FILL IN — AC5 (51st record)
async def test_polarity_overlap_is_advisory(): ...                   # FILL IN — AC4
async def test_ancestor_scope_collected(): ...                       # FILL IN — AC7
async def test_status_precedence(): ...                              # FILL IN — invalid + incomplete + conflict ⇒ invalid, all diagnostics kept
async def test_digests_exclude_generated_sections(): ...             # FILL IN — appending ## Consequences keeps input_digest
async def test_waiver_binding(): ...                                 # FILL IN — AC9
async def test_truncated_impact_is_incomplete(): ...                 # FILL IN — S6
async def test_evaluate_never_constructs_llm(monkeypatch): ...       # FILL IN — AC1 guard: LLMFactory.create raises
```

---

## Agent Instructions

1. Work in the feature worktree (`python -m scripts.sdd.ensure_worktree --slug sdd-decision-audit --feature-id FEAT-784`).
2. Read spec §2 (Overview, Portability principle), §3 Module 6, §5 AC1–AC11, AC19, §7 Known Risks.
3. Confirm TASK-5004, TASK-4999, TASK-5002 (and transitively P04, P05, P07) are `done`; read their delivered APIs before trusting the signatures above.
4. Verify the Codebase Contract; update it first if anything drifted.
5. Implement from the blueprint; every `FILL IN` resolved within its bound. Ambiguity → Completion Note, not improvisation.
6. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.
7. Commit only the listed files; close with `scripts/sdd/close_task.sh TASK-5005 sdd-decision-audit verified`.

---

## Completion Note

*(Agent fills this in when done)*
