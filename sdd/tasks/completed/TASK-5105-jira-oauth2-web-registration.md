# TASK-5105: Auto-register the Jira OAuth2 provider for the web channel

**Feature**: FEAT-791 — BotManager fixes — Jira web-channel OAuth2 registration + BotManager test-API drift
**Spec**: `sdd/specs/manager-manager-fixes.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned
**Discovered-from**: `issue:9b625450ce4a`

---

## Context

Implements spec §3 Modules 1 and 2 (Lane A). `BotManager` auto-builds and
registers the O365 OAuth2 provider from `parrot.conf`
(`_register_o365_oauth2_provider`, `manager.py:2917`) but has no Jira
equivalent. `_register_oauth2_providers` (`manager.py:2950`) registers
`JiraOAuth2Provider` only when `app["jira_oauth_manager"]` already exists —
which happens only on the Slack / MS Teams path (`parrot/integrations/manager.py`,
from per-bot `{BOTNAME}_JIRA_*` keys) or in the repo-root `app.py` that ships in
no distribution. `parrot/conf.py:744-746` defines `JIRA_CLIENT_ID`,
`JIRA_CLIENT_SECRET` and `JIRA_REDIRECT_URI`, but no server code reads them.

Result: FEAT-777's web Connections panel lists providers from
`OAuth2ProviderRegistry`, so a plain web deployment shows only Office 365, and
every external project must hand-wire `JiraOAuthManager(...).setup()` after
`BotManager.setup()`.

---

## Scope

- Add `BotManager._register_jira_oauth2_provider(self, app)` mirroring
  `_register_o365_oauth2_provider`.
- Call it from `BotManager.setup()` beside the existing O365 call, while the
  app is still mutable.
- Create `packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py`
  covering the configured / unconfigured / reuse / idempotent branches.
- Add the three Jira env keys to `docs/auth/connections.md` § "Adding a provider".

**NOT in scope**: any change to `jira_oauth.py`, `jira_provider.py`,
`descriptor.py` or `conf.py`; changing the `OAUTH2_PROVIDERS_FILE` descriptor
route's semantics; making `provider_id: jira` resolve to a built-in subclass
(explicitly rejected in spec §7); anything in Lane B (TASK-5106, TASK-5107).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Add `_register_jira_oauth2_provider` + its call site |
| `packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py` | CREATE | Unit tests for the four branches |
| `docs/auth/connections.md` | MODIFY | Document `JIRA_CLIENT_ID` / `JIRA_CLIENT_SECRET` / `JIRA_REDIRECT_URI` |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `2ac26be889` (dev, 2026-11-03).

### Verified Imports
```python
from parrot.auth.jira_oauth import JiraOAuthManager               # verified: packages/ai-parrot/src/parrot/auth/jira_oauth.py:226
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider   # verified: packages/ai-parrot/src/parrot/auth/oauth2/jira_provider.py:22
from parrot.auth.oauth2.registry import register_oauth2_provider, OAuth2ProviderRegistry
from parrot.services.identity_credential_sink import IdentityVaultCredentialStore
from parrot.conf import JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, JIRA_REDIRECT_URI  # verified: packages/ai-parrot/src/parrot/conf.py:744-746
from parrot.manager.manager import BotManager
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
class JiraOAuthManager(StandardOAuth2Manager):          # line 226
    token_set_cls = JiraTokenSet
    def __init__(                                       # line 231
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        app: Any = None,
        redis_url: Optional[str] = None,
        redis_client: Any = None,
        scopes: Optional[List[str]] = None,
        http_session: Optional[aiohttp.ClientSession] = None,
        credential_store: Optional[CredentialStore] = None,
        event_publisher: Any = None,
        callback_path: str = "/api/auth/jira/callback",
    ) -> None: ...
    def setup(self) -> None:                            # line 261
        # sets app["jira_oauth_manager"] AND app["oauth2_manager_jira"];
        # raises RuntimeError when either key already holds a DIFFERENT instance;
        # raises RuntimeError when self._app is None;
        # appends _on_startup/_on_cleanup and calls setup_jira_oauth_routes(app)

# packages/ai-parrot/src/parrot/auth/oauth2/jira_provider.py
class JiraOAuth2Provider(OAuth2Provider):               # line 22
    provider_id: str = "jira"
    display_name: str = "Jira"
    def __init__(self, manager: "JiraOAuthManager") -> None:   # line 52

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    def _register_descriptor_oauth2_providers(self, app: web.Application) -> None:  # line 2892
    def _register_o365_oauth2_provider(self, app: web.Application) -> None:         # line 2917
    async def _register_oauth2_providers(self, app: web.Application) -> None:       # line 2950
```

The O365 method (line 2917) is the pattern to copy. Its shape:
early-return on `not O365_CLIENT_ID or app.get("_o365_oauth2_provider_registered")`;
function-local imports; reuse `app.get(f"oauth2_manager_{O365OAuthManager.provider_id}")`
when present else construct + `.setup()`; `register_oauth2_provider(...)`; set the
guard key; `self.logger.info(...)`; whole body wrapped in
`try/except Exception: self.logger.exception(...)`.

### Does NOT Exist
- ~~`BotManager._register_jira_oauth2_provider`~~ — this task creates it
- ~~`app["_jira_oauth2_provider_registered"]`~~ — this task introduces the key
- ~~`parrot.conf.JIRA_SCOPES`~~ — not defined; only the three keys at `conf.py:744-746`
- ~~`parrot.conf.JIRA_TENANT_ID`~~ — not defined (that is an O365-only concept)
- ~~`JiraOAuthManager.provider_id`~~ — do NOT assume it is a class attribute; use the
  literal key `"oauth2_manager_jira"` / `"jira_oauth_manager"` that `setup()` sets (line 261)
- ~~`packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py`~~ — new file

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
      "path": "packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py",
      "action": "CREATE"
    },
    {
      "path": "docs/auth/connections.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._register_o365_oauth2_provider",
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._register_oauth2_providers",
    "sym:packages/ai-parrot/src/parrot/auth/jira_oauth.py#JiraOAuthManager",
    "sym:packages/ai-parrot/src/parrot/auth/oauth2/jira_provider.py#JiraOAuth2Provider"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Imports stay **function-local**, exactly as `_register_o365_oauth2_provider` does —
  `manager.py` must not grow a module-level dependency on `parrot.auth.jira_oauth`.
- Never raise: a misconfigured Jira must not prevent server startup. Wrap the whole
  body in `try/except Exception` + `self.logger.exception(...)`.
- `JiraOAuthManager.setup()` raises `RuntimeError` when `app["jira_oauth_manager"]`
  already holds a **different** instance — so the reuse branch must inspect that key
  **before** constructing, never after.
- Read the conf values through the module (`from parrot.conf import ...` inside the
  function) so `monkeypatch.setattr("parrot.conf.JIRA_CLIENT_ID", ...)` works in tests,
  matching how `test_o365_provider_registration.py` patches O365.
- `_register_oauth2_providers` must stay a safe no-op once this task has already
  registered: it checks `app.get("jira_oauth_manager")` and would otherwise register a
  second `JiraOAuth2Provider`. Verify the registry's behaviour and keep the result to
  exactly one `provider_id == "jira"` entry.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/manager/manager.py:2917` — the O365 method to mirror
- `packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py` — the test file to mirror
- `packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py` — startup-path tests

---

## Implementation Blueprint

### Steps (in order)
1. Add `_register_jira_oauth2_provider` immediately **above** `_register_o365_oauth2_provider`
   in `manager.py` — *why*: keeps the two sibling registrars adjacent and makes the
   O365 anchor the single, unambiguous attachment point.
2. Add the call in `setup()` directly after the existing O365 call — *why*: the app
   must still be mutable, and `JiraOAuthManager.setup()` appends `on_startup` /
   `on_cleanup` handlers and mounts routes, all of which require a mutable app.
3. Write the four unit tests — *why*: AC-1..AC-4 each name a distinct branch, and the
   reuse branch is the one that would otherwise raise `RuntimeError` in production.
4. Add the Jira row to `docs/auth/connections.md` — *why*: the env keys were previously
   dead config, so an operator has no way to discover them.
5. Run the Validation Commands and `ruff check --fix` on the changed files.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — new method)
```python
# occurrences: 1 (verified: grep -c '    def _register_o365_oauth2_provider(self, app: web.Application) -> None:' packages/ai-parrot-server/src/parrot/manager/manager.py)
# BEFORE — insert above `    def _register_o365_oauth2_provider(self, app: web.Application) -> None:` (verified: packages/ai-parrot-server/src/parrot/manager/manager.py:2917)
    def _register_jira_oauth2_provider(self, app: web.Application) -> None:
        """Wire the shared Jira manager and provider while the app is mutable.

        Mirrors :meth:`_register_o365_oauth2_provider`.  No-op when
        ``JIRA_CLIENT_ID`` is unset or the provider was already registered.
        Never raises: a misconfigured Jira must not block server startup.
        """
        from parrot.conf import JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, JIRA_REDIRECT_URI

        if not JIRA_CLIENT_ID or app.get("_jira_oauth2_provider_registered"):
            return

        try:
            from parrot.auth.jira_oauth import JiraOAuthManager
            from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
            from parrot.auth.oauth2.registry import register_oauth2_provider
            from parrot.services.identity_credential_sink import IdentityVaultCredentialStore

            # Inspect BOTH keys before constructing: JiraOAuthManager.setup()
            # raises RuntimeError if either already holds a different instance.
            manager = app.get("jira_oauth_manager") or app.get("oauth2_manager_jira")
            if manager is None:
                authdb = app.get("authdb")
                manager = JiraOAuthManager(
                    JIRA_CLIENT_ID,
                    JIRA_CLIENT_SECRET,
                    JIRA_REDIRECT_URI,
                    app=app,
                    credential_store=IdentityVaultCredentialStore(authdb) if authdb is not None else None,
                    event_publisher=app.get("connection_event_publisher"),
                )
                manager.setup()

            register_oauth2_provider(JiraOAuth2Provider(manager=manager))
            app["_jira_oauth2_provider_registered"] = True
            self.logger.info("Registered JiraOAuth2Provider with the global OAuth2ProviderRegistry")
        except Exception:  # noqa: BLE001
            self.logger.exception("Failed to register the Jira OAuth2 provider")
```
**Why this shape**: it is the O365 registrar with the Jira triple substituted, so the
two stay reviewable side by side. The `or` on the two app keys is deliberate — `setup()`
sets both and raises if either disagrees, so reading both before constructing is what
makes the Slack/Teams reuse path safe. The guard key and the `except Exception` are what
AC-3 and AC-4 test. Do not change the method name, the guard key, or the import locality.

### `packages/ai-parrot-server/src/parrot/manager/manager.py` (MODIFY — call site)
```python
# occurrences: 1 (verified: grep -c '        self._register_o365_oauth2_provider(self.app)' packages/ai-parrot-server/src/parrot/manager/manager.py)
# AFTER — insert below `        self._register_o365_oauth2_provider(self.app)` (verified: packages/ai-parrot-server/src/parrot/manager/manager.py:2407)
        self._register_jira_oauth2_provider(self.app)
```
**Why**: the app is still mutable here (line 2408 appends the `on_startup` callback right
after), which `JiraOAuthManager.setup()` requires for its route mounting and lifecycle hooks.

### `packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py` (CREATE)
```python
"""FEAT-791: Jira provider registration at BotManager setup time."""

from unittest.mock import Mock

import pytest
from aiohttp import web

from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider
from parrot.auth.oauth2.registry import OAuth2ProviderRegistry
from parrot.manager.manager import BotManager


def _manager() -> BotManager:
    manager = object.__new__(BotManager)
    manager.logger = Mock()
    return manager


@pytest.fixture(autouse=True)
def reset_oauth2_provider_registry():
    """Isolate the process-wide provider registry between tests."""
    OAuth2ProviderRegistry._reset()
    yield
    OAuth2ProviderRegistry._reset()


def _configure_jira(monkeypatch) -> None:
    monkeypatch.setattr("parrot.conf.JIRA_CLIENT_ID", "client-id")
    monkeypatch.setattr("parrot.conf.JIRA_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr("parrot.conf.JIRA_REDIRECT_URI", "https://example.test/api/auth/jira/callback")


def test_jira_provider_registered_when_configured(monkeypatch):
    """Configured Jira builds a manager and registers exactly one provider."""
    _configure_jira(monkeypatch)
    app = web.Application()
    # FILL IN: assert one provider with provider_id == "jira" is registered and
    # app["jira_oauth_manager"] is set — bounded by AC-1/AC-2.
    # Mirror test_o365_provider_registration.py's assertions on the registry.
    raise NotImplementedError


def test_jira_provider_not_registered_when_unconfigured(monkeypatch):
    """Unset JIRA_CLIENT_ID is a silent no-op, never an exception."""
    monkeypatch.setattr("parrot.conf.JIRA_CLIENT_ID", None)
    # FILL IN: assert the registry stays empty and nothing raised — bounded by AC-3.
    raise NotImplementedError


def test_jira_provider_reuses_existing_manager(monkeypatch):
    """A manager already built by the Slack/Teams path is reused, not replaced."""
    _configure_jira(monkeypatch)
    # FILL IN: pre-seed app["jira_oauth_manager"] with a Mock, assert the registered
    # provider wraps THAT instance and no new JiraOAuthManager was constructed —
    # bounded by AC-4 and by JiraOAuthManager.setup()'s RuntimeError on a different instance.
    raise NotImplementedError


def test_jira_provider_registration_is_idempotent(monkeypatch):
    """Calling the registrar twice registers exactly one provider."""
    _configure_jira(monkeypatch)
    # FILL IN: call _register_jira_oauth2_provider twice, assert one "jira" provider —
    # bounded by the app["_jira_oauth2_provider_registered"] guard key and AC-4.
    raise NotImplementedError
```
**Why this shape**: it is a structural copy of `test_o365_provider_registration.py`, which
already proves the `object.__new__(BotManager)` + registry-reset fixture pattern works for
this registrar family. The bodies are `FILL IN` because the exact construction mocking
(whether `JiraOAuthManager.setup()` can run against a bare `web.Application`, or needs its
route mounting patched) must be determined against the real code, not guessed. Keep the four
test names — the Acceptance Criteria reference them.

### `docs/auth/connections.md` (MODIFY)
```markdown
# occurrences: 1 (verified: grep -c '## Adding a provider' docs/auth/connections.md)
# AFTER — insert within the section opened by `## Adding a provider` (verified: docs/auth/connections.md:22)
# FILL IN: add a Jira row/paragraph listing `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET` and
# `JIRA_REDIRECT_URI` (default `/api/auth/jira/callback`), matching the formatting this
# section already uses for Office 365 — bounded by AC-5. Read the section first; if it is
# prose rather than a table, write prose.
```
**Why**: the keys existed in `conf.py` but were unreadable by any server path, so no
operator-facing doc mentions them. `docs/auth/delegated-auth-web-deployment.md:141` already
has an O365 env-key row — match whichever form `connections.md` itself uses.

### FILL IN checklist
- [ ] `test_jira_provider_registration.py::test_jira_provider_registered_when_configured` — registry + app-key assertions; bounded by AC-1/AC-2
- [ ] `test_jira_provider_registration.py::test_jira_provider_not_registered_when_unconfigured` — empty-registry assertion; bounded by AC-3
- [ ] `test_jira_provider_registration.py::test_jira_provider_reuses_existing_manager` — reuse of a pre-seeded manager; bounded by AC-4
- [ ] `test_jira_provider_registration.py::test_jira_provider_registration_is_idempotent` — double-call guard; bounded by AC-4
- [ ] `docs/auth/connections.md` — Jira env-key entry matching the file's existing format; bounded by AC-5

---

## Acceptance Criteria

- [ ] AC-1: `BotManager._register_jira_oauth2_provider` exists and is called from `setup()`.
- [ ] AC-2: With `JIRA_CLIENT_ID` set and no pre-existing manager, `OAuth2ProviderRegistry`
      holds exactly one provider with `provider_id == "jira"`, and `app["jira_oauth_manager"]` is set.
- [ ] AC-3: With `JIRA_CLIENT_ID` unset, nothing is registered and nothing raises.
- [ ] AC-4: A pre-existing `app["jira_oauth_manager"]` is reused; a second call registers nothing new.
- [ ] AC-5: `docs/auth/connections.md` § "Adding a provider" lists the three Jira env keys.
- [ ] AC-6: `test_o365_provider_registration.py` and `test_register_oauth2_providers.py` stay green.
- [ ] No linting errors: `ruff check` on the changed files.

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py -q`
- `pytest packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py -q`
- `pytest packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py -q`

---

## Test Specification

See the CREATE blueprint block above — the four test names are fixed; their bodies are the
`FILL IN` work. Run them with an absolute `PYTHONPATH` for both changed packages, because
the shared venv is editable-installed against the main checkout:

```bash
PYTHONPATH=/abs/path/to/worktree/packages/ai-parrot/src:/abs/path/to/worktree/packages/ai-parrot-server/src \
  pytest packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py -q
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`parrot sdd worktree ensure --slug manager-manager-fixes --feature-id FEAT-791`)
2. **Read the spec** at `sdd/specs/manager-manager-fixes.spec.md` (§3 M1/M2, §7)
3. **Check dependencies** — none
4. **Verify the Codebase Contract** — re-run `grep -c` on both anchors before editing
5. **Update status** in `sdd/tasks/index/manager-manager-fixes.json` → `"in-progress"`
6. **Implement** from the Implementation Blueprint; complete every `# FILL IN:` marker
7. **Verify** the Acceptance Criteria — run the Validation Commands
8. **Commit the code** — stage only the three files this task lists
9. **Close** with `parrot sdd task close TASK-5105 manager-manager-fixes verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: ai-parrot-8c (/sdd-fix, agent:sdd-fix)
**Date**: 2026-11-03
**Notes**: Added `BotManager._register_jira_oauth2_provider` (manager.py:2918)
and its call site at manager.py:2408, directly after the O365 call and before
the `on_startup` append, so the app is still mutable when
`JiraOAuthManager.setup()` mounts its callback route and lifecycle hooks.

The reuse branch reads `app["jira_oauth_manager"] or app["oauth2_manager_jira"]`
BEFORE constructing, because `setup()` sets both keys and raises `RuntimeError`
when either already holds a different instance — reading only one key would
have made the Slack/MS Teams path raise at startup.

Tests: 7 in `packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py`,
all passing — configured, unconfigured, reuse via each of the two app keys,
idempotence, no-double-registration through `_register_oauth2_providers`, and
the never-raises path (a `setup()` that throws is logged and leaves the guard
key unset). Three more than the four the blueprint listed: the alternate-key
reuse and the never-raises branches are the two that would actually break a
live deployment, and the startup interaction is what AC-4 turns on.

Docs: `docs/auth/connections.md` gained a "Built-in providers (no descriptor
needed)" subsection under § "Adding a provider", tabling both O365 and Jira env
keys and recording why a `provider_id: jira` descriptor is NOT equivalent
(generic manager, `toolkit_factory()` returns None, no JiraToolkit hydration).

`ruff check` clean. `test_o365_provider_registration.py` and
`test_oauth2_identity_store_binding.py` stay green.

**Deviations from spec**: one, and one pre-existing failure noted.

1. AC-6 asked that `test_register_oauth2_providers.py` stay green.
   `test_register_oauth2_providers_from_descriptors` in that module FAILS, but it
   fails identically on a clean `dev` checkout at the base commit
   (`AssertionError: Expected 'mock' to be called once. Called 2 times.`), so it
   is a pre-existing red, not a regression from this task. It was verified by
   running that single node id in the main checkout before and independently of
   this change. It is unrelated to Jira registration (it exercises the
   descriptor path) and is out of this task's scope; a ledger issue was opened
   for it separately.
2. The four blueprint test names were kept and three were added, as described
   above.
