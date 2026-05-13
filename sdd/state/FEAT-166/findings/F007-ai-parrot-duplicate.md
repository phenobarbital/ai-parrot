---
id: F007
title: Duplicate database_form.py inside ai-parrot — fallback shim
source_queries: [Q011]
---

A second `DatabaseFormTool` lives at
`packages/ai-parrot/src/parrot/forms/tools/database_form.py`.

Inspection shows it is **byte-equivalent to the parrot-formdesigner version**
(same `_FORM_QUERY`, same `_FIELD_TYPE_MAP`, same docstring). Only its
imports differ (`from ...tools.abstract import AbstractTool, ToolResult` and
`from ..registry import FormRegistry`, all relative within `parrot.forms`).

## Why it exists

`packages/ai-parrot/src/parrot/forms/__init__.py` is a re-export shim:

- Primary path: `try` block — `from parrot_formdesigner.* import …` for
  every symbol (lines ~14-70 of that file).
- Fallback path: `except ImportError:` — imports from the local
  `parrot.forms.*` submodules (lines ~70-105). This is the "stale copy"
  that still exists.

So the duplicate `database_form.py` only runs when `parrot-formdesigner`
is **not** installed. The test suite at `tests/forms/test_database_form.py`
imports via `from parrot.forms import …`, which goes through the shim and
ends up on the parrot-formdesigner implementation when it is installed
(the default for this repo, per `pyproject.toml`).

## Scope decision needed

Either:
- **(a) Mirror the refactor into the fallback copy** — keeps the fallback
  working but doubles the maintenance surface.
- **(b) Drop the fallback** — declare `parrot-formdesigner` a hard
  dependency of `parrot.forms` and delete the local fallback modules.
- **(c) Leave the fallback as a frozen legacy snapshot** — accept that
  `service=…` will not work when running without `parrot-formdesigner`.

The most surgical option for THIS feature is **(c)**: the fallback is
already a fully self-contained legacy snapshot; leaving it untouched
preserves the safety net without doubling the refactor.

Recommendation: out of scope here; flag for `/sdd-spec` discussion.
