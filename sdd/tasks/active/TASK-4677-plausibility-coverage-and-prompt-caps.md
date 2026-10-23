# TASK-4677: Record unexamined fields and cap the prompt answer and verdict reason

**Feature**: FEAT-737 — Plausibility coverage reporting and prompt length caps
**Spec**: `sdd/specs/services-plausibility-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4676
**Assigned-to**: unassigned
**Discovered-from**: `issue:95ecd6f621d9` (ledger, major — report does not record which eligible fields were NOT examined), `issue:bfc5ae62845c` (ledger, minor — plausibility prompt has no length cap on answers or LLM reason)

---

## Context

Implements spec §3 Modules 2, 3 and 4 — the behavioural half of FEAT-737, and
the task that actually resolves both ledger issues. TASK-4676 declared
`PlausibilityReport.not_examined`, the two `LLMValidationConfig` caps and the
two reason-code constants; this task makes `AnswerPlausibilityChecker` populate
and honour them.

All three modules land in one task because they all modify the **same file**,
`services/plausibility.py`. Splitting them would force a serial chain over one
file with no parallelism gained and three times the merge overhead.

Today `check()` returns `status="ok"` whenever the LLM answered, even when
eligible answers were never shown to it — cut by `cfg.max_fields`
(`plausibility.py:106`) or dropped as unrenderable (`plausibility.py:146-147`).
The worst case is an all-unrenderable batch returning `status="ok", items={}`,
indistinguishable from a clean pass over zero eligible fields.

---

## Scope

- Add `select_fields()` returning `(picked, not_examined)`; reduce
  `eligible_fields()` to a thin delegation so its public signature is unchanged.
- Add `_truncate()`; thread an optional answer cap through `_answer_text()` and
  `build_items()` (default `None` = uncapped, so direct callers are unchanged).
- Populate `not_examined` on all three `ok` return paths of `check()`, and
  truncate the model's `reason` with `cfg.max_reason_chars`.
- Extend `tests/formdesigner/test_plausibility_checker.py` with the eight cases
  in the spec's §4 table that belong to these modules.

**NOT in scope**:
- `core/llm_validation.py` — TASK-4676 owns every model change.
- `audio/engine.py`. Its `_pl_unchecked -= requested or set()`
  (`audio/engine.py:949`) and the `model_copy(update={...})` delta path in
  `on_plausibility_done()` both ignore unexamined fields, so the voice engine
  will still mark a capped or unrenderable field "checked" after this task.
  That is a deliberate non-goal (spec §1) and must be filed as its own ledger
  issue — see AC11.
- Re-checking, chunking or paginating past `max_fields`; making dict answers
  renderable; any change to `status`/`reason` semantics, the `threshold` gate,
  `implausible_fields()`, `_parse()` or `_identity()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` | MODIFY | `select_fields`, `_truncate`, answer/reason caps, `check()` composition |
| `packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py` | MODIFY | Coverage and cap test cases |

---

## Codebase Contract (Anti-Hallucination)

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

# ADDED BY THIS TASK to the same from-import block — both created by TASK-4676:
#   NOT_EXAMINED_MAX_FIELDS, NOT_EXAMINED_UNRENDERABLE

# verified: packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py:11-17
from parrot_formdesigner.services.plausibility import (
    AnswerPlausibilityChecker,
    PlausibilityBatch,
    PlausibilityBlocked,
    build_items,
    eligible_fields,
)
```

`asyncio`, `json`, `logging`, `time`, `Any`, `BaseModel`, `Field` are already
imported in `plausibility.py` — this task adds **no** stdlib or third-party
import, only the two constants above.

### Existing Signatures to Use

```python
# packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py
_ALWAYS_EXCLUDED = frozenset({FieldType.PASSWORD, FieldType.HIDDEN})                   # line 30
_OPTION_TYPES = frozenset({FieldType.SELECT, FieldType.MULTI_SELECT, FieldType.DYNAMIC_SELECT})  # line 31

class PlausibilityItemOut(BaseModel):     # line 34
    field_id: str                         # line 37
    plausible: bool                       # line 38
    confidence: float                     # line 39
    reason: str = ""                       # line 40

class PlausibilityBatch(BaseModel):       # line 43
    items: list[PlausibilityItemOut] = Field(default_factory=list)  # line 46

class PlausibilityBlocked(Exception):     # line 49

def _is_answered(value: Any) -> bool:     # line 75
def eligible_fields(form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig,
                    *, only: set[str] | None = None) -> list[FormField]:   # line 86
def _answer_text(field: FormField, value: Any, locale: str, labels: dict[str, str]) -> str | None:  # line 117
def build_items(form: FormSchema, fields: list[FormField], scalars: dict[str, Any],
                *, locale: str) -> list[dict[str, Any]]:                   # line 138
_SYSTEM_PROMPT = (...)                    # line 162

class AnswerPlausibilityChecker:          # line 169
    def __init__(self, client: "AbstractClient | None", *, config: LLMValidationConfig) -> None:  # line 172
    async def check(self, form: FormSchema, scalars: dict[str, Any], *, locale: str,
                    fields: set[str] | None = None) -> PlausibilityReport:  # line 177
    def _parse(self, response: Any) -> PlausibilityBatch:                   # line 231
    @staticmethod
    def _identity(response: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:  # line 250
    def _fail(self, reason: str) -> PlausibilityReport:                     # line 269
```

The exact body of `eligible_fields` that moves into `select_fields`
(verified `plausibility.py:93-106`):

```python
    excluded = set(cfg.exclude_field_types) | _ALWAYS_EXCLUDED
    picked: list[FormField] = []
    for field in form.iter_fields_recursive():
        if only is not None and field.field_id not in only:
            continue
        if not llm_validation_enabled(form, field):
            continue
        if field.read_only or field.field_type in excluded or is_sensitive(field):
            continue
        if not _is_answered(scalars.get(field.field_id)):
            continue
        picked.append(field)
    picked.sort(key=lambda f: 0 if f.required else 1)
    return picked[: cfg.max_fields]
```

`check()`'s three `ok` return paths, verified `plausibility.py:184`, `:189`, `:220-229`:

```python
        if not targets:
            return PlausibilityReport(status="ok", threshold=cfg.threshold, model=cfg.model, items={})   # 184
        ...
        if not items:
            return PlausibilityReport(status="ok", threshold=cfg.threshold, model=cfg.model, items={})   # 189
        ...
        return PlausibilityReport(                                                                       # 220
            status="ok", threshold=cfg.threshold, model=cfg.model, resolved_model=resolved_model,
            provider=provider, usage=usage, latency_ms=latency_ms, items=verdicts,
        )
```

Test-module fixtures (verified `test_plausibility_checker.py`):

```python
class FakeClient:                                   # line 20 — returns Msg with structured_output/output/model/provider
def _make_form(cfg: LLMValidationConfig | None = None) -> FormSchema:  # line 39 — 8 fields
SCALARS = {...}                                     # line 63; SCALARS["doc"] == {"blob_ref": "b1", "data_url": "data:x"}
@pytest.fixture
def form() -> FormSchema:                           # line 75
def _batch(*items):                                 # line 80
class TestEligibility:                              # line 84
class TestCheck:                                    # line 109
```

The 4 eligible ids under the default config are `{"nick0", "name", "color", "doc"}`
(asserted at `test_plausibility_checker.py:87`), of which `doc` is the
unrenderable one, and `name` is the only `required=True` field.

### Does NOT Exist

- ~~`plausibility.partition_fields()`~~ / ~~`eligible_fields_with_dropped()`~~ / ~~`select_eligible()`~~ — the new helper is `select_fields()` and nothing else.
- ~~`_truncate_text()`~~ / ~~`_cap()`~~ / ~~`textwrap.shorten` usage~~ — the helper is `_truncate(text, limit)`; do not import `textwrap`.
- ~~`LLMValidationConfig.max_answer_chars` with a `None` default~~ — it is a plain `int` with default 500 (TASK-4676); only `build_items`/`_answer_text` take `int | None`.
- ~~`PlausibilityReport.not_examined` as a `list`~~ — it is `dict[str, str]` (field id → reason code).
- ~~`form.iter_fields()`~~ — the real method is `form.iter_fields_recursive()` (used at `plausibility.py:95`).
- ~~`FormField.answer`~~ / ~~`FormField.value`~~ — answers come from the `scalars` dict, never off the field.
- ~~`PlausibilityItemOut.truncated`~~ — not added; truncation is not reported per item.
- `AnswerPlausibilityChecker._identity()` (line 250) and `_parse()` (line 231) exist but must **not** be modified.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py#eligible_fields",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py#build_items",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py#_answer_text",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py#AnswerPlausibilityChecker.check",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#PlausibilityReport",
    "sym:packages/parrot-formdesigner/src/parrot_formdesigner/core/llm_validation.py#LLMValidationConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- **Disjointness (AC5) is the trap.** `items` and `not_examined` must never
  share a key. Cap drops are by construction absent from `targets`; the
  unrenderable set is `{f.field_id for f in targets} - {i["field_id"] for i in items}`.
  Build the map as `cap_drops | unrenderable` and nothing else.
- **`_truncate` must not exceed the limit (AC6).** Slicing to `limit` and then
  appending `…` yields `limit + 1` characters. Slice to `limit - 1`, then append.
- **`build_items()` needs no change to find the unrenderable set.** `check()`
  already holds both `targets` and `items`; their `field_id` difference *is*
  what rendering dropped. Do not add an out-parameter to `build_items`.
- The `_fail()` path keeps `not_examined == {}` — `status="skipped"` already
  says the whole batch went unexamined (spec §3 Module 4 table).
- Async-first: `check()` stays `async`; `select_fields`, `_truncate`,
  `_answer_text` and `build_items` stay synchronous pure functions.
- `self.logger` for any new warning — never `print`.

### References in Codebase

- `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py:207-219` —
  the existing per-verdict loop where the `reason` cap goes.
- `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py:117-135` —
  `_answer_text`'s three render branches; the cap applies to the **final**
  string each branch produces, after option-label mapping and list joining.

---

## Implementation Blueprint

### Steps (in order)
1. Add `NOT_EXAMINED_MAX_FIELDS`/`NOT_EXAMINED_UNRENDERABLE` to the existing `..core.llm_validation` from-import — *why*: the codes are a wire contract and must come from one place, never inline literals.
2. Split `eligible_fields` into `select_fields` + a one-line wrapper — *why*: `check()` needs to know what the cap cut, while every existing caller (and 4 existing tests) must keep seeing a bare `list[FormField]` (AC8).
3. Add `_truncate` and thread `max_chars`/`max_answer_chars` through `_answer_text` and `build_items` — *why*: the cap must apply to the rendered text, so it belongs at the one place that produces it.
4. Rewrite `check()`'s three `ok` return paths to carry `not_examined`, and cap the verdict `reason` — *why*: `check()` is the only place holding both drop sources, so composing there keeps the map correct by construction.
5. Add the test cases — *why*: AC3/AC4/AC5/AC6/AC7 are all behavioural claims no reader can verify by eye.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` (MODIFY — imports)
```python
# occurrences: 1 (verified: grep -c '    llm_validation_enabled,' packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py)
# AFTER — insert below `    llm_validation_enabled,` (verified: services/plausibility.py:21)
    NOT_EXAMINED_MAX_FIELDS,
    NOT_EXAMINED_UNRENDERABLE,
```
**Why**: both names are created by TASK-4676 in `core/llm_validation.py`. `ruff`
sorts this block alphabetically on check, so place them where `ruff check --fix`
leaves them rather than fighting it.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` (MODIFY — selection split)
```python
# occurrences: 1 (verified: grep -c 'def eligible_fields(' packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py)
# REPLACE the whole function at `def eligible_fields(` (verified: services/plausibility.py:86-106)
def select_fields(
    form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
) -> tuple[list[FormField], dict[str, str]]:
    """Partition eligible fields into those to send and those the cap dropped.

    Args:
        form: The form whose fields are being judged.
        scalars: Submitted answers by field id.
        cfg: The form's LLM validation settings.
        only: When given, restrict consideration to these field ids.

    Returns:
        ``(picked, not_examined)`` — ``picked`` is the ``cfg.max_fields``-capped,
        required-first list; ``not_examined`` maps every field id cut by that cap
        to ``NOT_EXAMINED_MAX_FIELDS``.
    """
    excluded = set(cfg.exclude_field_types) | _ALWAYS_EXCLUDED
    picked: list[FormField] = []
    for field in form.iter_fields_recursive():
        if only is not None and field.field_id not in only:
            continue
        if not llm_validation_enabled(form, field):
            continue
        if field.read_only or field.field_type in excluded or is_sensitive(field):
            continue
        if not _is_answered(scalars.get(field.field_id)):
            continue
        picked.append(field)
    picked.sort(key=lambda f: 0 if f.required else 1)
    return picked[: cfg.max_fields], {f.field_id: NOT_EXAMINED_MAX_FIELDS for f in picked[cfg.max_fields :]}


def eligible_fields(
    form: FormSchema, scalars: dict[str, Any], cfg: LLMValidationConfig, *, only: set[str] | None = None
) -> list[FormField]:
    """Fields to send: enabled, answered, not read_only, type not excluded, not sensitive.

    Ordered required-first (stable), cut at ``cfg.max_fields``; ``only`` restricts to a subset.
    Thin wrapper over :func:`select_fields` — call that one to learn what the cap cut.
    """
    return select_fields(form, scalars, cfg, only=only)[0]
```
**Why this shape**: the filter/sort body is moved **verbatim** so the existing
eligibility semantics cannot drift; the only new logic is the second element of
the tuple. `picked.sort` is stable, so `picked[cfg.max_fields:]` is exactly the
tail the old `picked[: cfg.max_fields]` discarded. `eligible_fields` keeps its
signature and return type — do not change them (AC8).

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` (MODIFY — truncation + caps)
```python
# occurrences: 1 (verified: grep -c 'def _answer_text(field: FormField, value: Any, locale: str, labels: dict[str, str]) -> str | None:' packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py)
# BEFORE — insert above `def _answer_text(...)` (verified: services/plausibility.py:117)
def _truncate(text: str, limit: int) -> str:
    """Return ``text`` cut to at most ``limit`` characters, ending in ``…`` when cut.

    The marker replaces the final kept character rather than extending past
    ``limit``, so the result is never longer than ``limit``.
    """
    if limit <= 0 or len(text) <= limit:
        return text
    # FILL IN: return the cut string — slice to limit - 1 and append "…" so
    # len(result) == limit exactly; bounded by AC6.
```
Then, in `_answer_text`, add the keyword-only parameter and apply the cap to
each branch's final string:
```python
# occurrences: 1 (verified as above)
# REPLACE the signature line of `_answer_text` (verified: services/plausibility.py:117)
def _answer_text(
    field: FormField, value: Any, locale: str, labels: dict[str, str], *, max_chars: int | None = None
) -> str | None:
    """Render an answer as text; ``None`` when it cannot be rendered safely (dicts).

    ``max_chars`` caps the rendered result (``None`` = uncapped).
    """
```
```python
# occurrences: 1 (verified: grep -c 'def build_items(' packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py)
# REPLACE the signature and the `_answer_text` call inside `build_items` (verified: services/plausibility.py:138-145)
def build_items(
    form: FormSchema,
    fields: list[FormField],
    scalars: dict[str, Any],
    *,
    locale: str,
    max_answer_chars: int | None = None,
) -> list[dict[str, Any]]:
    """Prompt items: field_id, label, description, hint, field_type, options (labels), answer (text).

    ``max_answer_chars`` caps each rendered answer (``None`` = uncapped, the
    pre-FEAT-737 behaviour kept for direct callers).
    """
```
**Why**: the cap must be applied once, to the string that actually reaches the
prompt — after option labels are substituted and list items joined. Keeping the
default `None` means the 4 existing `build_items` call sites in the test module
and any external caller behave exactly as before (AC8). `_answer_text` returning
`None` still means "unrenderable" and must keep that meaning — do **not** let
truncation turn into `None`.

### `packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py` (MODIFY — check composition)
```python
# occurrences: 1 (verified: grep -c '        targets = eligible_fields(form, scalars, cfg, only=fields)' packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py)
# REPLACE — the line `        targets = eligible_fields(form, scalars, cfg, only=fields)` (verified: services/plausibility.py:182)
        targets, capped = select_fields(form, scalars, cfg, only=fields)
```
Then each of the three `ok` return paths gains `not_examined`:
```python
# path 1 — nothing eligible (verified: services/plausibility.py:183-184)
        if not targets:
            return PlausibilityReport(status="ok", threshold=cfg.threshold, model=cfg.model, items={})
            # FILL IN: pass not_examined=capped — when targets is empty, picked was
            # empty too, so capped is {} and this is cosmetic; keep it explicit so
            # every ok path reads the same; bounded by AC3.

# path 2 — nothing renderable (verified: services/plausibility.py:187-189)
        items = build_items(form, targets, scalars, locale=locale, max_answer_chars=cfg.max_answer_chars)
        if not items:
            # FILL IN: return status="ok" with not_examined = capped | every target id
            # mapped to NOT_EXAMINED_UNRENDERABLE — this is the all-unrenderable case
            # that AC4 forbids reporting as a silent clean pass.
            ...

# path 3 — success (verified: services/plausibility.py:220-229)
        # FILL IN: before the final return, compute
        #   unrenderable = {f.field_id for f in targets} - {i["field_id"] for i in items}
        # and pass not_examined = capped | {fid: NOT_EXAMINED_UNRENDERABLE for fid in unrenderable}
        # Assert nothing in that map is also a key of `verdicts`; bounded by AC5.
```
And the verdict reason is capped in the existing loop:
```python
# occurrences: 1 (verified: grep -c '                plausible=out.plausible, confidence=confidence, reason=out.reason or ""' packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py)
# REPLACE that line (verified: services/plausibility.py:218)
                plausible=out.plausible,
                confidence=confidence,
                reason=_truncate(out.reason or "", cfg.max_reason_chars),
```
**Why**: `check()` is the only scope holding both drop sources, so composing the
map here keeps it correct by construction instead of threading state through two
helpers. The `_fail()` path is deliberately untouched — a `skipped` report leaves
`not_examined` empty because its `status` already says nothing was examined.

### FILL IN checklist
- [ ] `_truncate` body — slice to `limit - 1` and append `…`; bounded by AC6 ("never exceeds the cap").
- [ ] `check()` path 1 — pass `not_examined=capped`; bounded by AC3.
- [ ] `check()` path 2 — `capped | {every target id: NOT_EXAMINED_UNRENDERABLE}`; bounded by AC4.
- [ ] `check()` path 3 — `capped | {targets − items: NOT_EXAMINED_UNRENDERABLE}`, disjoint from `verdicts`; bounded by AC5.
- [ ] `_answer_text` — apply `max_chars` to the final rendered string in all three branches, without turning a renderable answer into `None`; bounded by AC6.
- [ ] Test bodies for the eight cases in the Test Specification below.

---

## Acceptance Criteria

- [ ] `select_fields(form, SCALARS, LLMValidationConfig(enabled=True, max_fields=2))` returns 2 fields (required first) and a 2-entry `not_examined`, every value `"max_fields_cap"` (spec AC3).
- [ ] `eligible_fields(...)` still returns a bare `list[FormField]` with the same ids as before for the default config (spec AC8).
- [ ] `check()` over the default fixture returns `status="ok"` with `not_examined == {"doc": "unrenderable_answer"}` (spec AC4).
- [ ] A form whose only eligible answer is a dict returns `status="ok"`, `items == {}`, non-empty `not_examined`, and makes **no** LLM call (spec AC4).
- [ ] `set(report.items) & set(report.not_examined) == set()` on every path (spec AC5).
- [ ] `_truncate("x" * 2000, 50)` is 50 chars and ends with `…`; `_truncate("ab", 50) == "ab"` (spec AC6).
- [ ] `build_items(..., max_answer_chars=50)` caps the item answer; `max_answer_chars=None` leaves it verbatim (spec AC6/AC8).
- [ ] A 5000-char model `reason` with `max_reason_chars=20` is stored as 20 chars ending `…` (spec AC7).
- [ ] `_fail()`-path report (`None` client, `on_error="skip"`) has `not_examined == {}` (spec §3 M4 table).
- [ ] No linting errors: `ruff check packages/parrot-formdesigner/src/parrot_formdesigner/services/plausibility.py`
- [ ] AC11 — the `audio/engine.py` consumer gap is filed with
      `wikitoolkit ledger open --kind tech_debt --severity major --discovered-from spec:FEAT-737 --about sym:packages/parrot-formdesigner/src/parrot_formdesigner/audio/engine.py#VoiceFormEngine.on_plausibility_done --title ... --body ...`
      and its issue id recorded in the Completion Note below.
- [ ] All four Validation Commands pass.

---

## Validation Commands

- `pytest packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py -q`
- `pytest packages/parrot-formdesigner/tests/unit/test_plausibility_wire_report.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_ws_adapter.py -q`
- `pytest packages/parrot-formdesigner/tests/formdesigner/test_audio_engine_review_resume.py -q`

The last two are regression guards: they assert on the `plausibility_summary`
wire shape that `not_examined` widens.

---

## Test Specification

Extend the existing module — reuse `_make_form`, `SCALARS`, the `form` fixture,
`FakeClient` and `_batch`. Add `select_fields` and `_truncate` to the existing
`from parrot_formdesigner.services.plausibility import (...)` block.

```python
# packages/parrot-formdesigner/tests/formdesigner/test_plausibility_checker.py

class TestEligibility:  # extend the existing class
    def test_select_fields_reports_cap_drops(self):
        """The max_fields tail is returned as not_examined, not silently dropped."""
        cfg = LLMValidationConfig(enabled=True, max_fields=2)
        picked, not_examined = select_fields(_make_form(cfg), SCALARS, cfg)
        assert [f.field_id for f in picked][0] == "name" and len(picked) == 2
        assert set(not_examined) == {"nick0", "name", "color", "doc"} - {f.field_id for f in picked}
        assert set(not_examined.values()) == {"max_fields_cap"}

    def test_eligible_fields_signature_unchanged(self, form):
        """eligible_fields still returns a bare list — AC8."""
        got = eligible_fields(form, SCALARS, form.llm_validation)
        assert isinstance(got, list) and {f.field_id for f in got} == {"nick0", "name", "color", "doc"}


class TestLengthCaps:
    def test_truncate_marks_cut_and_respects_limit(self):
        """Over-limit text is cut TO the limit with a marker; short text is untouched."""
        # FILL IN: assert len == 50 and endswith("…") for 2000 chars at limit 50,
        # and that "ab" at limit 50 comes back unchanged — bounded by AC6.

    def test_build_items_caps_answer(self, form):
        """max_answer_chars bounds the rendered answer; None leaves it verbatim."""
        # FILL IN: use a scalars dict with a long "name" answer; compare the item's
        # "answer" under max_answer_chars=50 vs None — bounded by AC6/AC8.


class TestCoverageReporting:
    async def test_check_reports_unrenderable(self, form):
        """The dict-valued `doc` answer is reported, not silently omitted."""
        client = FakeClient(_batch({"field_id": "name", "plausible": True, "confidence": 0.9, "reason": "ok"}))
        rep = await AnswerPlausibilityChecker(client, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert rep.status == "ok"
        assert rep.not_examined == {"doc": "unrenderable_answer"}

    async def test_check_reports_cap_and_unrenderable_together(self):
        """Both reason codes can appear at once, and items stays disjoint."""
        # FILL IN: max_fields=2 over SCALARS; assert both codes present in
        # rep.not_examined and set(rep.items) & set(rep.not_examined) == set()
        # — bounded by AC5.

    async def test_check_all_unrenderable_is_not_silent(self):
        """An all-unrenderable batch is no longer indistinguishable from a clean pass."""
        # FILL IN: a form whose single eligible answer is a dict; assert
        # status == "ok", items == {}, not_examined non-empty, and client.calls == []
        # — bounded by AC4.

    async def test_check_truncates_reason(self, form):
        """A verbose model reason is capped before it is stored."""
        # FILL IN: cfg with max_reason_chars=20; FakeClient returning a 5000-char
        # reason; assert the stored reason is 20 chars ending "…" — bounded by AC7.

    async def test_fail_path_has_empty_not_examined(self, form):
        """A skipped report leaves not_examined empty — status already says it all."""
        rep = await AnswerPlausibilityChecker(None, config=form.llm_validation).check(form, SCALARS, locale="en")
        assert rep.status == "skipped" and rep.not_examined == {}
```

All 11 existing tests in this module must keep passing unchanged — in
particular `test_privacy_exclusions`, `test_required_first_and_max_fields`,
`test_only_subset` and `test_prompt_has_no_blob_or_data_url`, which call
`eligible_fields`/`build_items` with their current signatures.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug services-plausibility-tech-debt --feature-id FEAT-737`)
2. **Read the spec** at `sdd/specs/services-plausibility-tech-debt.spec.md` (§2, §3 Modules 2–4, §5, §7 Known Risks)
3. **Check dependencies** — `TASK-4676` must be `"done"` in
   `sdd/tasks/index/services-plausibility-tech-debt.json`. Its two config caps,
   the `not_examined` field and the two reason-code constants must all exist
   before this task compiles.
4. **Verify the Codebase Contract** — re-run every `grep -c` in the blueprint.
   A count that still matches but on a different line means the anchor moved:
   correct the `path:NN`. A count of `0` means drift — stop and report.
5. **Update status** in `sdd/tasks/index/services-plausibility-tech-debt.json` → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `FILL IN`
7. **Verify** all acceptance criteria — run the Validation Commands with
   `PYTHONPATH=packages/parrot-formdesigner/src` prefixed (the shared `.venv` is
   editable-installed against the MAIN checkout, so a bare `pytest` inside a
   worktree imports the wrong branch)
8. **File the AC11 ledger issue** for the `audio/engine.py` consumer gap before
   closing — the finding must not be silently dropped
9. **Commit the code** — stage only the two files this task lists
10. **Close the task** with `scripts/sdd/close_task.sh TASK-4677 services-plausibility-tech-debt verified`
11. **Fill in the Completion Note** below (including the AC11 issue id), then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**AC11 follow-up ledger issue**: `issue:<id>` — audio/engine.py ignores `not_examined`

**Deviations from spec**: none | describe if any
