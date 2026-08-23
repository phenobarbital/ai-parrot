# TASK-2388: BrowserAction discriminated union + ScrapingPlan.validate_steps()

**Feature**: FEAT-453 — Business Browser Automation
**Spec**: `sdd/specs/web-automation-infra.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** (Goal G2).

`ScrapingPlan.steps` is `List[Dict[str, Any]]` (plan.py:78) — the DSL is typed
in flight but **untyped at rest**. A malformed plan is only discovered when
execution reaches the bad step, which for a financial workflow means failing
half-way through an invoice rather than before the browser opens.

Implements spec **Module 3**.

---

## Scope

- Add a discriminated union over the 27 `BrowserAction` subclasses in
  `models.py`, keyed on the `action` literal each subclass already declares
  (e.g. `Navigate.action: Literal['navigate']`).
- Add `ScrapingPlan.validate_steps(*, strict: bool = True) -> list[BrowserAction]`
  which parses `self.steps` into typed actions and raises on the first invalid
  step, with the step index and the offending payload in the message.
- Keep it **opt-in**: `ScrapingPlan` construction must not start validating
  automatically, so no existing caller breaks.
- Write unit tests for unknown action types and missing required fields.

**NOT in scope**: calling `validate_steps()` from the toolkit (TASK-2390);
changing any action model's fields.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/models.py` | MODIFY | Add the discriminated union |
| `packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py` | MODIFY | Add validate_steps() |
| `packages/ai-parrot-tools/tests/scraping/test_plan_validation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from the actual codebase, re-checked on `dev`
> after the FEAT-449/450/452 merges. Use these exact imports and signatures.
> **DO NOT** invent, guess, or assume anything not listed here. If you need
> something absent, VERIFY it exists with `grep`/`read` and update this section
> FIRST.

### Verified Imports

```python
from parrot_tools.scraping.plan import ScrapingPlan     # verified: scraping/plan.py:59
from parrot_tools.scraping.models import BrowserAction  # verified: scraping/models.py:14
```

### Existing Signatures to Use

```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py
class ScrapingPlan(BaseModel):                      # line 59
    name: Optional[str] = None; version: str = "1.0"; tags: List[str] = []
    url: str; domain: str = ""; objective: str
    steps: List[Dict[str, Any]]                     # line 78  <- THE TARGET
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None
    fingerprint: str = ""
    def model_post_init(self, __context) -> None: ...   # line 97 (auto-populates domain/name/fingerprint)

# packages/ai-parrot-tools/src/parrot_tools/scraping/models.py — the 27 subclasses
class BrowserAction(BaseModel, ABC):                # line 14
    def get_action_type(self) -> str: ...           # line 24
# each subclass declares `action: Literal[...]`, e.g.:
#   Navigate:37  Click:45  Fill:66  Hover:76  Type:87  Extract:146  ExtractJsonLd:192
#   Submit:230  Select:242  Evaluate:293  PressKey:316  Refresh:326  Back:334
#   Scroll:342  GetCookies:388  SetCookies:397  Wait:407  Authenticate:478
#   AwaitHuman:514  AwaitKeyPress:534  AwaitBrowserEvent:549  GetText:570
#   Screenshot:579  GetHTML:598  WaitForDownload:612  UploadFile:633
#   Conditional:651  Loop:679
```

### Does NOT Exist

- ~~`ScrapingPlan.typed_steps`~~ / ~~`ScrapingPlan.parsed_steps`~~ — no such property today.
- ~~a pre-existing `BrowserActionUnion` / `AnyBrowserAction`~~ — **this task creates it**.
- ~~changing `steps` to `List[BrowserAction]`~~ — explicitly NOT the approach. Persisted plans are dicts on disk; keep the field type and validate on demand, or every stored plan breaks.

---

## Implementation Notes

### Key Constraints
- `BrowserAction` is `ABC` — the union must be over the concrete subclasses.
- Error messages must name the **step index** and the action type. A validation
  error that just says "invalid step" is nearly useless against a 20-step plan.
- Opt-in only. `strict=False` should collect and return all errors rather than
  raising on the first, for a lint-style report over a plans directory.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/scraping/advanced_actions.py` — the FEAT-222 extraction pattern
- `packages/ai-parrot/src/parrot/tools/obsidian.py` — FEAT-391 lazy-lifecycle toolkit
- `packages/ai-parrot/src/parrot/tools/execution_plan/toolkit.py` — FEAT-207 shared-state toolkit + run_id polling

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] `validate_steps()` returns typed `BrowserAction` instances for a valid plan
- [ ] An unknown `action` value raises, naming the step index
- [ ] `UploadFile` without the required `file_path` raises, naming the field
- [ ] Constructing a `ScrapingPlan` still does NOT validate automatically
- [ ] `strict=False` returns all errors instead of raising on the first
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_plan_validation.py -v`
- [ ] No linting errors: `ruff check` on every changed file

---

## Test Specification

> Minimal scaffold. The agent must make these pass and add more as needed.

```python
import pytest
from parrot_tools.scraping.plan import ScrapingPlan


class TestValidateSteps:
    def test_valid_plan_returns_typed_actions(self):
        plan = ScrapingPlan(url="http://x/", objective="t",
                            steps=[{"action": "navigate", "url": "http://x/"}])
        actions = plan.validate_steps()
        assert actions[0].get_action_type() == "navigate"

    def test_unknown_action_raises_with_index(self):
        plan = ScrapingPlan(url="http://x/", objective="t",
                            steps=[{"action": "navigate", "url": "http://x/"},
                                   {"action": "teleport"}])
        with pytest.raises(ValueError, match=r"step 1"):
            plan.validate_steps()

    def test_missing_required_field_raises(self):
        plan = ScrapingPlan(url="http://x/", objective="t",
                            steps=[{"action": "upload_file", "selector": "#f"}])
        with pytest.raises(ValueError, match="file_path"):
            plan.validate_steps()

    def test_construction_does_not_validate(self):
        ScrapingPlan(url="http://x/", objective="t", steps=[{"action": "bogus"}])  # must not raise
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-automation-infra.spec.md` — especially §6 Codebase Contract and §7 Decisions D1-D4.
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** before writing ANY code:
   - Confirm every import still resolves (`grep`/`read` the source).
   - Confirm every listed signature still matches.
   - If anything changed, update this contract FIRST, then implement.
   - **NEVER** reference an import, attribute, or method not in the contract
     without verifying it exists.
4. **Update status** in `sdd/tasks/index/web-automation-infra.json` → `"in-progress"`.
5. **Implement** per scope, contract, and notes — nothing more.
6. **Verify** every acceptance criterion.
7. **Move this file** to `sdd/tasks/completed/TASK-2388-browseraction-union-and-plan-validation.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
