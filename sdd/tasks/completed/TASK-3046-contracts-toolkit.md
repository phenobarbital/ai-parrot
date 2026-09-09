# TASK-3046: Prefixed read tools and confirming administration

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3045, TASK-3040
**Assigned-to**: unassigned
**Parallel**: false
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. Run after listed dependencies; shared-file edits are serialized by this DAG. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M9 in spec §3 and the corresponding normative §2 behavior. Covers AC10, AC11; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement ContractsToolkit name/tool_prefix=contracts with catalog_search/get_card/get_toc/read_section/obligations/expiring/verification_queue/related_contracts.
- Implement typed verify_card operations for verify/correct, party merge and owner override plus retire_answer; use confirming_tools with unprefixed method names.
- Route all reads/writes through shared trusted authorization/service boundary; metadata alone is not permission or confirmation. Never accept actor/tenant authority from model arguments.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot-tools/tests/contracts/test_toolkit.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit  # packages/ai-parrot/src/parrot/tools/toolkit.py:257
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| Toolkit confirmation | tool_prefix: str or None; confirming_tools: frozenset of unprefixed method names; generates requires_confirmation metadata | packages/ai-parrot/src/parrot/tools/toolkit.py:257; packages/ai-parrot/src/parrot/tools/toolkit.py:686 |

### New design interfaces (not existing imports)

Implement only this task’s scoped portion; sibling methods belong to their designated dependencies or follow-up tasks.

| Interface | Normative contract from spec §2 |
|---|---|
| ContractsToolkit | name=contracts, tool_prefix=contracts; catalog_search, get_card, get_toc, read_section, obligations, expiring, verification_queue, related_contracts; confirming verify_card and retire_answer |
| verify_card tool | Typed operation for field verification/correction, party merge or owner override; actor from trusted request context |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.
- Unmodified OntologyRAGMixin does not enforce the required pre-read authorization ordering; hybrid_concept_match targets Concepts, not Contracts.
- BOE SpanVerifier is domain-specific and the legal crew builder is inspection-only, not an executable contracts runner.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3045`: Shared answer authorization, release and audit service; inspect its completed artifact and committed interface before use.
- `TASK-3040`: Explicit bounded relation judgements and invalidation; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Generated names use contracts_ prefix and verify_card/retire_answer carry requires_confirmation metadata.
- [ ] Direct invocation cannot bypass read policy, my_contracts evidence narrowing, owner role or trusted confirmation.
- [ ] All documented tools return typed bounded data; retired sections are unavailable.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Generated names use contracts_ prefix and verify_card/retire_answer carry requires_confirmation metadata.
2. Direct invocation cannot bypass read policy, my_contracts evidence narrowing, owner role or trusted confirmation.
3. All documented tools return typed bounded data; retired sections are unavailable.

Validation: `uv run pytest packages/ai-parrot-tools/tests/contracts/test_toolkit.py -q`

Store execution logs in `artifacts/logs/task-3046.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3046-contracts-toolkit.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot_tools/contracts/toolkit.py`. `ContractsToolkit`
(`name='contracts'`, `tool_prefix='contracts'`) exposes the eight documented read
tools — catalog_search, get_card, get_toc, read_section, obligations, expiring,
verification_queue, related_contracts — plus the two confirming write tools declared
in `confirming_tools = {'verify_card', 'retire_answer'}`, which the base toolkit turns
into `routing_meta['requires_confirmation'] = True`. `verify_card` is the single
typed operation for field verification/correction, party merge and owner override.
Every read runs the shared `ContractRetrieval.authorize` gate and resolves cards
through `_authorized_card`, so `my_contracts` narrowing also gates direct tool calls;
every write goes through `ContractsAnswerService`, which re-checks the owner role and
the trusted confirmation — the metadata flag alone never authorises anything. The
actor and tenant come from the constructor-injected `RequestContext`; no tool takes a
user/actor/roles/tenant argument. Outputs are bounded (briefs, capped rows, capped
section bodies) and a retired section is unavailable with an explicit reason.

**Validation**: `pytest .../test_toolkit.py -q` -> 16 passed (whole contracts tools
suite 110 passed, `artifacts/logs/task-3046.log`); ruff clean. Tests pin the ten
prefixed tool names, confirmation metadata on exactly the two write tools, bounded
typed outputs, denial of all eight reads without a read role, the my_contracts
narrowing refusing a direct `get_card` for someone else's contract, the absence of
actor arguments on every signature, a retired section becoming unavailable, and that
owner role + confirmation are both required for verify/merge/retire while the actor is
taken from the trusted context.

**Deviations**: none.
