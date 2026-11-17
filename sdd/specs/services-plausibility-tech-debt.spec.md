---
type: feature
base_branch: dev
projects: [parrot-formdesigner]
tags: [plausibility, llm-validation, tech-debt, audit]
---

# Feature Specification: Plausibility coverage reporting and prompt length caps

**Feature ID**: FEAT-737
**Date**: 2026-10-24
**Author**: sdd-fix (agent)
**Status**: approved
**Target version**: current

---

## 1. Motivation & Business Requirements

> Drains ledger group `fixgroup:830468be893d` (2 issues, max severity `major`).

### Problem Statement

`AnswerPlausibilityChecker.check()` returns `PlausibilityReport(status="ok")`
whenever the LLM answered, even when some eligible answers were **never shown to
the model at all**. Two silent drop points exist today:

1. **`max_fields` cap** — `eligible_fields()` ends with
   `return picked[: cfg.max_fields]` (plausibility.py:106). Everything past the
   cap disappears with no record.
2. **Unrenderable answers** — `build_items()` skips any field whose
   `_answer_text()` returns `None`, i.e. dict answers and lists containing
   dicts/lists (plausibility.py:146-147). The `doc` field in the existing test
   fixture is exactly this shape.

The report therefore over-claims coverage: `status="ok"` with an `items` map that
silently omits fields. Nothing downstream can distinguish "the model judged this
answer plausible" from "the model never saw this answer". The worst case is an
all-unrenderable batch, which returns `status="ok", items={}` — indistinguishable
from a clean pass over zero eligible fields.

Separately, the prompt is built with **no length bound**. A single long free-text
answer is JSON-dumped into the prompt verbatim (`prompt = json.dumps(...)`,
plausibility.py:190), and the model's returned `reason` is stored verbatim
(`reason=out.reason or ""`, plausibility.py:218). Neither has a cap, so one
pathological answer can dominate the token budget of the batch, and a verbose or
adversarial model response is persisted unbounded into the audit record and
echoed to the client.

Ledger issues drained:

| Issue | Severity | Title |
|---|---|---|
| `issue:95ecd6f621d9` | major | Plausibility report does not record which eligible fields were NOT examined (max_fields cap, unrenderable answers) |
| `issue:bfc5ae62845c` | minor | Plausibility prompt has no length cap on answers or LLM reason |

### Goals

- G1 — `PlausibilityReport` records every eligible field that was **not**
  examined, with a machine-readable reason for each.
- G2 — Both existing drop points (`max_fields` cap, unrenderable answer) are
  reported; the all-unrenderable batch is no longer indistinguishable from a
  clean pass.
- G3 — Rendered answers and returned reasons are length-capped, by config, with
  a visible truncation marker.
- G4 — No change to the public signatures of `eligible_fields()` or
  `build_items()`: every existing caller keeps compiling and behaving.

### Non-Goals (explicitly out of scope)

- **Making the voice engine act on the new data.**
  `audio/engine.py:949` does `self._pl_unchecked -= requested or set()` on any
  non-blocked report, and `on_plausibility_done()`'s delta path rebuilds `merged`
  via `model_copy(update={...})` with an explicit field list. Both ignore
  not-examined fields, so after this feature the engine will still mark a capped
  or unrenderable field "checked". That is a real consequence and it is recorded
  as its own ledger issue rather than folded in here — it changes voice-flow
  control (fields staying unchecked re-trigger a check at review) and needs its
  own analysis and test matrix. This spec only makes the data exist and be
  correct at the source.
- Re-checking, chunking or paginating past the `max_fields` cap. The cap stays a
  hard cap; this feature makes it *visible*, not larger.
- Rendering dict answers (making them renderable). Still skipped by design —
  `_answer_text()` returning `None` is the privacy guard that keeps
  `blob_ref`/`data_url` payloads out of the prompt.
- Any change to `status`/`reason` semantics, the `threshold` gate, or
  `implausible_fields()`.

---

## 2. Architectural Design

### Overview

Two additive config knobs, one additive report field, and one new
selection helper that returns what it dropped. `check()` becomes the single place
that composes the full not-examined map from its two sources.

```
eligible_fields(form, scalars, cfg, only=)        ← public, signature UNCHANGED
        │  delegates to
        ▼
select_fields(form, scalars, cfg, only=)  ──→ (picked: list[FormField],
                                               not_examined: dict[str, str])
                                                        │
AnswerPlausibilityChecker.check()  ─────────────────────┘
        │  targets ─→ build_items() ─→ items        (unrenderable = targets − items)
        └──→ PlausibilityReport(not_examined = cap drops ∪ unrenderable)
```

The unrenderable set needs **no change to `build_items()`**: `check()` already
holds both `targets` and the returned `items`, so the difference of their
`field_id` sets is exactly what rendering dropped.

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `eligible_fields()` | wraps | keeps `-> list[FormField]`; body becomes a one-line delegation |
| `build_items()` | extends | gains keyword-only `max_answer_chars: int \| None = None`, default `None` = no cap (existing direct callers unchanged) |
| `AnswerPlausibilityChecker.check()` | modifies | composes `not_examined`, passes the answer cap, truncates `reason` |
| `wire_report()` | unaffected | `not_examined` is **not** added to `PLAUSIBILITY_AUDIT_FIELDS`, so it reaches the client |
| `audio/session_store.py` | unaffected | new field has a default; persisted reports deserialize |

### Data Models

```python
# core/llm_validation.py
class LLMValidationConfig(BaseModel):
    ...                                                   # existing fields unchanged
    max_answer_chars: int = Field(default=500, ge=1)
    max_reason_chars: int = Field(default=300, ge=1)


class PlausibilityReport(BaseModel):
    ...                                                   # existing fields unchanged
    not_examined: dict[str, str] = Field(default_factory=dict)
```

`not_examined` maps `field_id` → one of the two reason codes, declared as module
constants so tests and callers never spell them by hand:

```python
# core/llm_validation.py
NOT_EXAMINED_MAX_FIELDS: str = "max_fields_cap"
NOT_EXAMINED_UNRENDERABLE: str = "unrenderable_answer"
```

**Why client-facing, not audit-only**: `PLAUSIBILITY_AUDIT_FIELDS` exists to hide
*vendor* facts (`resolved_model`, `provider`, `usage`) per FEAT-732 spec §7 R10.
`not_examined` is not a vendor fact — it is a statement about the submitter's own
fields, and hiding it behind `wire_report()` would reproduce the exact
over-claimed-coverage problem this feature fixes, just one layer out.

### New Public Interfaces

```python
# services/plausibility.py
def select_fields(
    form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
) -> tuple[list[FormField], dict[str, str]]:
    """Partition eligible fields into those to send and those the cap dropped.

    Returns:
        ``(picked, not_examined)`` — ``picked`` is the ``cfg.max_fields``-capped,
        required-first list ``eligible_fields`` returns; ``not_examined`` maps
        each field id cut by the cap to ``NOT_EXAMINED_MAX_FIELDS``.
    """
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: config + report fields | yes | exact field names, types, defaults and constants fixed above | — |
| M2: `select_fields` split | yes | exact signature and return shape fixed above | — |
| M3: length caps | yes | cap sites and truncation marker fixed below | — |
| M4: `check()` composition | yes | all four return paths enumerated below | — |

### Module 1: Config knobs + report field
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py`
- **Responsibility**: declare `max_answer_chars`, `max_reason_chars`,
  `not_examined`, and the two reason-code constants.
- **Depends on**: nothing new.
- **Interface Skeleton**:
  ```python
  # core/llm_validation.py  (modifies core/llm_validation.py:44, :88)
  class LLMValidationConfig(BaseModel):
      max_answer_chars: int = Field(default=500, ge=1)
      """Max characters of a rendered answer placed in the prompt; longer text is
      truncated with a ``…`` marker so the model can see it was cut."""
      max_reason_chars: int = Field(default=300, ge=1)
      """Max characters kept from the model's returned ``reason``."""

  class PlausibilityReport(BaseModel):
      not_examined: dict[str, str] = Field(default_factory=dict)
      """Eligible field ids that were never shown to the model, by reason code.

      Empty on a ``skipped``/``blocked`` report — those statuses already say the
      whole batch was not examined. A ``status="ok"`` report with a non-empty
      ``not_examined`` means partial coverage: ``items`` is authoritative only
      for the field ids absent from this map.
      """

  NOT_EXAMINED_MAX_FIELDS: str = "max_fields_cap"
  NOT_EXAMINED_UNRENDERABLE: str = "unrenderable_answer"
  ```

### Module 2: `select_fields` / `eligible_fields` split
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py`
- **Responsibility**: expose what the `max_fields` cap dropped without changing
  the existing public signature.
- **Depends on**: M1 (reason constants).
- **Interface Skeleton**:
  ```python
  # services/plausibility.py  (modifies services/plausibility.py:86-106)
  def select_fields(
      form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
  ) -> tuple[list[FormField], dict[str, str]]:
      """Partition eligible fields into those to send and those the cap dropped."""

  def eligible_fields(
      form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
  ) -> list[FormField]:
      """Fields to send: enabled, answered, not read_only, type not excluded, not sensitive.

      Ordered required-first (stable), cut at ``cfg.max_fields``; ``only`` restricts to a subset.
      Thin wrapper over ``select_fields`` — use that one to learn what the cap cut.
      """
  ```
  The whole existing filter/sort body moves into `select_fields`; the cut becomes
  `picked[: cfg.max_fields]` for the return value and
  `{f.field_id: NOT_EXAMINED_MAX_FIELDS for f in picked[cfg.max_fields :]}` for
  the second element. `eligible_fields` returns `select_fields(...)[0]`.

### Module 3: Prompt and reason length caps
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py`
- **Responsibility**: bound the prompt's per-answer text and the stored reason.
- **Depends on**: M1 (config fields).
- **Interface Skeleton**:
  ```python
  # services/plausibility.py  (modifies services/plausibility.py:117, :138)
  def _truncate(text: str, limit: int) -> str:
      """Return ``text`` cut to ``limit`` characters, ending in ``…`` when cut."""

  def _answer_text(
      field: FormField, value: Any, locale: str, labels: dict[str, str], *, max_chars: int | None = None
  ) -> str | None:
      """Render an answer as text; ``None`` when it cannot be rendered safely (dicts).

      ``max_chars`` caps the rendered result (``None`` = uncapped).
      """

  def build_items(
      form: FormSchema, fields: list[FormField], scalars: dict[str, Any], *, locale: str,
      max_answer_chars: int | None = None,
  ) -> list[dict[str, Any]]:
      """Prompt items: field_id, label, description, hint, field_type, options (labels), answer (text).

      ``max_answer_chars`` caps each rendered answer (``None`` = uncapped, the
      pre-FEAT-737 behaviour for direct callers).
      """
  ```
  Truncation applies to the **final rendered string**, after option-label
  mapping and list joining, so a long multi-select renders then cuts. A cap is
  applied only when `max_chars` is not `None` and `len(text) > max_chars`; the
  marker `…` replaces the last character rather than extending past the limit,
  so the result is never longer than `max_chars`.

### Module 4: `check()` composition
- **Path**: `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py`
- **Responsibility**: populate `not_examined` on every `ok` return path and
  truncate the model's reason.
- **Depends on**: M1, M2, M3.
- **Interface Skeleton**:
  ```python
  # services/plausibility.py  (modifies services/plausibility.py:177-229)
  class AnswerPlausibilityChecker:
      async def check(
          self, form: FormSchema, scalars: dict[str, Any], *, locale: str, fields: set[str] | None = None
      ) -> PlausibilityReport:
          """Return the report; raise PlausibilityBlocked only under ``on_error == "block"``.

          The returned report's ``not_examined`` names every eligible field the
          model never saw — cut by ``cfg.max_fields`` or unrenderable.
          """
  ```
  All four `ok` return paths, exactly:

  | Path | Current line | `not_examined` |
  |---|---|---|
  | no targets | 184 | `{}` (nothing eligible ⇒ nothing cut) |
  | no renderable items | 189 | the cap drops **plus** every target id (all unrenderable) |
  | success | 220-229 | cap drops **plus** `{f.field_id for f in targets} − {i["field_id"] for i in items}` |
  | `_fail()` (`skipped`) | 269-275 | `{}` — unchanged, documented in M1 |

  `reason` becomes `_truncate(out.reason or "", cfg.max_reason_chars)`, and
  `build_items` is called with `max_answer_chars=cfg.max_answer_chars`.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_select_fields_reports_cap_drops` | M2 | `max_fields=2` over the 4 eligible fixture fields → `picked` is required-first len 2, `not_examined` names the other 2 with `max_fields_cap` |
| `test_eligible_fields_signature_unchanged` | M2 | `eligible_fields()` still returns a bare list and the same ids as before for the default config |
| `test_truncate_marks_cut_and_respects_limit` | M3 | over-limit text → `len == limit` and ends with `…`; at/under-limit text → returned unchanged |
| `test_build_items_caps_answer` | M3 | a 2000-char answer with `max_answer_chars=50` → item `answer` is 50 chars ending `…`; `max_answer_chars=None` → verbatim |
| `test_check_reports_unrenderable` | M4 | default config over `SCALARS` → `status="ok"`, `not_examined == {"doc": "unrenderable_answer"}` (the dict-valued fixture field) |
| `test_check_reports_cap_and_unrenderable_together` | M4 | `max_fields=2` → `not_examined` carries both reason codes, and no id appears in both `items` and `not_examined` |
| `test_check_all_unrenderable_is_not_silent` | M4 | a form whose only eligible answer is a dict → `status="ok"`, `items == {}`, `not_examined` non-empty, and **no LLM call made** |
| `test_check_truncates_reason` | M4 | model returns a 5000-char reason with `max_reason_chars=20` → stored reason is 20 chars ending `…` |
| `test_fail_path_has_empty_not_examined` | M4 | `None` client with `on_error="skip"` → `status="skipped"`, `not_examined == {}` |
| `test_wire_report_includes_not_examined` | M1 | `not_examined` survives `wire_report()` (it is not an audit-only field) |

### Validation Contract

tests:
- packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py
- packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py
- packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py
markers: none

### Test Data / Fixtures

Reuse the existing module fixtures in
`tests/formdesigner/test_plausibility_checker.py` — no new ones needed:

- `_make_form(cfg)` / the `form` fixture already declare 8 fields covering the
  privacy exclusions.
- `SCALARS["doc"] == {"blob_ref": "b1", "data_url": "data:x"}` is already the
  unrenderable case, and `doc` is already one of the 4 eligible ids
  (`test_privacy_exclusions` asserts `{"nick0", "name", "color", "doc"}`), so
  the unrenderable assertion needs no fixture change at all.
- `FakeClient` already returns `model`/`provider`, satisfying the FEAT-732
  identity gate.

---

## 5. Acceptance Criteria

- [ ] AC1 — `LLMValidationConfig` has `max_answer_chars` (default 500) and
      `max_reason_chars` (default 300), both `ge=1`.
- [ ] AC2 — `PlausibilityReport.not_examined` exists, defaults to `{}`, and maps
      field ids to `max_fields_cap` / `unrenderable_answer`.
- [ ] AC3 — A `status="ok"` report names every eligible field cut by the
      `max_fields` cap.
- [ ] AC4 — A `status="ok"` report names every eligible field dropped as
      unrenderable, including when that is *all* of them.
- [ ] AC5 — `items` and `not_examined` are disjoint on every return path.
- [ ] AC6 — Rendered prompt answers are capped at `cfg.max_answer_chars` with a
      `…` marker, and the result never exceeds the cap.
- [ ] AC7 — A stored verdict `reason` is capped at `cfg.max_reason_chars`.
- [ ] AC8 — `eligible_fields()` and `build_items()` keep their current public
      signatures; `build_items()`'s new parameter defaults to uncapped.
- [ ] AC9 — `not_examined` is absent from `PLAUSIBILITY_AUDIT_FIELDS` and
      therefore present in `wire_report()` output.
- [ ] AC10 — Every test in the Validation Contract passes, and `ruff check` is
      clean on the two changed files.
- [ ] AC11 — The voice-engine consumer gap named in §1 Non-Goals is filed as a
      ledger issue, with its id recorded in the task Completion Note.

---

## 6. Codebase Contract

> Verified against `7ccfee9e5` (dev, 2026-10-24).

### Verified Imports

```python
# verified: packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py:17-25
from ..core.llm_validation import (
    LLMValidationConfig,
    PlausibilityReport,
    PlausibilityVerdict,
    llm_validation_enabled,
)
from ..core.schema import FormField, FormSchema
from ..core.types import FieldType
from ..core.voice import is_sensitive

# verified: packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py:11-17
from parrot_formdesigner.services.plausibility import (
    AnswerPlausibilityChecker,
    PlausibilityBatch,
    PlausibilityBlocked,
    build_items,
    eligible_fields,
)
```

### Existing Class Signatures

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py
class LLMValidationConfig(BaseModel):
    enabled: bool = False                                                  # line 31
    threshold: float = Field(default=0.7, ge=0.0, le=1.0)                  # line 32
    on_error: Literal["skip", "block"] = "skip"                            # line 33
    on_implausible: Literal["annotate", "review", "reject"] = "annotate"   # line 34
    model: str | None = None                                               # line 42
    timeout_s: float = Field(default=8.0, gt=0.0)                          # line 43
    max_fields: int = Field(default=50, ge=1)                              # line 44
    exclude_field_types: list[FieldType] = Field(...)                      # line 45

class PlausibilityReport(BaseModel):
    status: Literal["ok", "skipped", "blocked"]                            # line 73
    reason: str | None = None                                              # line 74
    model: str | None = None                                               # line 75
    threshold: float                                                       # line 76
    latency_ms: int | None = None                                          # line 77
    items: dict[str, PlausibilityVerdict] = Field(default_factory=dict)    # line 78
    resolved_model: str | None = None                                      # line 79
    provider: str | None = None                                            # line 85
    usage: dict[str, Any] | None = None                                    # line 87

PLAUSIBILITY_AUDIT_FIELDS: frozenset[str] = frozenset({"resolved_model", "provider", "usage"})  # line 124
def wire_report(report: PlausibilityReport, **dump_kwargs: Any) -> dict[str, Any]:              # line 127

# packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py
def eligible_fields(form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig,
                    *, only: set[str] | None = None) -> list[FormField]:                        # line 86
def _answer_text(field: FormField, value: Any, locale: str, labels: dict[str, str]) -> str | None:  # line 117
def build_items(form: FormSchema, fields: list[FormField], scalars: dict[str, Any],
                *, locale: str) -> list[dict[str, Any]]:                                        # line 138

class AnswerPlausibilityChecker:
    def __init__(self, client: "AbstractClient | None", *, config: LLMValidationConfig) -> None:  # line 172
    async def check(self, form: FormSchema, scalars: dict[str, Any], *, locale: str,
                    fields: set[str] | None = None) -> PlausibilityReport:                      # line 177
    def _fail(self, reason: str) -> PlausibilityReport:                                         # line 269
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `select_fields()` | `eligible_fields()` | delegation | `plausibility.py:86` |
| `check()` | `select_fields()` | replaces the `eligible_fields` call | `plausibility.py:182` |
| `check()` | `build_items(max_answer_chars=)` | keyword arg | `plausibility.py:187` |
| `not_examined` | `wire_report()` | NOT excluded (reaches client) | `llm_validation.py:124` |

### Does NOT Exist (Anti-Hallucination)

- ~~`PlausibilityReport.unchecked`~~ / ~~`.skipped_fields`~~ / ~~`.coverage`~~ — no such field; the new one is `not_examined`.
- ~~`LLMValidationConfig.max_prompt_chars`~~ / ~~`.max_chars`~~ — the new names are `max_answer_chars` and `max_reason_chars`.
- ~~`plausibility.partition_fields()`~~ / ~~`.eligible_fields_with_dropped()`~~ — the new helper is `select_fields()`.
- ~~`PlausibilityItemOut.truncated`~~ — not added; truncation is not reported per item.
- `AnswerPlausibilityChecker._identity()` and `_parse()` exist (lines 250, 231) but are **not** touched by this feature.
- `audio/engine.py:_pl_unchecked` exists (line 150) but is **out of scope** — see §1 Non-Goals.

### Edit Sites (Blueprint Anchors)

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | `    max_fields: int = Field(default=50, ge=1)` | `llm_validation.py:44` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py` | MODIFY | `    usage: dict[str, Any] | None = None` | `llm_validation.py:87` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `    picked.sort(key=lambda f: 0 if f.required else 1)` | `plausibility.py:105` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `def _answer_text(field: FormField, value: Any, locale: str, labels: dict[str, str]) -> str | None:` | `plausibility.py:117` | 1 |
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `        targets = eligible_fields(form, scalars, cfg, only=fields)` | `plausibility.py:182` | 1 |
| `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py` | MODIFY | `class TestEligibility:` | `test_plausibility_checker.py:84` | 1 |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Pydantic v2 models, `Field(...)` with explicit bounds; Google-style
  docstrings; 120-column lines; `black` formats, `ruff check` gates.
- Keep the two source files the only production files touched. The tests file is
  the only test file that needs new cases.
- `self.logger` for any new warning; never `print`.

### Known Risks / Gotchas

- **`not_examined` widens the client wire shape.** `wire_report()` is dumped into
  `plausibility_summary` (`api/audio_ws.py:1265`). The existing assertions are
  relative (`["status"] == "ok"`, a `not {...}.intersection(...)` audit check,
  and `model_dump(exclude=PLAUSIBILITY_AUDIT_FIELDS)` compared against
  `wire_report` output) — verified at `test_audio_ws_adapter.py:511,533` and
  `tests/unit/test_plausibility_wire_report.py:21-28`. None pins an exact full
  dict, so the widening is safe; the contract tests are in the Validation
  Contract to prove it.
- **Disjointness is a real trap.** With `only=` plus a cap, a field can be both
  "a target" and "cut"; build the success-path map as
  `cap_drops | (target_ids − item_ids)` where `cap_drops` keys are by
  construction absent from `targets`, then assert disjointness in the test.
- **`_truncate` must not exceed the limit.** Appending `…` after slicing to
  `limit` yields `limit + 1`. Slice to `limit - 1` and append, so AC6's
  "never exceeds" holds.
- The shared `.venv` is editable-installed against the main checkout, so run the
  tests from the worktree with
  `PYTHONPATH=packages/parrot-formdesigner/src` prefixed.

### External Dependencies

None. No new packages.

---

## 8. Open Questions

None. Both issues are fully specified above; the one judgement call
(client-facing vs audit-only `not_examined`) is decided and justified in §2.

---

## 9. Design Research Cross-Check

Status: skipped (a two-issue tech-debt drain with a fixed, local blast radius —
`wiki_blast_radius` on `eligible_fields` reports impact confined to
`AnswerPlausibilityChecker.check()` plus the one test module).
