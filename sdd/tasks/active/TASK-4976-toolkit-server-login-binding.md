# TASK-4976: Bind the login principal + CLI broker in `parrot mcp-local` stdio servers

**Feature**: FEAT-774 — Connections for CLI agents and local MCP toolkits
**Spec**: `sdd/specs/connections-cli-local-mcp.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4975, TASK-4974, TASK-4973
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G4, AC-7, AC-8, AC-4): `create_toolkit_mcp_server` resolves the principal and a CLI broker **once at
process start** from the login file (default path, `PARROT_LOGIN_FILE`, or `parrot mcp-local --login-file`) and binds a
`ToolExecutionContext` to every adapter. Without a login the server behaves exactly as today. Host install entries
(`.mcp.json`, Codex `config.toml`) pass `PARROT_LOGIN_FILE` through when it is set at install time — never a token.

---

## Scope

- `toolkit_server.py`: `_ToolkitStdioMCPServer.__init__(config, toolkit, *, login_file=None)`; `_bind_identity()`
  called at the top of `start()`; `create_toolkit_mcp_server(name, root=..., *, login_file=None, **overrides)`.
- `local_cli.py`: `--login-file` option (envvar `PARROT_LOGIN_FILE`) passed to the factory.
- `claude_code/assets.py` / `codex/assets.py`: add `PARROT_LOGIN_FILE` to the entry env when set in `os.environ` at
  install time and not already in `section.env`.
- Tests.

**NOT in scope**: adapter/envelope code (TASK-4975); the end-to-end subprocess test (TASK-4981); `local_server.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` | MODIFY | login binding at start() |
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | MODIFY | --login-file option |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | PARROT_LOGIN_FILE passthrough |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | PARROT_LOGIN_FILE passthrough |
| `tests/mcp/test_toolkit_server_login.py` | CREATE | binding + host entry tests |

---

## Codebase Contract (Anti-Hallucination)

> Re-verified against `dev` @ `8ab2f60782` (2026-10-31), after FEAT-773 merged. The spec's §6 entries marked
> **planned** are re-anchored to code here; line numbers below are the current ones.

### Verified Imports
```python
# All parrot.cli / parrot.auth imports below are LAZY, inside a `contextlib.redirect_stdout(sys.stderr)` block (FEAT-485):
from parrot.cli.login import LoginFileError, LoginStore                         # TASK-4968
from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context   # TASK-4974
from parrot.auth.oauth2.remote_client import ServerConnectionsClient             # TASK-4972
from parrot.auth.oauth2.local_cache import build_cli_broker                      # TASK-4973
from parrot.mcp.adapter import ToolExecutionContext                              # TASK-4975 (light; may be top-level)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_server.py (imports asyncio, contextlib, importlib, logging, sys, Path, Any)
class _ToolkitStdioMCPServer(StdioMCPServer):                                    # :37
    def __init__(self, config: LocalServerConfig, toolkit: AbstractToolkit) -> None:   # :56 ; self._owned_toolkit = toolkit
    async def start(self) -> None:  try: await super().start()  finally: await self.stop()   # :62-67
def create_toolkit_mcp_server(name: str, root: Path = Path.cwd(), **overrides: Any) -> StdioMCPServer:   # :137 ; `    **overrides: Any,` :140
    # redirect block `with contextlib.redirect_stdout(sys.stderr):` :186 ; toolkit = toolkit_cls(**kwargs) :222
    server = _ToolkitStdioMCPServer(LocalServerConfig(name=f"parrot-{name}", version="1.0.0"), toolkit)   # :262
    server.register_tools(filtered_tools)                                        # :263
# AbstractToolkit.credential_provider: str | None (toolkit.py:331); propagated to each ToolkitTool (:717-718)
# AbstractTool.credential_provider (abstract.py:306)
# packages/ai-parrot/src/parrot/mcp/local_cli.py
@click.option("--list", "list_toolkits", is_flag=True, ...)                     # :160-166 ("--list" :161)
def mcp_local(name, config_path, include, exclude, list_toolkits) -> None        # :167-173
        server = create_toolkit_mcp_server(name, root, **overrides)               # :218
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py (imports: shutil, ... — check for `os`)
def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict   # :159 ; `"env": dict(section.env),` :181
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py (imports json, shutil)
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str        # :63 ; `if section.env:` :89 ; env_toml :90-91
# TASK-4975: MCPServerBase.execution_context attribute; MCPToolAdapter.execution_context attribute (mutable)
```

### Does NOT Exist
- ~~`create_toolkit_mcp_server(..., login_file=...)`, `--login-file`~~ — added here.
- ~~`ToolkitSection.user` / `principal` / `token`~~ — fields are class/enabled/kwargs/include/exclude/llm/llm_kwargs/env (`toolkit_config.py:50-57`); do not add any.
- ~~resolving identity inside the sync factory with `asyncio.run`~~ — the factory stays sync; resolution happens in `start()` (spec §3 M5).
- ~~writing the token or login content into host entries~~ — only the `PARROT_LOGIN_FILE` path, and only when already set.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/mcp/toolkit_server.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/local_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "tests/mcp/test_toolkit_server_login.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_server.py#create_toolkit_mcp_server",
    "sym:packages/ai-parrot/src/parrot/mcp/local_cli.py#mcp_local",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#toolkit_mcp_json_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#toolkit_mcp_block"
  ]
}
```

---

## Implementation Notes

- `_bind_identity()`: inside `contextlib.redirect_stdout(sys.stderr)` lazy-import the modules; `store =
  LoginStore(self._login_file)`; `record = await asyncio.to_thread(store.load_optional)`; `LoginFileError` →
  `logger.error(...)` and return (serve without identity; never crash the host); `None` → return.
  `async` resolve with `CliPrincipalResolver(store, client).resolve_with_roles("cli", record.user_id)`; `None` → warn,
  return. Providers = `{t.credential_provider for t in self.tools.values() adapters' tools if set}`; broker =
  `build_cli_broker(store, providers, client=client)` when providers else `None`.
  `ctx = ToolExecutionContext(permission_context=build_cli_permission_context(principal, roles=roles), broker=broker)`;
  set `self.execution_context = ctx` and `adapter.execution_context = ctx` for every adapter in `self.tools`.
- `start()` becomes: `await self._bind_identity()` then the existing try/finally.
- local_cli: `login_file` param (Path | None); pass `login_file=login_file` to the factory (not via `overrides`).
- Assets: add `import os`; compute `env = dict(section.env)`; `if os.environ.get("PARROT_LOGIN_FILE") and
  "PARROT_LOGIN_FILE" not in env: env["PARROT_LOGIN_FILE"] = os.environ["PARROT_LOGIN_FILE"]`. Codex: emit the
  `env = { ... }` line whenever the merged env is non-empty.
- Keep `tests/mcp/test_toolkit_server.py`, `test_local_cli.py`, `packages/ai-parrot/tests/mcp/test_hosts.py`,
  `test_toolkit_install.py` green (no login in their environment → unchanged output). Make the new tests set
  `PARROT_LOGIN_FILE`/`HOME` to a tmp path so a developer's real login never leaks in.

---

## Implementation Blueprint

> **CRITICAL — Executor-ready starting point.** Write each block below to its declared
> path nearly verbatim, then complete every `# FILL IN:` marker. This is NOT the full
> implementation: branches, edge cases and test bodies are `FILL IN` stubs by design.
> Never change a signature, class name, or file path the blueprint fixes.

### Steps (in order)
1. Add `login_file` to `_ToolkitStdioMCPServer` and the factory — *why*: AC-7 process-start binding.
2. Implement `_bind_identity()` and call it first in `start()` — *why*: resolution is async; factory stays sync.
3. Add `--login-file` to `mcp_local` — *why*: §3 M5.
4. Pass `PARROT_LOGIN_FILE` through in both host asset builders — *why*: hosts launch the server with their own env.
5. Write tests; run them plus the existing toolkit-server / local-cli / host tests.

### `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` (MODIFY — server class)
```python
# occurrences: 1 (verified: grep -c '    def __init__(self, config: LocalServerConfig, toolkit: AbstractToolkit) -> None:' mcp/toolkit_server.py)
# REPLACE that signature (verified: toolkit_server.py:56) and keep the body, adding `self._login_file = login_file`:
    def __init__(self, config: LocalServerConfig, toolkit: AbstractToolkit, *, login_file: Optional[Path] = None) -> None:

# REPLACE the body of start() (verified: toolkit_server.py:62-67) with:
        await self._bind_identity()
        try:
            await super().start()
        finally:
            await self.stop()

# INSERT as a new method right after start():
    async def _bind_identity(self) -> None:
        """Resolve the login principal + CLI broker once; no login → today's behaviour (AC-4)."""
        with contextlib.redirect_stdout(sys.stderr):
            from parrot.auth.oauth2.local_cache import build_cli_broker
            from parrot.auth.oauth2.remote_client import ServerConnectionsClient
            from parrot.cli.login import LoginFileError, LoginStore
            from parrot.cli.principal import CliPrincipalResolver, build_cli_permission_context
            from parrot.mcp.adapter import ToolExecutionContext
        store = LoginStore(self._login_file)
        # FILL IN: load (LoginFileError → logger.error + return; None → return); resolve_with_roles("cli", record.user_id)
        #          (None → logger.warning + return); providers from adapters' tools' credential_provider; broker via
        #          build_cli_broker when providers else None; ctx = ToolExecutionContext(...); assign to self and every
        #          adapter in self.tools — AC-7
```

### `packages/ai-parrot/src/parrot/mcp/toolkit_server.py` (MODIFY — factory)
```python
# occurrences: 1 (verified: grep -c '    \*\*overrides: Any,' mcp/toolkit_server.py)
# BEFORE `    **overrides: Any,` (verified: toolkit_server.py:140) insert:
    *,
    login_file: Optional[Path] = None,
# (add `Optional` to `from typing import Any`; docstring: document login_file)

# occurrences: 1 (verified: grep -c 'server = _ToolkitStdioMCPServer(LocalServerConfig(name=f"parrot-{name}", version="1.0.0"), toolkit)' mcp/toolkit_server.py)
# REPLACE that line (verified: toolkit_server.py:262) with:
    server = _ToolkitStdioMCPServer(
        LocalServerConfig(name=f"parrot-{name}", version="1.0.0"), toolkit, login_file=login_file,
    )
```

### `packages/ai-parrot/src/parrot/mcp/local_cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "--list",' mcp/local_cli.py)
# AFTER the whole `@click.option("--list", ...)` decorator (verified: local_cli.py:160-166) insert:
@click.option(
    "--login-file",
    "login_file",
    default=None,
    type=click.Path(path_type=Path),
    envvar="PARROT_LOGIN_FILE",
    help="parrot login file to bind the Navigator principal (default ~/.parrot/login.json).",
)
# add `login_file: Path | None,` as the last parameter of mcp_local (:167-173)

# occurrences: 1 (verified: grep -c '        server = create_toolkit_mcp_server(name, root, \*\*overrides)' mcp/local_cli.py)
# REPLACE that line (verified: local_cli.py:218) with:
        server = create_toolkit_mcp_server(name, root, login_file=login_file, **overrides)
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "env": dict(section.env),' claude_code/assets.py)
# REPLACE that line (verified: claude_code/assets.py:181) with:
        "env": _with_login_file(dict(section.env)),
# and add (module level, plus `import os`):
def _with_login_file(env: dict) -> dict:
    """Pass PARROT_LOGIN_FILE through when set at install time (a path, never a token)."""
    login_file = os.environ.get("PARROT_LOGIN_FILE")
    if login_file and "PARROT_LOGIN_FILE" not in env:
        env["PARROT_LOGIN_FILE"] = login_file
    return env
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        if section.env:' codex/assets.py)
# REPLACE the 3-line block `if section.env:` … `lines.append(f"env = {{ {env_toml} }}")` (verified: codex/assets.py:89-91) with:
        env = dict(section.env)
        login_file = os.environ.get("PARROT_LOGIN_FILE")
        if login_file and "PARROT_LOGIN_FILE" not in env:
            env["PARROT_LOGIN_FILE"] = login_file
        if env:
            env_toml = ", ".join(f"{key} = {json.dumps(value)}" for key, value in env.items())
            lines.append(f"env = {{ {env_toml} }}")
# (add `import os`)
```

### `tests/mcp/test_toolkit_server_login.py` (CREATE)
```python
"""Login binding for parrot mcp-local (FEAT-774 M5)."""
import pytest


def test_toolkit_server_without_login_unchanged(tmp_path, monkeypatch):
    # FILL IN: PARROT_LOGIN_FILE → missing tmp path; _bind_identity leaves execution_context None on server + adapters
    ...

async def test_toolkit_server_binds_principal_from_login_file(tmp_path, monkeypatch):
    # FILL IN: 0600 login file + patched CliPrincipalResolver.resolve_with_roles / build_cli_broker; toolkit with
    #          credential_provider="fake" → broker built for {"fake"}; every adapter has the same context; --login-file honoured
    ...

def test_host_entries_pass_login_file_env(tmp_path, monkeypatch):
    # FILL IN: PARROT_LOGIN_FILE set → toolkit_mcp_json_entry env and toolkit_mcp_block `env =` carry the path; unset → unchanged
    ...
```

### FILL IN checklist
- [ ] `_ToolkitStdioMCPServer._bind_identity` — load/resolve/broker/assign; bounded by AC-4 (no login → no change) and AC-7
- [ ] tests — tmp login file, patched resolver/broker, host entries

---

## Acceptance Criteria

- [ ] With a login, a `credential_provider` tool in `parrot mcp-local` runs with the bound context and broker (AC-7)
- [ ] Without a login (or a bad login file) the server behaves exactly as before (AC-4)
- [ ] `--login-file` / `PARROT_LOGIN_FILE` select the login file
- [ ] Host entries carry `PARROT_LOGIN_FILE` only when set at install time; never a token
- [ ] Existing toolkit-server / local-cli / hosts / toolkit-install tests stay green; `ruff check` clean

---

## Validation Commands

- `pytest tests/mcp/test_toolkit_server_login.py -q`
- `pytest tests/mcp/test_toolkit_server.py -q`
- `pytest tests/mcp/test_local_cli.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_hosts.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_toolkit_install.py -q`

---

## Test Specification

```python
# see tests/mcp/test_toolkit_server_login.py block in the blueprint
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
