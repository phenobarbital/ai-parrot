---
type: feature
base_branch: dev
feature_id: FEAT-898
projects: [ai-parrot]
tags: [bots, guardrails, security, ledger-fix]
discovered_from: issue:062128ff0d48
docs:
  policy: none
  pages: []
  api_modules: []
---

# Feature Specification: OUTPUT guardrails — scan the text answer beside a structured output

**Feature ID**: FEAT-898
**Date**: 2026-11-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:062128ff0d48` (minor vulnerability, discovered from `spec:FEAT-894`, filed by the FEAT-894
`/sdd-fix` run as out of scope there): `AbstractBot._run_output_pipeline` (`abstract.py:3297`) returns early
when `response.output` is not a `str` (`abstract.py:3328`). The whole OUTPUT pipeline is skipped, including a text
`response.response` kept beside the structured output.

`AIMessage.to_text` (`models/responses.py:263`) prefers `response.response`, so that text is what the caller
renders. Three producers put a string there beside a non-`str` `output`:

- A client that returns an explanation apart from a dict / DataFrame / HTML `output` (reproduced with
  `_ExplanationSecretClient`, `test_finalize_persist_turn.py:370`).
- `ask()` with a non-default output mode, where the formatter returns non-`str` content and a wrapped string
  (`base.py:1760–1762`).
- `get_response` (`abstract.py:5094`, used by `invoke` and `conversation`), which writes the markdown
  "**Question** / **Answer**" block (`abstract.py:5114`). It echoes the user's question and renders
  `str(output)` (`abstract.py:5022–5023`).

Example: with `SecretsGuardrail` on the OUTPUT stage, `ask()` against `_ExplanationSecretClient`
(`output={"html": "<b>chart</b>"}`, `response="your key is API_KEY=sk-…"`) returns the raw key in
`response.response` and `to_text`. Reproduced on `feat-FEAT-894-bots-abstract-tech-debt` (`d4f24dc697`).

The persisted turn is already safe: `_stored_turn_text` (`abstract.py:3404`) scans text the pipeline never judged
before it is stored (FEAT-886). The gap is the caller-visible text only.

### Goals
- When the OUTPUT pipeline has guardrails, `output` is not a `str`, and `response.response` is a non-empty `str`,
  that text is scanned once by the OUTPUT pipeline:
  - TRANSFORM rewrites `response.response`;
  - BLOCK replaces `response.response` with `_OUTPUT_BLOCKED_TEXT` and sets `metadata["error"] =
    "security_block"` (plus `block_reason` when given), as the `str` BLOCK path does;
  - FLAG reports reach `metadata["guardrails"]`.
- `_OUTPUT_VERDICT` records that verdict, so `_stored_turn_text` reuses it when the stored text is the scanned text.
  `ask()` against `_ExplanationSecretClient` still runs the OUTPUT guardrails exactly once.
- The structured `output` is never rewritten or replaced. A non-`str` `output` with no text answer beside it
  (`response.response` `None`, empty, or not a `str`) runs no guardrail, as today.
- The `str`-output path (PASS, TRANSFORM, BLOCK, `_propagate_output_verdict`) keeps its behaviour.

### Non-Goals (explicitly out of scope)
- Scanning the structured payload itself (walking a dict, a DataFrame or a `BaseModel`). `output` and
  `structured_output` stay as returned. A secret inside them still reaches a caller that reads them directly.
- `PandasAgent.ask` (`bots/data.py:1362`), which has no OUTPUT pipeline at all (documented at `data.py:2250`).
  That is a separate, deliberate design, not this early return.
- `issue:8f65307982dd` (turn-save transaction and per-session serialization). It is claimed by another session,
  which is handling it as FEAT-895 (`bots-abstract-tech-debt-2`).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:5dfb4350db770f85e3f4b77582ca97dafc26dcb6c3390f398558962485412c6d evaluation_digest=sha256:b1cb4433be0bb01d8c1f0c8cd109e80b10bca43e96544599d5cad2c871ffab58 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One change in `AbstractBot._run_output_pipeline` (`abstract.py:3297`):

1. The early return at `:3328` keeps only the `not pipeline.has_guardrails` case, plus a non-`str` `output` with
   no non-empty `str` `response.response`.
2. The text to scan is `response.output` for a `str` output and `response.response` otherwise. The
   `GuardrailContext` is built as today, then `pipeline.run(text, ctx)` is called.
3. For a non-`str` output, a new private helper `_apply_verdict_beside_structured_output(response, text, outcome,
   ctx)` applies the verdict to `response.response` only. It sets `_OUTPUT_VERDICT` to `(id(response), text,
   <verdict text>, ctx)`, where the verdict text is `_OUTPUT_BLOCKED_TEXT` on BLOCK, otherwise `outcome.content`
   (or `text` when `None`). On BLOCK it also sets `metadata["error"]` / `block_reason`, and on non-blocked runs it
   merges `outcome.flag_reports`. It returns `response`.
4. The `str` path below is unchanged.

`_propagate_output_verdict` is not called on the structured path: there is no `str` `output` to alias or fall
back to.

**BLOCK beside a structured output.** The verdict judged the text, not the payload, so only the text is replaced.
`output` keeps its type, so callers that index into a dict or a DataFrame do not crash on a block.
`structured_output` keeps the original either way, so replacing `output` would not withhold the payload.
`metadata["error"] == "security_block"` tells the caller the response was blocked.

**Cost.** A structured response with a text answer now runs the OUTPUT guardrails on that text:
- `ask()` against such a client: still one run, because `_stored_turn_text` reuses the verdict.
- `invoke` / `conversation`: two runs instead of one. The markdown wrapper is scanned in the pipeline, and the
  plain answer is scanned again in `_stored_turn_text`, as for a `str` output since FEAT-894.

A guardrail that calls an external service runs for these responses. That is accepted: the text is what the
caller renders.

### Component Diagram
```
ask() / get_response()
   └─ response.response = <text>              (client explanation / formatter wrapper / as_markdown)
   └─ _run_output_pipeline(response)
         ├─ output is str     → pipeline.run(output)  → existing PASS | TRANSFORM | BLOCK handling
         └─ output not str
               ├─ no text answer  → return (no run)
               └─ text answer     → pipeline.run(response.response)
                                      → _apply_verdict_beside_structured_output   ← new
                                          (rewrite / block text, flags, _OUTPUT_VERDICT; output untouched)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot._run_output_pipeline` | modifies | early return `abstract.py:3328`, docstring `:3313–3316` |
| `AbstractBot._apply_verdict_beside_structured_output` | new private method | next to `_propagate_output_verdict` |
| `AbstractBot._stored_turn_text` | consumer, unchanged | `abstract.py:3404`, reads `_OUTPUT_VERDICT` |
| `AbstractBot.get_response` | consumer, unchanged | `abstract.py:5094`, calls the pipeline at `:5128` |
| `BaseBot.ask` | consumer, unchanged | `base.py:1772` |
| `BaseBot.ask_stream` | consumer, unchanged | `base.py:2362` |

### Data Models
None.

### New Public Interfaces
None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: OUTPUT verdict for the text beside a structured output | yes | the branch, the helper and its verdict tuple are fixed in §2; the tests are listed in §4 | — |

### Module 1: OUTPUT verdict for the text beside a structured output
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`,
  `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py`
- **Responsibility**: a non-`str` `output` with a text answer beside it gets the OUTPUT verdict on that text.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # abstract.py — _run_output_pipeline (replaces the early return at :3328)
  _OUTPUT_VERDICT.set(None)
  pipeline = self._guardrail_pipelines[GuardrailStage.OUTPUT]
  structured = not isinstance(response.output, str)
  text = response.response if structured else response.output
  if not pipeline.has_guardrails or (structured and (not isinstance(text, str) or not text)):
      return response
  ctx = GuardrailContext(...)  # unchanged
  outcome = await pipeline.run(text, ctx)
  if structured:
      return self._apply_verdict_beside_structured_output(response, text, outcome, ctx)
  original = response.output
  ...  # existing str path, unchanged

  def _apply_verdict_beside_structured_output(
      self, response: AIMessage, text: str, outcome: PipelineOutcome, ctx: GuardrailContext
  ) -> AIMessage: ...
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_a_text_answer_beside_a_structured_output_is_redacted_for_the_caller` | M1 | `ask()` against `_ExplanationSecretClient` → the secret is in neither `response.response` nor `to_text`, `REDACTED` is in `response.response`, `output == {"html": "<b>chart</b>"}`, and the OUTPUT pipeline ran exactly once (the stored text reuses the verdict) |
| `test_a_question_echoed_beside_a_structured_output_is_redacted[invoke]` / `[conversation]` | M1 | a client with a dict `output` and no text answer; a question that carries a secret → the secret is not in `response.response` / `to_text`, `**Question**` is still there, `output` is the dict |
| `test_a_structured_output_with_no_text_answer_runs_no_guardrail[dict]` / `[dataframe]` | M1 | `_run_output_pipeline` on `output={"a": 1}` / a DataFrame with `response=None` → zero pipeline runs, `output` and `response` unchanged |
| `test_a_blocked_text_beside_a_structured_output` | M1 | an OUTPUT guardrail that BLOCKs text containing `secret-word` → `response.response == _OUTPUT_BLOCKED_TEXT`, `metadata["error"] == "security_block"`, `block_reason` set, `output` is the same dict |
| `test_text_the_pipeline_never_scanned_is_still_redacted_before_it_is_persisted` | M1 | existing (`:380`), unchanged; the stored and published text stay redacted |
| `test_a_dataframe_output_does_not_break_ask_and_is_persisted` and the other existing tests in the four contract files | M1 | unchanged; prove the `str` path, the DataFrame path and persistence hold |

### Integration Tests
| Test | Description |
|---|---|
| `test_structured_output_left_untouched` | existing (`tests/integration/test_guardrails_output.py:100`), unchanged: a dict `output` with no text answer is not rewritten |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py
- packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py
- packages/ai-parrot/tests/integration/test_guardrails_output.py
- packages/ai-parrot/tests/integration/test_security_guardrails_e2e.py
markers: none

### Test Data / Fixtures

The new tests reuse the helpers in `test_finalize_persist_turn.py` (`_guarded_bot`, `_stored`,
`_ExplanationSecretClient`) and in `test_turn_publish_after_save.py` (`SECRET`, `Client`, `_bot`). The BLOCK test
defines one local `Guardrail` subclass with `stages = {GuardrailStage.OUTPUT}`. The run counter wraps
`pipeline.run`, as `test_a_passing_response_scans_each_distinct_text_once` does.

---

## 5. Acceptance Criteria

- [ ] With OUTPUT guardrails registered, a non-empty `str` `response.response` beside a non-`str` `output` is
      scanned. A TRANSFORM rewrites it, a BLOCK replaces it with `_OUTPUT_BLOCKED_TEXT` and sets
      `metadata["error"] = "security_block"`, and FLAG reports reach `metadata["guardrails"]`.
- [ ] A non-`str` `output` is never rewritten. With no text answer beside it, no guardrail runs.
- [ ] `ask()` against `_ExplanationSecretClient` runs the OUTPUT guardrails exactly once.
- [ ] The new tests fail on `origin/dev` without the fix (mutation check) and pass with it.
- [ ] The four Validation Contract files pass from the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] `ruff check` passes on the changed files. `black` (line length 120) leaves the changed lines unchanged.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.bots.abstract import _OUTPUT_BLOCKED_TEXT  # verified: abstract.py:235
from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailResult, GuardrailStage  # verified: tests/integration/test_guardrails_output.py:23-28
from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail  # verified: test_finalize_persist_turn.py:29
from parrot.bots.guardrails.pipeline import PipelineOutcome  # verified: pipeline.py:62
from parrot.models import AIMessage  # verified: test_finalize_persist_turn.py:21
from .test_turn_publish_after_save import SECRET, Client, RecordingPublisher, _SecretClient, _bot  # verified: test_finalize_persist_turn.py:24
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
_OUTPUT_VERDICT: ContextVar[Optional[Tuple[int, str, str, Any]]]  # line 233 — (id(response), scanned, verdict, ctx)
_OUTPUT_BLOCKED_TEXT = "This response could not be delivered due to a content policy violation."  # line 235
class AbstractBot:
    async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage  # line 3297
        # :3313-3316 docstring: structured/DataFrame outputs are left untouched
        # :3328 early return when no guardrails or output is not a str
        # :3349-3356 BLOCK → output/response = blocked text, metadata error/block_reason
        # :3358-3370 non-blocked → _OUTPUT_VERDICT, TRANSFORM, _propagate_output_verdict, flag_reports
    async def _propagate_output_verdict(
        self, response: AIMessage, original: str, pipeline: Any, ctx: GuardrailContext,
        blocked_text: Optional[str] = None,
    ) -> None  # line 3372
    async def _stored_turn_text(self, response: AIMessage, plain: Optional[str], method: str = "persist")
        -> Optional[str]  # line 3404 — reuses _OUTPUT_VERDICT when plain == verdict[1]
    def as_markdown(self, response: AIMessage, ...) -> str  # line 5014 — :5022 Question, :5023 Answer: {output}
    async def get_response(self, response: AIMessage, return_sources: bool = True,
                           return_context: bool = False, return_tools: bool = False) -> AIMessage  # line 5094
        # :5114 response.response = self.as_markdown(...); :5128 return await self._run_output_pipeline(...)

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
class PipelineOutcome(BaseModel):  # line 62
    content: str | None  # line 78 — None when blocked
    blocked: bool  # line 79
    reason: str | None  # line 80
    flag_reports: dict[str, dict[str, Any]]  # line 81
class GuardrailPipeline:  # line 85
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome  # line 151

# packages/ai-parrot/src/parrot/bots/base.py
#   :1583 _plain_answer = response.to_text if isinstance(response.output, str) or response.response else None
#   :1760-1762 formatter: response.output = content; response.response = wrapped
#   :1772 response = await self._run_output_pipeline(response, method="ask")
#   :1785 assistant_text=await self._stored_turn_text(response, _plain_answer)

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage:
    output: Any  # line 99
    response: Optional[str]  # line 100
    @property
    def to_text(self) -> str  # line 263 — prefers self.response
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_apply_verdict_beside_structured_output` | `_OUTPUT_VERDICT` | `_OUTPUT_VERDICT.set((id(response), text, verdict, ctx))` | `abstract.py:233` |
| `_apply_verdict_beside_structured_output` | `_stored_turn_text` | reads `_OUTPUT_VERDICT` | `abstract.py:3422–3426` |

### Does NOT Exist (Anti-Hallucination)
- ~~`AbstractBot._apply_verdict_beside_structured_output`~~ — created by this feature.
- ~~a scan of `response.response` when `output` is not a `str`~~ — added by this feature.
- ~~a guardrail hook that walks a dict / DataFrame `output`~~ — there is none, and this feature adds none.
- ~~`test_a_text_answer_beside_a_structured_output_is_redacted_for_the_caller`,
  `test_a_question_echoed_beside_a_structured_output_is_redacted`,
  `test_a_structured_output_with_no_text_answer_runs_no_guardrail`,
  `test_a_blocked_text_beside_a_structured_output`~~ — created by this feature.

### Edit Sites (Blueprint Anchors)

Verified against: `e644c8f39c`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        Mirrors the pre-migration channel-egress guard` | `abstract.py:3313` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        if not pipeline.has_guardrails or not isinstance(response.output, str):` | `abstract.py:3328` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        outcome = await pipeline.run(response.output, ctx)` | `abstract.py:3346` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | ADD AFTER | `    async def _propagate_output_verdict(` (insert the helper before it) | `abstract.py:3372` | 1 |
| `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` | ADD AFTER | `async def test_text_the_pipeline_never_scanned_is_still_redacted_before_it_is_persisted():` (append after this test) | `test_finalize_persist_turn.py:380` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Build the `GuardrailContext` once, before the branch, so both paths share it.
- `_apply_verdict_beside_structured_output` is synchronous: it only applies an outcome.
- `black` line length 120, Google-style docstrings, strict type hints.

### Known Risks / Gotchas
- In a worktree the shared venv imports the main checkout: run pytest with `PYTHONPATH=packages/ai-parrot/src`.
- Never compare a DataFrame `output` with `==` or use it in a boolean context: that raises "truth value of a
  DataFrame is ambiguous" (`test_a_dataframe_output_does_not_break_ask_and_is_persisted`). The branch tests only
  `isinstance(response.output, str)`.
- `_OUTPUT_VERDICT` must be set on every scanned structured run, BLOCK included, so `_stored_turn_text` reuses it.
- FEAT-895 (`bots-abstract-tech-debt-2`, another session) edits `abstract.py` around `_persist_turn_unit`, which is
  far from the OUTPUT pipeline. A textual merge conflict is unlikely.

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:5dfb4350db770f85e3f4b77582ca97dafc26dcb6c3390f398558962485412c6d evaluation_digest=sha256:b1cb4433be0bb01d8c1f0c8cd109e80b10bca43e96544599d5cad2c871ffab58 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/f6bc0fce-c159-489e-87f9-3c2c9fe1644d/scratchpad/dev-clone/sdd/specs/bots-abstract-fixes.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: guardrails, ledger-fix, security
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "guardrails",
      "ledger-fix",
      "security"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/f6bc0fce-c159-489e-87f9-3c2c9fe1644d/scratchpad/dev-clone/sdd/specs/bots-abstract-fixes.spec.md"
    }
  ],
  "evaluation_digest": "sha256:b1cb4433be0bb01d8c1f0c8cd109e80b10bca43e96544599d5cad2c871ffab58",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:5dfb4350db770f85e3f4b77582ca97dafc26dcb6c3390f398558962485412c6d",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Q1. On BLOCK, replace the structured `output` too? — *Resolved*: no. The verdict judged the text, not the
  payload. Replacing `output` would change its type for callers that index into it, and `structured_output` keeps
  the original anyway. `metadata["error"] == "security_block"` marks the block.
- [x] Q2. Scan `str(output)` when there is no text answer? — *Resolved*: no. That is the "scan the structured
  payload" non-goal. It would also add a run to every structured agent that returns no text.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `none` — guardrail fix inside one private method, documented by its docstrings. No wiki page
  describes `_run_output_pipeline`'s structured-output branch.
- **Pages**: none.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-898-bots-abstract-fixes` off `origin/dev`.

- Module graph: one module, no edges.
- Shared files: none.
- Exclusive resources: none.
- Cross-feature: FEAT-895 (`bots-abstract-tech-debt-2`) also edits `abstract.py`, in the persistence section.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-14 | Jesus Lara | Created by /sdd-fix from `issue:062128ff0d48` (fixgroup:88037d5f223f) |
