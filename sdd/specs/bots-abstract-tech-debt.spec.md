---
type: feature
base_branch: dev
feature_id: FEAT-894
projects: [ai-parrot]
tags: [bots, guardrails, security, ledger-fix]
discovered_from: issue:a20713dc67a6
docs:
  policy: none
  pages: []
  api_modules: []
---

# Feature Specification: OUTPUT guardrails — scan a presentation wrapper when the output passes

**Feature ID**: FEAT-894
**Date**: 2026-11-14
**Author**: Jesus Lara
**Status**: approved
**Target version**: next patch

---

## 1. Motivation & Business Requirements

### Problem Statement

Ledger `issue:a20713dc67a6` (minor vulnerability, discovered from `spec:FEAT-886`, declared deferred in
PR #2121): `AbstractBot._run_output_pipeline` (`abstract.py:3296`) hands the OUTPUT verdict to
`response.response` through `_propagate_output_verdict` (`abstract.py:3363`) only on BLOCK (`:3345`) or on
TRANSFORM (`:3354–3356`). When the pipeline passes, a distinct string in `response.response` reaches the caller
unscanned.

`AIMessage.to_text` (`models/responses.py:263`) prefers `response.response`, so that string is the text the
caller renders. Two producers write a string there that differs from `output`:

- `get_response` (`abstract.py:5080`, used by `invoke` and `conversation`) writes the markdown
  "**Question** / **Answer** / **Sources**" block from `as_markdown` (`abstract.py:5100`). It echoes the user's
  question and the source titles, which are not in `output`.
- `ask()` with a non-default output mode writes the formatter's wrapped string (`base.py:1760–1762`), which can
  embed data that is not in `output`.

Example: with `SecretsGuardrail` on the OUTPUT stage, `invoke("my key is API_KEY=sk-…")` returns an answer
`"reply"` (PASS). The wrapper echoes the key in its Question block, and the caller receives it unredacted.

The persisted turn is already safe: `_stored_turn_text` (`abstract.py:3392`) stores the plain answer with a
verdict applied, never the wrapper (FEAT-886). The gap is the caller-visible text only.

### Goals
- On every non-blocked run, a non-empty string in `response.response` that differs from `response.output` is
  scanned by the same OUTPUT pipeline, whether `output` passed or was transformed. A TRANSFORM rewrites it, and a
  BLOCK replaces it with `response.output`. This is what `_propagate_output_verdict` already does on TRANSFORM.
- No extra pipeline run when `response.response` is `None`, empty, not a `str`, or equal to `response.output`.
  A plain `ask()` with no formatter still runs the OUTPUT guardrails exactly once.
- The BLOCK path, `_OUTPUT_VERDICT` and `_stored_turn_text` keep their behaviour.

### Non-Goals (explicitly out of scope)
- `issue:8f65307982dd` (no transaction spans the working-memory write and the outbox append in
  `_persist_turn_unit`; same-session requests are not serialized). It is in the same ledger fix group, but it is
  a cross-store design item, not part of this fix. This run does not claim it.
- The five `lint:duplicate-slug` issues of the same group (`AbstractBot.llm`, `.status`, `.system_prompt`,
  `.prompt_pipeline`, `.prompt_builder` and their `~2` setter pages). The `DuplicateSlugRule` change in PR #2113
  retires them, not code in `abstract.py`.
- Structured outputs. `_run_output_pipeline` returns early when `output` is not a `str` (`abstract.py:3321`), so
  a text `response.response` beside a dict or DataFrame `output` is still not scanned there. That early return is
  documented as deliberate ("matching today's behavior exactly"). Changing it changes behaviour for every
  structured agent, so it is filed as its own ledger issue by this run.
- The streaming path (`ask_stream`, `base.py:2362`), which does not write a presentation wrapper.

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:db1932a1fb527f298bc0a9ba5341a02b0cc750ca78ddd54c58bb330738be3933 evaluation_digest=sha256:625b56ba88792ae633715642ba536fd9f5dfa46b7e709e892f049dfb7edb6f84 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

One change in `AbstractBot._run_output_pipeline`'s non-blocked branch (`abstract.py:3351–3356`):

1. Apply a TRANSFORM to `response.output`, as today.
2. Call `await self._propagate_output_verdict(response, original, pipeline, ctx)` for every non-blocked outcome,
   not only inside the TRANSFORM `if`.

`_propagate_output_verdict` (`abstract.py:3363–3390`) needs no new branch:

- It returns early when `response.response` is not a non-empty `str`, or equals `response.output`. That covers an
  `ask()` without formatter, where `response.response` is `None` or the same text, so there is still one run.
- On PASS, `output == original`, so a distinct wrapper falls through to its last branch. It is scanned with the
  same `ctx`. A TRANSFORM result replaces it, and a BLOCK replaces it with `response.output`. The wrapper's FLAG
  reports are discarded, as on TRANSFORM today.
- On TRANSFORM, behaviour is unchanged.

The comment at `:3351–3352` ("a PASS never runs the guardrails a second time") and the docstrings of both
methods are updated: a PASS runs the guardrails a second time only for a distinct presentation wrapper.

**Cost.** A distinct wrapper now costs a second pipeline run on PASS, as it already did on TRANSFORM. This
applies to every `invoke` / `conversation` response and to formatter output modes in `ask()`. A guardrail that
calls an external service runs twice for those responses. That is accepted: the wrapper is the text the caller
renders.

### Component Diagram
```
ask() / get_response()
   └─ response.response = <wrapper>          (formatter / as_markdown)
   └─ _run_output_pipeline(response)
         ├─ pipeline.run(output)              → PASS | TRANSFORM | BLOCK
         └─ non-blocked: _propagate_output_verdict(response, …)   ← now also on PASS
               └─ distinct wrapper → pipeline.run(wrapper) → rewrite | fall back to output
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractBot._run_output_pipeline` | modifies | non-blocked branch, `abstract.py:3351–3356` |
| `AbstractBot._propagate_output_verdict` | reused, docstring only | `abstract.py:3363` |
| `AbstractBot.get_response` | consumer, unchanged | `abstract.py:5080`, calls the pipeline at `:5114` |
| `BaseBot.ask` | consumer, unchanged | `base.py:1772` |
| `BaseBot.ask_stream` | consumer, unchanged | `base.py:2362`, writes no wrapper |

### Data Models
None.

### New Public Interfaces
None.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: OUTPUT verdict reaches a passing response's wrapper | yes | the one call move, comment and docstrings are fixed in §2; the tests are listed in §4 | — |

### Module 1: OUTPUT verdict reaches a passing response's wrapper
- **Path**: `packages/ai-parrot/src/parrot/bots/abstract.py`,
  `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py`
- **Responsibility**: a non-blocked OUTPUT run always hands its verdict to a distinct `response.response`.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # abstract.py — _run_output_pipeline, non-blocked branch (replaces :3351-3356)
  _OUTPUT_VERDICT.set((id(response), original, outcome.content if outcome.content is not None else original, ctx))
  if outcome.content is not None and outcome.content != original:
      response.output = outcome.content
  # comment: a distinct presentation wrapper in `response.response` carries the verdict even on PASS
  await self._propagate_output_verdict(response, original, pipeline, ctx)
  ```

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_a_passing_response_scans_each_distinct_text_once[ask-1]` | M1 | replaces `test_a_passing_response_runs_the_output_guardrails_once`; `ask()` with no wrapper → exactly one OUTPUT run |
| `test_a_passing_response_scans_each_distinct_text_once[invoke-2]` / `[conversation-2]` | M1 | `get_response` wrapper → two runs: the answer, then the markdown block (contains `**Question**`) |
| `test_a_passing_output_still_scans_its_wrapper` | M1 | `_run_output_pipeline` on `AIMessage(output="reply", response="<div>reply API_KEY=<secret></div>")` → `output == "reply"`, the secret is in neither `response.response` nor `to_text`, `REDACTED` is in `response.response` |
| `test_a_question_echoed_in_the_markdown_wrapper_is_redacted[invoke]` / `[conversation]` | M1 | a question that carries a secret, answer `"reply"` → the secret is not in `response.response` / `to_text`; `**Question**` is still there |
| `test_a_blocked_wrapper_falls_back_to_the_passing_output` | M1 | an OUTPUT guardrail that BLOCKs only text containing `<div>`; `output="reply"`, `response="<div>reply</div>"` → `response.response == "reply"`, `output == "reply"`, no `security_block` in `metadata` |
| existing tests in the four contract files | M1 | unchanged; prove TRANSFORM, BLOCK, alias and persistence behaviour hold |

### Integration Tests
| Test | Description |
|---|---|
| — | none beyond the unchanged `tests/integration/test_guardrails_output.py` and `tests/integration/test_security_guardrails_e2e.py`, which pin TRANSFORM / BLOCK / FLAG through the same method |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py
- packages/ai-parrot/tests/unit/bots/test_turn_publish_after_save.py
- packages/ai-parrot/tests/integration/test_guardrails_output.py
- packages/ai-parrot/tests/integration/test_security_guardrails_e2e.py
markers: none

### Test Data / Fixtures

The new tests reuse the helpers in `test_finalize_persist_turn.py` (`_guarded_bot`, `_stored`) and in
`test_turn_publish_after_save.py` (`SECRET`, `Client`, `RecordingPublisher`, `_bot`). The BLOCK test defines one
local `Guardrail` subclass with `stages = {GuardrailStage.OUTPUT}`.

---

## 5. Acceptance Criteria

- [ ] With the OUTPUT pipeline passing, a distinct `response.response` is scanned. A TRANSFORM rewrites it, and a
      BLOCK replaces it with `response.output`.
- [ ] `ask()` without a wrapper still runs the OUTPUT guardrails exactly once.
- [ ] The new tests fail on `origin/dev` without the fix (mutation check) and pass with it.
- [ ] The four Validation Contract files pass from the worktree with `PYTHONPATH=packages/ai-parrot/src`.
- [ ] `ruff check` passes on the changed files. `black` (line length 120) leaves the changed lines unchanged.

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.bots.guardrails.base import Guardrail, GuardrailAction, GuardrailResult, GuardrailStage  # verified: tests/integration/test_guardrails_output.py:23-28
from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail  # verified: test_finalize_persist_turn.py:28
from parrot.models import AIMessage  # verified: test_finalize_persist_turn.py:20
from .test_turn_publish_after_save import SECRET, Client, RecordingPublisher, _SecretClient, _bot  # verified: test_finalize_persist_turn.py:23
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/bots/abstract.py
class AbstractBot:
    async def _run_output_pipeline(self, response: AIMessage, method: str) -> AIMessage  # line 3296
        # :3321 early return when no guardrails or output is not a str
        # :3342-3349 BLOCK → _propagate_output_verdict(..., blocked_text=response.output)
        # :3351-3356 non-blocked → _OUTPUT_VERDICT.set(...); propagate only on TRANSFORM
    async def _propagate_output_verdict(
        self, response: AIMessage, original: str, pipeline: Any, ctx: GuardrailContext,
        blocked_text: Optional[str] = None,
    ) -> None  # line 3363
    async def _stored_turn_text(self, response: AIMessage, plain: Optional[str], method: str = "persist")
        -> Optional[str]  # line 3392
    async def get_response(self, response: AIMessage, return_sources: bool = True,
                           return_context: bool = False, return_tools: bool = False) -> AIMessage  # line 5080
        # :5100 response.response = self.as_markdown(...); :5114 return await self._run_output_pipeline(...)

# packages/ai-parrot/src/parrot/bots/guardrails/pipeline.py
class GuardrailPipeline:  # line 85
    async def run(self, content: str, ctx: GuardrailContext) -> PipelineOutcome
        # non-blocked → content is the working content (never None); blocked → content None

# packages/ai-parrot/src/parrot/models/responses.py
class AIMessage:
    response: Optional[str]  # line 100
    @property
    def to_text(self) -> str  # line 263 — prefers self.response
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| unconditional propagate call | `_propagate_output_verdict` | `await self._propagate_output_verdict(response, original, pipeline, ctx)` | `abstract.py:3356` |

### Does NOT Exist (Anti-Hallucination)
- ~~a scan of `response.response` on PASS~~ — added by this feature.
- ~~a guardrail capability flag that marks a guardrail FLAG-only~~ — there is none; the wrapper scan runs the
  whole pipeline, as the TRANSFORM path does.
- ~~`test_a_passing_response_scans_each_distinct_text_once`~~ — created by this feature (it replaces
  `test_a_passing_response_runs_the_output_guardrails_once`, `test_finalize_persist_turn.py:272`).

### Edit Sites (Blueprint Anchors)

Verified against: `ff384eefbf`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        # (TRANSFORM) is propagated, so a PASS never runs the guardrails a second time.` | `abstract.py:3352` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `            await self._propagate_output_verdict(response, original, pipeline, ctx)` | `abstract.py:3356` | 1 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | `        """Make a TRANSFORM/BLOCK verdict reach ``response.response`` too (FEAT-886).` | `abstract.py:3371` | 1 |
| `packages/ai-parrot/tests/unit/bots/test_finalize_persist_turn.py` | MODIFY | `async def test_a_passing_response_runs_the_output_guardrails_once(entry: str):` | `test_finalize_persist_turn.py:272` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Keep `_propagate_output_verdict`'s early returns as the only gate for the extra run. Do not add a second check
  in `_run_output_pipeline`.
- `black` line length 120, Google-style docstrings, strict type hints.

### Known Risks / Gotchas
- In a worktree the shared venv imports the main checkout: run pytest with `PYTHONPATH=packages/ai-parrot/src`.
- `test_a_passing_response_runs_the_output_guardrails_once` pins the old invariant for `invoke` / `conversation`
  and must be replaced, not deleted. The `ask` case still asserts one run.
- `_OUTPUT_VERDICT` must still be set before the propagate call. `_stored_turn_text` reads it, and it records the
  `output` verdict, not the wrapper's.

### External Dependencies
None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:db1932a1fb527f298bc0a9ba5341a02b0cc750ca78ddd54c58bb330738be3933 evaluation_digest=sha256:625b56ba88792ae633715642ba536fd9f5dfa46b7e709e892f049dfb7edb6f84 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/f6bc0fce-c159-489e-87f9-3c2c9fe1644d/scratchpad/dev-clone/sdd/specs/bots-abstract-tech-debt.spec.md; message: no fenced yaml block under '## Decisions'

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
      "path": "/tmp/claude-1000/-home-jesuslara-proyectos-ai-parrot/f6bc0fce-c159-489e-87f9-3c2c9fe1644d/scratchpad/dev-clone/sdd/specs/bots-abstract-tech-debt.spec.md"
    }
  ],
  "evaluation_digest": "sha256:625b56ba88792ae633715642ba536fd9f5dfa46b7e709e892f049dfb7edb6f84",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:db1932a1fb527f298bc0a9ba5341a02b0cc750ca78ddd54c58bb330738be3933",
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

- [x] Q1. Fix in FEAT-886 or a new feature? — *Resolved (/sdd-fix plan)*: new feature. The plan listed FEAT-886 as
  `open` from a stale local index, but on `origin/dev` FEAT-886 is complete (`completed_at` 2026-11-13) and
  merged (PR #2121).
- [x] Q2. Run only the guardrails that can TRANSFORM or BLOCK on the wrapper? — *Resolved*: no. No capability flag
  marks a guardrail FLAG-only, and the TRANSFORM path already runs the whole pipeline on the wrapper.

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; spec authored by /sdd-fix from a ledger issue)

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## 10. Documentation

- **Policy**: `none` — guardrail-propagation fix inside one private method, documented by its docstrings. No wiki
  page describes `_propagate_output_verdict`.
- **Pages**: none.
- **API modules**: none.

---

## Worktree Strategy

One feature worktree `feat-FEAT-894-bots-abstract-tech-debt` off `origin/dev`.

- Module graph: one module, no edges.
- Shared files: none.
- Exclusive resources: none.
- Cross-feature: FEAT-892 (agent-memory-mixin, tasks pending) cites `abstract.py` persistence lines (`:2796`,
  `:2844`), not the OUTPUT pipeline.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-14 | Jesus Lara | Created by /sdd-fix from `issue:a20713dc67a6` (fixgroup:fdeb764ab324) |
