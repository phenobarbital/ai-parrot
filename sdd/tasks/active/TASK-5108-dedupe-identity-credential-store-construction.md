# TASK-5108: Build IdentityVaultCredentialStore once per startup

**Feature**: FEAT-791 — BotManager fixes — Jira web-channel OAuth2 registration + BotManager test-API drift
**Spec**: `sdd/specs/manager-manager-fixes.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5105
**Assigned-to**: unassigned
**Discovered-from**: `issue:9405771f42ef`

---

## Context

Found while draining `fixgroup:6dc7f7828af6` under FEAT-791.
`test_register_oauth2_providers.py::test_register_oauth2_providers_from_descriptors`
is red on `dev` (verified on a clean `origin/dev` checkout at `da4c41e745`):

    AssertionError: Expected 'mock' to be called once. Called 2 times.
    Calls: [call(<object ...>), call(<object ...>)]

The failing assertion is `credential_store.assert_called_once_with(app["authdb"])`.
It is the **test being right about a real duplication**, not a stale expectation:
one `_register_oauth2_providers(app)` call constructs
`IdentityVaultCredentialStore(authdb)` twice with the same `authdb`:

1. `manager.py:3038` — the identity-binding block, as `identity_store`.
2. `manager.py:2906` — inside `_register_descriptor_oauth2_providers(app)`,
   which `_register_oauth2_providers` calls at `manager.py:3058`.

In a real server the second construction is usually skipped, because
`setup()` already calls `_register_descriptor_oauth2_providers` at
`manager.py:2406` and it sets the `app["_descriptor_oauth2_providers_registered"]`
guard; the on-startup call then early-returns. The test calls
`_register_oauth2_providers` directly, so the guard is unset and both
constructions run — which is exactly how it surfaced the duplication.

Building the same store twice is wasteful and makes the two code paths able to
drift apart (one could get a store the other does not). Building it once and
passing it down removes both problems and makes the test green.

---

## Scope

- Give `_register_descriptor_oauth2_providers` an optional keyword-only
  `credential_store` parameter; when it is not supplied, build one as today.
- Pass the already-built `identity_store` from `_register_oauth2_providers`.
- Update the instance stub in `test_oauth2_identity_store_binding.py:19`
  (`lambda app: None`) so it tolerates the new keyword argument.

**NOT in scope**: changing the `app["_descriptor_oauth2_providers_registered"]`
guard or the `setup()` call site at `manager.py:2406`; changing what
`register_descriptor_providers` does with the store; the Jira registrar from
TASK-5105; `IdentityVaultCredentialStore` itself.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Accept and pass a pre-built credential store |
| `packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py` | MODIFY | Stub tolerates the new keyword argument |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `3ea76c6e6c` (feature branch HEAD, 2026-11-03).

### Verified Imports
```python
from parrot.services.identity_credential_sink import IdentityVaultCredentialStore  # function-local in both methods today
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
def _register_descriptor_oauth2_providers(self, app: web.Application) -> None:   # line 2893
    # early-returns on: not OAUTH2_PROVIDERS_FILE or app.get("_descriptor_oauth2_providers_registered")
    # builds: credential_store = IdentityVaultCredentialStore(authdb) if authdb is not None else None   # line 2906
    # whole body wrapped in try/except Exception -> self.logger.exception(...)

async def _register_oauth2_providers(self, app: web.Application) -> None:        # line 3003 region
    # authdb = app.get("authdb")                                                  # line 3029
    # if authdb is not None:  -> identity_store = IdentityVaultCredentialStore(authdb)   # line 3038
    #    ... binds identity_store onto each candidate via candidate.bind_credential_store(...)
    # else: logs "app['authdb'] unavailable — Identity Vault not bound; ..."
    # self._register_descriptor_oauth2_providers(app)                             # line 3058 (LAST statement in the try)
```

Call sites of `_register_descriptor_oauth2_providers` (both must keep working):
- `manager.py:2406` — from `setup()`, positional, no store available yet → must keep its own construction path.
- `manager.py:3058` — from `_register_oauth2_providers`, where `identity_store` already exists.

### Does NOT Exist
- ~~`BotManager._build_identity_store`~~ — no such helper; do not invent one
- ~~a module-level / cached `IdentityVaultCredentialStore` singleton~~ — each call constructs a new one
- ~~`app["identity_credential_store"]`~~ — the store is not published on the app mapping

### Trap (verified, do not skip)
`packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py:19`
stubs the method on the instance as:

```python
bm._register_descriptor_oauth2_providers = lambda app: None
```

That lambda accepts exactly one positional argument, so calling the real method
with a second positional OR a keyword argument breaks this currently-green test.
The stub must become `lambda app, **kwargs: None` (or equivalent). This file is
in FEAT-791's validation contract — it must stay green.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/manager/manager.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._register_descriptor_oauth2_providers",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._register_oauth2_providers"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- The new parameter is **keyword-only with a default of `None`**, so the
  positional `setup()` call at `manager.py:2406` is untouched.
- `identity_store` is currently assigned only inside `if authdb is not None:`.
  Initialize it to `None` before that branch so the name always exists when it
  is passed at line 3058 — otherwise the `else` path raises `NameError`, which
  the surrounding `except Exception` would swallow into a logged failure and
  silently stop registering descriptor providers.
- Passing `None` must behave exactly as today: the method falls back to
  `IdentityVaultCredentialStore(authdb) if authdb is not None else None`.
  When `authdb` is None both paths yield `None`, so the behaviour is identical.
- Keep imports function-local, as both methods already do.

### References in Codebase
- `manager.py:2906` — the construction to make conditional
- `manager.py:3038` — the construction to reuse
- `packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py` — the red test

---

## Implementation Blueprint

### Steps (in order)
1. Add the keyword-only parameter to `_register_descriptor_oauth2_providers` and
   use it when supplied — *why*: this is what removes the second construction,
   and the default keeps the `setup()` call site working unchanged.
2. Hoist `identity_store = None` above `if authdb is not None:` in
   `_register_oauth2_providers`, and pass it at the call — *why*: the name must
   exist on the `authdb is None` path or the call raises `NameError`.
3. Fix the stub in `test_oauth2_identity_store_binding.py` — *why*: its
   one-argument lambda cannot accept the new keyword and would turn a green
   test red.
4. Run the Validation Commands — the previously red descriptor test must pass
   and the four sibling OAuth2 suites must stay green.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — signature + construction)
```python
# occurrences: 1 (verified: grep -c '    def _register_descriptor_oauth2_providers(self, app: web.Application) -> None:' packages/ai-parrot-server/src/parrot/manager/manager.py)
# REPLACE the signature line (verified: manager.py:2893)
    def _register_descriptor_oauth2_providers(
        self, app: web.Application, *, credential_store: Any = None
    ) -> None:
        """Register configured descriptor providers while the app is mutable.

        Args:
            app: The aiohttp application.
            credential_store: An Identity Vault store already built by the
                caller. When omitted, one is constructed here — the
                ``setup()`` call site has none to share.
        """

# occurrences: 1 (verified: grep -c 'credential_store = IdentityVaultCredentialStore(authdb) if authdb is not None else None' packages/ai-parrot-server/src/parrot/manager/manager.py)
# REPLACE (verified: manager.py:2906)
            if credential_store is None:
                credential_store = IdentityVaultCredentialStore(authdb) if authdb is not None else None
```
**Why this shape**: keyword-only keeps the positional `setup()` call at
`manager.py:2406` valid with no edit. The `if credential_store is None` guard
preserves today's behaviour exactly for that caller. Do not change the guard key
or the `try/except`.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — reuse the store)
```python
# occurrences: 1 (verified: grep -c '            authdb = app.get("authdb")' packages/ai-parrot-server/src/parrot/manager/manager.py)
# BEFORE — insert above `            authdb = app.get("authdb")` (verified: manager.py:3029)
            identity_store = None

# occurrences: 1 (verified: grep -c '            self._register_descriptor_oauth2_providers(app)' packages/ai-parrot-server/src/parrot/manager/manager.py)
# REPLACE (verified: manager.py:3058)
            self._register_descriptor_oauth2_providers(app, credential_store=identity_store)
```
**Why**: `identity_store` is assigned only inside `if authdb is not None:`; without
the hoist, the `else` path would raise `NameError` at the call and the
`except Exception` would swallow it, silently skipping descriptor registration.

### `packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    bm._register_descriptor_oauth2_providers = lambda app: None' packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py)
# REPLACE (verified: test_oauth2_identity_store_binding.py:19)
    bm._register_descriptor_oauth2_providers = lambda app, **kwargs: None
```
**Why**: the stub replaces the method on the instance, so it must accept the
keyword the real call site now passes. `**kwargs` keeps it indifferent to the
argument's name.

### FILL IN checklist
- [ ] none — every block above is complete; no judgement calls remain

---

## Acceptance Criteria

- [ ] AC-1: `IdentityVaultCredentialStore` is constructed at most once per
      `_register_oauth2_providers(app)` call.
- [ ] AC-2: `test_register_oauth2_providers_from_descriptors` passes.
- [ ] AC-3: `test_oauth2_identity_store_binding.py` stays green.
- [ ] AC-4: `test_register_oauth2_providers.py`, `test_jira_provider_registration.py`
      and `test_o365_provider_registration.py` are fully green.
- [ ] AC-5: The `setup()` call site at `manager.py:2406` is unchanged.
- [ ] AC-6: With `app["authdb"]` absent, `_register_oauth2_providers` still
      completes and still calls the descriptor registrar (no `NameError`).
- [ ] No linting errors: `ruff check` on the changed files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py -q`

---

## Test Specification

No new test file. The previously red
`test_register_oauth2_providers_from_descriptors` is the specification: its
`credential_store.assert_called_once_with(app["authdb"])` must pass without the
assertion being changed. Run with an absolute `PYTHONPATH` for both packages,
since the shared venv is editable-installed against the main checkout.

---

## Agent Instructions

1. **Work in the feature worktree** — `.claude/worktrees/feat-FEAT-791-manager-manager-fixes`,
   on branch `feat-FEAT-791-manager-manager-fixes` (PR #1931). Never on `dev`.
2. **Read the spec** at `sdd/specs/manager-manager-fixes.spec.md`
3. **Check dependencies** — TASK-5105 must be `done` (it is; it touches the same file)
4. **Verify the Codebase Contract** — re-run each `grep -c` before editing
5. **Update status** in `sdd/tasks/index/manager-manager-fixes.json` → `"in-progress"`
6. **Implement** from the Implementation Blueprint
7. **Verify** — run the Validation Commands
8. **Commit the code** — stage only this task's two files
9. **Close** with `parrot sdd task close TASK-5108 manager-manager-fixes verified`
10. **Fill in the Completion Note**, then commit the SDD state and push to the PR branch

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
