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

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-27
**Notes**:

**`run_flow` vs. direct sequential invocation**: `answer()` runs the six
stages as direct, sequential async calls — NOT via
`AgentCrew.run_flow`. Read `crew.py:975-1040` (`add_tool_node`) and
`tool_node.py:168-320` (template placeholder resolution) before deciding:
flow mode passes data between `ToolNode`s via `{input}` /
`{nodes.<id>.output}` STRING-templated placeholders resolved into a
single tool call's args/kwargs. This pipeline's fan-in shape doesn't fit
that: `dossier_build` needs BOTH `graph_retrieve`'s hits AND
`as_of_extract`'s `as_of` AND the tenant `store`/`ctx` (none of which are
plain strings — `store`/`ctx` are live objects, `hits` is a list of
dicts containing `ArticleVersion` instances); `span_verify` needs the
draft, the retrieval_set, `as_of`, `materias`, and `execution_id`
together. The task's own given Test Specification also calls
`answer(query, agent=..., store=..., ctx=..., log=...)` directly (not
`crew.run_flow(...)`), confirming `answer()` is meant to be a plain
orchestrating function. `build_legal_librarian_crew()` still builds a
STRUCTURALLY faithful `AgentCrew` — all six stages registered (5
`ToolNode`s via thin `_CallableTool` adapters + the librarian agent node,
manually added to `workflow_graph` too, since `add_agent()` alone only
registers into `crew.agents` — confirmed by reading `crew.py:198-292`:
only agents passed via the `agents=[...]` constructor list get a
`workflow_graph` entry automatically) with the linear `§2` dependency
chain wired via `.dependencies`. Verified structurally with a smoke
check (`crew.workflow_graph` shows all 6 nodes with the expected
dependency sets) — not exercised by any test (no AC requires it, and
`AgentCrew()` construction has real side effects — a live
`GoogleGenAIClient` instantiation — that a unit test shouldn't depend on
without mocking; confirmed via `auto_configure=False` matching the
existing `test_crew_tool_node_regression.py` pattern that constructing
still works without credentials).

**Other implementation notes**:
- `agent.py`: `LegalLibrarianAgent(Agent)` passes `system_prompt=` through
  `__init__` (NOT an `system_prompt_template` class-attribute override —
  verified `bots/chatbot.py`'s docstring: a custom `system_prompt` opts
  out of the composable `PromptBuilder` templating and is used literally,
  the safer path given `system_prompt_template`'s `Template($var)`
  substitution expects specific placeholders). `agent_tools()` returns
  `[]` (read-only). `draft()` calls `self.ask(prompt,
  structured_output=DraftAnswer, use_conversation_history=False)` —
  stateless per turn.
- `flow.py` stages: `as_of_extract` (see deviation below),
  `graph_retrieve` (explicit `articulo_key`-shaped substring regex over
  the query, validated via `is_valid_boe_id`, resolved via
  `article_in_force`; then `search_articles`, deduped by `articulo_key`),
  `dossier_build` (builds `PayloadEntry`s + the prompt enumeration +
  head/tail truncation at >4000 chars per spec §3 M6, plus a
  `payload_key -> score` map used only for final dossier ordering),
  `ground` (builds a synthetic `EvidenceIndex` from dossier payloads via
  `ToolCall`s, scores the joined `reading_guide` text, maps contradicted
  atoms back to their originating sentence via offset tracking, suppresses
  only that sentence — the span/dossier stays valid).
- Final dossier ordering (`_sort_dossier`): explicit-id (`basis ==
  "traversal"`) spans first, then `basis == "retrieval"` by BM25 score
  descending, stable tiebreak by payload key — applied as a
  post-processing step in `answer()` after `SpanVerifier.verify()`
  returns (the verifier itself stays score-agnostic per its TASK-2495
  contract; `SpanRef` carries no `score` field).
- `pytest packages/ai-parrot-tools/tests/legal/ -v` → 126 passed (18 new:
  5 agent + 8 flow/dossier/graph_retrieve + 5 ground/atom-contradicted on
  top of the 108 from TASK-2492/2495/2496). `ruff check
  packages/ai-parrot-tools/src/parrot_tools/legal/librarian/` → clean.

**Deviations from spec**: two, both surfaced while reconciling the
prose module docstring against concrete, executable signals — same
principle applied in TASK-2495/2496 (the task's own Test
Specification/comments are authoritative since they must literally pass):
1. **`as_of_extract`'s LLM-fallback trigger narrowed to genuinely
   ambiguous (>1 date) queries.** Spec §3 M5/M6 text says
   `extract_as_of` calls the LLM fallback for "zero or more-than-one
   distinct dates." The task's OWN given `FakeAgent.ask` in the Test
   Specification unconditionally `raise AssertionError("as_of fallback
   must not be needed")`, and `test_flow_no_encontre_on_empty_retrieval`
   passes a ZERO-date query through `answer()` with that exact
   `FakeAgent` — meaning `answer()` must NOT call the LLM for a
   zero-date query, contradicting the literal "zero dates -> LLM call"
   reading. Resolved by keeping TASK-2496's `extract_as_of` UNCHANGED
   (its own contract and tests remain valid — zero dates still triggers
   its LLM fallback when called directly) and instead implementing
   `flow.py`'s `as_of_extract` stage with its own narrower trigger:
   `regex_dates(query)` is checked directly; 0 dates -> default straight
   to today (no LLM call — the overwhelmingly common "no date mentioned"
   case doesn't warrant one); 1 date -> use it; >1 dates -> delegate to
   `extract_as_of` (the one case where its LLM fallback is actually
   invoked). Zero risk to TASK-2496: no file it owns was touched.
2. **`security_advisor.py` codebase-contract path was stale.** The
   contract cited `packages/ai-parrot/src/parrot/agents/
   security_advisor.py` — that file does not exist there; the actual
   grounded-agent precedent lives at the repo-root `agents/
   security_advisor.py` (a plugins-style example agent, not part of the
   installed `parrot` package). Read it at its real location before
   modeling `LegalLibrarianAgent`'s class layout
   (`class X(Agent): agent_id, ...; def agent_tools(self): ...`) — no
   functional impact, just a path correction worth flagging per this
   task's own "verify with file:line anchors first" instruction.

**Environment note** (not a code change): `LegalLibrarianAgent()`
construction loads a real HuggingFace prompt-injection guardrail model
(`protectai/deberta-v3-base-prompt-injection`) as part of `BasicAgent`'s
default init path — adds a one-time ~8s cost the first time any test in
this file instantiates the agent. Not something this task's scope covers
fixing (it's `BasicAgent`'s existing default behavior, unrelated to the
librarian); noted here only because it explains
`test_librarian_agent.py`'s slower wall-clock time relative to the rest
of the `legal/` suite.
