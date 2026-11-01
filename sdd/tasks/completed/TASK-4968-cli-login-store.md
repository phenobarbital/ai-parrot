# TASK-4968: `parrot login` / `parrot logout` and the 0600 LoginStore

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-4966
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (G1, U1, AC-1, AC-2): `parrot login --server <url>` runs navigator-auth's RFC 8628 device grant as the
public client `parrot-cli` (PKCE S256), stores the result in `~/.parrot/login.json` (0600, lock file, atomic write,
`O_NOFOLLOW`); `parrot logout` revokes best-effort and wipes the login file and the connection cache. `refresh_login` is
the refresh helper TASK-4972/4978 reuse.

---

## Scope

- Create `packages/ai-parrot/src/parrot/cli/login.py`: `LoginRecord`, `LoginFileError`, `LoginExpired`,
  `LoginPrerequisiteError`, `LoginStore` (`for_uid`, `load_optional`, `save`, `delete`), `refresh_login`, click
  commands `login` and `logout`, constants `DEFAULT_LOGIN_PATH`, `DEFAULT_CLIENT_ID`, `DEFAULT_SCOPES`,
  `CACHE_FILENAME`.
- Register `login`, `logout`, `whoami` (→ `parrot.cli.login`) and `connect`, `connections`, `disconnect`
  (→ `parrot.cli.connect`) in `cli._lazy_commands` — all six now, so no later task touches `cli/__init__.py`.
- Tests: store round-trip/0600/lock/symlink/owner; device-grant happy path against a fake AS; fail-loud without the
  device endpoint (exit 2); refresh rotation + `invalid_grant`; logout wipes.

**NOT in scope**: the `whoami` command body and filling `roles`/`tenant_id` from `/me` (TASK-4974 — `whoami` and `connect`/`connections`/`disconnect` resolve only once TASK-4974/4977 land); the connection cache class (TASK-4973 — logout only unlinks the file by name); server endpoints.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/cli/login.py` | CREATE | LoginStore, refresh_login, login/logout |
| `packages/ai-parrot/src/parrot/cli/__init__.py` | MODIFY | six lazy command entries |
| `packages/ai-parrot/tests/cli/test_login.py` | CREATE | store + device grant + logout tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
import aiohttp, click                                # core deps
from pydantic import BaseModel, Field
from parrot.auth.oauth2.device_code import (         # TASK-4966
    DeviceCodeError, discover_authorization_server, make_pkce_pair, poll_device_token, request_device_authorization,
)
# stdlib: asyncio, base64, fcntl, json, os, pwd, stat, sys, tempfile, time, webbrowser, contextlib, pathlib, typing
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/cli/__init__.py
class LazyGroup(click.Group):                      # :19 ; get_command maps "a-b" → module attribute a_b (:99-100)
cli._lazy_commands = { ... }                       # :109-141 ; last entry `    "mcp-serve": "parrot.integrations.agentd.cli",` :140
# Pattern to COPY (do not import — that module is deleted by TASK-4980):
# packages/ai-parrot-tools/src/parrot_tools/jira_local_auth.py
#   LocalJiraTokenStore.locked() — sidecar `<name>.lock`, fcntl.flock LOCK_EX, parent mkdir mode 0o700
#   LocalJiraTokenStore._write() — tempfile.mkstemp in same dir, os.fchmod(fd, 0o600), fsync, os.replace, chmod 0600
#   path env override pattern: os.environ.get(...) then .expanduser()   (:24, :38-41)
# navigator-auth metadata keys: token_endpoint, device_authorization_endpoint, userinfo_endpoint, revocation_endpoint
# userinfo (backend.py:2194): {"sub": str(user_id), "email"?: ...} ; refresh: grant_type=refresh_token, rotation on
#   (OAUTH_REFRESH_ROTATION=True) → response carries a NEW refresh_token ; invalid → {"error": "invalid_grant"}
```

### Does NOT Exist
- ~~`parrot.cli.login` / `LoginStore` / `LoginRecord`~~ — created here.
- ~~`parrot login` / `logout` / `whoami` / `connect` / `connections` / `disconnect` lazy entries~~ — added here (`cli/__init__.py:109-141`).
- ~~importing `parrot_tools.jira_local_auth`~~ — forbidden: TASK-4980 deletes it; copy the pattern instead.
- ~~`ConnectionCache` / `parrot.auth.oauth2.local_cache`~~ — TASK-4973; logout deletes `<login dir>/connections.cache` by path.
- ~~navigator-auth `TokenAuth` as the login path~~ — it validates partner JWTs; the CLI path is `Oauth2Provider` (spec §6).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/cli/login.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot/src/parrot/cli/__init__.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/cli/test_login.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/cli/__init__.py#LazyGroup"
  ]
}
```

---

## Implementation Notes

- `LoginStore.__init__(path=None)`: `path or os.environ.get("PARROT_LOGIN_FILE") or DEFAULT_LOGIN_PATH`, then
  `.expanduser()`. Explicit `path` wins over the env var (TASK-4976's `--login-file` passes it explicitly).
- `load_optional(*, expected_uid=None)`: absent → `None`; open with `os.O_RDONLY | os.O_NOFOLLOW` (symlink → `ELOOP` →
  `LoginFileError`); `os.fstat` must be a regular file with `st_mode & 0o077 == 0`; when `expected_uid` is given,
  `st_uid == expected_uid`; corrupt JSON → `LoginFileError`. Fail closed: never return a record from a bad file.
- `save()` takes the sidecar lock and writes atomically with 0600 (copy the FEAT-696 pattern). Parent dir 0700.
- `cache_key` = `base64.urlsafe_b64encode(os.urandom(32)).decode()` (S4, §8 Q2: file only, no keyring).
- AC-2: missing `device_authorization_endpoint` in discovery, or `invalid_client`/`unauthorized_client` from the device
  endpoint → `LoginPrerequisiteError` naming the endpoint / the `parrot-cli` client; the command prints it to stderr and
  `sys.exit(2)`. Never fall back to a `--user` identity.
- Prompts (`verification_uri`, `user_code`) go to stderr (`click.echo(..., err=True)`); `--no-browser` skips
  `webbrowser.open`.
- Never print or log tokens. `asyncio.run` wraps the async flow inside the click command (pattern: `jira_cli.py`).

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add the six lazy entries to `cli/__init__.py` — *why*: one writer for that file keeps later tasks parallel.
2. Create `login.py` (store half) — *why*: file hygiene is the S4/S11 security boundary.
3. Complete the login/logout/refresh FILL INs — *why*: AC-1/AC-2.
4. Write `test_login.py` with a fake AS (aiohttp `TestServer`) and run the validation commands.

### `packages/ai-parrot/src/parrot/cli/__init__.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "mcp-serve": "parrot.integrations.agentd.cli",' cli/__init__.py)
# AFTER — insert below `    "mcp-serve": "parrot.integrations.agentd.cli",` (verified: cli/__init__.py:140)
    # FEAT-774 — CLI login + connections (Navigator principal for CLI surfaces).
    "login": "parrot.cli.login",
    "logout": "parrot.cli.login",
    "whoami": "parrot.cli.login",
    "connect": "parrot.cli.connect",
    "connections": "parrot.cli.connect",
    "disconnect": "parrot.cli.connect",
```

### `packages/ai-parrot/src/parrot/cli/login.py` (CREATE — part 1: models + store)
```python
"""`parrot login` / `logout` and the 0600 login file (FEAT-774 M1). Never logs token material."""
from __future__ import annotations

import asyncio, base64, contextlib, fcntl, json, logging, os, stat, sys, tempfile, time, webbrowser
import pwd
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import aiohttp
import click
from pydantic import BaseModel, Field

from parrot.auth.oauth2.device_code import (
    DeviceCodeError, discover_authorization_server, make_pkce_pair, poll_device_token, request_device_authorization,
)

logger = logging.getLogger(__name__)
DEFAULT_LOGIN_PATH = Path("~/.parrot/login.json")
DEFAULT_CLIENT_ID = "parrot-cli"
DEFAULT_SCOPES = ("openid", "profile", "email")
CACHE_FILENAME = "connections.cache"   # TASK-4973's ConnectionCache lives next to the login file


class LoginFileError(RuntimeError):
    """Login file unreadable, wrong owner/mode, or a symlink (fail closed)."""


class LoginExpired(RuntimeError):
    """The refresh token was rejected (invalid_grant); run `parrot login` again."""


class LoginPrerequisiteError(RuntimeError):
    """navigator-auth is missing the device endpoint or the `parrot-cli` client (AC-2)."""


class LoginRecord(BaseModel):
    """Contents of ~/.parrot/login.json (0600). Never logged."""

    server_url: str
    client_id: str = DEFAULT_CLIENT_ID
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    expires_at: float
    scopes: List[str] = Field(default_factory=list)
    user_id: str
    email: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    cache_key: str
    issued_at: float


class LoginStore:
    """Atomic, locked, 0600 store for one login record."""

    def __init__(self, path: Optional[Path] = None) -> None:
        raw = path or os.environ.get("PARROT_LOGIN_FILE") or DEFAULT_LOGIN_PATH
        self.path = Path(raw).expanduser()

    @classmethod
    def for_uid(cls, uid: int) -> "LoginStore":
        """``pwd.getpwuid(uid).pw_dir / .parrot/login.json`` (agentd, TASK-4979)."""
        return cls(Path(pwd.getpwuid(uid).pw_dir) / ".parrot" / "login.json")

    @property
    def cache_path(self) -> Path:
        return self.path.with_name(CACHE_FILENAME)

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        # FILL IN: copy LocalJiraTokenStore.locked (sidecar "<name>.lock", flock LOCK_EX, parent mkdir 0o700) — S4
        raise NotImplementedError

    def load_optional(self, *, expected_uid: Optional[int] = None) -> Optional[LoginRecord]:
        """None when absent. O_NOFOLLOW; regular file; mode & 0o077 == 0; owner == expected_uid when given."""
        # FILL IN: os.open(O_RDONLY | O_NOFOLLOW) → FileNotFoundError → None; ELOOP / bad mode / bad owner / bad JSON
        #          → LoginFileError (message names the path, never the content) — bounded by AC-11, S11
        raise NotImplementedError

    def save(self, record: LoginRecord) -> None:
        """Atomic write under the lock file, mode 0600."""
        # FILL IN: copy LocalJiraTokenStore._write (mkstemp in same dir, fchmod 0600, fsync, os.replace) — AC-1
        raise NotImplementedError

    def delete(self) -> bool:
        """Remove the login file; True when something was deleted."""
        with self._locked():
            try:
                self.path.unlink()
                return True
            except FileNotFoundError:
                return False
```

### `packages/ai-parrot/src/parrot/cli/login.py` (CREATE — part 2: refresh + commands, appended)
```python
async def refresh_login(record: LoginRecord, session: aiohttp.ClientSession) -> LoginRecord:
    """grant_type=refresh_token at the discovered token_endpoint; keeps the rotated refresh token."""
    if not record.refresh_token:
        raise LoginExpired("no refresh token; run `parrot login` again")
    meta = await discover_authorization_server(session, record.server_url)
    # FILL IN: POST meta["token_endpoint"] {grant_type, refresh_token, client_id}; {"error": "invalid_grant"} → LoginExpired;
    #          return record.model_copy(update={access_token, refresh_token (new or old), expires_at=now+expires_in})
    raise NotImplementedError


async def _login_flow(server: str, client_id: str, scopes: List[str], open_browser: bool) -> LoginRecord:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
        try:
            meta = await discover_authorization_server(session, server)
        except DeviceCodeError as exc:
            raise LoginPrerequisiteError(f"cannot discover the authorization server at {server}: {exc}") from exc
        device_url = meta.get("device_authorization_endpoint")
        if not device_url:
            raise LoginPrerequisiteError("server metadata has no device_authorization_endpoint (enable Oauth2Provider)")
        verifier, challenge = make_pkce_pair()
        # FILL IN: request_device_authorization (invalid_client/unauthorized_client → LoginPrerequisiteError naming the
        #          `client_id` public client); echo verification_uri + user_code to stderr; webbrowser.open unless disabled;
        #          poll_device_token(token_endpoint, code_verifier=verifier); GET userinfo (Bearer) → sub/email;
        #          build LoginRecord(cache_key=urlsafe_b64(os.urandom(32)), issued_at=time.time()) — AC-1, AC-2
        raise NotImplementedError


@click.command("login")
@click.option("--server", envvar="PARROT_SERVER_URL", required=True, help="AI-Parrot / navigator-auth base URL.")
@click.option("--client-id", envvar="PARROT_CLI_CLIENT_ID", default=DEFAULT_CLIENT_ID, show_default=True)
@click.option("--scopes", default=None, help="Space- or comma-separated scopes (default: openid profile email).")
@click.option("--no-browser", is_flag=True, default=False, help="Print the verification URL instead of opening it.")
def login(server: str, client_id: str, scopes: Optional[str], no_browser: bool) -> None:
    """Log in with the RFC 8628 device grant and store ~/.parrot/login.json (0600)."""
    wanted = scopes.replace(",", " ").split() if scopes else list(DEFAULT_SCOPES)
    store = LoginStore()
    try:
        record = asyncio.run(_login_flow(server, client_id, wanted, not no_browser))
    except (LoginPrerequisiteError, DeviceCodeError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(2)
    store.save(record)
    # roles/tenant are filled from GET /api/v1/connections/me by TASK-4974
    click.echo(f"Logged in as {record.email or record.user_id}", err=True)


@click.command("logout")
def logout() -> None:
    """Revoke the login (best effort) and delete the login file and the connection cache."""
    store = LoginStore()
    # FILL IN: load_optional (LoginFileError → still delete); best-effort POST revocation_endpoint {token: refresh or access,
    #          client_id} with errors swallowed; store.delete(); store.cache_path.unlink(missing_ok=True) — AC-1, AC-6
    raise NotImplementedError
```
**Why this shape**: the spec fixes `LoginRecord`, `LoginStore` (incl. `for_uid`, `load_optional(expected_uid=)`) and
`refresh_login(record, session)`; the extra exception types and `cache_path` give TASK-4972/4973/4979 stable names. The
`# roles/tenant ...` comment line is the anchor TASK-4974 attaches to — keep it verbatim.

### `packages/ai-parrot/tests/cli/test_login.py` (CREATE)
```python
"""parrot login / logout and LoginStore (FEAT-774 M1)."""
import os, time

import pytest
from click.testing import CliRunner

from parrot.cli.login import LoginFileError, LoginRecord, LoginStore, login, logout, refresh_login


@pytest.fixture
def login_record() -> LoginRecord:
    return LoginRecord(server_url="http://parrot.test", access_token="at", refresh_token="rt", expires_at=time.time() + 3600,
                       user_id="1042", email="jlara@example.com", tenant_id="troc", roles=["agents:use"],
                       cache_key="k" * 43, issued_at=time.time())


def test_login_store_roundtrip_0600_and_lock(tmp_path, login_record):
    # FILL IN: save → mode 0600 + lock file exists → load_optional == record; symlink → LoginFileError;
    #          chmod 0644 → LoginFileError; expected_uid=os.getuid()+1 → LoginFileError
    ...

def test_login_device_grant_happy_path(monkeypatch, tmp_path):
    # FILL IN: fake AS (aiohttp TestServer): discovery → device_authorization (assert code_challenge present) → pending ×2
    #          → slow_down → token; userinfo sub "1042" → saved LoginRecord.user_id == "1042"; asyncio.sleep patched
    ...

def test_login_fails_loudly_without_device_endpoint(monkeypatch, tmp_path):
    # FILL IN: discovery without device_authorization_endpoint → exit_code 2 and the message names it (AC-2)
    ...

async def test_refresh_login_rotation_and_invalid_grant(login_record):
    # FILL IN: new refresh token kept; {"error": "invalid_grant"} → LoginExpired
    ...

def test_logout_revokes_and_wipes(monkeypatch, tmp_path, login_record):
    # FILL IN: revoke called best-effort (and a failing revoke still wipes); login file + connections.cache deleted
    ...
```

### FILL IN checklist
- [ ] `LoginStore._locked` / `save` — copy the FEAT-696 pattern; bounded by AC-1 (0600, atomic)
- [ ] `LoginStore.load_optional` — O_NOFOLLOW, regular file, mode, owner, JSON; bounded by AC-11/S11 (fail closed)
- [ ] `refresh_login` — rotation + invalid_grant → LoginExpired
- [ ] `_login_flow` — device request, prompts to stderr, poll, userinfo, record; bounded by AC-1/AC-2
- [ ] `logout` — best-effort revoke then wipe both files; bounded by AC-1/AC-6
- [ ] test bodies — fake AS fixture, 0600/symlink/owner cases

---

## Acceptance Criteria

- [ ] `parrot login --server <url>` completes the device grant with PKCE S256 and writes `login.json` with mode 0600 (AC-1)
- [ ] Missing device endpoint or `parrot-cli` client → exit 2 naming it (AC-2)
- [ ] `load_optional` rejects symlinks, group/other-readable files and a wrong owner with `LoginFileError`
- [ ] `parrot logout` revokes best-effort and deletes `login.json` and `connections.cache`
- [ ] `parrot --help` lists login/logout/whoami/connect/connections/disconnect
- [ ] `ruff check` clean on touched files; no token material in any log or message (AC-14)

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/test_login.py -q`

---

## Test Specification

```python
# see packages/ai-parrot/tests/cli/test_login.py block in the blueprint
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

**Completed by**: gpt-5.6-sol (codex) (1 attempt), orchestrated by sdd-worker
**Date**: 2026-10-31
**Notes**: Implemented as specified; task and merge-tier tests green.
