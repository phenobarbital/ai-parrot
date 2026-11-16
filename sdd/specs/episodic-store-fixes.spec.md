---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [memory, episodic, attribution, cross-session]
docs:
  policy: required
  pages: [wiki/memory/agent-memory.md]
---

# Feature Specification: Cross-scope episodic citations and reviews

**Feature ID**: FEAT-903
**Date**: 2026-11-16
**Author**: Jesus Lara / Codex
**Status**: approved

## 1. Motivation & Business Requirements

### Problem Statement

Issue `issue:33b9921c84ac`: same-user episodes from earlier sessions and agent-level
episodes are recalled but excluded from citation and review. Their lessons cannot
earn dynamics updates when they help or fail in a later session.

### Goals

- Cite and review visible episodes under their original recording namespace.
- Preserve frozen canonical identity, versioning, dedupe encoding and stored state.
- Preserve request provenance and runtime evidence admission, including tenant,
  agent, user, anonymous-session, room, crew and model isolation.
- Deliver this as a separate follow-up after merged FEAT-892 / PR #2139, as the
  owner explicitly confirmed on 2026-11-16.

### Non-Goals

No session removal from identity, state migration, visibility expansion, provider
calls, dependency additions, brain review changes, or re-exposure of operator-only
review tools. The companion issue `issue:74d48035e07b` was already addressed by
commit `2be959226d`; its regression remains part of validation.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:29339780c5972add521c437014dcc4585f721dc530e32fe570d32877aca058ac evaluation_digest=sha256:3ef3bbac2d696956310f784123f5e0e42b4f1cd75f40eaca433056c7f4724927 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

Keep episode identity and outcome identity separate. An episode reference contains
its original namespace. A review signal retains the actual requesting scope; never
rewrite its user/session to the episode's recording scope. The existing
`visible_to_scope` policy determines whether the request can use the episode.

`cite` and `review` keep their public signatures. Their `namespace` argument denotes
the trusted requesting namespace. Resolution searches only existing recall scopes,
then rechecks visibility. Ref construction uses the stored episode namespace. Review
checks the signal exactly matches the requesting namespace, checks the persisted
citation and full current episode ref, then applies the existing durable transition.

`ReviewCommand` uses visibility for episode refs; brain refs retain current scope
checks. Canonical and dedupe encodings remain byte-for-byte unchanged. SQLite's latest
outcome revision query also matches signal tenant/agent/user/session from the existing
JSON payload using NULL-safe comparisons. This prevents two sessions' identically
named outcomes from suppressing each other on shared episode state. No schema migration.

### Exposure transport

Add `MemoryCandidate.memory_ref: MemoryRef | None` and
`MemoryContext.memory_refs: tuple[MemoryRef, ...]`. Candidate scope stays the request
scope. The assembler carries a ref only when its complete candidate text fits the
budget. Non-episodic candidates cannot supply review refs. Validate consistency between
candidate source, ID, version, kind and the ref. The manager emits original episode
refs and no longer labels visible cross-session episodes `episodic_context`.

Final exposure creation consumes only typed refs whose corresponding delivered token
survives final packing and whose namespace is visible. It must not reconstruct an
episode namespace from the request or consult shared mutable request maps. Missing
typed references fail closed. Existing fixtures that synthesize reviewable contexts
must explicitly provide their typed references.

Citation validation retains exact exposure/request binding and compares full refs,
not only canonical keys (model_id is deliberately excluded from canonical identity).
Citation merging allows different recording namespaces within one tenant/agent,
rejects conflicting full refs with the same canonical key, and preserves the 64-ref
limit. Visibility and delivered membership remain runtime admission responsibilities.
The manager passes the request namespace to `review`, including mixed citations.

### Integration and cache behavior

Reuse `episodic.visibility.recall_scopes` and `visible_to_scope`. Preserve backend
exact recorded-namespace checks. Invalidate each successfully reviewed recorded
namespace and the request namespace; the hybrid index already invalidates every
derived scope for the same tenant/agent. Review-only changes do not alter cached
episode content; dynamics state is resolved from durable state at ranking time.

## 3. Module Breakdown

| Module | Responsibility | Dependency | Delegation eligible |
|---|---|---|---|
| M1 | Visible citations, review admission, SQLite outcome isolation and tests | Existing visibility policy | No: security-sensitive admission |
| M2 | Typed original refs through packing and final exposure; integration tests | M1 review contract | No: lifecycle integration |
| M3 | Document identity, provenance and visibility | M1 and M2 contracts | No: requires verified behavior |

### Interface Skeletons

Existing signatures remain unchanged, except the private delivered-ref parser becomes
a lookup over supplied typed refs. Verified anchors are in §6.

```python
async def cite(self, memory_ids: list[str], *, namespace: MemoryNamespace, exposure_id: str) -> MemoryCitation:
    """Cite visible stored episodes using their recorded namespaces."""

async def review(self, memory_ids: list[str], signal: ReviewSignal, *, namespace: MemoryNamespace,
                 exposure_id: str) -> list[ReviewReceipt]:
    """Review visible cited episodes while retaining the invoking signal scope."""

def validate_citation(citation: MemoryCitation, exposure: MemoryExposure, *,
                      scope: MemoryRequestScope) -> MemoryCitation:
    """Require full delivered-ref membership and request visibility."""

def _delivered_memory_ref(delivered_ref: str, scope: MemoryRequestScope,
                          memory_refs: tuple[MemoryRef, ...]) -> MemoryRef | None:
    """Find the original visible ref corresponding to a final delivered token."""
```

M3 updates `wiki/memory/agent-memory.md`; it introduces no Python interface.

## 4. Test Specification

Test visible same-user prior-session and agent-level refs, anonymous isolation,
foreign principals, room/crew/model narrowing, full-ref equality, mixed citation
merges, packed/dropped candidates, unchanged state keys, distinct outcome scopes,
durable restart replay, stale revisions within one scope, and retained toolkit exclusion.
Use existing deterministic SQLite and FAISS fixtures; no live provider calls.

### Validation Contract

tests:
- packages/ai-parrot/tests/memory/dynamics/test_models.py
- packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py
- packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py
- packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py
- packages/ai-parrot/tests/memory/dynamics/test_attribution.py
- packages/ai-parrot/tests/memory/dynamics/test_reviews.py
- packages/ai-parrot/tests/memory/unified/test_models.py
- packages/ai-parrot/tests/memory/unified/test_context.py
- packages/ai-parrot/tests/memory/unified/test_manager.py
- packages/ai-parrot/tests/memory/unified/test_manager_real_store.py
- packages/ai-parrot/tests/memory/agent_memory/test_review_fixes.py
- packages/ai-parrot/tests/memory/agent_memory/test_documentation.py
markers: none

## 5. Acceptance Criteria

- [ ] Visible old-session and agent-level episodes enter final exposure with their original refs.
- [ ] Only completely delivered episode candidates can be cited; forged full refs are rejected.
- [ ] A mixed citation can review visible episodes with different recorded namespaces.
- [ ] Foreign tenant/agent/user and anonymous-session refs fail closed; optional filters still narrow.
- [ ] Every episode retains one canonical state key; signals retain requesting identity.
- [ ] Two requesting scopes with the same outcome ID remain independent; replay stays idempotent.
- [ ] Existing canonical/dedupe encodings, brain restrictions and operator-only tools remain intact.
- [ ] Declared validation, lint, documentation and independent review pass.

## 6. Codebase Contract

Verified against `33637365e4`; planning reservation HEAD `bbf72bdcce18d83de524088e30b5a64aff55b1d4`.

### Verified Imports

```python
from parrot.memory.episodic.visibility import recall_scopes, visible_to_scope  # visibility.py:19,61
from parrot.memory.episodic.models import MemoryNamespace  # models.py
from parrot.memory.dynamics.models import MemoryRef, MemoryCitation, MemoryExposure, ReviewCommand, ReviewSignal
from parrot.memory.agent_memory.models import MemoryRequestScope
from parrot.memory.unified.models import MemoryCandidate, MemoryContext
```

### Edit Sites

All anchors have one occurrence, verified with `rg -n -F` on 2026-11-16.
Paths in the first column are repository-relative.

| Path | Line | Anchor | Count |
|---|---:|---|---:|
| packages/ai-parrot/src/parrot/memory/dynamics/models.py | 393 | `class ReviewCommand(BaseModel):` | 1 |
| packages/ai-parrot/src/parrot/memory/agent_memory/attribution.py | 172 | `def validate_citation(` | 1 |
| packages/ai-parrot/src/parrot/memory/episodic/store.py | 458 | `    async def cite(` | 1 |
| packages/ai-parrot/src/parrot/memory/episodic/backends/sqlite.py | 428 | `                latest_cursor = await database.execute(` | 1 |
| packages/ai-parrot/src/parrot/memory/unified/models.py | 18 | `class MemoryCandidate(BaseModel):` | 1 |
| packages/ai-parrot/src/parrot/memory/unified/context.py | 124 | `    def assemble_candidates(` | 1 |
| packages/ai-parrot/src/parrot/memory/unified/manager.py | 240 | `    def commit_memory_exposure(` | 1 |
| packages/ai-parrot/tests/memory/dynamics/test_evidence_models.py | 67 | `def test_synthetic_and_forged_scope_rejected()` | 1 |
| packages/ai-parrot/tests/memory/dynamics/test_store_reviews.py | 92 | `async def test_cite_does_not_reinforce(` | 1 |
| packages/ai-parrot/tests/memory/dynamics/test_sqlite_backend.py | 722 | `async def test_apply_review_requires_exact_episode_scope(` | 1 |
| packages/ai-parrot/tests/memory/dynamics/test_attribution.py | 116 | `def test_final_packing_controls_citable_refs()` | 1 |
| packages/ai-parrot/tests/memory/unified/test_context.py | 46 | `class TestContextAssembler:` | 1 |
| packages/ai-parrot/tests/memory/unified/test_manager_real_store.py | 172 | `async def test_only_exact_scope_episodes_enter_the_review_manifest(` | 1 |
| wiki/memory/agent-memory.md | 201 | `### Dynamics and Reviews` | 1 |

### Does NOT Exist

No original typed reference on MemoryCandidate or MemoryContext; no async exposure
commit API; no requirement to migrate canonical state keys; no trusted evidence
registry in AgentMemoryToolkit (review methods remain operator-only).

## 7. Implementation Notes & Constraints

Async I/O, Pydantic v2, existing dependencies only, black line length 120 and ruff.
Do not change `clients/base.py`, canonical encoders, brain contracts or caller scope.
Keep query filters before resolution and fail with existing non-disclosing errors.

## Worktree Strategy

One feature worktree provisioned by `parrot sdd worktree ensure`. M2 consumes M1's
visible citation/review semantics; M3 documents both. No shared native rebuild or
environment mutation. FEAT-892 / PR #2139 is already merged. Planning uses an
isolated clean checkout of dev because another session owns changes in the main tree.

## Decisions

The owner's recorded decision `mem-afd67bae717c` and 2026-11-16 confirmation govern
this follow-up. This explicitly supersedes FEAT-892 §E10's exact recording/request
namespace equality and §C5's exact equality admission for episode refs. B1-B3
canonical identity, C5 dedupe encoding, model filter semantics and brain restrictions
remain unchanged. No decision-plane governing entries were returned for this scope.

## Consequences

<!-- decision-audit: input_digest=sha256:29339780c5972add521c437014dcc4585f721dc530e32fe570d32877aca058ac evaluation_digest=sha256:3ef3bbac2d696956310f784123f5e0e42b4f1cd75f40eaca433056c7f4724927 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/ai-parrot-episodic-planning-5d23ba57/sdd/specs/episodic-store-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: attribution, cross-session, episodic
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "attribution",
      "cross-session",
      "episodic"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/ai-parrot-episodic-planning-5d23ba57/sdd/specs/episodic-store-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:3ef3bbac2d696956310f784123f5e0e42b4f1cd75f40eaca433056c7f4724927",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:29339780c5972add521c437014dcc4585f721dc530e32fe570d32877aca058ac",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Review identity: original episode namespace with visibility check (owner decision).
- [x] Delivery route: separate follow-up feature from dev (owner confirmation).
- [x] Signal provenance: preserve requesting scope; use visibility for episode admission.

## 9. Design Research Cross-Check

Independent read-only Codex explorer reviewed current sources with a neutral issue
brief. CONFIRM: preserve signal provenance and dedupe; carry typed refs through
packing; compare full refs to prevent model_id forgery; scope SQLite latest outcome
revision by requesting identity; invalidate recorded/request caches. All are included
above. This is design research, not a completed implementation review.

## 10. Documentation

Update `wiki/memory/agent-memory.md` to describe original recording identity,
request visibility, mixed citations, unchanged state keys and runtime-only outcomes.
