# TASK-2497: `LegalLibrarianAgent` + retrieval DAG (`ToolNode` stages around one LLM node)

**Feature**: FEAT-449 — Legal Librarian Answer Layer
**Spec**: `sdd/specs/legal-librarian-answer-layer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2495, TASK-2496
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 — assembles the §2 flow:
`as_of_extract → graph_retrieve → dossier_build → librarian (LLM) → span_verify → ground`.
Every stage except `librarian` is a deterministic callable wrapped in a
`ToolNode`; the single LLM node emits a `DraftAnswer` (payload keys + verbatim
quotes — never offsets) and the post-LLM gates seal the final `LegalAnswer`.

Blocks TASK-2499.

---

## Scope

- `librarian/agent.py`: `class LegalLibrarianAgent(Agent)` — read-only (no
  write tools mounted), no conversation memory, low temperature; class
  docstring carries the R2 invariant verbatim. System prompt = librarian rules
  (R1/R5: may rank, flag conflicts, state corpus-scoped absence, narrate
  traversal-derived context; must NOT resolve conflicts or assert beyond the
  dossier) + "the ONLY legal `payload_key` values are the ones enumerated;
  quotes must be copied verbatim from the shown text". Expose
  `async def draft(self, enumerated_dossier: str, query: str, as_of: date) -> DraftAnswer`
  that calls `self.ask(..., structured_output=DraftAnswer)` and returns
  `response.structured_output`.
- `librarian/flow.py`: stage callables + a builder:
  1. `as_of_extract(query) -> {query, as_of}` (default `date.today()`), using
     `extract_as_of` with the agent's `ask` bound as `llm_ask`.
  2. `graph_retrieve` — explicit-id pass FIRST (`BOE-A-\d{4}-\d+` regex,
     `is_valid_boe_id`, `article_key` shapes) resolved via
     `article_in_force(store, ctx, key, as_of)`; THEN
     `search_articles(store, ctx, query, as_of, limit=20)`.
  3. `dossier_build` — `retrieval_set: dict[str, PayloadEntry]` (payload =
     stored normalized text; `content_hash` carried from the record, NOT
     recomputed), explicit-id entries first, then BM25 order, cap 20; prompt
     enumeration shows `payload_key`, title, `valid_from`/`valid_to`, full
     text (>4000 chars ⇒ head 2000 + `\n[...]\n` + tail 1000, flagged).
  4. `librarian` — `LegalLibrarianAgent.draft(...)`.
  5. `span_verify` — `SpanVerifier.verify(...)`; `SuppressionLog.append`
     each record; fill `as_of`, `materias`, `suppressed_count`, `disclaimer`.
  6. `ground` — `GroundednessScorer().score(guide_text, evidence)` with
     `evidence = EvidenceIndex` built from dossier payloads; any
     `contradicted` numeric/identifier atom ⇒ suppress that sentence via the
     same record path (`atom_contradicted`).
  Builder `build_legal_librarian_crew(agent, store, ctx, log) -> AgentCrew`
  registering the six nodes with `add_tool_node` / agent node and wiring
  dependencies; plus a convenience
  `async def answer(query, *, agent, store, ctx, log, user_id=None) -> LegalAnswer`
  that runs the stages (via `run_flow` or direct sequential calls if
  `ToolNode` plumbing needs data passing that flow mode does not support —
  verify `tool_node.py`/`crew.py` first and note the choice).
- Final dossier order: explicit-id spans first, then BM25 desc, stable
  tiebreak by `payload_key`.
- Tests (LLM mocked with canned `DraftAnswer`s; store = `FakeGraphStore`):
  `test_dossier_build_order_and_truncation`, `test_explicit_boe_id_resolved_first`,
  `test_flow_prunes_fabricated_payload_key`, `test_flow_prunes_mangled_quote`,
  `test_flow_ground_suppresses_contradicted_atom`, `test_flow_no_encontre_on_empty_retrieval`,
  `test_agent_has_no_write_tools`.

**NOT in scope**: multi-materia routing / `IntentRouterMixin`; guide
regeneration after pruning (R12 — returned as-is); wiki adapter (TASK-2498).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/agent.py` | CREATE | `LegalLibrarianAgent` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/flow.py` | CREATE | stages, builder, `answer()` |
| `packages/ai-parrot-tools/src/parrot_tools/legal/librarian/__init__.py` | MODIFY | exports |
| `packages/ai-parrot-tools/tests/legal/test_librarian_flow.py` | CREATE | flow tests with mocked LLM |
| `packages/ai-parrot-tools/tests/legal/test_librarian_agent.py` | CREATE | agent config tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-08-27 against `dev` (+ TASK-2495/2496 deliverables).

### Verified Imports
```python
from parrot.bots import Agent                                            # bots/__init__.py:4  (Agent at bots/agent.py:1236)
from parrot.bots.flows.crew import AgentCrew, ToolNode                   # flows/crew/__init__.py:5-13; ToolNode tool_node.py:168
from parrot.security.groundedness.scorer import GroundednessScorer       # scorer.py:56
from parrot.security.groundedness.evidence import EvidenceIndex          # evidence.py:31
from parrot.security.groundedness.policy import GroundednessReport, AtomVerdict  # policy.py:58,43
from parrot_tools.legal.ids import is_valid_boe_id, article_key, normalize_boe_id  # ids.py:43,94,19
from parrot_tools.legal.boe.queries import article_in_force, search_articles       # queries.py:24 (+TASK-2496)
from parrot_tools.legal.librarian.models import (DraftAnswer, LegalAnswer, PayloadEntry, SuppressionRecord)  # TASK-2495
from parrot_tools.legal.librarian.verifier import SpanVerifier           # TASK-2495
from parrot_tools.legal.librarian.suppression import SuppressionLog      # TASK-2495
from parrot_tools.legal.librarian.as_of import extract_as_of             # TASK-2496
```

### Existing Signatures to Use
```python
# bots/abstract.py:4202
async def ask(self, ..., structured_output: Optional[Union[Type[BaseModel], StructuredOutputConfig]] = None, ...) -> AIMessage
#   parsed model on `response.structured_output`.

# bots/flows/crew/tool_node.py:168
class ToolNode(Node):
    tool: ToolLike; node_id: str; args: List[Any]; kwargs: Dict[str, Any]
    description: Optional[str]; dependencies: Set[str]; successors: Set[str]
#   "Registered into a crew via AgentCrew.add_tool_node()" — crew.py:975 def add_tool_node(...)
#   READ crew.py:975-1040 and tool_node.py:168-300 for how a ToolNode receives the previous
#   node's output in flow mode (template placeholders in args/kwargs) BEFORE deciding between
#   run_flow and direct sequential invocation.

# security/groundedness
class GroundednessScorer:
    def __init__(self, policy: GroundednessPolicy | None = None)                    # scorer.py:66
    def score(self, answer_text: str, evidence: EvidenceIndex) -> GroundednessReport  # scorer.py:74
class EvidenceIndex:
    def __init__(self)                                                              # evidence.py:52
    @classmethod from_tool_calls(cls, tool_calls, policy, user_prompt=None)         # evidence.py:61
#   inner helper add_text(text) at evidence.py:91 — check whether a public "add text" entry point
#   exists; if only from_tool_calls is public, build a synthetic ToolCall list from dossier payloads.
class AtomVerdict(BaseModel): atom: Atom; verdict: Literal["supported","contradicted","unsupported"]  # policy.py:43
class GroundednessReport(BaseModel): score, total_atoms, supported, contradicted, unsupported, ...   # policy.py:58
#   READ policy.py:58-100 to find the per-atom verdict list field name (needed to map a
#   contradicted atom back to its sentence).
```

### Does NOT Exist
- ~~`LegalLibrarianAgent`, `librarian/flow.py`~~ — created here.
- ~~`KnowledgeRouter`~~ — does not exist; no routing in v1.
- ~~`GraphIndexToolkit` reading `norma`/`articulo`~~ — impossible (closed `NodeKind`); never route legal retrieval through GraphIndex.
- ~~LLM-emitted `SpanRef.start/end`~~ — the agent emits `DraftAnswer` only.
- ~~`GroundednessScorer` as the span verifier~~ — it is the complementary atom check in stage 6 only.
- ~~Reading-guide regeneration after pruning~~ — R12: returned as-is.
- ~~Conversation memory on the librarian~~ — none; each `answer()` is stateless.

---

## Implementation Notes

### Pattern to Follow
```python
# dossier enumeration (stage 3)
def _enumerate(entries: list[PayloadEntry], windows: dict[str, tuple[str, str | None]]) -> str:
    lines = []
    for e in entries:
        text = e.payload if len(e.payload) <= 4000 else e.payload[:2000] + "\n[...]\n" + e.payload[-1000:] + "\n(texto truncado en la muestra; la verificación usa el texto íntegro)"
        vf, vt = windows[e.payload_key]
        lines.append(f"### payload_key: {e.payload_key}\n{e.title} — vigente {vf} → {vt or 'actualidad'}\n{text}")
    return "\n\n".join(lines)
```

### Key Constraints
- Stages 1–3, 5, 6 are pure/deterministic given the store — no LLM inside.
- `content_hash` in `PayloadEntry` is carried from the record; recomputation
  is the verifier's job.
- One LLM call for the draft (+ at most one for `as_of` fallback).
- `execution_id`: generate with `uuid4().hex` per `answer()` call.
- `self.logger` at stage boundaries; Google-style docstrings; strict typing.

### References in Codebase
- `packages/ai-parrot/src/parrot/agents/security_advisor.py` — grounded, read-only agent precedent (`_audit_citations`)
- `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py:106,975` — `AgentCrew`, `add_tool_node`
- `packages/ai-parrot-tools/tests/legal/conftest.py` — `FakeGraphStore`, `legal_tenant_ctx`

---

## Acceptance Criteria

- [ ] A canned `DraftAnswer` citing a `payload_key` not in the retrieval set ⇒ span pruned, sentence suppressed, `SuppressionRecord(span_not_found)` appended to the (fake) log, `suppressed_count == 1`
- [ ] A canned draft with a mangled quote ⇒ pruned + `quote_mismatch`
- [ ] Empty retrieval ⇒ `LegalAnswer.not_found` non-empty, `dossier == []`, no exception, LLM still may be skipped (document the choice)
- [ ] `LegalAnswer.as_of` equals the date used by `graph_retrieve`
- [ ] Explicit `BOE-A-…` id in the query is resolved via `article_in_force` and ordered first in the dossier
- [ ] A guide sentence with a numeric atom contradicted by the evidence is suppressed with reason `atom_contradicted`
- [ ] `LegalLibrarianAgent` mounts no write tools and has no memory
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/legal/ -v`
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/legal/librarian/`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/legal/test_librarian_flow.py
from datetime import date
import pytest
from parrot_tools.legal.librarian.models import DraftAnswer, DraftReadingNote, DraftSpan
from parrot_tools.legal.librarian.flow import answer


class FakeLog:
    def __init__(self): self.records = []
    async def append(self, record): self.records.append(record)


class FakeAgent:
    """Stands in for LegalLibrarianAgent — returns a canned DraftAnswer."""
    def __init__(self, draft): self._draft = draft
    async def draft(self, enumerated_dossier, query, as_of): return self._draft
    async def ask(self, *a, **k): raise AssertionError("as_of fallback must not be needed")


async def test_flow_prunes_fabricated_payload_key(seeded_store, legal_tenant_ctx):
    fabricated = DraftAnswer(reading_order=["BOE-A-9999-1:art99:0"], conflicts=[], not_found=[],
        reading_guide=[DraftReadingNote(text="Dice algo inventado.", basis="llm",
                                        spans=[DraftSpan(payload_key="BOE-A-9999-1:art99:0", quote="inventado")])])
    log = FakeLog()
    ans = await answer("plazo de tres meses a 2019-06-01", agent=FakeAgent(fabricated),
                       store=seeded_store, ctx=legal_tenant_ctx, log=log)
    assert ans.as_of == date(2019, 6, 1)
    assert all(r.id != "BOE-A-9999-1:art99" for r in ans.dossier)
    assert ans.suppressed_count == 1 and log.records[0].reason in {"span_not_found", "anchor_lost"}
    assert all(note.spans for note in ans.reading_guide)


async def test_flow_no_encontre_on_empty_retrieval(fake_store, legal_tenant_ctx):
    ans = await answer("jurisprudencia del TC sobre X", agent=FakeAgent(DraftAnswer(reading_order=[], conflicts=[], reading_guide=[], not_found=[])),
                       store=fake_store, ctx=legal_tenant_ctx, log=FakeLog())
    assert ans.dossier == [] and ans.reading_guide == [] and ans.not_found
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§2 Overview flow, §3 M6, §6, §7 "Structured-output size")
2. **Check dependencies** — TASK-2495 and TASK-2496 completed
3. **Verify the Codebase Contract** — read `crew.py:975-1040`, `tool_node.py:168-320`, `policy.py:58-100`, `evidence.py:31-170` before designing stage plumbing
4. **Update status** in `sdd/tasks/index/legal-librarian-answer-layer.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-2497-librarian-agent-and-retrieval-flow.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below — state whether `run_flow` or direct sequential invocation was used and why

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
