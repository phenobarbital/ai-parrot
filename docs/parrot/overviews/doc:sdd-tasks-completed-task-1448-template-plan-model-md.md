---
type: Wiki Overview
title: 'TASK-1448: Implement TemplatePlan and ParamSpec models'
id: doc:sdd-tasks-completed-task-1448-template-plan-model-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: typed parameters.
relates_to:
- concept: mod:parrot_tools.scraping.plan
  rel: mentions
- concept: mod:parrot_tools.scraping.template_plan
  rel: mentions
---

# TASK-1448: Implement TemplatePlan and ParamSpec models

**Feature**: FEAT-222 — ScrapingFlow: Composable Long-Horizon Scraping
**Spec**: `sdd/specs/scrapingflow-composable-scraping.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`TemplatePlan` is a parameterized plan template that produces concrete `ScrapingPlan`s via
`bind(**kwargs)`. This is the first layer of the ScrapingFlow system: reusable plans with
typed parameters.

Implements spec §Module 1 (ParamSpec & TemplatePlan).

---

## Scope

- Create `ParamSpec` Pydantic model: name, type (string|int|date|enum|url), required, default, choices, description
- Create `TemplatePlan` Pydantic model: name, objective_template, url_template, params, steps_template, selectors, tags, browser_config, version, source, created_at, fingerprint
- Implement `bind(**kwargs)`:
  - Validate kwargs against ParamSpec list (missing required, type mismatches, enum violations)
  - Render `{{param}}` placeholders in url_template, objective_template, and all string values in steps_template (recursively walk dicts/lists)
  - Use `re.sub(r'\{\{(\w+)\}\}', replacer, text)` — NOT str.format()
  - Produce a `ScrapingPlan` with fingerprint = `_compute_fingerprint(template_name + sorted_param_hash)`
- Write comprehensive unit tests

**NOT in scope**: Registry storage for templates (deferred), flow models (TASK-1449)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/scraping/template_plan.py` | CREATE | ParamSpec, TemplatePlan models |
| `packages/ai-parrot-tools/tests/scraping/test_template_plan.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_tools.scraping.plan import ScrapingPlan, _compute_fingerprint  # plan.py:59, 31
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/scraping/plan.py
class ScrapingPlan(BaseModel):  # line 59
    name: Optional[str] = None
    version: str = "1.0"
    tags: List[str]
    url: str
    domain: str = ""
    objective: str
    steps: List[Dict[str, Any]]
    selectors: Optional[List[Dict[str, Any]]] = None
    browser_config: Optional[Dict[str, Any]] = None
    source: str = "llm"
    fingerprint: str = ""  # auto-computed from URL in model_post_init

def _compute_fingerprint(normalized_url: str) -> str: ...  # line 31 — 16-char SHA-256

# Pattern to follow:
# packages/ai-parrot-tools/src/parrot_tools/scraping/extraction_models.py
class ExtractionPlan(BaseModel):  # line 69
    def to_scraping_plan(self) -> ScrapingPlan: ...  # line 127 — translation pattern
```

### Does NOT Exist
- ~~`ScrapingPlan.bind()`~~ — does NOT exist; bind() lives on TemplatePlan
- ~~`ScrapingPlan.params`~~ — does NOT exist; params are on TemplatePlan
- ~~`parrot_tools.scraping.template_plan`~~ — this is what you're creating

---

## Implementation Notes

### Key Constraints
- `{{param}}` rendering uses regex, not str.format() — avoids KeyError on CSS/JSON braces
- Single braces `{index}` must pass through unchanged (Loop's convention is different)
- Fingerprint override: after constructing ScrapingPlan, override its auto-computed fingerprint
  with `plan.fingerprint = _compute_fingerprint(self.name + param_hash_str)`
- Type validation in bind(): "int" checks isinstance(int), "date" checks ISO string parseable,
  "enum" checks value in choices list, "url" checks starts with http(s)

---

## Acceptance Criteria

- [ ] `ParamSpec` validates type/choices/required/default fields
- [ ] `bind()` renders `{{param}}` in url_template, objective_template, steps_template recursively
- [ ] `bind()` raises `ValueError` for missing required params
- [ ] `bind()` raises `ValueError` for type mismatches
- [ ] `bind()` fills defaults for optional params
- [ ] Two binds with different params produce different fingerprints
- [ ] Same params always produce the same fingerprint
- [ ] `{index}` single-brace tokens pass through unchanged
- [ ] All tests pass: `pytest packages/ai-parrot-tools/tests/scraping/test_template_plan.py -v`

---

## Test Specification

```python
import pytest
from parrot_tools.scraping.template_plan import TemplatePlan, ParamSpec


@pytest.fixture
def flight_template():
    return TemplatePlan(
        name="search-flights",
        objective_template="Search flights from {{origin}} to {{destination}}",
        url_template="https://example.com/flights?from={{origin}}&to={{destination}}",
        params=[
            ParamSpec(name="origin", type="string", required=True),
            ParamSpec(name="destination", type="string", required=True),
        ],
        steps_template=[
            {"action": "navigate", "url": "{{url}}"},
            {"action": "wait", "condition": ".results", "condition_type": "selector"},
        ],
    )


class TestTemplatePlanBind:
    def test_bind_basic(self, flight_template):
        plan = flight_template.bind(origin="SEA", destination="LAX")
        assert plan.url == "https://example.com/flights?from=SEA&to=LAX"
        assert "SEA" in plan.objective
        assert isinstance(plan, ScrapingPlan)

    def test_bind_missing_required_raises(self, flight_template):
        with pytest.raises(ValueError, match="origin"):
            flight_template.bind(destination="LAX")

    def test_bind_unique_fingerprints(self, flight_template):
        p1 = flight_template.bind(origin="SEA", destination="LAX")
        p2 = flight_template.bind(origin="SFO", destination="JFK")
        assert p1.fingerprint != p2.fingerprint

    def test_single_braces_pass_through(self):
        tmpl = TemplatePlan(
            name="test", objective_template="test", url_template="http://example.com",
            params=[], steps_template=[{"action": "loop", "selector": ".item-{i}"}],
        )
        plan = tmpl.bind()
        assert plan.steps[0]["selector"] == ".item-{i}"
```

---

## Completion Note

Created `template_plan.py` with `ParamSpec` and `TemplatePlan` Pydantic v2
models.

- `ParamSpec` has a `model_validator` rejecting `type="enum"` without `choices`.
- `TemplatePlan.bind(**kwargs)` validates params (missing-required, per-type
  checks for string/int/date/enum/url, bool explicitly rejected for int),
  fills defaults for optional params, then renders `{{param}}` placeholders via
  `re.sub(r'\{\{(\w+)\}\}', ...)` (NOT `str.format()`) recursively across
  url/objective/steps/selectors. Single-brace `{i}` tokens and unknown
  `{{placeholders}}` pass through unchanged.
- The rendered URL is exposed as an implicit `{{url}}` placeholder for steps
  (matches the spec fixture `{"action":"navigate","url":"{{url}}"}`).
- The produced `ScrapingPlan` fingerprint is set in the constructor to
  `_compute_fingerprint(name + sorted(params))` (declared params only, url
  excluded) so distinct param sets get distinct fingerprints and identical
  sets are stable. `TemplatePlan.fingerprint` is a separate name-based
  computed_field.

19 unit tests pass; ruff clean.
