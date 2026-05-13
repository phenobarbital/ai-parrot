---
id: F004
title: FormRegistry.register — boundary between service and tool
source_queries: [Q004]
---

`packages/parrot-formdesigner/src/parrot_formdesigner/services/registry.py`

`FormRegistry.register(form, *, persist=False, overwrite=True)` (lines 146-189):
- Stores `form` in an `asyncio.Lock`-guarded dict.
- If `persist=True` and a `FormStorage` backend is configured, calls
  `await self._storage.save(form, tenant=form.tenant)`.
- Fires async `on_register` callbacks.

Design implication: the registry is an injection-time dependency of the
**tool**, not the service. Keeping it that way (a) preserves the existing
contract for `api/handlers.py` and the test suite, (b) keeps services pure
(in → FormSchema), and (c) lets services be reused by callers that don't
want registry side-effects (e.g. ad-hoc preview / dry-run).

## Name collision warning

A `services/` package **already exists at the package level**:
`parrot_formdesigner/services/` (contains `registry.py`, `storage.py`,
`cache.py`, `validators.py`, `forwarder.py`, `submissions.py`).

The new package proposed by the user is **nested under `tools/`**:
`parrot_formdesigner/tools/services/`. This is a different Python package
(`parrot_formdesigner.tools.services`) — no import collision, but readers
must mentally distinguish the two. Documenting this clearly in the
sub-package `__init__.py` is recommended.
