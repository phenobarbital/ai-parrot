---
type: Wiki Overview
title: 'TASK-1319: Add `JSBundle` model and `InfographicTemplate.js_bundles` field'
id: doc:sdd-tasks-completed-task-1319-jsbundle-and-template-js-bundles-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module 7 from the spec. The optional LLM enhance pipeline (Module 2 /
relates_to:
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.infographic_templates
  rel: mentions
---

# TASK-1319: Add `JSBundle` model and `InfographicTemplate.js_bundles` field

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 7)
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Parallel**: true
**Assigned-to**: unassigned

---

## Context

Module 7 from the spec. The optional LLM enhance pipeline (Module 2 /
TASK-1325) needs a declarative, per-template whitelist of JavaScript
bundles that the LLM is allowed to reference. The HTML-serving CSP
(Module 5 / TASK-1322) consumes the same list to build the
`script-src` allowlist. Templates that don't ship JS leave `js_bundles`
unset — no behavioral change for the seven built-in templates.

This task introduces the `JSBundle` model and the new optional field on
`InfographicTemplate`. No template content is modified.

---

## Scope

- Add `JSBundle` Pydantic v2 model in `parrot/models/infographic.py`
  (or new sibling `parrot/models/infographic_assets.py` if you prefer
  module boundaries — keep import path stable and document it).
- Add `js_bundles: Optional[List[JSBundle]] = None` to
  `InfographicTemplate` (`parrot/models/infographic_templates.py:47`).
- Implement Pydantic `model_validator(mode='after')` on `JSBundle` enforcing
  cross-field rules:
  - `scope == "cdn"` ⇒ `url` AND `sri_hash` required, `inline` must be `None`.
  - `scope == "inline"` ⇒ `inline` required, `url` and `sri_hash` must be
    `None`.
- Add unit tests for both the model validators and the template round-trip.

**NOT in scope**:
- Populating `js_bundles` on any of the seven built-in templates (they
  remain `None`).
- Any CSP / SRI enforcement logic — that lives in TASK-1322 and TASK-1325.
- Any new dependency — the `sha384-...` value is just a string field.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/models/infographic.py` | MODIFY | Add `JSBundle` BaseModel + `model_validator`. |
| `packages/ai-parrot/src/parrot/models/infographic_templates.py` | MODIFY | Add `js_bundles: Optional[List[JSBundle]] = None` field; import `JSBundle`. |
| `packages/ai-parrot/tests/unit/models/test_jsbundle.py` | CREATE | Unit tests for `JSBundle` validators. |
| `packages/ai-parrot/tests/unit/models/test_template_js_bundles.py` | CREATE | Round-trip + integration with `InfographicTemplate`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from pydantic import BaseModel, Field, model_validator
# stdlib-equivalent for typing: from typing import List, Literal, Optional

from parrot.models.infographic_templates import InfographicTemplate, BlockSpec
# verified: packages/ai-parrot/src/parrot/models/infographic_templates.py:47, :21

# After this task:
from parrot.models.infographic import JSBundle
# verified location: packages/ai-parrot/src/parrot/models/infographic.py
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/models/infographic_templates.py
class InfographicTemplate(BaseModel):                                 # line 47
    name: str
    description: str
    block_specs: List[BlockSpec]                                      # line 51
    default_theme: Optional[str] = None
    def to_prompt_instruction(self) -> str: ...                       # line 60
```

```python
# packages/ai-parrot/src/parrot/models/infographic.py
# Module already contains: BlockType (line 45), ChartType (line 64),
# InfographicResponse (line 657), ThemeConfig + theme_registry (line 863).
# Add JSBundle near the end, before theme_registry, or in a clearly marked
# "Asset declarations" block.
```

### Does NOT Exist
- ~~`JSBundle`~~ — created by this task.
- ~~`InfographicTemplate.js_bundles`~~ — created by this task.
- ~~`JSBundle.integrity`~~ — the field is `sri_hash`, not `integrity`. Stick
  with `sri_hash` for parity with the spec.

---

## Implementation Notes

### Pattern to Follow

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator


class JSBundle(BaseModel):
    """Declarative JavaScript bundle attached to an InfographicTemplate."""

    name: str = Field(..., description="Stable identifier (e.g. 'echarts').")
    url: Optional[str] = Field(default=None,
                               description="Required when scope='cdn'.")
    inline: Optional[str] = Field(default=None,
                                  description="Required when scope='inline'.")
    sri_hash: Optional[str] = Field(default=None,
                                    description="'sha384-...' — required for cdn.")
    scope: Literal["inline", "cdn"] = "inline"

    @model_validator(mode="after")
    def _validate_scope_consistency(self) -> "JSBundle":
        if self.scope == "cdn":
            if not self.url or not self.sri_hash:
                raise ValueError(
                    "scope='cdn' requires both 'url' and 'sri_hash'")
            if self.inline is not None:
                raise ValueError("scope='cdn' must not set 'inline'")
        else:  # inline
            if self.inline is None:
                raise ValueError("scope='inline' requires 'inline' source")
            if self.url is not None or self.sri_hash is not None:
                raise ValueError(
                    "scope='inline' must not set 'url' or 'sri_hash'")
        return self
```

```python
# In parrot/models/infographic_templates.py — add the field:
from parrot.models.infographic import JSBundle  # circular-safe via lazy import if needed

class InfographicTemplate(BaseModel):
    name: str
    description: str
    block_specs: List[BlockSpec]
    default_theme: Optional[str] = None
    js_bundles: Optional[List[JSBundle]] = None    # NEW (FEAT-197)

    def to_prompt_instruction(self) -> str: ...  # unchanged
```

### Key Constraints
- The seven existing built-in templates MUST continue to work — their
  `js_bundles` will simply be `None`.
- If the `parrot.models.infographic` ↔ `parrot.models.infographic_templates`
  import direction creates a circular import, prefer adding `JSBundle` in
  the *templates* module instead, or use a local import inside the
  template class. Document whichever you choose in the file's docstring.

---

## Acceptance Criteria

- [ ] `JSBundle(name='x', scope='inline', inline='/*js*/')` validates.
- [ ] `JSBundle(name='x', scope='cdn', url='https://cdn/x.js', sri_hash='sha384-AAA')` validates.
- [ ] `JSBundle(name='x', scope='cdn', url=None, sri_hash='sha384-AAA')` raises `ValueError`.
- [ ] `JSBundle(name='x', scope='cdn', url='https://cdn/x.js', sri_hash=None)` raises `ValueError`.
- [ ] `JSBundle(name='x', scope='inline', inline=None)` raises `ValueError`.
- [ ] `InfographicTemplate(...).model_dump()['js_bundles']` round-trips when set; is `None` when unset.
- [ ] All seven built-in templates still validate (`infographic_registry.list_templates()` length unchanged).
- [ ] `pytest packages/ai-parrot/tests/unit/models/test_jsbundle.py packages/ai-parrot/tests/unit/models/test_template_js_bundles.py -v` passes.
- [ ] `ruff check` and `mypy --strict` clean on both files.

---

## Test Specification

```python
# packages/ai-parrot/tests/unit/models/test_jsbundle.py
import pytest
from parrot.models.infographic import JSBundle


class TestJSBundleValidation:
    def test_inline_ok(self):
        b = JSBundle(name="x", scope="inline", inline="/*js*/")
        assert b.scope == "inline"

    def test_cdn_ok(self):
        b = JSBundle(name="echarts", scope="cdn",
                     url="https://cdn/x.js", sri_hash="sha384-AAAA")
        assert b.scope == "cdn"

    @pytest.mark.parametrize("kwargs", [
        dict(scope="cdn", url=None, sri_hash="sha384-AAAA"),
        dict(scope="cdn", url="https://cdn/x.js", sri_hash=None),
        dict(scope="cdn", url="https://cdn/x.js", sri_hash="sha384-AAA",
             inline="oops"),
        dict(scope="inline", inline=None),
        dict(scope="inline", inline="x", url="https://cdn/x.js"),
    ])
    def test_invalid_combinations_rejected(self, kwargs):
        with pytest.raises(ValueError):
            JSBundle(name="x", **kwargs)
```

```python
# packages/ai-parrot/tests/unit/models/test_template_js_bundles.py
import json
from parrot.models.infographic import JSBundle
from parrot.models.infographic_templates import (
    BlockSpec, InfographicTemplate, infographic_registry,
)
from parrot.models.infographic import BlockType


def test_template_js_bundles_default_none():
    t = InfographicTemplate(name="t", description="d",
                            block_specs=[BlockSpec(block_type=BlockType.TITLE)])
    assert t.js_bundles is None


def test_template_js_bundles_round_trip():
    t = InfographicTemplate(
        name="t2", description="d",
        block_specs=[BlockSpec(block_type=BlockType.CHART)],
        js_bundles=[JSBundle(name="echarts", scope="cdn",
                             url="https://cdn/echarts.min.js",
                             sri_hash="sha384-AAAA")],
    )
    restored = InfographicTemplate.model_validate(
        json.loads(t.model_dump_json()))
    assert restored.js_bundles is not None
    assert restored.js_bundles[0].name == "echarts"


def test_builtin_templates_still_valid():
    # All seven built-ins must survive the schema change.
    names = infographic_registry.list_templates()
    assert len(names) >= 7
    for n in names:
        tpl = infographic_registry.get(n)
        assert tpl.js_bundles is None  # built-ins ship without bundles
```

---

## Agent Instructions

1. Confirm there's no existing `JSBundle` (`grep -rn "class JSBundle"`).
2. Pick a home for the model (`infographic.py` vs sibling) — prefer the
   existing module unless it triggers a circular import.
3. Add the field on `InfographicTemplate`, then run both test files.
4. Run the broader infographic test suite to confirm no regression:
   `pytest packages/ai-parrot/tests/unit/models/ -v -k infographic`.
5. Move this file to `sdd/tasks/completed/` and update the per-spec index.

---

## Completion Note

*(Agent fills this in when done)*
