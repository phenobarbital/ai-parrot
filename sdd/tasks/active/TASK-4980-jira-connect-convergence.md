# TASK-4980: Jira convergence: drop oauth2_local, alias `parrot jiratoolkit auth` to `parrot connect jira`

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4977
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 10 (G8, AC-12): `JiraToolkit` drops the fixed `local:cli` identity (`auth_type="oauth2_local"`,
`FileTokenCredentialResolver`); every 3LO call requires a `PermissionContext` (the existing non-local branch).
`parrot jiratoolkit auth|status|logout` delegate to `parrot connect jira`, `parrot connections`, `parrot disconnect jira`;
`sync-kb` uses the cached/pulled access token. `jira_local_auth.py` and its two test files are deleted (hard cut).

---

## Scope

- `jiratoolkit.py`: remove the `oauth2_local` block (`auth_type="oauth2_local"` now raises `ValueError`), the
  `_local_single_user` branch in `_pre_execute`, and the `jira_local_auth` import.
- `jira_cli.py`: `parse_pasted_redirect` becomes a re-export of `parrot.auth.oauth2.paste.parse_pasted_redirect`;
  `auth` → deprecated alias of `run_connect(provider="jira", paste=True)` that prints the new command; `status` /
  `logout` delegate; `sync-kb` / `_load_fresh_token` use the login + cache (`RemoteConnectionResolver`) and derive
  `cloud_id`/`site_url` via `fetch_accessible_resources`; drop the `jira_local_auth` import and now-unused helpers.
- Delete `jira_local_auth.py`, `tests/unit/test_jira_local_auth.py`, `tests/unit/test_oauth2_local_wiring.py`.
- Update `test_jira_cli.py` / `test_jiratoolkit_oauth.py`; add a convergence test.

**NOT in scope**: FEAT-773's server-side Jira provider; Telegram/Slack Jira commands; the KB format.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | MODIFY | remove local single-user mode |
| `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` | MODIFY | aliases + re-export + sync-kb via cache |
| `packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py` | DELETE | hard cut |
| `packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py` | DELETE | hard cut |
| `packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py` | DELETE | hard cut |
| `packages/ai-parrot-tools/tests/unit/test_jira_cli.py` | MODIFY | drop local-store tests, alias tests |
| `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py` | MODIFY | oauth2_local rejected |
| `packages/ai-parrot-tools/tests/unit/test_jira_connect_convergence.py` | CREATE | AC-12 tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
from parrot.auth.oauth2.paste import parse_pasted_redirect                  # TASK-4977
from parrot.cli.connect import run_connect                                  # TASK-4977 (lazy inside commands)
from parrot.auth.oauth2.local_cache import RemoteConnectionResolver, open_connection_cache   # TASK-4973
from parrot.auth.oauth2.remote_client import ServerConnectionsClient        # TASK-4972
from parrot.auth.jira_oauth import fetch_accessible_resources, fetch_myself # jira_cli.py:23-30 (already)
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
from .jira_local_auth import FileTokenCredentialResolver                    # :69 (REMOVE)
    credential_provider = "jira"                                            # :838 (keep)
        if self.auth_type == "oauth2_local": ... self._local_single_user = True ; else: self._local_single_user = False   # :930-936
    async def _pre_execute(self, tool_name: str, /, **kwargs) -> None:     # :1318
        perm_ctx = kwargs.get("_permission_context")                        # :1340
        if self._local_single_user: ... user_key = "local:cli" ...          # :1341-1356 (REMOVE branch)
        else: if perm_ctx is None: raise AuthorizationRequired(...)          # keep — becomes the only path
# packages/ai-parrot-tools/src/parrot_tools/jira_cli.py
from parrot.auth.jira_oauth import (DEFAULT_SCOPES, JiraTokenSet, build_authorization_url, exchange_code,
    fetch_accessible_resources, fetch_myself)                               # :23-30
from parrot_tools.jira_local_auth import FileTokenCredentialResolver, LocalJiraTokenStore   # :32 (REMOVE)
def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]          # :42 → re-export
def _load_fresh_token(site: Optional[str] = None) -> JiraTokenSet           # :240 (rewrite)
@click.group(name="jiratoolkit") def cli()                                  # :261
def auth(site, scopes, env_file, client_id, client_secret, redirect_uri, allow_bare_code) -> None   # :283 (→ alias)
def status(site) -> None   # :356 ; def logout(site) -> None :384 ; def sync_kb(output, projects) -> None :395 (uses token.site_url / cloud_id)
# tests referencing the local store: test_jira_cli.py:132-133, :234 (JIRA_AUTH_TYPE=oauth2_local), :388, :396 (LocalJiraTokenStore)
```

### Does NOT Exist
- ~~`parrot_tools.jira_local_auth`, `LocalJiraTokenStore`, `FileTokenCredentialResolver`~~ — deleted here; nothing may import them afterwards (grep the repo, docs included).
- ~~`JiraToolkit._local_single_user`~~ — removed.
- ~~a `local:cli` user key~~ — removed (G8).
- ~~a provider refresh token on the laptop~~ — never (AC-14); the CLI holds only cached access tokens.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jira_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py",
      "action": "DELETE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_local_auth.py",
      "action": "DELETE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_oauth2_local_wiring.py",
      "action": "DELETE"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-tools/tests/unit/test_jira_connect_convergence.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py#JiraToolkit",
    "sym:packages/ai-parrot-tools/src/parrot_tools/jira_cli.py#parse_pasted_redirect"
  ]
}
```

---

## Implementation Notes

- `auth_type == "oauth2_local"` → `raise ValueError("auth_type 'oauth2_local' was removed; run `parrot login` then
  `parrot connect jira` (FEAT-774)")` — explicit, not silent.
- `auth` alias keeps its click options for one release but ignores the client-id/secret ones; it prints
  "`parrot jiratoolkit auth` is deprecated — use `parrot connect jira`" to stderr, then runs `run_connect(...,
  provider="jira", paste=True, ...)` via the same plumbing as `parrot connect` (no login → exit 2).
- `_load_fresh_token(site)`: login required; `access_token = await RemoteConnectionResolver("jira", cache=..., client=...)
  .resolve("cli", login.user_id)`; `None` → ClickException("Jira is not connected — run `parrot connect jira`");
  `fetch_accessible_resources` → pick `site` (or the first) → build the `JiraTokenSet`-shaped object `sync_kb` needs
  (`access_token`, `cloud_id`, `site_url`; no refresh token). FILL IN the exact shape against `JiraTokenSet`.
- Grep for leftovers after deleting: `grep -rn "jira_local_auth\|oauth2_local\|LocalJiraTokenStore" packages docs`
  must return nothing outside the CHANGELOG-style notes.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Remove the local mode from `jiratoolkit.py` — *why*: G8, AC-12.
2. Turn `jira_cli.py` commands into aliases and rewrite `_load_fresh_token` — *why*: one connect flow.
3. Delete `jira_local_auth.py` and its two test files (`git rm`) — *why*: hard cut.
4. Update the two remaining Jira test files, add the convergence test, run the validation commands.

### `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from .jira_local_auth import FileTokenCredentialResolver' parrot_tools/jiratoolkit.py)
# DELETE that line (verified: jiratoolkit.py:69)

# occurrences: 1 (verified: grep -c '        if self.auth_type == "oauth2_local":' parrot_tools/jiratoolkit.py)
# REPLACE the if/else block (verified: jiratoolkit.py:930-936) with:
        if self.auth_type == "oauth2_local":
            raise ValueError(
                "auth_type 'oauth2_local' was removed (FEAT-774); run `parrot login` then `parrot connect jira`"
            )

# occurrences: 1 (verified: grep -c '            user_key = "local:cli"' parrot_tools/jiratoolkit.py)
# In _pre_execute (verified: jiratoolkit.py:1341-1356) DELETE the `if self._local_single_user:` branch and dedent its
# `else:` body so the PermissionContext-required path is the only one.
# FILL IN: remove every remaining `_local_single_user` reference (grep) — AC-12
```

### `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from parrot_tools.jira_local_auth import FileTokenCredentialResolver, LocalJiraTokenStore' parrot_tools/jira_cli.py)
# REPLACE that import (verified: jira_cli.py:32) with:
from parrot.auth.oauth2.paste import parse_pasted_redirect  # noqa: F401 — re-export (moved to core, FEAT-774)

# occurrences: 1 (verified: grep -c 'def parse_pasted_redirect(text: str) -> Tuple\[str, Optional\[str\]\]:' parrot_tools/jira_cli.py)
# DELETE the local definition (verified: jira_cli.py:42-67)

# occurrences: 1 (verified: grep -c 'def auth(site, scopes, env_file, client_id, client_secret, redirect_uri, allow_bare_code) -> None:' parrot_tools/jira_cli.py)
# REPLACE the body of auth (verified: jira_cli.py:283-351) with:
    """Deprecated alias of `parrot connect jira` (FEAT-774)."""
    click.echo("`parrot jiratoolkit auth` is deprecated — use `parrot connect jira`.", err=True)
    # FILL IN: LoginStore(); no login → stderr hint + sys.exit(2); asyncio.run(run_connect(client, cache, "jira",
    #          scopes=..., open_browser=True, paste=True, device=False, prompt=click.prompt, echo=...)) — AC-12

# FILL IN: status → list connections filtered to jira (reuse parrot.cli.connect plumbing); logout → disconnect("jira")
#          + cache.delete("jira"); _load_fresh_token → RemoteConnectionResolver + fetch_accessible_resources (see notes);
#          remove now-unused imports/helpers (build_authorization_url, exchange_code, upsert_env, _new_state, ...) only if
#          no remaining code uses them
```

### `packages/ai-parrot-tools/tests/unit/test_jira_connect_convergence.py` (CREATE)
```python
"""Jira converges on parrot connect (FEAT-774 M10, AC-12)."""
import importlib

import pytest


def test_jiratoolkit_local_mode_removed():
    # FILL IN: JiraToolkit(auth_type="oauth2_local") → ValueError; oauth2_3lo _pre_execute without _permission_context
    #          → AuthorizationRequired; importlib.import_module("parrot_tools.jira_local_auth") → ModuleNotFoundError
    ...

def test_jira_cli_auth_aliases_connect(monkeypatch, tmp_path):
    # FILL IN: patch parrot.cli.connect.run_connect; `parrot jiratoolkit auth` invokes it with provider "jira", paste=True;
    #          parrot_tools.jira_cli.parse_pasted_redirect is parrot.auth.oauth2.paste.parse_pasted_redirect
    ...
```

### FILL IN checklist
- [ ] `jiratoolkit.py` — remove every `_local_single_user` use; bounded by AC-12
- [ ] `jira_cli.auth` alias, `status`, `logout`, `_load_fresh_token`; bounded by AC-12/AC-14
- [ ] test updates in `test_jira_cli.py` / `test_jiratoolkit_oauth.py`; new convergence tests

---

## Acceptance Criteria

- [ ] `auth_type="oauth2_local"` is rejected by `JiraToolkit`; `_pre_execute` without a `PermissionContext` raises `AuthorizationRequired` (AC-12)
- [ ] `jira_local_auth.py` and its two test files no longer exist; nothing imports them (AC-12)
- [ ] `parrot jiratoolkit auth` delegates to the generic connect flow; `parse_pasted_redirect` lives in `parrot.auth.oauth2.paste` (AC-12)
- [ ] `sync-kb` works from the cached/pulled access token; no refresh token on the laptop (AC-14)
- [ ] `ruff check` clean on touched files

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/unit/test_jira_connect_convergence.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jira_cli.py -q`
- `pytest packages/ai-parrot-tools/tests/unit/test_jiratoolkit_oauth.py -q`

---

## Test Specification

```python
# see packages/ai-parrot-tools/tests/unit/test_jira_connect_convergence.py block in the blueprint
```

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug connections-cli-local-mcp --feature-id FEAT-774 --spec sdd/specs/connections-cli-local-mcp.spec.md --index sdd/tasks/index/connections-cli-local-mcp.json`)
2. **Read the spec** at the path listed above for full context (§2 Overview, §3 for this module, §7 gotchas)
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/connections-cli-local-mcp.json`
4. **Verify the Codebase Contract** — before writing ANY code re-run each `grep -c` in the blueprint;
   if a count differs, fix the anchor in this file first. Never use anything under "Does NOT Exist".
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every `# FILL IN:` marker,
   never change a signature or path the blueprint fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src` (plus one entry per other
   changed package, e.g. `packages/ai-parrot-server/src`) and `ruff check` the touched files
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh <TASK-ID> connections-cli-local-mcp verified` — never move the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
