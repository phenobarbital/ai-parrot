---
type: feature
base_branch: dev
feature_id: FEAT-893
projects: [ai-parrot]
tags: [bots, guardrails, security, pandas-agent, ledger-fix]
discovered_from: issue:3e29dbe2f16a
docs:
  policy: none
  pages: []
  api_modules: []
---

# Feature Specification: PandasAgent.ask — OUTPUT guardrails on the returned answer

**Feature ID**: FEAT-893
**Date**: 2026-11-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:3e29dbe2f16a` (major vulnerability, discovered from `spec:FEAT-886` in the review of PR #2121):
`PandasAgent.ask` (`bots/data.py:1362`) is a full override that never reaches `BaseBot.ask`, and it never
calls `AbstractBot._run_output_pipeline` (`bots/abstract.py:3296`). The answer it returns reaches the caller
without an OUTPUT guardrail verdict, so for example `SecretsGuardrail` redaction is skipped.

Re-verified on `origin/dev` `d76103c422` (PR #2121 merged) for this spec:

- `data.py` contains no `_run_output_pipeline` call. Its own comment says
  `# PandasAgent has NO output pipeline` (`data.py:2250`).
- `answer_memory.store_interaction(...)` (`data.py:2239`) stores the unscanned `answer_text`.
- FEAT-886 commit `2a923cc86c` scans only the **persisted** conversation turn, through
  `_stored_turn_text` inside the save `try` (`data.py:2263`). The caller still receives the raw text.
- `PandasAgent.ask` has six `return response` sites (`data.py:2033`, `:2056`, `:2069`, `:2081`, `:2096`,
  `:2293`). The first five are early returns for the infographic, interactive and inline A2UI paths. None of
  the six gives the answer an OUTPUT verdict.

The caller-visible answer is in more than one place:

- `response.response`, which `AIMessage.to_text` prefers (`models/responses.py:263`).
- `response.output` (`content` is an alias of `output`, `models/responses.py:241`). In DEFAULT, TELEGRAM and
  MSTEAMS modes it is the LLM's structured `PandasAgentResponse`, whose `explanation` is the same answer
  (`data.py:1734`).

`_run_output_pipeline` only scans a plain-text `output`. Calling it alone would leave the DEFAULT-mode
answer unscanned, because there `output` is a `PandasAgentResponse`.

### Goals
- Every successful return of `PandasAgent.ask` (all six sites) gives the caller-visible answer text an OUTPUT
  guardrail verdict: TRANSFORM rewrites it, BLOCK replaces it with the canned notice and sets
  `metadata["error"] = "security_block"`, and FLAG reports are merged into `metadata["guardrails"]`.
- That verdict covers a plain-text `output`, `response.response`, and the `explanation` of the
  structured `PandasAgentResponse`. No unredacted copy survives in the returned `AIMessage`.
- `AnswerMemory.store_interaction` and the persisted conversation turn receive the judged text. Persistence
  reuses that verdict instead of running the guardrails a second time.
- Without OUTPUT guardrails, behaviour and output are unchanged, and no guardrail code runs.

### Non-Goals (explicitly out of scope)
- Persisting turns on the five early-return paths. They return before `answer_memory` and
  `_persist_finalized_turn` today. That is a separate defect, filed as its own ledger issue by this run.
  FEAT-892 TASK-5673 (agent-memory-mixin, pending) plans a single preparation/finalization step for
  `PandasAgent.ask`.
- Scanning non-text payloads: `response.data` rows, `response.code`, chart and map configs, A2UI envelopes and
  HTML artifacts. This matches `_run_output_pipeline`'s rule that structured and DataFrame outputs stay
  untouched.
- Any change to `AbstractBot`, `BaseBot`, `_run_output_pipeline`, `_stored_turn_text` or the guardrail
  pipeline.
- `PandasAgent.ask_stream`: it is inherited from `BaseBot.ask_stream`, which already runs the pipeline
  (`base.py:2362`).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:4711bfdb7d1ce8b6abc5bc59034e2d289af2b69ecd675fd5b327af2c2ebda5b9 evaluation_digest=sha256:7200fe72036475b4ab6bd91a5f1a9367d5eb1e0e666facd73844c765ada70b3a rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

All production changes are in `bots/data.py`:

1. **New method `PandasAgent._guard_answer(response, data_response=None, method="ask") -> AIMessage`.**
   It returns `response` unchanged when `self._guardrail_pipelines[GuardrailStage.OUTPUT].has_guardrails` is
   false. Otherwise it:
   1. Runs `await self._run_output_pipeline(response, method=method)`. This judges a plain-text `output`
      exactly as `BaseBot.ask` does and propagates a rewrite to an aliased or wrapped `response.response`.
      If that run BLOCKed (`metadata["error"] == "security_block"`), it applies the block to every text
      field (step 4) and returns.
   2. Seeds a per-call `judged: Dict[str, str]` cache with text that step 1 already judged: the final `output`
      when it is a `str`, and `response.response` when step 1 changed it.
   3. Judges each remaining caller-visible text that is a non-empty `str`, using the cache: first
      `response.response`, then `data_response.explanation`. One `GuardrailContext` serves the call. It is
      built like `_stored_turn_text` builds its own (`stage=OUTPUT`, `agent_name`, `user_id`, `session_id`,
      `method`, `extras=self._output_extras(response, pipeline)`). Each `pipeline.run` merges its FLAG
      reports through `self._merge_guardrail_reports`. A TRANSFORM writes the rewritten text back to its field.
   4. **BLOCK** on any text: `response.response`, a `str` `output` and `data_response.explanation` all become
      `_OUTPUT_BLOCKED_TEXT` (imported from `.abstract`, so the notice is the one `BaseBot` uses).
      `metadata["error"] = "security_block"` and `metadata["block_reason"]` are set when a reason exists.
      Data, code and artifacts are left in place, as `_run_output_pipeline` does on a BLOCK.
2. **Main path.** Right after the markdown-table repair and before `answer_memory.store_interaction`
   (`data.py:2239`), it calls `response = await self._guard_answer(response, data_response)` and re-reads
   `answer_text = getattr(response, "response", None) or response.content`. `store_interaction` and the
   persisted turn then receive the judged text. The persisted `assistant_text` becomes
   `str(answer_text) if answer_text else ""` instead of a second `_stored_turn_text` scan. After the repair
   step, `response.response` is the `str` answer whenever there is one, so the text is already judged.
3. **Early returns.** The five early `return response` sites become
   `return await self._guard_answer(response, data_response)`.
4. A guardrail error follows the pipeline's own `on_error` contract. `fail_closed` becomes a BLOCK and
   `fail_open` a PASS (`guardrails/pipeline.py:175`). The judge runs before the save `try`, so an unexpected
   exception fails the request as in `BaseBot.ask` and is never swallowed into returning unscanned text.

### Component Diagram
```
PandasAgent.ask ─┬─ early returns (infographic / interactive / inline A2UI) ─┐
                 └─ main path: formatter → repair markdown ──────────────────┤
                                                                             ▼
                                        _guard_answer(response, data_response)
                                          ├─ _run_output_pipeline (str output)
                                          └─ pipeline.run (response.response, explanation)
                                                                             ▼
                          main path only: answer_memory.store_interaction → _persist_finalized_turn
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot._run_output_pipeline` | uses | `abstract.py:3296`, unchanged |
| `AbstractBot._output_extras` | uses | `abstract.py:3289`, unchanged |
| `AbstractBot._merge_guardrail_reports` | uses | `abstract.py:3431`, unchanged |
| `GuardrailPipeline.run` / `.has_guardrails` | uses | `guardrails/pipeline.py:151` / `:135` |
| `PandasAgent.ask` | modifies | six return sites and the persistence text |

### Data Models
None new.

### New Public Interfaces
None. `_guard_answer` is private to `PandasAgent`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: PandasAgent answer guard | yes | The algorithm, call sites, BLOCK semantics and persistence text are fixed in §2 | — |

### Module 1: PandasAgent answer guard
- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`,
  `packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py`
- **Responsibility**: one OUTPUT verdict for the answer `PandasAgent.ask` returns, remembers and persists.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # data.py — imports, after `from .mixins.intent_router import IntentRouterMixin` (data.py:29)
  from .abstract import _OUTPUT_BLOCKED_TEXT
  from .guardrails.base import GuardrailContext, GuardrailStage

  class PandasAgent(IntentRouterMixin, BasicAgent):
      async def _guard_answer(
          self,
          response: AIMessage,
          data_response: Optional[PandasAgentResponse] = None,
          method: str = "ask",
      ) -> AIMessage:
          """Give the answer ``ask()`` returns an OUTPUT guardrail verdict (FEAT-893)."""
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_text_answer_is_redacted_for_the_caller` | M1 | `SecretsGuardrail`; stub client returns the secret as `output` and `response` → returned `output`, `response`, `content`, `to_text` hold no secret and contain `REDACTED` |
| `test_structured_answer_explanation_is_redacted` | M1 | stub client returns a `PandasAgentResponse(explanation=<secret>)` as `output` → returned `response.response` and `response.output.explanation` are redacted |
| `test_answer_memory_and_persisted_turn_get_the_judged_text` | M1 | `answer_memory.get(turn_id)` answer, stored history turn and published turn are redacted |
| `test_persistence_does_not_rescan` | M1 | a counting OUTPUT guardrail runs once per distinct text, and never on the persisted text a second time |
| `test_block_replaces_every_answer_field` | M1 | a BLOCKing OUTPUT guardrail → `response`, `output` (str) or `explanation` carry the canned notice, `metadata["error"] == "security_block"` |
| `test_early_return_path_is_guarded` | M1 | the interactive early return (patched `_extract_last_interactive_result` / `_finalize_interactive_response`) returns a redacted `response.response` |
| `test_no_guardrails_leaves_the_answer_untouched` | M1 | no OUTPUT guardrails → answer unchanged, no `guardrails` metadata |
| existing `test_finalize_persist_turn.py::test_pandas_agent_*` | M1 | unchanged; prove the FEAT-886 persistence contract still holds |

### Integration Tests
| Test | Description |
|---|---|
| — | none; the unit tests drive the real `PandasAgent.ask` with a stub client and a real `SecretsGuardrail` |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py
- packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py
markers: none

### Test Data / Fixtures

The tests reuse `_pandas()` / `_PandasClient` from `tests/unit/bots/test_finalize_persist_turn.py` and `SECRET`
from `tests/unit/bots/test_turn_publish_after_save.py`, which is how FEAT-886's own PandasAgent tests are built.

---

## 5. Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py
      packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` passes from the worktree with
      `PYTHONPATH=packages/ai-parrot/src`.
- [ ] With `SecretsGuardrail` on the OUTPUT stage, no field of the `AIMessage` returned by `PandasAgent.ask`
      (`output`, `content`, `response`, `to_text`, structured `explanation`) contains the secret, on both the
      main path and an early-return path.
- [ ] `AnswerMemory` and the persisted conversation turn hold the redacted text. Each distinct answer text is
      judged once.
- [ ] A BLOCKing OUTPUT guardrail yields the canned notice and `metadata["error"] == "security_block"`.
- [ ] With no OUTPUT guardrails the returned answer is byte-identical to today's.
- [ ] `ruff check` passes on the changed test file, and `bots/data.py` gains no new findings over the 7
      pre-existing ones (`issue:aee666627fc7`).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.bots.data import PandasAgent, PandasAgentResponse  # verified: data.py:124, :415
from parrot.bots.guardrails.base import GuardrailContext, GuardrailStage  # verified: abstract.py:133
from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail  # verified: test_finalize_persist_turn.py:231
from parrot.bots.abstract import _OUTPUT_BLOCKED_TEXT  # verified: abstract.py:237 (module constant)
from parrot.models import AIMessage  # verified: test_finalize_persist_turn.py:20
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    self._guardrail_pipelines: Dict[GuardrailStage, GuardrailPipeline]  # line 755
    def _output_extras(self, response: AIMessage, pipeline: GuardrailPipeline) -> Dict[str, Any]  # line 3289
    async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage  # line 3296
        # resets _OUTPUT_VERDICT; no-op unless pipeline.has_guardrails and isinstance(response.output, str);
        # BLOCK → output = _OUTPUT_BLOCKED_TEXT, metadata["error"] = "security_block", metadata["block_reason"]
    async def _stored_turn_text(self, response: AIMessage, plain: Optional[str], method: str = "persist") -> Optional[str]  # line 3392
    def _merge_guardrail_reports(self, response: AIMessage, flag_reports: Dict[str, Dict[str, Any]]) -> None  # line 3431

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
class PipelineOutcome(BaseModel):  # line 62 — content: str | None, blocked: bool, reason: str | None, flag_reports
class GuardrailPipeline:
    def has_guardrails(self) -> bool  # line 135 (property)
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome  # line 151

# packages/ai-parrot/src/parrot/bots/data.py
class PandasAgentResponse(BaseModel):  # line 124 — explanation: str, data, data_variable(s), code
class PandasAgent(IntentRouterMixin, BasicAgent):  # line 415
    async def ask(self, question: str, session_id=None, user_id=None, use_conversation_history=True, memory=None,
                  ctx=None, structured_output=None, output_mode=None, format_kwargs=None,
                  return_structured=True, use_tools=True, **kwargs) -> AIMessage  # line 1362
        # data_response: Optional[PandasAgentResponse] bound at :1676

# packages/ai-parrot/src/parrot/memory/agent.py
class AnswerMemory:  # line 7
    async def store_interaction(self, turn_id: str, question: str, answer: Any) -> None  # line 15
    async def get(self, turn_id: str) -> Optional[Dict[str, Any]]  # line 26
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_guard_answer` (main path) | `PandasAgent.ask` | call before `answer_memory.store_interaction` | `data.py:2239` |
| `_guard_answer` (early returns) | `PandasAgent.ask` | `return await self._guard_answer(response, data_response)` | `data.py:2033, 2056, 2069, 2081, 2096` |
| judged persisted text | `_persist_finalized_turn` | `assistant_text=` | `data.py:2263-2269` |

### Does NOT Exist (Anti-Hallucination)
- ~~`_run_output_pipeline` call in `bots/data.py`~~: none on `d76103c422`. This feature adds it, inside
  `_guard_answer`.
- ~~`PandasAgent.ask_stream`~~: not overridden. The inherited `BaseBot.ask_stream` already runs the pipeline.
- ~~a public "judge this text" helper on `AbstractBot`~~: only `_run_output_pipeline` (scans `output`) and
  `_stored_turn_text` (persistence text, discards FLAG reports, hides BLOCK) exist.
- ~~`tests/unit/bots/test_pandasagent_output_guardrails.py`~~: created by this feature.

### Edit Sites (Blueprint Anchors)

Verified against: `d76103c422`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `from .mixins.intent_router import IntentRouterMixin` | `data.py:29` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `    async def ask(` | `data.py:1362` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `                            return response` (infographic A2UI, after `"InfographicRenderResult detected (A2UI) — bypassing formatter: "`) | `data.py:2033` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `return response  # skip formatter + structured reformat` (infographic HTML, then interactive HTML) | `data.py:2056`, `:2081` | 2 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `                        return response` (interactive A2UI after `interactive_envelope.artifact_id,`; inline A2UI after `else:`) | `data.py:2069`, `:2096` | 3 (with :2033) |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `                await self.answer_memory.store_interaction(` | `data.py:2239` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `# PandasAgent has NO output pipeline` | `data.py:2250` | 1 |
| `packages/ai-parrot/src/parrot/bots/data.py` | MODIFY | `_stored_text = (await self._stored_turn_text(response, str(answer_text))) if answer_text else None` | `data.py:2263` | 1 |
| `packages/ai-parrot/tests/unit/bots/test_pandasagent_output_guardrails.py` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `_run_output_pipeline` and `_stored_turn_text` for building `GuardrailContext` and handling the
  outcome. Do not change either of them.
- `black` line length 120, Google-style docstrings, strict type hints, `self.logger` only.
- Keep the guard a no-op when the OUTPUT pipeline is empty. Most PandasAgents run without guardrails.

### Known Risks / Gotchas
- In a worktree the shared venv imports the main checkout. Run pytest with `PYTHONPATH=packages/ai-parrot/src`.
- After the markdown repair, `response.response` is the `str` answer whenever one exists. The persisted
  text relies on this, so keep the guard after the repair and before `store_interaction`.
- `_run_output_pipeline` resets the task's `_OUTPUT_VERDICT`. `_guard_answer` does not depend on it, and
  persistence no longer calls `_stored_turn_text`.
- `bots/data.py` has 7 pre-existing ruff findings (`issue:aee666627fc7`). Do not fix them here and do not add
  new ones.
- FEAT-892 TASK-5673 also edits `PandasAgent.ask` (pending, not started). Its anchors will need re-verification
  after this merges.

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:4711bfdb7d1ce8b6abc5bc59034e2d289af2b69ecd675fd5b327af2c2ebda5b9 evaluation_digest=sha256:7200fe72036475b4ab6bd91a5f1a9367d5eb1e0e666facd73844c765ada70b3a rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/b79dcf75-656f-42a1-a81f-bad70e986aef/scratchpad/dev-clone/sdd/specs/bots-data-fixes-2.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: guardrails, ledger-fix, pandas-agent, security
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
      "pandas-agent",
      "security"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/b79dcf75-656f-42a1-a81f-bad70e986aef/scratchpad/dev-clone/sdd/specs/bots-data-fixes-2.spec.md"
    }
  ],
  "evaluation_digest": "sha256:7200fe72036475b4ab6bd91a5f1a9367d5eb1e0e666facd73844c765ada70b3a",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:4711bfdb7d1ce8b6abc5bc59034e2d289af2b69ecd675fd5b327af2c2ebda5b9",
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

- [x] Q1. Reuse parent FEAT-886 or a new feature? *Resolved (/sdd-fix)*: new feature. The planner listed
  FEAT-886 as `open` only because the main checkout's local `dev` was 73 commits behind. On `origin/dev`
  its index has `completed_at` set and PR #2121 is merged.
- [x] Q2. Should the early-return paths also persist the turn? *Out of scope*. They are filed as a separate
  ledger issue. This feature only guarantees that the returned answer carries a verdict on every path.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `none`. This is an internal security fix with no new public API. No wiki page describes
  PandasAgent's guardrail coverage.
- **Pages**: none.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-893-bots-data-fixes-2` off `origin/dev`.

- Module graph: one module, no edges.
- Shared files: none.
- Exclusive resources: none.
- Cross-feature: FEAT-892 TASK-5673 later modifies `PandasAgent.ask` in the same file.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-14 | Jesus Lara | Created by /sdd-fix from `issue:3e29dbe2f16a` (fixgroup:6d5c6e4dd1d6) |
