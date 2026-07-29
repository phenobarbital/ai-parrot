---
type: Wiki Overview
title: 'TASK-951: Document the JiraSpecialist prompt-layer stack'
id: doc:sdd-tasks-completed-task-951-jira-prompt-layers-docs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 7** of FEAT-138. Adds a developer-facing
relates_to:
- concept: mod:parrot.bots.prompts
  rel: mentions
---

# TASK-951: Document the JiraSpecialist prompt-layer stack

**Feature**: FEAT-138 — jira_analyst_systemprompt_hardening
**Spec**: `sdd/specs/jira_analyst_systemprompt_hardening.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-947
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of FEAT-138. Adds a developer-facing
documentation page describing the new layered system prompt for
`JiraSpecialist`, what `JIRA_GROUNDING_LAYER` enforces, and how
subclasses (`Jirachi`, future variants) can extend or replace layers.

Without this page, future contributors will revert to the legacy
monolithic-string pattern instead of composing layers.

---

## Scope

Create `docs/jira-specialist-prompt-layers.md` covering:

1. **Why layers** — short rationale referring to the FEAT-138 spec
   and the failure modes that drove the change.
2. **The layer stack** — bullet list of every layer
   `JiraSpecialist` installs by default and its role.
3. **Sentinel phrases** — document the verbatim strings (`No results
   found for <KEY>`, `Jira lookup failed: <message>`) and that they
   are assertion targets in the regression tests.
4. **Extending or overriding** — how a subclass can add, remove, or
   replace a layer:
   ```python
   class MyJira(JiraSpecialist):
       def __init__(self, **kwargs):
           builder = JiraSpecialist._build_jira_prompt_builder()
           builder.add(my_extra_layer)
           kwargs.setdefault("prompt_builder", builder)
           super().__init__(**kwargs)
   ```
5. **Anti-patterns** — explicit "do NOT" list:
   - Do not set `system_prompt_template` (the attribute no longer exists).
   - Do not import `JIRA_SPECIALIST_PROMPT` (deleted in TASK-947).
   - Do not localise the sentinel phrases — they are assertion targets.
   - Do not add anti-hallucination rules outside `JIRA_GROUNDING_LAYER`.
6. **Cross-references**:
   - Spec: `sdd/specs/jira_analyst_systemprompt_hardening.spec.md`
   - Layer source: `parrot/bots/prompts/domain_layers.py`
   - Builder source: `parrot/bots/prompts/builder.py`
   - Regression tests: `tests/test_jira_specialist_grounding.py`

**NOT in scope**: rewriting the higher-level prompt-layer system
documentation (already exists per
`sdd/specs/composable-prompt-layer.spec.md`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/jira-specialist-prompt-layers.md` | CREATE | The new doc page |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/bots/jira_specialist.py (post-TASK-947)
class JiraSpecialist(Agent):
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW
    @staticmethod
    def _build_jira_prompt_builder() -> PromptBuilder: ...

# packages/ai-parrot/src/parrot/bots/prompts/__init__.py (post-TASK-946)
from parrot.bots.prompts import (
    PromptBuilder, get_domain_layer,
    JIRA_WORKFLOW_LAYER, JIRA_GROUNDING_LAYER,
)
```

### Does NOT Exist

- ~~`docs/sdd/jira-specialist.md`~~ — the doc lives at `docs/`, not
  `docs/sdd/`. Verify path before writing.
- ~~`PromptBuilder.jira()`~~ — no factory. Reference
  `_build_jira_prompt_builder()` instead.

---

## Implementation Notes

### Pattern to Follow

Match the tone and depth of an existing developer doc such as
`docs/contextual-embedding.md` or `docs/parent-child-retrieval.md`
(both already on `dev`). Headings, code fences, and cross-link style
should match.

### Key Constraints

- No CLI commands the reader cannot run (verify any `pytest`
  invocations).
- Keep the doc under ~250 lines.
- All code samples must compile / import — verify by running each
  snippet's imports in a Python REPL before committing.

---

## Acceptance Criteria

- [ ] `docs/jira-specialist-prompt-layers.md` exists, ~150-250 lines.
- [ ] Document references the spec by path and Feature ID (FEAT-138).
- [ ] Both sentinel phrases appear verbatim.
- [ ] Anti-pattern list explicitly mentions the removed
      `system_prompt_template` and `JIRA_SPECIALIST_PROMPT`.
- [ ] At least one code sample showing how a subclass adds an extra
      layer compiles when its imports are exercised.
- [ ] `markdownlint docs/jira-specialist-prompt-layers.md` (if the
      project runs it) passes; otherwise prose is well-structured.

---

## Test Specification

No automated tests; the deliverable is documentation. Verification is
manual and via the ACs above.

---

## Agent Instructions

1. Read TASK-947's resulting `jira_specialist.py` to copy the
   `_build_jira_prompt_builder` signature accurately.
2. Read one existing `docs/*.md` page on `dev` for tone/structure.
3. Update index → `"in-progress"`.
4. Write the doc.
5. Verify code samples by running their imports.
6. Move file to `completed/`; update index → `"done"`.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-05-01
**Notes**: Created `docs/jira-specialist-prompt-layers.md` (174 lines). Covers all 6
spec-listed sections: rationale, layer stack table, sentinel phrases, subclass extension
patterns (add/replace/custom builder), anti-patterns, and cross-references. All code
samples verified against the actual PromptBuilder API (add(), remove(), default()).
**Deviations from spec**: Imports not verified via a live REPL due to the broken Cython
chain in the test environment (navigator.utils.file ImportError). Verified instead via
grep of builder.py method signatures and __init__.py exports.
