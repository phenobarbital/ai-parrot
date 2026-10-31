# TASK-4977: `parrot connect` / `connections` / `disconnect`, paste parser in core, and REPL slash commands

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4973
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6 (G5, U3, S10, AC-9, AC-10): connect a provider from the CLI. `run_connect` starts FEAT-773's connect
for `channel="cli"`, opens/prints the authorize URL, and completes either by **polling** the connection status until it
is connected *after* `started_at`, or by **pasting** the redirected URL (state verified with `hmac.compare_digest`,
posted to `/complete`), or — with `--device` — through the server device endpoints. On success the access token is
pulled into the encrypted cache. `parse_pasted_redirect` moves from `parrot_tools/jira_cli.py` into core.

---

## Scope

- Create `packages/ai-parrot/src/parrot/auth/oauth2/paste.py` (`parse_pasted_redirect`, moved verbatim).
- Create `packages/ai-parrot/src/parrot/cli/connect.py`: `ConnectFailed`, `run_connect`, click commands `connect`,
  `connections`, `disconnect`.
- `parrot/cli/commands.py`: `/connect`, `/connections`, `/disconnect` built-ins (prompts inside `ctx.suspend()`).
- Tests.

**NOT in scope**: turning `jira_cli.parse_pasted_redirect` into a re-export and the `parrot jiratoolkit auth` alias (TASK-4980); server endpoints (TASK-4970/4971).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/auth/oauth2/paste.py` | CREATE | parse_pasted_redirect (moved) |
| `packages/ai-parrot/src/parrot/cli/connect.py` | CREATE | run_connect + click commands |
| `packages/ai-parrot/src/parrot/cli/commands.py` | MODIFY | /connect /connections /disconnect |
| `packages/ai-parrot/tests/cli/test_connect.py` | CREATE | poll/paste/device/slash tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
import click, hmac, webbrowser
from datetime import datetime
from parrot.auth.oauth2.remote_client import ConnectAttempt, NotLoggedIn, ServerConnectionsClient   # TASK-4972
from parrot.auth.oauth2.local_cache import CachedConnection, ConnectionCache, open_connection_cache  # TASK-4973
from parrot.auth.oauth2.paste import parse_pasted_redirect                       # created here
from parrot.cli.login import LoginStore                                          # TASK-4968
```

### Existing Signatures to Use
```python
# packages/ai-parrot-tools/src/parrot_tools/jira_cli.py
def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]:   # :42-67 — COPY body verbatim (urlparse/parse_qs,
#   raises click.ClickException on error= / missing code; bare code → (text, None))
# Server status (GET /api/v1/connections/{provider}) → IntegrationDescriptor JSON:
#   status: "connected" | "disconnected" | "needs_reconnect"   (models.py:18 — NOT "active")
#   connected_at: ISO datetime | null ; updated_at: ISO datetime | null
#   persist_credential keeps the OLD connected_at when the same account re-connects (service.py: `connected_at=existing.connected_at if same_account else now`)
#   but always sets updated_at = now
# TASK-4972 ServerConnectionsClient: start_connect(provider, *, channel="cli", scopes=None) -> ConnectAttempt(provider, state, auth_url, started_at, expires_in)
#   status(provider) -> dict ; complete(provider, *, code, state) -> dict ; pull_token(provider) -> PulledToken
#   list() -> list ; disconnect(provider) ; device_start(provider) -> {handle, user_code, verification_uri, verification_uri_complete, expires_in, interval}
#   device_poll(provider, handle) -> {status: pending|completed|failed|expired, interval?, reason?}
# TASK-4973: open_connection_cache(store) -> ConnectionCache ; ConnectionCache.put(CachedConnection) / delete(provider)
# packages/ai-parrot/src/parrot/cli/commands.py
class CommandContext(Protocol): bot; config; dispatcher; runner; renderer (property, .print); history; def suspend(self) -> ContextManager[None]   # :41-64
@dataclass class SlashCommand: name; description; handler   # :68
def _register_builtins(self) -> None   # :187 ; `SlashCommand("help", "List all available slash commands.", _cmd_help),` :207
# handler convention: `async def _cmd_x(ctx: "CommandContext", args: str) -> None`, output via ctx.renderer.print("[cyan]..[/cyan]")  (:352-361)
```

### Does NOT Exist
- ~~`parrot.cli.connect`, `run_connect`, `parrot.auth.oauth2.paste`~~ — created here.
- ~~`status == "active"` in the connections API~~ — **spec drift**: the descriptor reports `"connected"`. Poll for
  `status == "connected"`.
- ~~`connected_at >= started_at` alone as the completion test~~ — a re-connect of the same account keeps the old
  `connected_at`; use `max(connected_at, updated_at) >= started_at` (both ISO strings → `datetime.fromisoformat(...).timestamp()`).
- ~~`/connect` handlers in `commands.py`~~ — added here.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/auth/oauth2/paste.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/connect.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/commands.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_connect.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#SlashCommandDispatcher",
    "sym:packages/ai-parrot/src/parrot/cli/commands.py#CommandContext"
  ]
}
```

---

## Implementation Notes

- `run_connect(client, cache, provider, *, scopes, open_browser, paste, device, prompt, echo, poll_interval_s=2.0)`
  (spec §3 M6 signature). Order: `device` → device flow; else `attempt = await client.start_connect(provider,
  scopes=scopes)`, echo the URL (and `webbrowser.open` if `open_browser`); if `paste` → prompt immediately, else poll every
  `poll_interval_s` until connected-after-start or `attempt.expires_in` elapses, then fall back to the paste prompt.
- Paste: `code, state = parse_pasted_redirect(prompt("Paste the redirected URL"))`; `state is None or not
  hmac.compare_digest(state, attempt.state)` → `ConnectFailed("state mismatch")`; else `client.complete(provider,
  code=code, state=state)`.
- Device: `device_start` → echo `user_code` + `verification_uri` → loop `device_poll` honouring `interval` until
  `completed` (or `failed`/`expired` → `ConnectFailed`).
- Success: `pulled = await client.pull_token(provider)` → `cache.put(CachedConnection(..., pulled_at=time.time()))`;
  return `{"provider", "account_id", "status": "connected"}`.
- Click commands: no login → "Not logged in — run `parrot login`" + exit 2. `connect` options: `--scopes`,
  `--no-browser`, `--paste`, `--device`. Echo goes to stderr for prompts; `connections` prints a table (provider, status,
  account, scopes, expires). `disconnect`: `client.disconnect` + `cache.delete(provider)`.
- Slash commands: build the client/cache from `LoginStore()`; run prompts inside `with ctx.suspend():` and use
  `click.prompt` / `click.echo`; render results with `ctx.renderer.print`. Insert before the `help` entry.
- Never echo the code or the state value.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Create `paste.py` by copying `parse_pasted_redirect` verbatim — *why*: AC-12 moves it to core.
2. Create `connect.py` — *why*: one `run_connect` serves click, slash commands and the Jira alias (TASK-4980).
3. Register the three slash commands — *why*: AC-9.
4. Write tests with a stub client; run the validation commands.

### `packages/ai-parrot/src/parrot/auth/oauth2/paste.py` (CREATE)
```python
"""Parse a pasted OAuth redirect URL (moved from parrot_tools/jira_cli.py, FEAT-774 M6)."""
from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

import click


def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]:
    # FILL IN: copy docstring + body VERBATIM from parrot_tools/jira_cli.py:42-67 — AC-12
    raise NotImplementedError
```

### `packages/ai-parrot/src/parrot/cli/connect.py` (CREATE)
```python
"""`parrot connect` / `connections` / `disconnect` (FEAT-774 M6)."""
from __future__ import annotations

import asyncio, hmac, logging, sys, time, webbrowser
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import click

from parrot.auth.oauth2.local_cache import CachedConnection, ConnectionCache, open_connection_cache
from parrot.auth.oauth2.paste import parse_pasted_redirect
from parrot.auth.oauth2.remote_client import ConnectAttempt, NotLoggedIn, ServerConnectionsClient
from parrot.cli.login import LoginStore

logger = logging.getLogger(__name__)


class ConnectFailed(RuntimeError):
    """A connect attempt ended without a connection (one-line reason)."""


def _ts(value: Optional[str]) -> float:
    return datetime.fromisoformat(value).timestamp() if value else 0.0


def _completed_after(status: Dict[str, Any], started_at: float) -> bool:
    """Connected AND touched after this attempt started (S10; updated_at covers same-account re-connects)."""
    return status.get("status") == "connected" and max(_ts(status.get("connected_at")), _ts(status.get("updated_at"))) >= started_at


async def run_connect(
    client: ServerConnectionsClient, cache: ConnectionCache, provider: str, *, scopes: Optional[List[str]],
    open_browser: bool, paste: bool, device: bool, prompt: Callable[[str], str], echo: Callable[[str], None],
    poll_interval_s: float = 2.0,
) -> Dict[str, Any]:
    """start_connect → poll | paste (state check) | device; then pull the access token into the cache."""
    if device:
        # FILL IN: device_start → echo user_code + verification_uri → device_poll loop honouring interval → completed,
        #          failed/expired → ConnectFailed — AC-10
        raise NotImplementedError
    attempt = await client.start_connect(provider, scopes=scopes)
    echo(f"Open this URL to connect {provider}:\n  {attempt.auth_url}")
    if open_browser:
        webbrowser.open(attempt.auth_url)
    # FILL IN: unless paste: poll client.status(provider) every poll_interval_s until _completed_after(...) or
    #          attempt.expires_in elapsed; then (or when paste) prompt → parse_pasted_redirect → hmac.compare_digest(state,
    #          attempt.state) else ConnectFailed("state mismatch") → client.complete(...) — AC-9, S10
    pulled = await client.pull_token(provider)
    await cache.put(CachedConnection(
        provider=provider, access_token=pulled.access_token, expires_at=pulled.expires_at,
        scopes=list(pulled.scopes), account_id=pulled.account_id, pulled_at=time.time(),
    ))
    return {"provider": provider, "account_id": pulled.account_id, "status": "connected"}


# FILL IN: click commands `connect` (PROVIDER; --scopes, --no-browser, --paste, --device), `connections`, `disconnect`
#          (PROVIDER) — each: store = LoginStore(); no login → stderr hint + sys.exit(2); asyncio.run(...) with
#          `async with ServerConnectionsClient(store) as client` and open_connection_cache(store); ConnectFailed → exit 1
```

### `packages/ai-parrot/src/parrot/cli/commands.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            SlashCommand("help", "List all available slash commands.", _cmd_help),' cli/commands.py)
# BEFORE — insert above that line (verified: commands.py:207)
            SlashCommand(
                "connect",
                "Connect a provider for this login. Usage: /connect <provider> [--paste|--device]",
                _cmd_connect,
            ),
            SlashCommand("connections", "List this login's provider connections.", _cmd_connections),
            SlashCommand("disconnect", "Disconnect a provider. Usage: /disconnect <provider>", _cmd_disconnect),

# APPEND three module-level handlers after `_cmd_quit` (verified: commands.py:381), e.g.:
async def _cmd_connect(ctx: "CommandContext", args: str) -> None:
    """Handle /connect — run the CLI connect flow with the terminal suspended for prompts."""
    # FILL IN: parse provider + --paste/--device from args (no provider → usage); lazy-import click, LoginStore,
    #          ServerConnectionsClient, open_connection_cache, run_connect; no login → ctx.renderer.print hint;
    #          `with ctx.suspend():` await run_connect(..., prompt=click.prompt, echo=click.echo) — AC-9
    raise NotImplementedError
# FILL IN: _cmd_connections (table via ctx.renderer.print) and _cmd_disconnect (client.disconnect + cache.delete)
```

### `packages/ai-parrot/tests/cli/test_connect.py` (CREATE)
```python
"""parrot connect (FEAT-774 M6, AC-9)."""
import pytest

from parrot.cli.connect import ConnectFailed, run_connect


async def test_connect_poll_completes_only_new_connection():
    # FILL IN: stub client.status → first a pre-existing "connected" row with connected_at/updated_at < started_at
    #          (must NOT complete), then updated_at >= started_at → completes; token pulled into cache
    ...

async def test_connect_paste_fallback_state_check():
    # FILL IN: paste=True; mismatched state → ConnectFailed and complete() not called; matching → complete(code, state)
    ...

async def test_connect_device_flow():
    ...

async def test_slash_connect_uses_suspend():
    # FILL IN: fake CommandContext whose suspend() records entry; /connect jira --paste enters suspend around the prompt
    ...
```

### FILL IN checklist
- [ ] `paste.py` — verbatim copy of `jira_cli.parse_pasted_redirect`
- [ ] `run_connect` device branch and poll/paste branch; bounded by AC-9/AC-10/S10
- [ ] click commands `connect` / `connections` / `disconnect`
- [ ] slash handlers `_cmd_connect` / `_cmd_connections` / `_cmd_disconnect`; bounded by AC-9 (suspend around prompts)
- [ ] tests — stub client + cache

---

## Acceptance Criteria

- [ ] Poll completes only when the connection is `connected` and touched at/after `started_at` (AC-9, S10)
- [ ] Paste verifies `state` with `hmac.compare_digest` and posts `{code, state}` to `/complete` (AC-9)
- [ ] `--device` completes through the server device endpoints (AC-10)
- [ ] On success the access token is in the encrypted cache; `/connect`, `/connections`, `/disconnect` exist (AC-9)
- [ ] `parse_pasted_redirect` importable from `parrot.auth.oauth2.paste`; `ruff check` clean

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_connect.py -q`
- `pytest packages/ai-parrot/tests/cli/test_commands_context.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/cli/test_connect.py block in the blueprint
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
