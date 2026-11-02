---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server, docs]
tags: [oauth2, jira, botmanager, test-drift, ledger-fix]
---

# Feature Specification: BotManager fixes — Jira web-channel OAuth2 registration + BotManager test-API drift

**Feature ID**: FEAT-791
**Date**: 2026-11-03
**Author**: /sdd-fix (agent:sdd-fix)
**Status**: approved
**Target version**: 0.29.x

---

## 1. Motivation & Business Requirements

This spec drains ledger fix group `fixgroup:6dc7f7828af6` — two independent,
`major` issues that both land in
`packages/ai-parrot-server/src/parrot/manager/manager.py`.

### Problem Statement

**A. `issue:9b625450ce4a` — Jira OAuth2 provider is never registered for the web channel.**
`BotManager` auto-builds and registers the O365 provider from `parrot.conf`
(`_register_o365_oauth2_provider`, `manager.py:2917`), but has no equivalent for
Jira. `_register_oauth2_providers` (`manager.py:2950`) registers
`JiraOAuth2Provider` **only if** `app["jira_oauth_manager"]` already exists;
otherwise it logs a warning and moves on. The only code paths that construct a
`JiraOAuthManager` are `parrot/integrations/manager.py` (MS Teams / Slack, from
per-bot `{BOTNAME}_JIRA_*` keys) and the repo-root `app.py` (not part of any
distribution). `parrot/conf.py` defines `JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`
and `JIRA_REDIRECT_URI` (`conf.py:744-746`) but **no server code reads them**.

Consequence: FEAT-777's web lane (Connections panel, IntegrationsMenu, Connect
pill) lists providers from `OAuth2ProviderRegistry`, so a plain web deployment
shows only Office 365 even though `JiraToolkit` declares
`credential_provider = "jira"` and the Jira 3LO engine (FEAT-773 M7) is
complete. Every external project must hand-wire
`JiraOAuthManager(...).setup()` after `BotManager.setup()`.

The `OAUTH2_PROVIDERS_FILE` descriptor route is not a substitute: it produces a
generic `StandardOAuth2Manager` + `DescriptorOAuth2Provider` whose
`toolkit_factory()` returns `None`, leaving `app["jira_oauth_manager"]` unset
and no `JiraToolkit` factory available for hydration.

**B. `issue:31f12d3a6967` — 19 tests red on `dev` from BotManager API drift.**
Confirmed again on `049e5f4be1` (2026-11-03): `19 failed, 6 passed`.
- `packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py` — 16 tests
  call `BotManager._build_prompt_builder(...)`, which no longer exists anywhere
  in `packages/*/src`.
- `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` — 3 tests:
  `test_yaml_agent_toolkit_persist_roundtrip` calls the removed
  `BotManager._build_from_registry` (`test_tooling_integration.py:327`);
  `test_dataset_manager_datasources_in_memory` fails `assert 0 == 2` at line 389;
  `test_user_override_session_isolation` fails
  `'NoneType' object has no attribute 'list_tools'` at line 472.

Consequence: the merge/feature-tier selector picks these up as direct importers
of `manager.py`, so **every** feature that touches `BotManager` reports them as
"new red" (`new_red=19, baseline_red=0` — seen in FEAT-704 PR #1821 and
TASK-4480). The gate shows false failures.

### Goals
- A plain web deployment with `JIRA_CLIENT_ID` set registers `JiraOAuth2Provider`
  automatically, exactly as O365 does today.
- The 19 drifted tests are green on `dev`, exercising the **current** API.
- `docs/auth/connections.md` § "Adding a provider" documents the Jira env keys.

### Non-Goals (explicitly out of scope)
- Changing the descriptor (`OAUTH2_PROVIDERS_FILE`) route's semantics, or
  making `provider_id: jira` resolve to `JiraOAuthManager` — the mirror of
  `_register_o365_oauth2_provider` is the chosen option (§7).
- Any change to `JiraOAuthManager`, `JiraOAuth2Provider`, `jira_oauth.py` or
  `descriptor.py` behaviour. They are read-only reference here.
- Restoring `_build_prompt_builder` / `_build_from_registry` — they were
  removed deliberately; the tests move to the replacement API.
- Fixing MongoDB/DocumentDB availability in CI. If a test in group B turns out
  to need a live service, it is marked/skipped, not made to pass by starting one.

---

## 2. Architectural Design

### Overview

Two independent lanes, no shared code:

- **Lane A (M1, M2)** adds `BotManager._register_jira_oauth2_provider`, a
  near-exact mirror of `_register_o365_oauth2_provider`, called from the same
  mutable-app site, plus unit tests and a docs row.
- **Lane B (M3, M4)** repoints two test modules at the current API.

### Component Diagram
```
BotManager.setup()
   ├─ _register_o365_oauth2_provider(app)   (exists, manager.py:2917)
   ├─ _register_jira_oauth2_provider(app)   (NEW, M1)
   │     └─ JiraOAuthManager(JIRA_CLIENT_ID, …).setup()
   │           └─ register_oauth2_provider(JiraOAuth2Provider(manager=…))
   └─ on_startup → _register_oauth2_providers(app)   (exists, manager.py:2950)
         └─ sees app["jira_oauth_manager"] already set → registers nothing twice
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `BotManager.setup()` | calls | new `_register_jira_oauth2_provider(self.app)` beside the O365 call |
| `JiraOAuthManager` | constructs | from `parrot.conf` JIRA keys; `.setup()` mounts routes |
| `JiraOAuth2Provider` | constructs | `register_oauth2_provider(JiraOAuth2Provider(manager=…))` |
| `IdentityVaultCredentialStore` | constructs | `IdentityVaultCredentialStore(authdb)` when `app["authdb"]` exists |
| `BotManager._register_oauth2_providers` | idempotence | must stay a no-op double-registration guard |
| `AgentRegistry._apply_prompt_config` | test target | replacement API for `_build_prompt_builder` |

### New Public Interfaces

Nothing public. One new private method:

```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    def _register_jira_oauth2_provider(self, app: web.Application) -> None:
        """Wire the shared Jira manager and provider while the app is mutable."""
```

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: `_register_jira_oauth2_provider` | yes | mirror of `_register_o365_oauth2_provider`, signature + guard key fixed below | — |
| M2: Jira registration tests + docs row | yes | mirrors `tests/unit/test_o365_provider_registration.py` | — |
| M3: `test_yaml_prompt_config.py` repoint | yes | target API fixed: `get_preset()` + `AgentRegistry._apply_prompt_config(bot, PromptConfig(...))` | — |
| M4: `test_tooling_integration.py` repoint | no | 2 of 3 failures are not API drift; root cause must be diagnosed first | `assert 0 == 2` and the `None` tool_manager need investigation |

### Module 1: Jira OAuth2 provider auto-registration
- **Path**: `packages/ai-parrot-server/src/parrot/manager/manager.py`
- **Responsibility**: build a `JiraOAuthManager` from `parrot.conf` and register
  `JiraOAuth2Provider` when `JIRA_CLIENT_ID` is set, at `setup()` time while the
  app is still mutable.
- **Depends on**: existing `_register_o365_oauth2_provider` (pattern only).
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot-server/src/parrot/manager/manager.py  (modifies manager.py:2917 region)
  def _register_jira_oauth2_provider(self, app: web.Application) -> None:
      """Wire the shared Jira manager and provider while the app is mutable.

      No-op when ``JIRA_CLIENT_ID`` is unset or
      ``app['_jira_oauth2_provider_registered']`` is already truthy.
      Reuses ``app['oauth2_manager_jira']`` / ``app['jira_oauth_manager']``
      when a manager was already built (Slack/Teams path), otherwise
      constructs ``JiraOAuthManager(JIRA_CLIENT_ID, JIRA_CLIENT_SECRET,
      JIRA_REDIRECT_URI, app=app, credential_store=…, event_publisher=…)``
      and calls ``.setup()``. Never raises: logs via ``self.logger.exception``.
      """
  ```
  Call site: beside the existing O365 call, before the `on_startup` append.

### Module 2: Registration tests + docs
- **Path**: `packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py` (new),
  `docs/auth/connections.md` (modify)
- **Responsibility**: prove the three branches (configured / unset / already
  built) and document `JIRA_CLIENT_ID JIRA_CLIENT_SECRET JIRA_REDIRECT_URI`.
- **Depends on**: Module 1.

### Module 3: `test_yaml_prompt_config.py` repoint
- **Path**: `packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py`
- **Responsibility**: 16 tests exercise the current API instead of
  `BotManager._build_prompt_builder`. Each test keeps its name and its
  assertion intent; only the construction changes:
  `builder = BotManager._build_prompt_builder(cfg)` becomes a bot whose
  `_prompt_builder` is `get_preset(cfg["preset"])`, then
  `AgentRegistry._apply_prompt_config(bot, PromptConfig(**cfg))`.
- **Depends on**: nothing (test-only).

### Module 4: `test_tooling_integration.py` repair
- **Path**: `packages/ai-parrot-server/tests/studio/test_tooling_integration.py`
- **Responsibility**: diagnose and fix the three failures. Known facts:
  `_build_from_registry` (line 327) no longer exists; line 389 asserts
  `len(registered) == 2` and gets 0; line 472 calls `list_tools()` on a `None`
  `tool_manager` after a DocumentDB connection to `localhost:27017` is refused.
  A test that genuinely needs a live service is marked/skipped with a reason,
  never deleted and never made to pass by weakening its assertion.
- **Depends on**: nothing (test-only).

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_jira_provider_registered_when_configured` | M1/M2 | `JIRA_CLIENT_ID` set → exactly one `JiraOAuth2Provider` in the registry, `app["jira_oauth_manager"]` set |
| `test_jira_provider_not_registered_when_unconfigured` | M1/M2 | `JIRA_CLIENT_ID` unset → registry empty, no exception |
| `test_jira_provider_reuses_existing_manager` | M1/M2 | a pre-built `app["jira_oauth_manager"]` is reused, not replaced |
| `test_jira_provider_registration_is_idempotent` | M1/M2 | calling twice registers once |
| `TestYAMLPresetSelection` (4) | M3 | presets default/minimal/voice/agent produce the expected layers |
| `TestYAMLRemoveOperation` (3) | M3 | remove single / multiple / nonexistent-is-noop |
| `TestYAMLAddOperation` (4) | M3 | add domain layer by name / multiple / inline dict / mixed |
| `TestYAMLCustomizeOperation` (3) | M3 | customize template / preserves priority / nonexistent-is-noop |
| `TestYAMLCombinedOperations` (2) | M3 | full config flow + renders correctly |

### Integration Tests
| Test | Description |
|---|---|
| `test_yaml_agent_toolkit_persist_roundtrip` | M4 — Studio toolkit spec survives the DB-bot rebuild |
| `test_dataset_manager_datasources_in_memory` | M4 — replayed datasources register |
| `test_user_override_session_isolation` | M4 — per-user toolkit overrides stay session-local |

### Validation Contract

tests:
- packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py
- packages/ai-parrot-server/tests/unit/test_o365_provider_registration.py
- packages/ai-parrot-server/tests/unit/test_register_oauth2_providers.py
- packages/ai-parrot-server/tests/manager/test_oauth2_identity_store_binding.py
- packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py
- packages/ai-parrot/tests/manager/test_botmanager_prompt_config.py
- packages/ai-parrot-server/tests/studio/test_tooling_integration.py
markers: none

---

## 5. Acceptance Criteria

- [ ] `BotManager._register_jira_oauth2_provider` exists and is called from `setup()`.
- [ ] With `JIRA_CLIENT_ID` set and no pre-existing manager, `OAuth2ProviderRegistry`
      contains exactly one provider with `provider_id == "jira"` after `setup()`.
- [ ] With `JIRA_CLIENT_ID` unset, nothing is registered and nothing raises.
- [ ] A pre-existing `app["jira_oauth_manager"]` (Slack/Teams path) is reused,
      and `_register_oauth2_providers` does not double-register.
- [ ] `docs/auth/connections.md` § "Adding a provider" lists the three Jira env keys.
- [ ] `pytest packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py` → 0 failed.
- [ ] `pytest packages/ai-parrot-server/tests/studio/test_tooling_integration.py` → 0 failed
      (a test needing a live service may be skipped with an explicit reason, not deleted).
- [ ] The full Validation Contract runs green from the feature worktree.
- [ ] No behaviour change to `jira_oauth.py`, `descriptor.py` or `conf.py` semantics.

---

## 6. Codebase Contract

> Verified against `049e5f4be1` (dev, 2026-11-03).

### Verified Imports
```python
from parrot.auth.jira_oauth import JiraOAuthManager          # jira_oauth.py:226
from parrot.auth.oauth2.jira_provider import JiraOAuth2Provider  # jira_provider.py:22
from parrot.auth.oauth2.registry import register_oauth2_provider, OAuth2ProviderRegistry
from parrot.services.identity_credential_sink import IdentityVaultCredentialStore
from parrot.conf import JIRA_CLIENT_ID, JIRA_CLIENT_SECRET, JIRA_REDIRECT_URI  # conf.py:744-746
from parrot.registry.registry import PromptConfig, AgentRegistry  # used by tests/manager/test_botmanager_prompt_config.py:9
from parrot.bots.prompts.presets import get_preset            # used at test_botmanager_prompt_config.py:53
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/auth/jira_oauth.py
class JiraOAuthManager(StandardOAuth2Manager):              # line 226
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, *,
                 app: Any = None, redis_url: Optional[str] = None, redis_client: Any = None,
                 scopes: Optional[List[str]] = None, http_session: Optional[aiohttp.ClientSession] = None,
                 credential_store: Optional[CredentialStore] = None, event_publisher: Any = None,
                 callback_path: str = "/api/auth/jira/callback") -> None:   # line 231
    def setup(self) -> None:                                 # line 261
        # sets app["jira_oauth_manager"] AND app["oauth2_manager_jira"];
        # raises RuntimeError if either key already holds a DIFFERENT instance;
        # raises RuntimeError if app is None; mounts routes via setup_jira_oauth_routes(app)

# packages/ai-parrot/src/parrot/auth/oauth2/jira_provider.py
class JiraOAuth2Provider(OAuth2Provider):                    # line 22
    provider_id: str = "jira"
    def __init__(self, manager: "JiraOAuthManager") -> None: # line 52

# packages/ai-parrot-server/src/parrot/manager/manager.py
class BotManager:
    def _register_o365_oauth2_provider(self, app: web.Application) -> None:   # line 2917
    async def _register_oauth2_providers(self, app: web.Application) -> None: # line 2950
    def _register_descriptor_oauth2_providers(self, app: web.Application) -> None:  # line 2892
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `_register_jira_oauth2_provider` | `BotManager.setup()` | direct call | `manager.py:2407` |
| `_register_jira_oauth2_provider` | `JiraOAuthManager.setup()` | method call | `jira_oauth.py:261` |
| `_register_jira_oauth2_provider` | `register_oauth2_provider` | function call | `manager.py:2944` (O365 precedent) |

### Does NOT Exist (Anti-Hallucination)
- ~~`BotManager._build_prompt_builder`~~ — removed; zero hits in `packages/*/src`.
- ~~`BotManager._build_from_registry`~~ — removed; zero hits in `packages/*/src`.
- ~~`BotManager._register_jira_oauth2_provider`~~ — this feature creates it.
- ~~`parrot.conf.JIRA_SCOPES`~~ — not defined; only the three keys at `conf.py:744-746`.
- ~~`app["_jira_oauth2_provider_registered"]`~~ — this feature introduces the key.
- ~~`packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py`~~ — new file.

### Edit Sites (Blueprint Anchors)

> Verified against `049e5f4be1`. `/sdd-task` MUST re-run each `grep -c`.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `        self._register_o365_oauth2_provider(self.app)` | `manager.py:2407` | 1 |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | `    def _register_o365_oauth2_provider(self, app: web.Application) -> None:` | `manager.py:2917` | 1 |
| `packages/ai-parrot-server/tests/unit/test_jira_provider_registration.py` | CREATE | — | — | — |
| `packages/ai-parrot/tests/bots/prompts/test_yaml_prompt_config.py` | MODIFY | `        builder = BotManager._build_prompt_builder({"preset": "default"})` | `test_yaml_prompt_config.py:43` | 1 |
| `packages/ai-parrot-server/tests/studio/test_tooling_integration.py` | MODIFY | `    bot = mgr._build_from_registry("test-agent", app=MagicMock())` | `test_tooling_integration.py:327` | 1 |
| `docs/auth/connections.md` | MODIFY | `## Adding a provider` | `connections.md:22` | 1 |

---

## 7. Implementation Notes & Constraints

### Decision: mirror O365, do not reroute the descriptor path
The ledger issue offered two options. **Chosen: mirror
`_register_o365_oauth2_provider`.** Rationale: it reuses a shipped, tested
pattern; it keeps `JiraToolkit` hydration working because the real
`JiraOAuthManager`/`JiraOAuth2Provider` pair is constructed; and it leaves the
descriptor route untouched for genuinely generic providers. Making
`provider_id: jira` resolve to a built-in subclass would add a special case to
a deliberately generic loader.

### Patterns to Follow
- Copy `_register_o365_oauth2_provider` structurally: early return on unset
  client id or an already-set guard key; reuse an existing
  `app[f"oauth2_manager_{provider_id}"]` before constructing; wrap everything in
  `try/except Exception` + `self.logger.exception(...)` so a misconfigured Jira
  never prevents server startup.
- `JiraOAuthManager.setup()` raises if `app["jira_oauth_manager"]` already holds
  a *different* instance — the reuse branch must therefore check that key
  **before** constructing, not after.
- Imports stay function-local, exactly as the O365 method does.
- Lane B is test-only: do **not** restore the removed BotManager helpers, and do
  not change `manager.py` for Lane B.
- Worktree validation needs an absolute `PYTHONPATH` per changed package
  (`packages/ai-parrot/src`, `packages/ai-parrot-server/src`).

### Constraints
- `ruff check --fix` on changed files; `black` line-length 120.
- No new dependency.
- Both lanes must be separately revertible — keep M1/M2 and M3/M4 in distinct commits.

---

## 8. Ledger Linkage

| Issue | Lane | Modules | Closed by |
|---|---|---|---|
| `issue:9b625450ce4a` | A | M1, M2 | the task implementing M1/M2 |
| `issue:31f12d3a6967` | B | M3, M4 | the task implementing M3/M4 |
