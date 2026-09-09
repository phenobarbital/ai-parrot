# TASK-3045: Shared answer authorization, release and audit service

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3029, TASK-3035, TASK-3043, TASK-3044
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M9 in spec §3 and the corresponding normative §2 behavior. Covers AC10, AC11; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement ContractsAnswerService.answer and retire_answer with shared gate used by both producers and transport adapters.
- Perform closed-set pre-triage before retrieval: evaluative/deontic requests yield interpretation_required; uncertain classification fails closed. Optional structured triage sees question only and cannot generate AQL or change permission.
- Authorize located handoff clauses, enumerate bounded dossier, invoke injected draft producer, then verify and persist every outcome including denial/failure before release; audit outage is service failure.
- Enforce authenticated owner and trusted transport confirmation for verification/correction/party merge/owner override/retirement service operations. Invalidate answer caches and buffer substantive streaming until verification and audit succeed.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/service.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_service.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.ontology.authorization import AuthorizationChecker  # packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:43
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| AuthorizationChecker.check | async (self, spec: AuthorizationSpec, user_context: dict[str, Any], resolved_entities: dict[str, str], tenant_id: str) -> tuple[bool, str or None]; OR rules | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:62 |
| _check_same_department | DOCUMENT(@target_id).department; matches any target, constructs tenant_id + "_ontology" database | packages/ai-parrot/src/parrot/knowledge/ontology/authorization.py:293 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| ContractsAnswerService | async answer(question, *, request_context, parameters=None) -> ContractAnswer or typed clarification; async retire_answer(answer_id, *, request_context, reason) |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- Unmodified OntologyRAGMixin does not enforce the required pre-read authorization ordering; hybrid_concept_match targets Concepts, not Contracts.
- BOE SpanVerifier is domain-specific and the legal crew builder is inspection-only, not an executable contracts runner.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3029`: Catalog aliases, audit, sources and publication state; inspect its completed artifact and committed interface before use.
- `TASK-3035`: Verification and refresh preserve human decisions; inspect its completed artifact and committed interface before use.
- `TASK-3043`: Deterministic authorized retrieval and typed pattern binds; inspect its completed artifact and committed interface before use.
- `TASK-3044`: Versioned citation and claim verification gate; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Lookup, interpretation handoff, denied/out_of_scope/not_found and typed clarification follow spec contracts with no legal judgment text.
- [ ] Forged actor/roles, unconfirmed writes, direct bypass and audit outage fail closed.
- [ ] Streaming cannot expose raw draft; retired evidence cannot reach lookup or handoff; every released outcome has an audit record.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Lookup, interpretation handoff, denied/out_of_scope/not_found and typed clarification follow spec contracts with no legal judgment text.
2. Forged actor/roles, unconfirmed writes, direct bypass and audit outage fail closed.
3. Streaming cannot expose raw draft; retired evidence cannot reach lookup or handoff; every released outcome has an audit record.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_service.py -q`

Store execution logs in `artifacts/logs/task-3045.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3045-contracts-answer-service.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot_tools/contracts/service.py`.
`ContractsAnswerService.answer` runs the fixed chain both producers share: closed-set
pre-triage on the question alone (evaluative/deontic -> `interpretation_required`
before any retrieval; an optional structured triage adapter sees only the question and
cannot generate AQL or widen permissions), then authorize-then-retrieve, then a
bounded enumerated dossier (`MAX_DOSSIER_CARDS`) handed to the injected producer,
then `CitationVerifier`, then audit, then release. Every outcome is persisted before
it is returned — including denials, not_found and verification failures — and an audit
outage raises `ServiceUnavailable` instead of releasing an unaudited answer.
Clarifications are returned as the typed `Clarification`, never as a new answer kind.
A handoff LOCATES up to `MAX_HANDOFF_CLAUSES` clauses after authorization and each
one still has to survive the citation gate (a lint finding caught that the first
draft computed them and then dropped them on the floor).
`stream_answer` buffers everything substantive until the whole gate has passed, so a
raw draft can never reach a transport. Owner-only operations (`retire_answer`,
`verify_card`, `merge_parties`) require the owner role **and** a trusted transport
confirmation; retirement records the invalidated answer id for transport caches.

**Validation**: `pytest .../test_service.py -q` -> 20 passed (whole contracts tools
suite 94 passed, `artifacts/logs/task-3045.log`); ruff clean. Tests cover the lookup /
handoff / denied / not_found / clarification shapes with no judgment text, pre-triage
running before retrieval, an unverifiable draft degrading to not_found, forged tenant
and missing principal, audit outage failing both an answer and a denial, owner role +
confirmation enforcement, a forged owner role refused by the tenant check, retirement
suppressing evidence from a later lookup **and** from a later handoff, streaming
emitting nothing for a denial or an unverified draft, and the bounded dossier.

**Deviations**: none.
