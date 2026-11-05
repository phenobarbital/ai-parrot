# TASK-5143: Docs: per-component LLM defaults and keys

**Feature**: FEAT-796 — Per-Component LLM Defaults
**Spec**: `sdd/specs/per-component-llm-defaults.spec.md`
**Status**: done
**Priority**: low
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5140, TASK-5141, TASK-5142
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (AC9). Operators need one page listing every variable, the cascade and the `CREW_AI_KEY` alias.

---

## Scope

- Create `docs/configuration/llm-defaults.md`: table of `DEFAULT_LLM`, `AGENT_LLM`, `CREW_LLM`, `EXPERT_{JUDGMENT,BALANCED,TEMPLATED}_LLM`, key pattern `<COMPONENT>_<PROVIDER>_API_KEY`, cascade order, `CREW_AI_KEY` alias, `UsageRecord.component` values.
- Add a short `CREW_GOOGLE_API_KEY` note + link in `docs/crew_handler.md` under the `## Google Credentials (\`CREW_AI_KEY\`)` heading.
- Add a doc-presence test.

**NOT in scope**: Code changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/configuration/llm-defaults.md` | CREATE | operator doc |
| `docs/crew_handler.md` | MODIFY | CREW_GOOGLE_API_KEY note |
| `packages/ai-parrot/tests/test_llm_defaults_documented.py` | CREATE | doc test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: Use these exact imports, names and signatures. Verify anything not listed
> before using it. Anchors verified at dev `e179aba02f`.

### Verified Imports
```python
import pathlib
```

### Existing Signatures to Use
```python
# docs/crew_handler.md:570
## Google Credentials (`CREW_AI_KEY`)
# pattern: packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py (skips when docs/ missing)
```

### Does NOT Exist
- ~~`docs/configuration/`~~ — directory does not exist yet; create it

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "docs/configuration/llm-defaults.md",
      "action": "CREATE"
    },
    {
      "path": "docs/crew_handler.md",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/test_llm_defaults_documented.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

### Key Constraints
- Keep `CREW_AI_KEY` in crew_handler.md — `test_crew_key_documented.py` asserts it.
- Doc test must skip when the docs tree is absent (wheel checkout), like the crew doc test.

---

## Implementation Blueprint

> Write each block nearly verbatim, then complete every `# FILL IN:` marker.
> Never change a signature, name or path the blueprint fixes.

### Steps (in order)
1. Write the doc page — *why*: AC9.
2. Crew handler note — *why*: discoverability.
3. Doc test.

### `docs/configuration/llm-defaults.md` (CREATE)
```markdown
# Per-component LLM defaults (FEAT-796)
## Variables
| Variable | Component | Builtin default |
|---|---|---|
# FILL IN: one row per variable; builtins from crew.py _CREW_BUILTIN_LLM, experts/policy.py, handler
## API keys
# FILL IN: <COMPONENT>_<PROVIDER>_API_KEY, Google family -> GOOGLE, per-tier expert keys only,
#          CREW_GOOGLE_API_KEY -> CREW_AI_KEY (alias) -> GOOGLE_API_KEY; explicit credentials win
## Usage attribution
# FILL IN: UsageRecord.component values; not a metric label
```

### `docs/crew_handler.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c '## Google Credentials (`CREW_AI_KEY`)' docs/crew_handler.md) — AFTER line 570: -->
> FEAT-796: `CREW_GOOGLE_API_KEY` is now the primary crew key; `CREW_AI_KEY` remains a silent alias.
> See [per-component LLM defaults](configuration/llm-defaults.md).
```

### `packages/ai-parrot/tests/test_llm_defaults_documented.py` (CREATE)
```python
"""FEAT-796 docs presence (TASK-5143)."""
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("name", ["DEFAULT_LLM", "CREW_LLM", "AGENT_LLM", "EXPERT_JUDGMENT_LLM", "CREW_GOOGLE_API_KEY", "CREW_AI_KEY"])
def test_llm_defaults_documented(name: str) -> None:
    doc = ROOT / "docs" / "configuration" / "llm-defaults.md"
    if not doc.exists():
        pytest.skip("docs tree not present")
    assert name in doc.read_text(encoding="utf-8")
```

### FILL IN checklist
- [ ] doc rows/sections; bounded by AC9

---

## Acceptance Criteria

- [ ] Doc page lists every variable, cascade and alias
- [ ] crew_handler.md links it and still mentions CREW_AI_KEY
- [ ] Doc tests pass

---

## Validation Commands

- `pytest packages/ai-parrot/tests/test_llm_defaults_documented.py -q`
- `pytest packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py -q`

---

## Test Specification

```python
# see blueprint
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-component-llm-defaults --feature-id FEAT-796`), never on `dev`.
2. Read the spec; confirm every `Depends-on` task is `done` in `sdd/tasks/index/per-component-llm-defaults.json`.
3. Verify the Codebase Contract (re-run the `grep -c` of every anchor) before writing code.
4. Mark the task `in-progress` in the index and commit only that file.
5. Implement from the blueprint; complete every `# FILL IN:`.
6. Run the Validation Commands with `PYTHONPATH` set to the changed packages' absolute `src` dirs; `ruff check` the touched files.
7. Commit only the listed files; close with `parrot sdd task close TASK-5143 per-component-llm-defaults verified`; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker; seat mistral (nova), 1 attempt, 0 retries
**Date**: 2026-11-04
**Notes**: Reviewer-correction fb8b480532: doc listed lowercase usage tags and a non-existent `global` tag, and vague builtin defaults; fixed to match code (AGENT/CREW/EXPERT_<TIER>). 6 doc tests pass. Review not recorded (coder_record_review server bug).

**Deviations from spec**: none
