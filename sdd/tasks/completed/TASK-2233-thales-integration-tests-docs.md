# TASK-2233: Integration tests (e2e mocked, checkpoint resume, partial sources) + docs

**Feature**: FEAT-425 — "Thales" Research Flow with Structured Citations, Decks & Final Report
**Spec**: `sdd/specs/agentcrew-tales-research.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2231, TASK-2232
**Assigned-to**: unassigned

---

## Context

Module 7 of FEAT-425 — the closure task. Proves the assembled flow end to
end with mocked LLMs/tools (no network), exercises FEAT-399 checkpoint
resume and source-degradation, and writes the user guide. This task also
walks the spec's §5 Acceptance Criteria checklist and is the natural place
to catch integration gaps the unit-tested modules missed.

---

## Scope

- Create `packages/ai-parrot/tests/flows/thales/test_integration.py`:
  - `test_thales_e2e_mocked_llm` — full `ThalesRunner.run()` with mocked
    LLM/tool responses: thesis → ≥10 decks → slides → final document
    (+ `.pdf` when weasyprint importable) → executive summary + infographic;
    `manifest.json` complete; every `Finding` carries ≥1 `SourceClaim` with
    `source_tool` and `verification` set.
  - `test_thales_checkpoint_resume` — interrupt after the research phase
    (mock a node to raise once / cancel), resume via the FEAT-399
    checkpoint (`AgentsFlow.resume(flow_id, checkpoint_id)` or the runner's
    resume path) and complete the run.
  - `test_thales_partial_sources` — `sources=["web", "arxiv"]` (deep
    disabled) → run succeeds; decks cite only web+arxiv.
- Write `docs/flows/thales.md`: quickstart (Python API + HTTP), the ≥10
  `num_decks` floor and its cost implication (N angles × M sources research
  calls), source list & the `research-tools-for-agents` extension contract,
  artifact/manifest layout, PDF behavior with/without weasyprint,
  verification-channel semantics (`groundedness` vs `provider_grounding`).
- Verify and tick the spec §5 acceptance-criteria boxes that are satisfied;
  report any that aren't (do NOT tick unmet criteria).

**NOT in scope**: fixing implementation bugs beyond small integration glue
(file findings for anything structural); real-LLM/network tests.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/thales/test_integration.py` | CREATE | e2e / resume / degradation tests |
| `packages/ai-parrot/tests/flows/thales/conftest.py` | CREATE | `mock_research_outputs` + shared fixtures |
| `docs/flows/thales.md` | CREATE | User guide |
| `sdd/specs/agentcrew-tales-research.spec.md` | MODIFY | Tick satisfied §5 acceptance criteria |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-17 against `dev`.

### Verified Imports
```python
from parrot.flows.thales import ThalesRunner                  # TASK-2231
from parrot.flows.thales.models import ThalesConfig, ThalesResult
from parrot.bots.flows.flow.flow import AgentsFlow            # flow/flow.py:173
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py — checkpoint/resume:
class AgentsFlow(PersistenceMixin):                    # L173
    #   __init__(..., checkpoint: bool = False, flow_id: Optional[str] = None, ...)
    def suspend(self): ...                             # dump ephemeral history to durable storage
    @classmethod
    def resume(cls, flow_id, checkpoint_id): ...       # reconstruct + resume (FEAT-399)
# Checkpoint tests precedent: packages/ai-parrot/tests/flows/checkpoint/
#   (e.g. test_flow_export.py) — reuse their store fixtures/mocks rather
#   than standing up real Redis.

# Fixture precedent for mocked deep research:
#   packages/ai-parrot/tests/test_deep_research_mock.py — how the
#   interactions stream/client is mocked without network.
```

### Does NOT Exist
- ~~Live-network or real-LLM tests in CI~~ — everything mocked; no API keys.
- ~~`docs/flows/`~~ — directory may not exist yet; create it (verify —
  check before use).
- ~~A pre-existing conftest for thales tests~~ — this task creates it.
- ~~`AgentsFlow.resume()` as an instance method~~ — it is a classmethod
  `resume(cls, flow_id, checkpoint_id)` (flow.py API outline).

---

## Implementation Notes

### Key Constraints
- All three integration tests must run offline and deterministically.
- Fixtures include one duplicate URL (bibliography dedupe assertion) and
  one date-less source ("n.d." assertion) — mirroring the spec §4 fixture
  description.
- The e2e test asserts manifest completeness by walking
  `ThalesResult.model_dump()` against the artifacts written to `tmp_path`.
- Docs follow the existing docs/ tone (see `docs/orchestration/agentsflow.md`
  for style precedent).

### References in Codebase
- `packages/ai-parrot/tests/flows/checkpoint/` — checkpoint test fixtures.
- `tests/integration/test_crew_infographic_e2e.py` — FEAT-308 e2e precedent
  for infographic assertions.

---

## Acceptance Criteria

- [ ] All three integration tests pass offline: `pytest packages/ai-parrot/tests/flows/thales/test_integration.py -v`
- [ ] e2e run yields ≥10 decks, per-deck slides, final document, bibliography-last ordering, summary + infographic, complete `manifest.json`
- [ ] Checkpoint-resume test completes a run interrupted mid-flow
- [ ] Partial-sources run degrades without error
- [ ] `docs/flows/thales.md` covers quickstart, ≥10 floor + cost note, extension contract, PDF behavior, verification channels
- [ ] Spec §5 checklist updated truthfully (unmet criteria reported, not ticked)
- [ ] No linting errors: `ruff check packages/ai-parrot/tests/flows/thales/`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/thales/test_integration.py
import pytest

@pytest.mark.asyncio
async def test_thales_e2e_mocked_llm(tmp_path, mock_research_outputs):
    runner = ThalesRunner(thesis="open-source flight stacks bridge LATAM talent",
                          output_dir=tmp_path, ...)
    result = await runner.run()
    assert len(result.decks) >= 10
    assert (tmp_path / "manifest.json").exists()
    assert all(f.claims for d in result.decks for f in d.findings)

@pytest.mark.asyncio
async def test_thales_checkpoint_resume(tmp_path, mock_research_outputs):
    """Interrupt after research; resume completes and manifest is whole."""

@pytest.mark.asyncio
async def test_thales_partial_sources(tmp_path, mock_research_outputs):
    runner = ThalesRunner(thesis="t", sources=["web", "arxiv"], output_dir=tmp_path, ...)
    result = await runner.run()
    tools = {c.source_tool for d in result.decks for f in d.findings for c in f.claims}
    assert "deep_research" not in tools
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-2231, TASK-2232 must be in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code
4. **Update status** in `sdd/tasks/index/agentcrew-tales-research.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2233-thales-integration-tests-docs.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude, Sonnet)
**Date**: 2026-08-17
**Notes**: Implemented `conftest.py` (`FakeAgent`/`FakeClient` dispatching
by call shape — `structured_output=` for planner/slide_spec,
`deep_research=True` for the deep node, plain `question=` for
`synthesize_results`; `mock_research_outputs` fixture with a duplicate
arxiv URL across every angle for bibliography dedupe and one date-less
angle for "n.d."; an autouse `patched_checkpoint_store` in-memory
`CheckpointStore` fixture, since `assemble_thales_flow` always passes
`checkpoint=True` and every test that runs a real flow would otherwise
hit a real Redis) and `test_integration.py` (e2e — now exercising BOTH
persistence surfaces + a populated infographic, not just output_dir;
checkpoint persistence; partial sources). All 3 pass offline; full
`packages/ai-parrot/tests/flows/thales/` suite: **77 passed**.

Found and fixed one real bug via genuine e2e execution (not caught by
any prior unit test, since none constructed `FinalDocumentNode` with
`store=None`): it crashed with `AttributeError: 'NoneType' object has
no attribute 'save_artifact'`. Fixed with the same None-guard pattern
used everywhere else in the feature; regression test added to TASK-2230's
`test_fanin_nodes.py`.

Walked spec §5 truthfully (10/12 ticked): two criteria explicitly
NOT ticked, per the cardinal rule against ticking unmet criteria:
1. **Checkpoint resume** — persistence during a run IS verified
   (`test_checkpoint_is_written_during_a_run`), but a full
   `AgentsFlow.resume()` round-trip genuinely does not work for Thales's
   node shapes (`resume()` calls `from_definition()` with no
   `node_factories` param — confirmed by reading its body — so none of
   Thales's custom-field-heavy nodes can be reconstructed). Fixing this
   is an engine change the spec's own AC list forbids ("No changes to
   flow.py"). Documented in both the spec and `docs/flows/thales.md`.
2. **`ResearchDeck.groundedness` deck-level provenance** — never
   populated (per-claim `SourceClaim.verification` labeling IS correct
   and tested; the separate deck-level dict field is simply unused).
   Closing this would require widening `_ResearchNode`'s deps wire
   format, which would break TASK-2229's already-shipped
   `DeckBuilderNode` test fixtures — left as a reported gap rather than
   a risky ripple-effect change, per this task's own scope note.

Wrote `docs/flows/thales.md` (quickstart Python + HTTP, the `num_decks`
floor and its N×M cost, source list + the `research-tools-for-agents`
extension contract, artifact/manifest layout, PDF behavior, verification
channels, and a dedicated section on the checkpoint-resume limitation).
`ruff check` on every touched/created file shows only pre-existing style
categories. `grep -r matplotlib` empty. Verified `git diff dev...HEAD`
touches none of `flow.py`/`crew.py`/`abstract.py`.

**Deviations from spec**: See the two unticked acceptance criteria above
(both verified, both documented, neither silently worked around).
