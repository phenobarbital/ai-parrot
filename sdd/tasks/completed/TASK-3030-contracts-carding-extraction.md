# TASK-3030: Bounded evidenced header and obligation extraction

**Feature**: FEAT-539 - Contracts Card & Ontology
**Spec**: `sdd/specs/contracts-card-ontology.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2–4h)
**Depends-on**: TASK-3025, TASK-3026
**Assigned-to**: unassigned
**Parallel**: true
**Parallelism notes**: Execute in core worktree feat-FEAT-539-contracts-card-ontology. May run alongside ready tasks with disjoint owned files after all dependencies complete. No concurrent edits to any file listed below. M8 commits must be integrated into the core lane before the delta job. Packaging task alone owns pyproject.toml/uv.lock; DOCX task alone owns bookstore/library.py.

---

## Context

Implements M3 in spec §3 and the corresponding normative §2 behavior. Covers AC2; full feature acceptance remains governed by spec §§4–5.

## Scope

- Implement deterministic cover/term/notice/party/signature selection and first/last/three deontic-density fallback, capped at 12000 header characters.
- Perform one structured header call and at most max_obligation_sections calls (default 12), with deterministic section order; prohibit derived facts in draft prompts.
- Validate exact evidence for each extracted nested field; absent/invalid quote caps confidence at 0.5. On unavailable/failed LLM use filename/type/date heuristics at 0.3 with fallback origin and no invented obligations.
- Treat document instructions as data; bind only approved output models and standard taxonomy.

**NOT in scope**: implementation owned by other tasks, new dependencies beyond the separately assigned approved rapidfuzz extra, verification UI, OCR, automatic messages, new scheduler or transport infrastructure. Do not modify generic ontology/GraphIndex APIs to bypass the contracts adapters.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/contracts/carding.py` | CREATE | Task-owned deliverable |
| `packages/ai-parrot/tests/knowledge/contracts/test_carding.py` | CREATE | Focused verification / fixtures |

## Codebase Contract (Anti-Hallucination)

Relevant spec references were re-read on 2026-09-09 against dev `7ba8ef6b0`. These are source-verified contracts, not a claim that optional integrations were connected. New dependency interfaces come from spec §2 and must be verified after their owning tasks commit.

### Verified Imports

```python
from parrot.knowledge.bookstore.carding import slugify, unique_slug, derive_toc  # packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49
from parrot.knowledge.pageindex.llm_adapter import PageIndexLLMAdapter  # packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:99
```

### Existing Signatures to Use

| Existing callable | Verified signature / constraint | Source |
|---|---|---|
| slugify / unique_slug | slugify(text: str) -> str; unique_slug(base: str, taken: set[str]) -> str | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:49 |
| derive_toc | derive_toc(tree: dict[str, Any], max_depth: int = 2) -> tuple[list[TocEntry], str] | packages/ai-parrot/src/parrot/knowledge/bookstore/carding.py:88 |
| ask_structured | async (self, prompt: str, output_type: type, temperature: float = 0.0, system_prompt: Optional[str] = None) -> Any | packages/ai-parrot/src/parrot/knowledge/pageindex/llm_adapter.py:99 |

### Does NOT Exist

- All task CREATE paths and contracts public interfaces are new at decomposition time; do not import unfinished dependency outputs.
- No SQLite catalog, generic BookCard inheritance or scheduler integration is authorized.

## Implementation Notes

Use strict type hints, Pydantic v2, async entrypoints, black/isort and lazy optional dependencies with actionable errors. Offload synchronous parsing/content reads. Keep core independent of parrot_tools and parrot.scheduler. Validate configured identifiers and bind user SQL/AQL values. Treat source documents as untrusted data. Re-read dependency contracts and owned files before editing; do not overwrite another worker's changes.

### Dependency interfaces

- `TASK-3025`: Typed contract models and standard aliases; inspect its completed artifact and committed interface before use.
- `TASK-3026`: Tenant-bound asynchronous catalog protocol; inspect its completed artifact and committed interface before use.

## Acceptance Criteria

- [ ] Fake adapter counts exactly the allowed 1+N bound, excluding PageIndex indexing and explicit relation calls.
- [ ] Selection and truncation are stable; unsupported evidence and model failures produce conservative provenance/fallback.
- [ ] Prompts contain no derived status/deadline/parent ID output fields and document prompt injection cannot change tool routing.
- [ ] Changes stay within owned files, imports are verified and appropriate focused validation is recorded.

## Test Specification

1. Fake adapter counts exactly the allowed 1+N bound, excluding PageIndex indexing and explicit relation calls.
2. Selection and truncation are stable; unsupported evidence and model failures produce conservative provenance/fallback.
3. Prompts contain no derived status/deadline/parent ID output fields and document prompt injection cannot change tool routing.

Validation: `uv run pytest packages/ai-parrot/tests/knowledge/contracts/test_carding.py -q`

Store execution logs in `artifacts/logs/task-3030.log`. Use frozen dates, synthetic sources, fake structured adapters and explicit failure injection. Live Postgres suites require explicit `GRAPHINDEX_PG_DSN` and temporary schemas; no default DSN fallback. Arango suites require explicit test configuration. Missing services skip only those suites and do not count as live acceptance. Do not fabricate benchmark results or pilot signoff.

## Agent Instructions

1. Read the full spec and this scope; confirm all dependency tasks are completed and committed.
2. Use the designated worktree; verify every referenced import/signature and update stale contracts before code changes.
3. Update only `sdd/tasks/index/contracts-card-ontology.json` assignment/status timestamps for this task, never the historical monolithic index.
4. Implement only owned files, validate acceptance criteria and record real results.
5. Move this artifact to `sdd/tasks/completed/TASK-3030-contracts-carding-extraction.md` when complete, update its per-spec index entry, and commit implementation plus SDD state.
6. Fill in the completion note; unavailable external acceptance must remain pending rather than being reported as successful.

## Completion Note

Completed 2026-09-09 by sdd-worker (Claude Opus 5).

**Implementation**: created `parrot/knowledge/contracts/carding.py` (extraction
half; TASK-3031 adds assembly/derivations). `select_header_nodes` picks one node per
ordered category (cover, parties, definitions, scope, term, renewal, termination,
notice, governing law, signature) and falls back to first + last + the three densest
deontic sections; `select_obligation_nodes` ranks obligation-flavoured titles, then
deontic density, then document order; `build_header_material` concatenates node-
labelled bodies under the 12,000-character cap and records truncation notes.
`draft_contract` spends exactly one `ContractHeaderDraft` call plus at most
`max_obligation_sections` (default 12) `ObligationsDraft` calls — PageIndex indexing
and relation judgement are outside this budget. Evidence is verified before it counts:
`validate_header_evidence` drops any quote that is not verbatim in the cited node body
(whitespace-normalised) and caps that field at 0.5; `validate_obligation_clauses`
drops clauses whose excerpt is unverifiable or that cite a node the pass never read.
No adapter or a failed header call yields `fallback_header_draft` at confidence 0.3
with `card_origin=fallback` and zero obligations; `guess_effective_date` refuses to
promote a bare year to a date. Prompts fence document text as untrusted DATA, bind
only the two approved output models, and never mention derived facts.

**Validation**: `pytest .../test_carding.py -q` -> 42 passed (whole contracts suite
233 passed, `artifacts/logs/task-3030.log`); ruff clean. A counting fake adapter
proves the 1+N bound (including the zero-N and "upper bound, not a quota" cases and
that a failed section still counts but does not abort), selection/truncation
determinism, dropped unsupported evidence, invented obligations never reaching the
draft, filename type/date heuristics, and that an injected "ignore your instructions"
clause changes neither the call budget, nor the bound output models, nor the
immutable system prompt.

**Deviations**: none.
