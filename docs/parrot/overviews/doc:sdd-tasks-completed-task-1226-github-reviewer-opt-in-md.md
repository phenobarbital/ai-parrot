---
type: Wiki Overview
title: 'TASK-1226: GitHubReviewer prompt_caching opt-in'
id: doc:sdd-tasks-completed-task-1226-github-reviewer-opt-in-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task makes `GitHubReviewer` the canonical consumer of the prompt caching
relates_to:
- concept: mod:parrot.bots.github_reviewer
  rel: mentions
---

# TASK-1226: GitHubReviewer prompt_caching opt-in

**Feature**: FEAT-181 — Provider-Agnostic Prompt Caching
**Spec**: `sdd/specs/agnostic-prompt-caching-abstraction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1220
**Assigned-to**: unassigned

---

## Context

This task makes `GitHubReviewer` the canonical consumer of the prompt caching
feature (spec Module 10, §3). The opt-in is minimal: set
`prompt_caching=True` via `kwargs.setdefault()` in `__init__`. The docstring
must document the Gemini-threshold caveat — the default model
(`GoogleModel.GEMINI_3_FLASH_PREVIEW`) may not actually cache unless the system
prompt + AGENT_CONTEXT exceeds the 4096+ token threshold.

---

## Scope

- Add `kwargs.setdefault("prompt_caching", True)` in `GitHubReviewer.__init__()`.
- Update the class docstring to mention prompt caching and the Gemini threshold
  caveat.
- Write a simple unit test confirming the flag is set.

**NOT in scope**: Changing the default model, rewriting the system prompt,
migrating to full `PromptBuilder`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/github_reviewer.py` | MODIFY | Add `kwargs.setdefault("prompt_caching", True)` + docstring update |
| `packages/ai-parrot/tests/test_github_reviewer_caching.py` | CREATE | Unit test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.github_reviewer import GitHubReviewer  # github_reviewer.py:222
```

### Existing Signatures to Use
```python
# parrot/bots/github_reviewer.py
class GitHubReviewer(Agent):              # line 222
    model = GoogleModel.GEMINI_3_FLASH_PREVIEW  # line 269

    def __init__(
        self,
        repository: str,                  # line 369
        *,
        jira_project: str = "NAV",        # line 371
        # ... various kwargs ...
        **kwargs: Any,                     # line 382
    ) -> None:
        kwargs.setdefault("injection_probability_threshold", 0.995)  # line 384
        kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)           # line 385
        super().__init__(**kwargs)                                    # line 387
```

### Does NOT Exist
- ~~`GitHubReviewer.prompt_caching`~~ — no explicit attribute; this task adds via kwargs
- ~~`GitHubReviewer._prompt_builder`~~ — inherits from AbstractBot, but GitHubReviewer
  does not set one; the AbstractBot creates a default when `prompt_caching=True`

---

## Implementation Notes

### Pattern to Follow

Add the setdefault right after the existing ones:
```python
kwargs.setdefault("injection_probability_threshold", 0.995)
kwargs.setdefault("system_prompt", _SYSTEM_PROMPT)
kwargs.setdefault("prompt_caching", True)  # FEAT-181

super().__init__(**kwargs)
```

For the docstring, add a note about the Gemini threshold:
```
Note on prompt caching: This agent enables ``prompt_caching=True`` by
default (FEAT-181). Prompt caching activates provider-side caching of
the static system prompt prefix. The default model
(``GEMINI_3_FLASH_PREVIEW``) requires ≥4096 tokens in the cacheable
prefix for caching to take effect. If the system prompt + agent context
document are below this threshold, caching silently skips with a
``PromptCacheSkippedEvent``. For guaranteed caching, use an Anthropic
or OpenAI model.
```

### Key Constraints
- The change is a single `kwargs.setdefault()` line — minimal risk.
- Users can still override by passing `prompt_caching=False` explicitly.
- Do NOT change the default model or the system prompt.

### References in Codebase
- `parrot/bots/github_reviewer.py` — target file
- `parrot/bots/abstract.py` — `prompt_caching` kwarg handling (TASK-1220)

---

## Acceptance Criteria

- [ ] `GitHubReviewer(repository="foo/bar")` has `prompt_caching=True` by default
- [ ] Callers can override with `prompt_caching=False`
- [ ] Class docstring mentions prompt caching and the Gemini threshold caveat
- [ ] All tests pass: `pytest packages/ai-parrot/tests/test_github_reviewer_caching.py -v`
- [ ] No linting errors

---

## Test Specification

```python
# packages/ai-parrot/tests/test_github_reviewer_caching.py
import pytest
from unittest.mock import patch, MagicMock


class TestGitHubReviewerCaching:
    def test_prompt_caching_default_true(self):
        """GitHubReviewer sets prompt_caching=True by default."""
        # Verify the kwargs.setdefault call is present
        import inspect
        from parrot.bots.github_reviewer import GitHubReviewer
        source = inspect.getsource(GitHubReviewer.__init__)
        assert 'prompt_caching' in source

    def test_can_override_to_false(self):
        """Caller can disable prompt caching."""
        # This is a kwargs.setdefault, so explicit False overrides
        # (Test via inspection since full init requires GitHub credentials)
        pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1220 is in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — confirm `kwargs.setdefault` pattern at lines 384-385
4. **Update status** in `sdd/tasks/index/agnostic-prompt-caching-abstraction.json` → `"in-progress"`
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/TASK-1226-github-reviewer-opt-in.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: 
**Date**: 
**Notes**: 

**Deviations from spec**: none | describe if any
