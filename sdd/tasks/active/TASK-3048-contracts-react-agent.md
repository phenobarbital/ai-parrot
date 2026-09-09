# TASK-3048: ReAct ContractsAgent with shared release gate

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3046, TASK-3047
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M10 in spec §3 and the corresponding normative §2 behavior. Covers AC10; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement ContractsAgent with ContractsToolkit for chat/MCP using established Agent abstraction.
- Treat model result as draft only and release final answer through ContractsAnswerService with request-scoped dossier and verifier/audit. Preserve interpretation_required behavior and trusted write confirmation.
- Buffer streaming answer text until gate completion and prevent raw model-answer fallback on tool/provider/service errors.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/agent.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_agent.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit  # packages/ai-parrot/src/parrot/tools/toolkit.py:257
from parrot.bots import Agent  # packages/ai-parrot/src/parrot/bots/__init__.py:2
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| Toolkit confirmation | tool_prefix: str or None; confirming_tools: frozenset of unprefixed method names; generates requires_confirmation metadata | packages/ai-parrot/src/parrot/tools/toolkit.py:257; packages/ai-parrot/src/parrot/tools/toolkit.py:686 |
| LegalLibrarianAgent.draft | async (self, enumerated_dossier: str, query: str, as_of: date) -> DraftAnswer; stateless structured output precedent | packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py:79 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| ContractsAgent | ReAct producer using the toolkit and shared service release gate; never release its raw model draft |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- Unmodified OntologyRAGMixin does not enforce the required pre-read authorization ordering; hybrid_concept_match targets Concepts, not Contracts.
- BOE SpanVerifier is domain-specific and the legal crew builder is inspection-only, not an executable contracts runner.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3046`: Prefixed read tools and confirming administration; inspect its completed artifact and committed interface before use.
- `TASK-3047`: Executable fixed contracts answer runner; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] ReAct and fixed flow return equivalent protected answer shapes on the same synthetic cases.
- [ ] Adversarial tool/model drafts, retired citations, forged context and audit failure cannot escape through chat/MCP or streaming.
- [ ] Shared service is actually invoked; no duplicate independent citation policy or new transport is introduced.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. ReAct and fixed flow return equivalent protected answer shapes on the same synthetic cases.
2. Adversarial tool/model drafts, retired citations, forged context and audit failure cannot escape through chat/MCP or streaming.
3. Shared service is actually invoked; no duplicate independent citation policy or new transport is introduced.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_agent.py -q`

Store execution logs in `artifacts/logs/task-3048.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3048-contracts-react-agent.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Pending execution. Record executor, completion date, implementation summary, validation evidence and deviations when this task is completed.
