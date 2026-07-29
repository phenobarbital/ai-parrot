# TASK-1969: Free-text feature intake — FeatureDraft + FeatureIntake

**Feature**: FEAT-388 — `parrot devloop` CLI Homologation
**Spec**: `sdd/specs/devloop-cli-homologation.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 2 (goals G4, G5). Users type a free-text feature request; a
configurable light LLM fills a structured `FeatureDraft`, which is rendered
as a brainstorm markdown in `sdd/proposals/` and wrapped in a
`FeatureBrief(document_kind="brainstorm")` — the document-driven contract
FEAT-378's PlannerNode already consumes.

---

## Scope

- Create `parrot/cli/devloop/intake.py` with:
  - `FeatureDraft` (Pydantic): `title`, `slug` (kebab-case),
    `problem_statement`, `requirements: list[str]`,
    `acceptance_criteria: list[str]`, `affected_areas: list[str] = []`,
    `out_of_scope: list[str] = []`, `open_questions: list[str] = []`.
  - `FeatureIntake` with `async generate(text) -> FeatureDraft`,
    `async regenerate(text, guidance) -> FeatureDraft`,
    `write_document(draft) -> Path`,
    `build_brief(draft, document_path, *, dev_agents=None,
    judge_panel=None) -> FeatureBrief`.
- Config key `DEV_LOOP_INTAKE_LLM` (default `"anthropic:claude-haiku-4-5"`),
  resolved through `LLMFactory.create()`; structured output via
  `client.invoke(prompt, output_type=FeatureDraft)`.
- One retry on structured-output validation failure, appending the
  validation error to the prompt.
- Document rendering with FEAT-145 frontmatter; collision-safe filenames
  (`-2`, `-3`, … suffix — never overwrite).
- Unit tests (LLM client mocked).

**NOT in scope**: any console/wizard wiring (TASK-1970); the catalog;
preflight checks for the intake key (TASK-1971).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/devloop/intake.py` | CREATE | FeatureDraft + FeatureIntake |
| `packages/ai-parrot/tests/cli/devloop/test_intake.py` | CREATE | Unit tests, mocked client |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-07-28 on `dev` @ `623f0a6`.

### Verified Imports

```python
from parrot.clients.factory import LLMFactory            # factory.py:128
from parrot.models.responses import InvokeResult          # responses.py:1337
from parrot.flows.dev_loop.models import (
    FeatureBrief,      # models.py:1068
    DevAgentSpec,      # models.py:388
    JudgePanelConfig,  # models.py:1209
)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/clients/factory.py:160
@staticmethod
def create(llm: str, model_args: Optional[Dict[str, Any]] = None,
           tool_manager: Optional[Any] = None, **kwargs) -> AbstractClient:
# llm format: "provider:model" or "provider"

# packages/ai-parrot/src/parrot/clients/claude.py:1810 (all clients)
async def invoke(self, prompt: str, *, output_type: Optional[type] = None,
                 structured_output: Optional[StructuredOutputConfig] = None,
                 model: Optional[str] = None, system_prompt: Optional[str] = None,
                 max_tokens: int = 4096, temperature: float = 0.0,
                 use_tools: bool = False, tools: Optional[list] = None,
                 ) -> InvokeResult:
# InvokeResult.output holds the parsed FeatureDraft instance.
# model=None ⇒ per-client _lightweight_model default (FEAT-069).

# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:1068
class FeatureBrief(BaseModel):
    kind: Literal["feature"] = "feature"
    document_path: str            # must exist + be readable at validation
    document_kind: Literal["brainstorm", "proposal", "spec"]
    jira_issue_key: Optional[str] = None
    dev_agents: Optional[List[DevAgentSpec]] = None
    judge_panel: Optional[JudgePanelConfig] = None
```

Config access pattern (see `bootstrap.py:55-70`):
```python
from parrot import conf
value = conf.config.get("DEV_LOOP_INTAKE_LLM", fallback="anthropic:claude-haiku-4-5")
```

### Does NOT Exist

- ~~`DEV_LOOP_INTAKE_LLM`~~ — this task introduces the key (zero hits today).
- ~~`FeatureDraft` / `FeatureIntake`~~ — this task creates them; do NOT add
  them to `parrot/flows/dev_loop/models.py` (CLI-side only, spec §2).
- ~~`AbstractClient.completion()` structured shortcut~~ — use `invoke()`.
- FeatureBrief validates `document_path` readability — write the document
  BEFORE constructing the brief.

---

## Implementation Notes

### Pattern to Follow
- Deferred heavy imports inside method bodies (`# noqa: PLC0415`) like every
  method in `parrot/cli/devloop/console.py` — module import must stay light.
- Generated document skeleton (frontmatter matches
  `sdd/proposals/*.brainstorm.md` convention):

```markdown
---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: <title>

**Date**: <today>
**Author**: <$USER> (via parrot devloop intake)
**Status**: generated

## Problem Statement
...

## Constraints & Requirements
...

## Acceptance Criteria
...

## Out of Scope / Open Questions
...
```

### Key Constraints
- async throughout; Google docstrings; strict typing; `self.logger`.
- Slug sanitation: lowercase kebab-case, strip anything outside
  `[a-z0-9-]`; fall back to a slugified title if the LLM's slug is empty.
- Retry exactly once on `ValidationError` from `invoke` parsing.

---

## Acceptance Criteria

- [ ] `pytest packages/ai-parrot/tests/cli/devloop/test_intake.py -v` passes.
- [ ] With `DEV_LOOP_INTAKE_LLM` unset, the factory receives
      `anthropic:claude-haiku-4-5`; setting it switches the string (G4).
- [ ] Document lands in `sdd/proposals/<slug>.brainstorm.md` with FEAT-145
      frontmatter; re-run creates `<slug>-2.brainstorm.md` (G4).
- [ ] `build_brief` returns a valid `FeatureBrief` with
      `document_kind="brainstorm"` and passthrough pool/judges.
- [ ] `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/cli/devloop/test_intake.py
class FakeClient:
    """invoke() returns canned InvokeResult(output=FeatureDraft(...));
    a failing variant raises ValidationError once, then succeeds."""

async def test_generate_returns_draft(...): ...
async def test_generate_retries_once_on_validation(...): ...
def test_write_document_frontmatter(tmp_path): ...
def test_write_document_collision_suffix(tmp_path): ...
def test_build_brief_assembly(tmp_path): ...
def test_default_llm_key(monkeypatch): ...
```

---

## Agent Instructions

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — none
3. **Verify the Codebase Contract** before writing any code
4. **Update status** in `sdd/tasks/index/devloop-cli-homologation.json`
5. **Implement**, **verify**, **move this file** to `sdd/tasks/completed/`,
   **update index**, **fill the Completion Note**

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-07-28
**Notes**: Implemented `FeatureDraft` + `FeatureIntake` in
`parrot/cli/devloop/intake.py` exactly per the public interface in spec
§2. Heavy imports (`parrot.conf`, `parrot.clients.factory`,
`parrot.flows.dev_loop.models`) are deferred into method bodies, with a
`TYPE_CHECKING`-only import for the `DevAgentSpec`/`FeatureBrief`/
`JudgePanelConfig` type hints so the module stays light at import time
(module-level import of `parrot.flows.dev_loop.models` would otherwise
transitively run `flows/dev_loop/__init__.py`'s heavy eager imports).
Verified the real `AnthropicClient.invoke()` swallows a failed
structured-output parse into a raw-string `.output` rather than raising
— `_invoke_draft`/`_retry_after_failure` therefore treat BOTH a raised
`pydantic.ValidationError` from `invoke()` AND a non-`FeatureDraft`
`.output` as a validation failure eligible for the one allowed retry,
covering both the mocked test's raise-then-succeed pattern and the real
client's swallow-into-string behavior. Slug sanitation is a small
self-contained regex helper (no new dependency) per the task's
constraint. `pytest packages/ai-parrot/tests/cli/devloop/test_intake.py
-v` → 11/11 passed; `pytest packages/ai-parrot/tests/cli/ -q` → 110
passed (no regressions). `ruff check --fix` applied to both new files
(modern `list`/`X | None` style — no verbatim-move constraint here,
unlike TASK-1968's catalog.py); the one remaining `DTZ011` (`date.
today()`) was left as-is, matching the unsuppressed convention already
used throughout `bots/jira_specialist.py`.

**Deviations from spec**: none
