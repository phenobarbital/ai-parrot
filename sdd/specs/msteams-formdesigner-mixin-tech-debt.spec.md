---
type: feature
base_branch: dev
projects: [ai-parrot-integrations, parrot-formdesigner]
tags: [msteams, formdesigner, wizard, hardening, sdd-fix]
---

# Feature Specification: MS Teams FormDesigner mixin — wizard fall-through fix + hardening

**Feature ID**: FEAT-745
**Date**: 2026-10-25
**Author**: agent:sdd-fix
**Status**: approved
**Target version**: n/a — internal fix, no version bump

---

## 1. Motivation & Business Requirements

### Problem Statement

Four open `wikitoolkit` ledger issues against the FEAT-734 Teams
FormDesigner mixin and its FEAT-733 config surface:

1. **`issue:6dc190ef283d` (bug, major)** — `TeamsFormDesignerMixin.
   handle_formdesigner_card` (`formdesigner_mixin.py:345-370`) returns
   `False` when `PICKER_ACTION_KEY` carries an unrecognized control value
   (not `PICKER_GET_FORM`, not a `{"kind": "wizard"}` dict). The wrapper
   (`wrapper.py:584-592`) then falls through to the FEAT-551 standalone
   branch, which submits with the bot's **service token** and leaves the
   control key in the extracted answers. Spec FEAT-734 requires: every
   submission that carries a FormDesigner control key is answered by the
   mixin (`return True`) and never substitutes the service token. The
   envelope-without-control case when the mixin is not enabled
   (`formdesigner_mixin.py:359-360`) is a *deliberate* fallback to the
   FEAT-551 lane and must be documented as such, not changed.
2. **`issue:ec85bd42970e` (tech_debt, minor)** — `MSTeamsAgentConfig`
   (`models.py`): an invalid `<NAME>_FORMDESIGNER_TENANT_MAP` env JSON is
   warned about and silently ignored (fail-open: the operator configured
   tenant mapping and it silently does not apply), and a
   `formdesigner_tenant_map` passed directly or via `from_dict` is never
   validated at all.
3. **`issue:cc81b5eee807` (tech_debt, minor)** — hardening items from the
   FEAT-734 review (sub-items (a)–(f); (a)'s next-step *form re-fetch*
   comparison already shipped — the remaining gap is the rendered
   metadata check):
   - (a) neither `serve_form` nor `_fd_wizard_action` compares
     `rendered.metadata["form_version"]` with `state.form_version`;
   - (b) `serve_form` calls `self._fd_wizards.start(...)` before the
     section render — a failed render strands orphan wizard state until
     TTL;
   - (c) `serve_form` / `handle_listforms` catch only `FormDesignerError`;
     local-mode `LocalFormReader` registry exceptions propagate into the
     Teams handler despite `serve_form`'s "without raising into Teams"
     contract;
   - (d) `_fd_identity` logs the resolved tenant at INFO on every turn
     (`formdesigner_mixin.py:167`);
   - (e) `render.py:216` parses `section_index` with bare `int()`, which
     accepts `" 1"`, `"+1"` and non-ASCII digits;
   - (f) `build_empty_forms_card(*, tenant, locale)` never uses `tenant`;
     `build_error_card(message, *, locale)` never uses `locale`.
4. **`issue:337359a3ec81` (tech_debt, low)** — leftover exploratory
   comment block in `RecentActivityCache.seen()`
   (`formdesigner_submit.py:261-263`): "Update timestamp to keep it fresh
   or just return True? … Let's just return True."

### Goals
- No FormDesigner control submission ever reaches the FEAT-551
  service-token lane (`issue:6dc190ef283d`).
- `formdesigner_tenant_map` is validated fail-closed on every construction
  path (`issue:ec85bd42970e`).
- Close hardening items (a)–(f) (`issue:cc81b5eee807`).
- Drop the exploratory comment (`issue:337359a3ec81`).

### Non-Goals (explicitly out of scope)
- Any change to envelope verification, `verify_envelope`,
  `resolve_submit_tenant` or the FEAT-733 fail-closed model.
- Any change to the FEAT-551 `_handle_formdesigner_submit` wrapper branch
  itself.
- New wizard features or card layout changes.

---

## 2. Architectural Design

No new components; surgical edits to five existing files.

### M1 — wizard-control fall-through guard (`issue:6dc190ef283d`)
In `handle_formdesigner_card`, after the `PICKER_GET_FORM` and wizard-dict
branches, add a terminal guard: when `control is not None` (any
unrecognized `PICKER_ACTION_KEY` value — wrong string, dict with a
different `kind`, anything else), send
`build_error_card("This form action is not valid.")` and `return True`.
Document in the method docstring that an envelope **without** a control
key on a not-enabled mixin intentionally returns `False` so the wrapper's
FEAT-551 standalone branch (service token) handles it. Behavior table
after the fix:

| submitted_data | result |
|---|---|
| `PICKER_GET_FORM` control | serve/picker (unchanged) |
| wizard-dict control | `_fd_wizard_action` (unchanged) |
| any other non-None control | error card, `return True` (**new**) |
| envelope only, mixin enabled | `_fd_submit` lane (unchanged) |
| envelope only, mixin NOT enabled | `return False` → FEAT-551 lane (unchanged, now documented) |
| no control, no envelope | `return False` (unchanged — wrapper only calls with one of the keys present) |

### M2 — tenant-map validation (`issue:ec85bd42970e`)
Add a module-level helper in `models.py`:
`_validated_tenant_map(value: Any, *, source: str) -> Optional[Dict[str, str]]`
that returns `None` for `None`/empty, returns the dict when it is a
`dict` with non-empty `str` keys and values, and raises
`ValueError(f"formdesigner_tenant_map from {source} must be a JSON object of
non-empty strings")` otherwise. Call it:
- in `__post_init__` on a directly-passed `self.formdesigner_tenant_map`;
- on the env-var path, replacing the warn-and-ignore `except` block —
  invalid JSON or shape now **raises** at startup (fail-closed: a
  configured-but-broken tenant map must not silently change tenant
  resolution);
- in `from_dict` the field flows through `__post_init__` (dataclass), so no
  separate call is needed there — verify with a test.

### M3 — mixin hardening (`issue:cc81b5eee807` a–d, f)
- (a) In `serve_form` (multi-section branch) and `_fd_wizard_action`
  (post-`advance` render): when `rendered.metadata.get("form_version")` is
  present and differs from `state.form_version`, discard the wizard state
  and send `build_error_card("This form changed. Send /getform to start
  again.")` (same copy as the existing re-fetch check). Absent metadata
  (local mode) keeps today's behavior.
- (b) In `serve_form`, wrap the post-`start` render path so any failure
  discards the just-created wizard state
  (`self._fd_wizards.discard(conversation_id=..., form_uid=...)`) before
  the error card goes out. Implementation shape: keep `start` where it is,
  add the discard to the `except FormDesignerError` handler (and the new
  broad handler from (c)) when a state was created in this call.
- (c) In `serve_form` and `handle_listforms`, add a trailing
  `except Exception:` (with `# noqa: BLE001` and
  `self._fd_logger.exception(...)`) that sends
  `build_error_card("Forms are unavailable.")` — honoring `serve_form`'s
  documented "without raising into Teams" contract for local-mode registry
  exceptions. `_fd_send_turn_problem`/identity failures stay outside this
  guard (already handled by `formdesigner_turn`).
- (d) `formdesigner_mixin.py:167` → `self._fd_logger.debug(...)`.
- (f) Remove the unused `tenant` parameter from `build_empty_forms_card`
  and the unused `locale` parameter from `build_error_card`
  (`formdesigner_cards.py:100,110`); update every call site (grep:
  `formdesigner_mixin.py`, `dialogs/orchestrator.py`, tests).

### M4 — strict section_index parsing (`issue:cc81b5eee807` e)
`render.py` `handle_render`: replace the bare `int(raw_section)` with an
ASCII-decimal guard — `raw_section.isascii() and raw_section.isdecimal()`
must hold before `int()`; otherwise the existing
`"section_index must be an integer"` 400 response. The subsequent range
check is unchanged.

### M5 — comment cleanup (`issue:337359a3ec81`)
Delete the three exploratory comment lines in `RecentActivityCache.seen()`
(`formdesigner_submit.py:261-263`); keep the code and the spec-S9 docstring.

---

## 3. Module Breakdown

| Module | File(s) | Issue |
|---|---|---|
| M1 | `msteams/formdesigner_mixin.py` | `issue:6dc190ef283d` |
| M2 | `msteams/models.py` | `issue:ec85bd42970e` |
| M3 | `msteams/formdesigner_mixin.py`, `msteams/formdesigner_cards.py`, `msteams/dialogs/orchestrator.py` | `issue:cc81b5eee807` |
| M4 | `parrot_formdesigner/api/render.py` | `issue:cc81b5eee807` (e) |
| M5 | `msteams/formdesigner_submit.py` | `issue:337359a3ec81` |

Paths relative to `packages/ai-parrot-integrations/src/parrot/integrations/`
and `packages/parrot-formdesigner/src/`.

---

## 4. Acceptance Criteria

- [ ] An unrecognized `PICKER_ACTION_KEY` value (string or dict) makes
      `handle_formdesigner_card` return `True` and send an error card; a
      submission with both an unknown control and an envelope never reaches
      `_handle_formdesigner_submit` (test via the mixin unit tests).
- [ ] Envelope-only submission with the mixin not enabled still returns
      `False` (regression guard for the documented FEAT-551 fallback).
- [ ] `MSTeamsAgentConfig(formdesigner_tenant_map={"g": 1})` and an invalid
      `<NAME>_FORMDESIGNER_TENANT_MAP` env JSON both raise `ValueError`;
      a valid map still round-trips via `from_dict`.
- [ ] `serve_form` render failure after wizard `start` leaves no state in
      `self._fd_wizards`; a rendered `form_version` mismatch discards state
      and sends the "form changed" card.
- [ ] Local-mode reader exceptions in `serve_form`/`handle_listforms`
      produce an error card, not a raised exception.
- [ ] `render.py` rejects `" 1"`, `"+1"`, `"١"` for `section_index` with
      the existing 400; `"1"` still works.
- [ ] `_fd_identity` tenant log line is DEBUG; exploratory comment gone;
      card builders have no unused parameters; all call sites updated.
- [ ] `ruff check` clean on every changed file; affected test modules green
      (`tests/msteams/`, `parrot-formdesigner` render tests).

---

## 5. Codebase Contract

**Verified Imports / Symbols** (verified 2026-10-25 on dev):
- `TeamsFormDesignerMixin.handle_formdesigner_card` — `formdesigner_mixin.py:345`
- `TeamsFormDesignerMixin.serve_form` — `formdesigner_mixin.py:234`; wizard
  `start` at `:260`, `except FormDesignerError` at `:280`
- `TeamsFormDesignerMixin._fd_wizard_action` — `formdesigner_mixin.py:448`;
  re-fetch version check already present at `:489-495`
- tenant INFO log — `formdesigner_mixin.py:167`
- `build_empty_forms_card` / `build_error_card` — `formdesigner_cards.py:100,110`
- `PICKER_ACTION_KEY = "_formdesigner_action"`, `PICKER_GET_FORM = "get_form"`
  — `formdesigner_cards.py:12-13`
- `MSTeamsAgentConfig` dataclass with `__post_init__` env fallbacks and
  tenant-map env parsing — `models.py:84,152-167`; `from_dict` at `:253-257`
- `RecentActivityCache.seen` — `formdesigner_submit.py:249`; comments at `:261-263`
- `handle_render` `int(raw_section)` — `parrot_formdesigner/api/render.py:215-217`
- wrapper dispatch — `msteams/wrapper.py:583-592`

**Does NOT exist** (do not invent):
- No `form_version` key guarantee in local-mode render metadata — the M3(a)
  check must tolerate its absence.
- No i18n use inside `build_error_card` (`_t` is not called there).

---

## 6. Ledger Linkage

| Issue | Module(s) | Closes via |
|---|---|---|
| `issue:6dc190ef283d` | M1 | TASK (Discovered-from) |
| `issue:ec85bd42970e` | M2 | TASK (Discovered-from) |
| `issue:cc81b5eee807` | M3 + M4 | TASK (Discovered-from) |
| `issue:337359a3ec81` | M5 | TASK (Discovered-from) |

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-10-25 | agent:sdd-fix | Initial spec from ledger fixgroup:69e76db2d3c1 (4 of 7 issues; 3 were already resolved by FEAT-733 and closed with evidence) |
