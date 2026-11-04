# TASK-5151: Sweep the remaining gemini-2.5 src literals (conf, bots, plugins, handlers, templates)

**Feature**: FEAT-798 — Retire gemini-2.5-{pro,flash}: move the Google defaults to Gemini 4 Argon / 3.8-flash and bump google-genai
**Spec**: `sdd/specs/google-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 3** (literals half). Outside the client satellite and the FEAT-796 builtins, 17 source
files still ship a 2.5 id as a default or as a docstring example. These are plain string literals. Core
cannot import the client enum (circular import, `conf.py:448-457`), so they stay strings: flash-class →
`"gemini-3.8-flash"`, and the single pro-class docstring example → `"gemini-4-argon"`.

## Scope

Replace the literal at each site below and create a narrow source-scan test over exactly these files.

**NOT in scope**: `loaders/abstract.py` and `e2e/models.py` (they pin `gemini-2.5-flash-lite`, which is not
deprecated); `clients/base.py` (a non-goal, reviewed exclusion); `models/google.py` (TASK-5147); FEAT-796
builtins (TASK-5150); client satellite (TASK-5148/5149).

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `ONTOLOGY_AQL_MODEL` fallback (:166) |
| `packages/ai-parrot/src/parrot/bots/base.py` | MODIFY | :493, :495 |
| `packages/ai-parrot/src/parrot/bots/voice.py` | MODIFY | :438 |
| `packages/ai-parrot/src/parrot/bots/scraper/scraper.py` | MODIFY | :98 |
| `packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py` | MODIFY | prompt text :29 |
| `packages/ai-parrot/src/parrot/bots/factory/builders/tool_agent_builder.py` | MODIFY | prompt text :31 |
| `packages/ai-parrot/src/parrot/bots/mixins/model_switching.py` | MODIFY | docstring :30 |
| `packages/ai-parrot/src/parrot/bots/abstract.py` | MODIFY | docstring :968 (pro → argon) |
| `packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py` | MODIFY | :26 |
| `packages/ai-parrot/src/parrot/interfaces/images/plugins/classify.py` | MODIFY | :55 |
| `packages/ai-parrot/src/parrot/interfaces/images/plugins/analisys.py` | MODIFY | :16 |
| `packages/ai-parrot/src/parrot/memory/episodic/reflection.py` | MODIFY | :94 |
| `packages/ai-parrot/src/parrot/setup/providers/google.py` | MODIFY | :16 |
| `packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py` | MODIFY | docstring :6 |
| `packages/ai-parrot-server/src/parrot/handlers/google_generation.py` | MODIFY | POST default :115 |
| `packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py` | MODIFY | :188, :199 |
| `packages/ai-parrot/tests/unit/test_flash_default_literals.py` | CREATE | source scan of these 16 files |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.memory.episodic.reflection import ReflectionEngine   # verified: reflection.py:76 (class), ctor default :94
from parrot.setup.providers.google import GoogleWizard            # verified: setup/providers/google.py:7, default_model :16
```

### Existing Signatures to Use
```python
# verbatim anchors (occurrences in the file):
conf.py:166             ONTOLOGY_AQL_MODEL = config.get("ONTOLOGY_AQL_MODEL", fallback="gemini-2.5-flash")   (1)
bots/base.py:493,495    kwargs["model"] = "gemini-2.5-flash"     (2 — :493 under `elif llm.client_type == "google":`, :495 under `except Exception:`)
bots/voice.py:438       model=kwargs.get("model", "gemini-2.5-flash"),   (1)
bots/scraper/scraper.py:98   or "gemini-2.5-flash"   (1)
rag_builder.py:29       - Default model: provider=`google`, model=`gemini-2.5-flash`,   (1)
tool_agent_builder.py:31  5. Default model: provider=`google`, model=`gemini-2.5-flash`,   (1)
model_switching.py:30   llm="google:gemini-2.5-flash",   (1)
bots/abstract.py:968    "model": "gemini-2.5-pro",   (1)
classifybase.py:26 / classify.py:55 / analisys.py:16   self._model_name: str = kwargs.get("model_name", "gemini-2.5-flash")   (1 each)
reflection.py:94        model: str = "gemini-2.5-flash",   (1)
setup/providers/google.py:16   default_model: str = "gemini-2.5-flash"   (1)
knowledge/bookstore/_llm.py:6  - ``PARROT_BOOKSTORE_LLM`` — heavy model, e.g. ``"google:gemini-2.5-flash"``   (1)
handlers/google_generation.py:115   client = GoogleGenAIClient(model=data.get("model", "gemini-2.5-flash"))   (1)
autonomous/deploy/templates.py:188,199   llm="google:gemini-2.5-flash",   (2 — under name="Assistant" and name="DataAnalyst")
```

### Does NOT Exist
- ~~`from parrot.clients.google.models import GoogleModel` inside `conf.py`~~ — forbidden (circular import, `conf.py:448-457`).
- ~~`parrot.conf.LLM_MODEL_NAME`~~ — not a setting.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/conf.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/base.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/voice.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/scraper/scraper.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/factory/builders/tool_agent_builder.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/mixins/model_switching.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/bots/abstract.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/interfaces/images/plugins/classify.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/interfaces/images/plugins/analisys.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/memory/episodic/reflection.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/setup/providers/google.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/handlers/google_generation.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_flash_default_literals.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/memory/episodic/reflection.py#ReflectionEngine",
    "sym:packages/ai-parrot/src/parrot/setup/providers/google.py#GoogleWizard"
  ]
}
```

---

## Implementation Blueprint

### Steps (in order)
1. In every file above, replace `gemini-2.5-flash` with `gemini-3.8-flash` (whole id only — never touch `-lite` or `-image`) — *why*: flash-class per spec §2.
2. In `bots/abstract.py:968`, replace `"gemini-2.5-pro"` with `"gemini-4-argon"` — *why*: pro-class docstring example.
3. Create the scan test — *why*: it proves this task's files stay clean before TASK-5155's repo-wide guard lands.

### Every MODIFY row
```python
# occurrences per file: see the Codebase Contract list (2 in bots/base.py and templates.py, else 1)
# Whole-id replace: re.sub(r"gemini-2\.5-flash(?![-\w])", "gemini-3.8-flash", text) — then verify with
#   grep -n 'gemini-2\.5' <file>   → no output
```

### `packages/ai-parrot/tests/unit/test_flash_default_literals.py` (CREATE)
```python
"""FEAT-798: the core/server source files swept by TASK-5151 no longer name a retired 2.5 id."""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
RETIRED = re.compile(r"gemini-2\.5-(?:pro|flash)(?![-\w])")
SWEPT_FILES = (
    "packages/ai-parrot/src/parrot/conf.py",
    "packages/ai-parrot/src/parrot/bots/base.py",
    "packages/ai-parrot/src/parrot/bots/voice.py",
    "packages/ai-parrot/src/parrot/bots/scraper/scraper.py",
    "packages/ai-parrot/src/parrot/bots/factory/builders/rag_builder.py",
    "packages/ai-parrot/src/parrot/bots/factory/builders/tool_agent_builder.py",
    "packages/ai-parrot/src/parrot/bots/mixins/model_switching.py",
    "packages/ai-parrot/src/parrot/bots/abstract.py",
    "packages/ai-parrot/src/parrot/interfaces/images/plugins/classifybase.py",
    "packages/ai-parrot/src/parrot/interfaces/images/plugins/classify.py",
    "packages/ai-parrot/src/parrot/interfaces/images/plugins/analisys.py",
    "packages/ai-parrot/src/parrot/memory/episodic/reflection.py",
    "packages/ai-parrot/src/parrot/setup/providers/google.py",
    "packages/ai-parrot/src/parrot/knowledge/bookstore/_llm.py",
    "packages/ai-parrot-server/src/parrot/handlers/google_generation.py",
    "packages/ai-parrot-server/src/parrot/autonomous/deploy/templates.py",
)


@pytest.mark.parametrize("rel_path", SWEPT_FILES)
def test_no_retired_gemini_literal(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    hits = [n for n, line in enumerate(text.splitlines(), 1) if RETIRED.search(line)]
    assert not hits, f"{rel_path}: retired gemini-2.5 id on lines {hits}"


def test_reflection_and_wizard_defaults() -> None:
    """The two constructor-level defaults are the flash successor."""
    # FILL IN: assert inspect.signature(ReflectionEngine.__init__).parameters["model"].default == "gemini-3.8-flash"
    #          and GoogleWizard.default_model == "gemini-3.8-flash" — bounded by spec §2 table
```
**Why**: `parents[4]` resolves `packages/ai-parrot/tests/unit/<file>` to the repo root. FILL IN: verify the depth before relying on it.

### FILL IN checklist
- [ ] `REPO_ROOT` depth verified.
- [ ] `test_reflection_and_wizard_defaults` body with its two imports.

---

## Acceptance Criteria

- [ ] `grep -n 'gemini-2\.5-\(pro\|flash\)\b' <each file>` prints nothing (lite/image untouched).
- [ ] `ONTOLOGY_AQL_MODEL` falls back to `gemini-3.8-flash`.
- [ ] `ruff check` clean on every touched Python file.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/test_flash_default_literals.py -q`
- `pytest packages/ai-parrot/tests/unit/test_conf_default_llm.py -q`

## Test Specification
See the CREATE block above.

---

## Agent Instructions

1. Work in the feature worktree: `parrot sdd worktree ensure --slug google-migration --feature-id FEAT-798 --spec sdd/specs/google-migration.spec.md --index sdd/tasks/index/google-migration.json`
2. Read the spec (§2 table, §3 M3).
3. Check dependencies: none.
4. Verify every anchor with `grep -c`.
5. Mark the task `in-progress` in the index and commit only that file.
6. Implement from the blueprint.
7. Run the Validation Commands with an absolute worktree `PYTHONPATH`.
8. Commit only the files listed above.
9. Close with `parrot sdd task close TASK-5151 google-migration verified`, then fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
