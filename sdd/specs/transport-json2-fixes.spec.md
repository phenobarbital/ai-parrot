---
type: feature
base_branch: dev
feature_id: FEAT-664
tags: [bugfix, odoo, transport]
---

# FEAT-664 — JSON-2 Transport Fixes

**Ledger issues**: `issue:e17074affa1b`, `issue:f5ae793643be`

## Problem

The JSON-2 transport (`parrot_tools/odoo/transport/json2.py`) has two bugs
in `_build_body`:

1. **create fallback too narrow** (major): `_is_create_signature_error`
   checks only for `".create:"` + `"missing a required argument"` /
   `"unexpected keyword argument"`. Odoo 19 models with a `create` override
   can reject `vals_list` with different error text (e.g. `"got an
   unexpected keyword argument 'vals_list'"`). The `web_save` fallback
   never fires.

2. **get_views unmapped** (minor): `get_views` takes `(views, options)`
   where `views` is a list of `(view_id, view_type)` tuples — not record
   ids. The generic fallback at the end of `_build_body` hits `OdooRPCError`
   because `_looks_like_ids` returns `False`.

## Solution

### M1 — Widen create fallback detection

Relax `_is_create_signature_error` to also match `"unexpected keyword
argument"` without requiring `".create:"` prefix, or detect any 4xx/5xx
from a `create` call and retry via `web_save`. The safer option: keep
the text-match guard but add the `"vals_list"` keyword as an alternative
trigger (so `"unexpected keyword argument 'vals_list'"` is caught).

### M2 — Add get_views mapping

Add an explicit `get_views` branch in `_build_body` that maps `args[0]` →
`views` and `args[1]` (if present) → `options`.

## Files

- `packages/ai-parrot-tools/src/parrot_tools/odoo/transport/json2.py`

## Acceptance Criteria

- AC1: `_build_body("create", [{"name": "test"}], None)` returns `{"vals_list": {"name": "test"}}`.
- AC2: `_is_create_signature_error` returns `True` for `"got an unexpected keyword argument 'vals_list'"`.
- AC3: `_build_body("get_views", [[(False, "form")], {}], None)` returns `{"views": [...], "options": {}}`.
- AC4: Existing tests pass; new unit tests for the two fixes.
