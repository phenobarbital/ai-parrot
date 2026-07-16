---
type: Wiki Overview
title: 'TASK-002: `parse_repo_specs` — DEV_LOOP_REPOS → RepoSpec parser'
id: doc:sdd-tasks-completed-task-002-parse-repo-specs-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements **Module 2** of the spec. `conf.DEV_LOOP_REPOS` (`conf.py:870`)
  is a
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.flows.dev_loop
  rel: mentions
- concept: mod:parrot.flows.dev_loop.models
  rel: mentions
---

# TASK-002: `parse_repo_specs` — DEV_LOOP_REPOS → RepoSpec parser

**Feature**: FEAT-253 — Complete FEAT-250 Repo Wiring
**Spec**: `sdd/specs/complete-feat-250-dev-loop-repo-wiring.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec. `conf.DEV_LOOP_REPOS` (`conf.py:870`) is a
raw `list[str]` and nothing converts it into `RepoSpec` objects, so a repo can't
be declared via environment. `conf.py` must not import `dev_loop`, so the parser
lives in the `dev_loop` package and is called by the demo server (TASK-004) and
available to the flow builder.

---

## Scope

- Add `parse_repo_specs(raw: list[str]) -> list[RepoSpec]` in a new module
  `packages/ai-parrot/src/parrot/flows/dev_loop/config.py` and re-export it from
  `parrot/flows/dev_loop/__init__.py`.
- Each entry is one of:
  - a **JSON object string** → `RepoSpec(**json)` (honors `alias`/`branch`/`private`);
  - a **full clone URL** → `RepoSpec(alias=<derived>, url=<entry>)`. Support
    `https://github.com/owner/name(.git)` and `git@github.com:owner/name.git`;
  - an **`owner/name` slug** → `RepoSpec(alias=<name>, url=<entry>)`.
- Alias derivation: the repo's `<name>` component, with a trailing `.git` stripped.
- Skip blank / whitespace-only entries. Invalid JSON falls back to URL/slug handling.
- Add unit tests.

**NOT in scope**: calling the parser from `server.py` (TASK-004); any conf change
(TASK-001); cloning behavior (TASK-003).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/config.py` | CREATE | `parse_repo_specs` helper. |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Re-export `parse_repo_specs`. |
| `packages/ai-parrot/tests/flows/dev_loop/test_parse_repo_specs.py` | CREATE | Unit tests. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop.models import RepoSpec     # models.py:185
from parrot.flows.dev_loop import parse_repo_specs    # NEW (this task) — re-export
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models.py:185
class RepoSpec(BaseModel):
    alias: str                 # short name; also the clone dir name
    url: str                   # https URL or 'owner/name' slug (also accepts git@... url)
    branch: str = "main"
    private: bool = False
```

### Does NOT Exist
- ~~`parse_repo_specs`~~ — being created here. No DEV_LOOP_REPOS parser exists today.
- ~~`RepoSpec.from_str` / `RepoSpec.parse`~~ — no such classmethod; build via the
  normal `RepoSpec(...)` constructor.
- ~~importing `dev_loop` from `conf.py`~~ — forbidden; the parser stays in the
  `dev_loop` package.

---

## Implementation Notes

### Pattern to Follow
```python
import json
from typing import List
from parrot.flows.dev_loop.models import RepoSpec


def _alias_from_url(url: str) -> str:
    # git@github.com:owner/name.git  ->  name
    # https://github.com/owner/name(.git) -> name
    # owner/name -> name
    tail = url.rsplit(":", 1)[-1] if url.startswith("git@") else url
    name = tail.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def parse_repo_specs(raw: list[str]) -> List[RepoSpec]:
    specs: List[RepoSpec] = []
    for entry in raw or []:
        entry = (entry or "").strip()
        if not entry:
            continue
        if entry.startswith("{"):
            try:
                specs.append(RepoSpec(**json.loads(entry)))
                continue
            except (ValueError, TypeError):
                pass  # fall through to url/slug
        specs.append(RepoSpec(alias=_alias_from_url(entry), url=entry))
    return specs
```

### Key Constraints
- Pure, synchronous helper (no I/O). Pydantic v2 model construction.
- Be tolerant: never raise on a blank line; only malformed JSON that is ALSO not
  a usable url/slug would surface a pydantic error (acceptable).

---

## Acceptance Criteria

- [ ] `parse_repo_specs(["phenobarbital/ai-parrot"])` → alias `ai-parrot`, url preserved.
- [ ] `parse_repo_specs(["git@github.com:phenobarbital/ai-parrot.git"])` → alias `ai-parrot`.
- [ ] `parse_repo_specs(["https://github.com/phenobarbital/ai-parrot.git"])` → alias `ai-parrot`.
- [ ] JSON entry round-trips `branch`/`private`/`alias`.
- [ ] Blank/whitespace entries skipped.
- [ ] `from parrot.flows.dev_loop import parse_repo_specs` works.
- [ ] Tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_parse_repo_specs.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/config.py`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_parse_repo_specs.py
import pytest
from parrot.flows.dev_loop import parse_repo_specs
from parrot.flows.dev_loop.models import RepoSpec


def test_parse_repo_specs_slug():
    [s] = parse_repo_specs(["phenobarbital/ai-parrot"])
    assert s.alias == "ai-parrot" and s.url == "phenobarbital/ai-parrot"


def test_parse_repo_specs_ssh_url():
    [s] = parse_repo_specs(["git@github.com:phenobarbital/ai-parrot.git"])
    assert s.alias == "ai-parrot"
    assert s.url == "git@github.com:phenobarbital/ai-parrot.git"


def test_parse_repo_specs_https_url():
    [s] = parse_repo_specs(["https://github.com/phenobarbital/ai-parrot.git"])
    assert s.alias == "ai-parrot"


def test_parse_repo_specs_json():
    [s] = parse_repo_specs(['{"alias":"x","url":"o/n","branch":"dev","private":true}'])
    assert (s.alias, s.branch, s.private) == ("x", "dev", True)


def test_parse_repo_specs_skips_blanks():
    assert parse_repo_specs(["", "  ", "o/n"]) == [RepoSpec(alias="n", url="o/n")]
```

---

## Agent Instructions

1. Read the spec (§2 New Public Interfaces, §3 Module 2).
2. Verify the Codebase Contract before editing.
3. Update index → `in-progress`.
4. Implement, run tests + ruff.
5. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
