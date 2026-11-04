# TASK-5202: Tutorials: first tool and deployment

**Feature**: FEAT-803 — GitHub Pages Informative Site Redesign
**Spec**: `sdd/specs/github-pages-informative-site.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M
**Depends-on**: TASK-5197
**Assigned-to**: unassigned

---

## Context

Beginner tutorials 3–4 (spec G4, M6, AC4). Deployment uses aiohttp + gunicorn only — never FastAPI/uvicorn (codebase conventions). Implements spec §3 Module 6 (Beginner Tutorials).

**Merge gate**: FEAT-801 (all 8 tasks) and its M9 mkdocstrings cut-over have NOT landed on dev yet (verified at `0b8c3a1fa2`: `mkdocs.yml:54` still has `- mkdocstrings:`, `requirements-docs.txt` still lists `mkdocstrings[python]>=1.0.8`, `.github/workflows/docs.yml:38` still has the editable install). This task may be developed now but the feature must not merge until that gate is clear. Never remove mkdocstrings yourself — M9 owns it.

---

## Scope

- Create `docs/tutorials/first-tool.md` — write a @tool function and attach it to an Agent.
- Create `docs/tutorials/deployment.md` — serve an agent as an aiohttp service with production config (spec §8 Q1).
- Write `tests/docs_site/test_tutorials_advanced.py`.

**NOT in scope**: Other tutorials; mkdocs.yml (TASK-5197 already lists these paths).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/tutorials/first-tool.md` | CREATE | write a @tool function and attach it to an Agent |
| `docs/tutorials/deployment.md` | CREATE | serve an agent as an aiohttp service with production config (spec §8 Q1) |
| `tests/docs_site/test_tutorials_advanced.py` | CREATE | structure checks |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (for code shown in tutorials)
```python
from parrot.bots import Chatbot, Agent, BasicAgent   # verified: packages/ai-parrot/src/parrot/bots/__init__.py:12 (Agent, BasicAgent) + lazy Chatbot export (line 20)
from parrot.tools import tool                        # FILL IN: verify — `tool` is defined at packages/ai-parrot/src/parrot/tools/decorators.py:59; confirm it is re-exported by parrot/tools/__init__.py, else use `from parrot.tools.decorators import tool`
```
### Existing Signatures
```python
# packages/ai-parrot/src/parrot/bots/chatbot.py:33   class Chatbot(BaseBot)
# packages/ai-parrot/src/parrot/bots/agent.py:40     class BasicAgent(Chatbot, NotificationMixin)
# packages/ai-parrot/src/parrot/bots/agent.py:1576   class Agent(BasicAgent)
# packages/ai-parrot/src/parrot/bots/abstract.py:1604 async def configure(self, app=None) -> None
# packages/ai-parrot/src/parrot/bots/base.py:1069    async def ask(...)
# packages/ai-parrot/src/parrot/tools/decorators.py:59 def tool(_func=None, *, name=None, description=None, ...)
```
Constructor kwargs (`name`, `llm="provider:model"`, `tools=`, `system_prompt=`…) MUST be checked against `AbstractBot.__init__` (abstract.py:289) and the examples in `docs/getting-started.md` before you write them. Every snippet must be runnable as shown given an API key.

### Does NOT Exist
- ~~`docs/overrides/`~~ — does not exist on dev; created by TASK-5197
- ~~`docs/tutorials/`~~ — does not exist on dev; created by TASK-5201 / TASK-5202
- ~~favicon / social-card raster assets~~ — do not exist yet on dev; created by TASK-5195
- ~~`tests/docs_site/`~~ — does not exist; each task creates its own test module there (no `__init__.py`, no `conftest.py`)
- ~~Wiki page slugs derived from section labels~~ — section labels (e.g. "Bots & Agents") are NOT page slugs; take targets from `wiki/_index.yaml` / the released `techwiki-manifest.json`

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/tutorials/first-tool.md",
      "action": "CREATE"
    },
    {
      "path": "docs/tutorials/deployment.md",
      "action": "CREATE"
    },
    {
      "path": "tests/docs_site/test_tutorials_advanced.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Content/design only — no product Python code. Test modules are plain-pytest, filesystem-only (no `parrot` import needed except where stated).
- Two-surface doctrine: Pages = what/why; Wiki = technical reference. Cross-link, never copy (AC11).


---

## Implementation Blueprint

### Steps (in order)
1. Read `docs/getting-started.md` for the working patterns — *why*: tutorials must not invent APIs.
2. Write each tutorial using the spec §3 M6 pattern (800–1200 words) — *why*: AC4.
3. Run every snippet once against a real key if available; otherwise note it in the Completion Note.
4. Write tests.

### `docs/tutorials/<name>.md` (CREATE)
```markdown
# Your First <Thing>

> **Time**: ~10 minutes
> **Prerequisites**: AI-Parrot installed, API key configured

## What You'll Build

## Step 1: Set Up

## Step 2: Define <components>

## Step 3: Run It

## What's Next

- [<related tutorial>](<other>.md)
- [Wiki: <section>](https://github.com/phenobarbital/ai-parrot/wiki/<Page-from-manifest>)
```
<!-- FILL IN: body per step — bounded by verified imports above -->

### `tests/docs_site/test_tutorials_advanced.py` (CREATE)
```python
"""FEAT-803 AC4: tutorials follow the beginner pattern."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", ["first-tool", "deployment"])
def test_tutorial_pattern(name: str) -> None:
    text = (ROOT / "docs" / "tutorials" / f"{name}.md").read_text(encoding="utf-8")
    for heading in ("## What You'll Build", "## Step 1", "## What's Next"):
        assert heading in text
    assert "```python" in text
    assert 600 <= len(text.split()) <= 1500
    # FILL IN: assert every `from parrot` import line in the page is importable (importlib.util.find_spec on the module)
```
### FILL IN checklist
- [ ] Tutorial bodies
- [ ] Import-check test

---

## Acceptance Criteria

- [ ] Tutorials exist and follow the pattern (AC4)
- [ ] All shown imports verified against the codebase
- [ ] `pytest tests/docs_site/test_tutorials_advanced.py -q` passes

## Validation Commands

- `pytest tests/docs_site/test_tutorials_advanced.py -q`

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug github-pages-informative-site --feature-id FEAT-803`).
2. Read the spec; check every Depends-on is `done` in `sdd/tasks/index/github-pages-informative-site.json`.
3. Verify the Codebase Contract; fix stale entries first.
4. Implement from the blueprint, completing every FILL IN.
5. Run the Validation Commands; commit only listed files.
6. `parrot sdd task close TASK-5202 github-pages-informative-site verified`, fill the Completion Note, commit SDD state.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
