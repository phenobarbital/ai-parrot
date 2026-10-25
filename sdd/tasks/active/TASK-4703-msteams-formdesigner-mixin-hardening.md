# TASK-4703: MS Teams FormDesigner mixin hardening — wizard fall-through, tenant-map validation, cleanup

**Feature**: FEAT-745 — MS Teams FormDesigner mixin — wizard fall-through fix + hardening
**Spec**: `sdd/specs/msteams-formdesigner-mixin-tech-debt.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:6dc190ef283d`
**Discovered-from**: `issue:ec85bd42970e`
**Discovered-from**: `issue:cc81b5eee807`
**Discovered-from**: `issue:337359a3ec81`

---

## Context

Implements spec modules M1, M2, M3 and M5 (everything inside
`packages/ai-parrot-integrations`). Four ledger issues from the FEAT-733/734
reviews: the major wizard-control fall-through to the FEAT-551 service-token
lane, fail-open tenant-map validation, assorted hardening items (a)–(d) and
(f), and a leftover exploratory comment.

---

## Scope

- **M1** — in `TeamsFormDesignerMixin.handle_formdesigner_card`, add a
  terminal guard: any non-`None` `PICKER_ACTION_KEY` control that is neither
  `PICKER_GET_FORM` nor a `{"kind": "wizard"}` dict sends
  `build_error_card("This form action is not valid.")` and returns `True`.
  Extend the docstring to document that an envelope-only submission on a
  not-enabled mixin deliberately returns `False` (FEAT-551 service-token
  fallback).
- **M2** — add `_validated_tenant_map(value, *, source)` to `models.py`
  (None/empty → None; dict of non-empty str→str → dict; anything else →
  `ValueError`). Use it in `__post_init__` for the directly-passed field and
  on the env path, replacing the warn-and-ignore `except` (invalid env JSON
  now raises — fail-closed).
- **M3(a)** — in `serve_form` (multi-section) and `_fd_wizard_action`
  (post-advance render): if `rendered.metadata.get("form_version")` is
  present and `!= state.form_version`, discard state and send the existing
  "This form changed. Send /getform to start again." card. Tolerate absent
  metadata (local mode).
- **M3(b)** — a `serve_form` failure after `self._fd_wizards.start(...)`
  must discard the just-created state before the error card goes out.
- **M3(c)** — add trailing `except Exception:  # noqa: BLE001` guards to
  `serve_form` and `handle_listforms` (log with
  `self._fd_logger.exception`, send `build_error_card("Forms are
  unavailable.")`).
- **M3(d)** — downgrade the per-turn tenant log (`formdesigner_mixin.py:167`)
  from INFO to DEBUG.
- **M3(f)** — drop the unused `tenant` param from `build_empty_forms_card`
  and the unused `locale` param from `build_error_card`; update all call
  sites (mixin, `dialogs/orchestrator.py`, tests).
- **M5** — delete the exploratory comment lines in
  `RecentActivityCache.seen()` (`formdesigner_submit.py:261-263`).
- Tests for the new behaviors (see Test Specification).

**NOT in scope**: `render.py` section_index parsing (TASK-4704); any change
to `verify_envelope`, `resolve_submit_tenant`, or the FEAT-551 wrapper
branch.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_mixin.py` | MODIFY | M1, M3(a)(b)(c)(d), call-site updates for M3(f) |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/models.py` | MODIFY | M2 tenant-map validation |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_cards.py` | MODIFY | M3(f) signature cleanup |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/dialogs/orchestrator.py` | MODIFY | M3(f) call-site update (if it passes removed kwargs) |
| `packages/ai-parrot-integrations/src/parrot/integrations/msteams/formdesigner_submit.py` | MODIFY | M5 comment removal |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_mixin_roundtrip.py` | MODIFY | M1/M3 tests |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_cards.py` | MODIFY | M3(f) signature updates |
| `packages/ai-parrot-integrations/tests/msteams/test_formdesigner_serve.py` | MODIFY | M3(a)(b)(c) serve tests |

(Test placement may follow the existing module that already covers the
touched function; do not create new test files if an existing one fits.)

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports / Symbols (dev, 2026-10-25)
- `handle_formdesigner_card` — `formdesigner_mixin.py:345`; wizard branch
  `:355-357`; envelope branch `:358-369`; `return False` at `:370`.
- `serve_form` — `formdesigner_mixin.py:234`; `self._fd_wizards.start` at
  `:260`; `except FormDesignerError` at `:280`.
- `_fd_wizard_action` — `formdesigner_mixin.py:448`; re-fetch version check
  already exists at `:489-495` (keep it); post-advance render `:505-513`.
- tenant INFO log — `formdesigner_mixin.py:167` (inside `_fd_identity`).
- `PICKER_ACTION_KEY`/`PICKER_GET_FORM` — `formdesigner_cards.py:12-13`.
- `build_empty_forms_card(*, tenant, locale="en")` — `formdesigner_cards.py:100`
  (`tenant` unused); `build_error_card(message, *, locale="en")` — `:110`
  (`locale` unused).
- `MSTeamsAgentConfig` dataclass — `models.py`; field at `:84`; env tenant-map
  parse (warn-and-ignore) at `:152-167`; `from_dict` at `:253-257`
  (dataclass ⇒ `__post_init__` runs on every construction path).
- `RecentActivityCache.seen` — `formdesigner_submit.py:249`; exploratory
  comments `:261-263`.
- `self._fd_wizards.discard(conversation_id=..., form_uid=...)` — used at
  `formdesigner_mixin.py:485,491` (existing call shape).

### Does NOT Exist
- No guaranteed `form_version` key in local-mode render metadata — M3(a)
  must tolerate absence.
- No `_t()` call inside `build_error_card` — removing `locale` breaks no i18n.

---

## Acceptance Criteria

- Unknown control (string and dict cases) → error card + `return True`;
  unknown control WITH envelope never calls `_fd_submit`/FEAT-551 lane.
- Envelope-only + mixin not enabled → `return False` (regression).
- `MSTeamsAgentConfig(formdesigner_tenant_map={"g": 1})` raises `ValueError`;
  invalid `<NAME>_FORMDESIGNER_TENANT_MAP` env JSON raises; valid map
  round-trips through `from_dict`.
- Failed render after wizard start leaves no wizard state; rendered
  `form_version` mismatch discards state + "form changed" card.
- Non-`FormDesignerError` reader exception → error card, no raise.
- Tenant log at DEBUG; comments removed; card-builder signatures clean and
  all call sites updated.
- `ruff check` clean on changed files.

## Validation Commands

```bash
PYTHONPATH=packages/ai-parrot-integrations/src:packages/ai-parrot/src:packages/parrot-formdesigner/src \
  pytest packages/ai-parrot-integrations/tests/msteams/ -q
ruff check packages/ai-parrot-integrations/src/parrot/integrations/msteams/
```

## Test Specification

- `handle_formdesigner_card` with `{"_formdesigner_action": "bogus"}` and
  with `{"_formdesigner_action": {"kind": "other"}}` → returns True, error
  card sent (assert via the fake turn-context used by existing mixin tests).
- Same with an `_formdesigner` envelope also present → `_fd_submit` not
  called.
- Mixin not enabled + envelope only → returns False.
- `MSTeamsAgentConfig` tenant-map validation: direct, from_dict, env-var
  (monkeypatched `config.get`), valid and invalid shapes.
- `serve_form` with a reader whose `render_teams` raises
  `FormDesignerError` → `_fd_wizards.get(...)` is None afterwards.
- `serve_form`/`handle_listforms` with a reader raising `RuntimeError` →
  error card, no exception.

## Agent Instructions

Implement exactly this scope. Keep existing behavior for recognized
controls. Never touch `verify_envelope` or wrapper.py.

## Completion Note

(filled on close)
