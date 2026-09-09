# TASK-3047: Executable fixed contracts answer runner

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3045
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M10 in spec §3 and the corresponding normative §2 behavior. Covers AC10; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement executable async fixed runner composing deterministic retrieval, enumerated dossier, one stateless structured draft and shared service verifier/audit release gate.
- Keep API/A2A/report entrypoints callable through existing transports. An optional inspectable crew cannot substitute for tested execution.
- Support explicit handoff/empty/denied outcomes without unnecessary drafting; model/source instructions cannot add tools, evidence or privileges.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/flow.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_flow.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
# No existing integration import is required; standard-library typing and declared Pydantic v2 are available.
# Contracts interfaces are NEW dependency outputs, not verified pre-existing imports.
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| LegalLibrarianAgent.draft | async (self, enumerated_dossier: str, query: str, as_of: date) -> DraftAnswer; stateless structured output precedent | packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py:79 |
| build_legal_librarian_crew | Inspection artifact; explicitly not executable via run_flow | packages/ai-parrot-tools/src/parrot_tools/legal/librarian/flow.py:494 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| answer flow | Executable async runner with deterministic retrieval, enumerated dossier, one stateless structured draft, verifier and audit; build an inspectable crew only if useful, not as a substitute for the runner |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- Unmodified OntologyRAGMixin does not enforce the required pre-read authorization ordering; hybrid_concept_match targets Concepts, not Contracts.
- BOE SpanVerifier is domain-specific and the legal crew builder is inspection-only, not an executable contracts runner.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3045`: Shared answer authorization, release and audit service; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] One actual runner invocation executes stages in order, drafts at most once and returns audited ContractAnswer.
- [ ] No raw draft or substantive partial stream escapes; citation/audit failure matches shared service behavior.
- [ ] First vertical fixture covers ingest, authorized fixed answer, retirement and rejected reuse before ReAct polishing.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. One actual runner invocation executes stages in order, drafts at most once and returns audited ContractAnswer.
2. No raw draft or substantive partial stream escapes; citation/audit failure matches shared service behavior.
3. First vertical fixture covers ingest, authorized fixed answer, retirement and rejected reuse before ReAct polishing.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_flow.py -q`

Store execution logs in `artifacts/logs/task-3047.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3047-contracts-fixed-answer-flow.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot_tools/contracts/flow.py` — an **executable**
runner, not an inspection artifact. `ContractsAnswerFlow.run` drives the fixed stage
order (triage, retrieve, dossier, draft, verify, audit, release) through the shared
`ContractsAnswerService`, so authorization, verification and audit are literally the
same code the ReAct path uses; the flow and the service share ONE producer instance.
`ContractsDraftProducer` enumerates a bounded, deterministic dossier (retrieved
obligations first, then the rest, each with an `evidence_id`), renders it into a
single stateless structured call, and maps the model's `evidence_ids` back to
citations — an id that is not in the dossier cites nothing, so the claim is dropped by
the verifier. Without an adapter the draft is deterministic and costs no call. The
draft system prompt states that contract text is untrusted DATA and cannot grant
tools, evidence or privileges. Clarifications, handoffs and denials short-circuit
before drafting, so they spend no model call. `answer()` is the convenience
entrypoint for API/A2A/report callers.

**Validation**: `pytest .../test_flow.py -q` -> 14 passed (whole contracts tools suite
124 passed, `artifacts/logs/task-3047.log`); ruff clean. Tests assert the stage order
of one real invocation with exactly one draft call, statelessness across two runs,
zero draft calls for clarification/handoff/denial, an invented evidence id dropping
its claim, a citation-less claim degrading to not_found, a prompt-injected summary
neither adding evidence ids nor privileges, audit failure matching the service, and
the first vertical slice: answer -> retire -> the same evidence refused on reuse, with
both outcomes audited.

**Deviations**: none. No inspectable crew object is built — the spec explicitly says
one must not substitute for tested execution, and the legal librarian's crew builder
is documented as non-executable.
