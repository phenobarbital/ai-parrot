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

### Completion Note

`fixtures/wiki_kb_vault/`: a minimal committed contract-structured
vault — `Private/secret.md` (the §2 rule 1 canary) and a pre-seeded
`locked: true` `Projects/Legacy Project/Legacy Project.md` with a
distinctive `## Human Notes` sentence (the §9/§19 rule 8/9 canary).
Copied fresh into a `tmp_path` per test (never mutated in place).

`test_wiki_kb_contract.py`: 15 tests, each named by the contract §
it enforces, running the real `run_ingest()` pipeline against the
fixture vault with deterministic stubbed strong/cheap clients + a fake
Fireflies MCP tool_manager (no live API calls) — self-contained (does
not import test helpers from `test_wiki_kb_ingest.py`, keeping this
oracle independent of any other task's test internals):
- §14/R3: re-ingesting a known id is a no-op skip; no `Revisions/`
  folder, no `source-revision`/`revision-detected` strings anywhere.
- §10/§17/D1/D2: raw provenance is plain paths; `primary_project ∈
  projects`.
- §14.2: raw summary bytes hash-match the frontmatter's `summary_sha256`.
- §2 rule 1: the `Private/` canary file is untouched after ingest.
- §9: the locked `Legacy Project` page's Human Notes survive byte-for-
  byte; it is never in `report.updated`.
- §34: a forced validation failure leaves no `ingest |` log entry.
- §17/§19: meeting + project page headings present verbatim.
- §8.2: meeting filename has no unsafe punctuation and uses the
  meeting's dateString-derived date.
- §8.1: `run_lint()` reports zero `broken_wikilink` findings post-ingest.
- Rule #12: the renderer emits "None identified" rather than fabricating
  content the mocked extraction never supplied.
- §16: `run_project_reconcile()` returns `not_created` for an unjustified
  new-project candidate.
- G9: `FIREFLIES_WIKI_EMAIL_ENABLED` defaults to `False`.
- §31: `run_archive()` moves a note older than a 7-day window.
- §28/D3: `run_query()` resolves a GraphIndex-ranked candidate against
  the real Obsidian page before answering.
- G11: `test_existing_agent_suites_unaffected` shells out to `pytest` in
  two separate subprocess groups (the repo-root `tests/` package and
  `packages/ai-parrot/tests/` package both import as the dotted name
  `tests.conftest` — a pre-existing, unrelated repo-layout ambiguity
  that trips `ImportPathMismatchError` if mixed in one pytest process)
  and asserts both groups exit 0.

Verified: `pytest packages/ai-parrot/tests/integration/test_wiki_kb_contract.py`
(15 passed, including the G11 regression subprocess check); `ruff
check` clean; `mypy` clean; full wiki-kb suite across all 16 tasks (112
tests) stays green.
