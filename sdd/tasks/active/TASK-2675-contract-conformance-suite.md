# TASK-2675: Contract-conformance test suite (QA oracle, §34/§36)

**Feature**: FEAT-481 — Fireflies → Obsidian LLM-Wiki Knowledge-Base Agent
**Spec**: `sdd/specs/fireflies-wiki-knowledgebase-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2660, TASK-2661, TASK-2662, TASK-2663, TASK-2664, TASK-2665, TASK-2666, TASK-2667, TASK-2668, TASK-2669, TASK-2670, TASK-2671, TASK-2672, TASK-2673, TASK-2674
**Assigned-to**: unassigned

---

## Context

Spec Module 16 — the executable acceptance oracle. Verifies the agent's output
against the operating contract (`sdd/references/obsidian-wiki-operating-contract.md`)
section by section, over a fixture vault.

## Scope

- `tests/integration/test_wiki_kb_contract.py`: a fixture contract-structured vault + sample bundles; run the ingest pipeline and assert against the contract:
  - Dedup/immutability (§14/§14.3), chronological reconcile (§2 r16/§19 r10), raw hash-verify (§14.2), provenance + plain-path raw links (§10/§17/D1), `primary_project ∈ projects` (D2), GraphIndex-primary query then Obsidian verify (§28/D3), Private/ untouched (§2 #1), Human Notes/locked preserved (§9), post-op gate blocks bad writes (§34), page-template heading fidelity (§17/§19/§20/§21/§22/§23), Obsidian-safe filenames + meeting-tz date (§8.2), no dangling wikilinks (§8.1), no fabrication (rule #12), new-project discipline (§16), email disabled (G9), archive window configurable (§31).
- Assert **existing agents' suites stay green** (additive-only, G11).

**NOT in scope**: node implementations (their own tasks).

## Files to Create / Modify
| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_wiki_kb_contract.py` | CREATE | the §34/§36 conformance oracle |
| `packages/ai-parrot/tests/integration/fixtures/wiki_kb_vault/…` | CREATE | fixture vault + sample bundles |

## Codebase Contract (Anti-Hallucination)
### Notes
- Exercises the whole subsystem (TASK-2660–2674); mock the MCP + LLM tier clients with deterministic stubs so assertions are stable.
- Contract section references are authoritative: `sdd/references/obsidian-wiki-operating-contract.md`.
### Does NOT Exist
- ~~a revision/`source-revision`/`revision-detected` path~~ — assert these are absent (R3).

## Implementation Notes
- One test (or parametrized case) per contract guarantee; name tests by the § they enforce for traceability.
- Use recorded/stubbed LLM outputs; no live API calls in CI.

## Acceptance Criteria
- [ ] Conformance suite passes against the fixture vault, covering every §5 acceptance criterion.
- [ ] Confirms no existing agent/toolkit test regressed (G11).
- [ ] `ruff`/`mypy` clean.

## Test Specification
```python
async def test_contract_conformance_full_ingest(): ...
def test_no_revision_artifacts_exist(): ...
def test_existing_agent_suites_unaffected(): ...
```
