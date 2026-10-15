# TASK-4369: GoogleModel catalogue refresh — add Gemini 4 Argon, delete the four dead ids

**Feature**: FEAT-688 — Raise the google-genai floor and refresh GoogleModel for Gemini 4.x (Argon)
**Spec**: `sdd/specs/gemini-upgrade.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 1** plus the enum/factory tests of §4. `GoogleModel` lacks the
Gemini 4.x generation and carries four ids the Gemini API no longer serves (live
`models.list`, 2026-10-15 — finding `sdd/state/FEAT-688/findings/F011-live-catalogue-verification.md`).
Operator decision U2: retire by **pure deletion** — no `deprecated_models` registry.

## Scope

- Add `GEMINI_4_ARGON = "gemini-4-argon"` to `GoogleModel`.
- Delete five members of `GoogleModel`: `GEMINI_3_7_PRO`, `GEMINI_3_7_FLASH_THINKING`,
  `GEMINI_3_7_FLASH_LITE`, `GEMINI_DEEP_RESEARCH`, `GEMINI_DEEP_RESEARCH_PREVIEW`
  (four distinct values; the last two share one value).
- Update `packages/ai-parrot/tests/test_google_models.py`: drop the three assertions on retired
  ids, add Argon, retired-id absence, and the 49/31 alias-count guard.
- Add two `list_models("google")` tests to `packages/ai-parrot/tests/test_llm_factory.py`.

**NOT in scope**:
- `VertexAIModel` — untouched, **including its own `GEMINI_3_7_PRO` (models.py:85)** (decision U5, spec §8 Q3).
- `IMAGEN_*` members — untouched (spec §8 Q4).
- `GEMINI_3_7_FLASH = "gemini-3.7-flash"` — still served; keep it.
- `client.py` gates (`"gemini-3.7-pro"` in prefixes / `_requires_thinking`) — TASK-4370.
- Adding any other live id (spec §8 Q2).
- Any `deprecated_models` attribute anywhere.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` | MODIFY | +1 member, −5 members in `GoogleModel` |
| `packages/ai-parrot/tests/test_google_models.py` | MODIFY | drop retired-id assertions, add Argon + guards |
| `packages/ai-parrot/tests/test_llm_factory.py` | MODIFY | add two `list_models("google")` tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.clients.google.models import GoogleModel   # models.py:11 (already imported in test_google_models.py:3)
from parrot.clients.factory import LLMFactory          # already imported in test_llm_factory.py:12
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-google/src/parrot/clients/google/models.py
class GoogleModel(Enum):                                   # line 11, plain Enum (NOT StrEnum)
    # Gemini 3.8 series                                    # line 18  ← insertion anchor
    GEMINI_3_7_FLASH = "gemini-3.7-flash"                  # line 21  ← KEEP
    GEMINI_3_7_PRO = "gemini-3.7-pro"                      # line 22  ← delete (also at line 85 in VertexAIModel — do NOT touch that one)
    GEMINI_3_7_FLASH_THINKING = "gemini-3.7-flash-thinking"  # line 23  ← delete
    GEMINI_3_7_FLASH_LITE = "gemini-3.7-flash-lite"        # line 24  ← delete
    GEMINI_DEEP_RESEARCH = "gemini-deep-research-preview-04-2026"          # line 54 ← delete
    GEMINI_DEEP_RESEARCH_PREVIEW = "gemini-deep-research-preview-04-2026"  # line 55 ← delete
class VertexAIModel(Enum):                                 # line 76 — untouched

# packages/ai-parrot/src/parrot/clients/factory.py
class LLMFactory:
    @staticmethod
    def list_models(provider: str) -> Dict[str, list]      # line 224
    # returns {"active": [m.value for m in client_class.models],          (iteration skips aliases)
    #          "deprecated": list(getattr(client_class, "deprecated_models", None) or {})}
```

Name-level references to the five deleted members in `packages/*/src`: **none** (verified by
grep 2026-10-15). In tests: only `test_google_models.py:19,20,39`.

### Does NOT Exist
- ~~`GoogleModel.GEMINI_4_PRO`~~ / ~~`GEMINI_4_FLASH`~~ — upstream publishes exactly one 4.x id.
- ~~`GoogleGenAIClient.deprecated_models`~~ — not being added (U2). Do not create it.
- ~~`parrot.clients.google.DEPRECATIONS`~~ — `DEPRECATIONS` exists only in `parrot.clients.openai.models`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-client-google/src/parrot/clients/google/models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_google_models.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/test_llm_factory.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-google/src/parrot/clients/google/models.py#GoogleModel",
    "sym:packages/ai-parrot/src/parrot/clients/factory.py#LLMFactory.list_models"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- `GoogleModel` is a plain `Enum`: a member whose value already exists becomes a silent alias.
  `gemini-4-argon` is a new value — confirm with the alias-count test.
- Post-condition (verified by simulating the edit): **49 names, 31 distinct values, 18 aliases**.
- `LLMFactory.list_models("google")["active"]` will contain 31 ids; `["deprecated"]` stays `[]`.

---

## Implementation Blueprint

### Steps (in order)
1. Insert the Argon block in `models.py` above `# Gemini 3.8 series` — because the file is ordered newest-first.
2. Delete the five members — the 3.7 lines are contiguous (22–24) and the deep-research lines are contiguous (54–55).
3. Edit `test_google_models.py` — because lines 19, 20, 39 would raise `AttributeError` after step 2.
4. Append the factory tests to `test_llm_factory.py`.
5. Run the Validation Commands.

### `packages/ai-parrot-client-google/src/parrot/clients/google/models.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c -x '    # Gemini 3.8 series' models.py)
# BEFORE — insert above `    # Gemini 3.8 series` (verified: models.py:18)
    # Gemini 4.x series (Argon)
    GEMINI_4_ARGON = "gemini-4-argon"
```
```python
# DELETE — occurrences of `    GEMINI_3_7_PRO = "gemini-3.7-pro"`: 2 (verified: grep -c, lines 22 and 85).
# Disambiguate: delete ONLY the copy inside GoogleModel, i.e. this 3-line run (lines 22-24):
    GEMINI_3_7_PRO = "gemini-3.7-pro"
    GEMINI_3_7_FLASH_THINKING = "gemini-3.7-flash-thinking"
    GEMINI_3_7_FLASH_LITE = "gemini-3.7-flash-lite"
# The VertexAIModel copy at line 85 sits between `GEMINI_3_7_FLASH = ...` and `GEMINI_3_6_FLASH = ...`
# with no THINKING/LITE neighbours — leave it.
```
```python
# DELETE — occurrences: 1 each (verified: models.py:54, 55)
    GEMINI_DEEP_RESEARCH = "gemini-deep-research-preview-04-2026"
    GEMINI_DEEP_RESEARCH_PREVIEW = "gemini-deep-research-preview-04-2026"
```
**Why**: spec M1. The `# Gemini 3.7 series` comment stays — `GEMINI_3_7_FLASH` remains under it.
`client.py:5348` hardcodes the live `deep-research-pro-preview-12-2025`, so nothing depends on the
deleted deep-research members.

### `packages/ai-parrot/tests/test_google_models.py` (MODIFY)
```python
# occurrences: 1 each (verified: lines 19, 20, 39) — DELETE these three lines:
    assert GoogleModel.GEMINI_3_7_PRO.value == "gemini-3.7-pro"
    assert GoogleModel.GEMINI_3_7_FLASH_THINKING.value == "gemini-3.7-flash-thinking"
    assert GoogleModel("gemini-3.7-pro") is GoogleModel.GEMINI_3_7_PRO
```
```python
# APPEND at end of file

RETIRED_VALUES = (
    "gemini-3.7-pro",
    "gemini-3.7-flash-thinking",
    "gemini-3.7-flash-lite",
    "gemini-deep-research-preview-04-2026",
)
RETIRED_NAMES = (
    "GEMINI_3_7_PRO",
    "GEMINI_3_7_FLASH_THINKING",
    "GEMINI_3_7_FLASH_LITE",
    "GEMINI_DEEP_RESEARCH",
    "GEMINI_DEEP_RESEARCH_PREVIEW",
)


def test_google_model_enum_has_gemini_4_argon():
    """GEMINI_4_ARGON is registered and reachable by value (FEAT-688)."""
    assert GoogleModel.GEMINI_4_ARGON.value == "gemini-4-argon"
    assert GoogleModel("gemini-4-argon") is GoogleModel.GEMINI_4_ARGON


@pytest.mark.parametrize("value", RETIRED_VALUES)
def test_google_model_retired_values_raise(value):
    """Ids no longer served by the Gemini API are deleted outright (FEAT-688 U2)."""
    # FILL IN: assert GoogleModel(value) raises ValueError — bounded by AC-2


def test_google_model_retired_names_absent():
    """The five retired member names are gone from GoogleModel."""
    # FILL IN: assert none of RETIRED_NAMES is in GoogleModel.__members__ — bounded by AC-2


def test_google_model_alias_count():
    """Guards against a new member silently collapsing onto an existing value."""
    assert len(GoogleModel.__members__) == 49
    assert len({m.value for m in GoogleModel}) == 31
```
**Why**: the module has no `import pytest` today (line 3 is the only import) — add `import pytest`
above the `GoogleModel` import, because the parametrized test needs it.

### `packages/ai-parrot/tests/test_llm_factory.py` (MODIFY)
```python
# APPEND at end of file


# ── FEAT-688 Google catalogue ────────────────────────────────────────────────


def test_list_models_google_includes_argon():
    """The Gemini 4 Argon id is published as an active Google model."""
    models = LLMFactory.list_models("google")
    assert "gemini-4-argon" in models["active"]
    # FILL IN: assert "gemini-3.7-pro" not in models["active"] — bounded by AC-2


def test_list_models_google_has_no_deprecations():
    """Google retires by deletion (FEAT-688 U2) — no deprecation registry."""
    assert LLMFactory.list_models("google")["deprecated"] == []
```
**Why**: pins the U2 decision so a future registry is a deliberate, test-breaking change.

### FILL IN checklist
- [ ] `test_google_model_retired_values_raise` body (`pytest.raises(ValueError)`)
- [ ] `test_google_model_retired_names_absent` body
- [ ] `gemini-3.7-pro` absence assertion in `test_list_models_google_includes_argon`
- [ ] `import pytest` added to `test_google_models.py`

---

## Acceptance Criteria

- [ ] AC-1: `GoogleModel.GEMINI_4_ARGON.value == "gemini-4-argon"` and `GoogleModel("gemini-4-argon")` resolves to it.
- [ ] AC-2: `GoogleModel` has 49 names / 31 distinct values; the five names are gone; each of the four retired values raises `ValueError`.
- [ ] AC-3: `VertexAIModel` is byte-identical to before (`git diff` shows no change in lines 76-99).
- [ ] AC-4: `LLMFactory.list_models("google")` → `"gemini-4-argon"` in `active`, `deprecated == []`.
- [ ] AC-5: `ruff check` clean on the three files.

## Validation Commands
- `pytest packages/ai-parrot/tests/test_google_models.py -q`
- `pytest packages/ai-parrot/tests/clients/test_google_models.py -q`
- `pytest packages/ai-parrot/tests/test_llm_factory.py -q`

Run with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-client-google/src` inside the worktree.

## Test Specification

See the blueprint blocks for `test_google_models.py` and `test_llm_factory.py`.
`packages/ai-parrot/tests/clients/test_google_models.py` must keep passing unchanged (it pins
`GEMINI_3_FLASH_COMPUTER_USE = "gemini-3-flash-preview"`, which is NOT retired).

---

## Agent Instructions

1. **Work in the feature worktree** — `python -m scripts.sdd.ensure_worktree --slug gemini-upgrade --feature-id FEAT-688`
2. **Read the spec** `sdd/specs/gemini-upgrade.spec.md` (§3 M1, §4, §6)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run `grep -c` on every anchor before editing
5. **Update status** in `sdd/tasks/index/gemini-upgrade.json` → `"in-progress"` and commit only that file
6. **Implement** from the blueprint; complete every `# FILL IN:`
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only the three listed files
9. **Close** with `scripts/sdd/close_task.sh TASK-4369 gemini-upgrade verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
