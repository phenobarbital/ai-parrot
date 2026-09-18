# TASK-3365: `parrot claude install --remote` — native HTTP `.mcp.json` entry (M7a)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3351
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (Claude part), AC13, AC14. The pass-through (TASK-3364) is the
default path; this task adds the optional **native** registration for Claude
Code: `.mcp.json` entry `{"type": "http", "url": …, "headers": {"Authorization":
"Bearer ${TOKEN_ENV}"}}` under the unchanged key `wikitoolkit`, so the
`mcp__wikitoolkit__*` approvals in `.claude/settings.local.json` stay valid.
Claude Code 2.1.274 expands `${VAR}` at config level (brainstorm §8); the
task's test must assert the header shape, and the e2e task (TASK-3367) covers
the runtime. Uninstall/status must recognise both entry shapes.

---

## Scope

- `assets.mcp_json_entry_remote(url, token_env) -> dict`.
- `installer._install_mcp_json(root, *, remote=None)`: choose the remote entry when given; `_is_wikitoolkit_entry(entry)` recognising stdio (`command` endswith `wikitoolkit`, `args == ["mcp"]`) and http (`type == "http"` + `headers.Authorization` startswith `"Bearer ${"`) shapes; `_uninstall_mcp_json` removes either; `integration_status()` adds `"mcp_transport": "stdio" | "http" | None`.
- `install_claude_integration(..., remote: WikiRemoteConfig | None = None)` threads it.
- CLI `parrot claude install --remote [--remote-url URL] [--token-env NAME]`: `remote = WikiRemoteConfig(url=remote_url, token_env=token_env)` when `--remote-url` given, else `config.remote`; `--remote` without either → `ClickException`.
- Tests.

**NOT in scope**: Codex (TASK-3366), pass-through, docs (TASK-3367), the hook/skill/CLAUDE.md blocks (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | `mcp_json_entry_remote` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | remote entry, shape detection, status |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | `--remote`, `--remote-url`, `--token-env` |
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_claude.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.knowledge.wiki.claude_code import assets                                   # installer.py:33
from parrot.knowledge.wiki.claude_code.installer import (install_claude_integration, uninstall_claude_integration, integration_status,
    _install_mcp_json, _uninstall_mcp_json, _managed_server_names, _is_managed_toolkit_entry)   # installer.py:770, :855, :985, :462, :552, :304, :420
from parrot.knowledge.wiki.claude_code.assets import mcp_json_entry, resolve_wikitoolkit_bin, MCP_JSON_ENTRY   # assets.py:108, :83, :71
from parrot.knowledge.wiki.project import WikiRemoteConfig, load_effective_config, WikiConfigError   # TASK-3351 / project.py
from parrot.knowledge.wiki.claude_code.cli import claude as claude_group                # cli.py:50 (`parrot claude` group); install() :107; status() :205
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
MCP_JSON_ENTRY: dict = {"command": "wikitoolkit", "args": ["mcp"], "env": {}}      # :71-75
def resolve_wikitoolkit_bin(root: Path) -> str                                    # :83
def mcp_json_entry(root: Path) -> dict                                            # :108-116 (anchor `^def mcp_json_entry(root: Path) -> dict:` 1 occurrence) → {"command": resolve_wikitoolkit_bin(root), "args": ["mcp"], "env": {}}
PERMISSION_RULES (mcp__wikitoolkit__wiki_symbol_lookup / wiki_code_outline / wiki_blast_radius) :52-63
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _install_mcp_json(root: Path) -> str                                          # :462-551 — `entry = assets.mcp_json_entry(root)` (:~485, 1 occurrence); `if servers.get("wikitoolkit") == entry:` reconciliation; only touches "wikitoolkit" + managed "parrot-<name>" keys
def _uninstall_mcp_json(root: Path) -> tuple[str | None, list[str]]                # :552 — `if "wikitoolkit" in servers: del servers["wikitoolkit"]` (:582-584)
def _is_managed_toolkit_entry(entry, root, name) -> bool                          # :420-461 (shape rule for parrot-<name>; model for the new _is_wikitoolkit_entry)
def install_claude_integration(root, config=None, git_hook=True, gitignore=True, bookstore=True, toolkits=(), approve_mcp=True) -> list[str]   # :770-778 (anchor `^def install_claude_integration(` 1×) — calls `actions.append(_install_mcp_json(root))` at :842
def integration_status(root: Path) -> dict[str, Any]                              # :985 — mapping artifact → bool/detail
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
@click.group(name="claude") :50 · install(path_, git_hook, gitignore, build_now, bookstore, tool_guards, toolkits_, all_toolkits, approve_mcp) :107 — options :57-106; body :118-140 calls install_claude_integration(root, config, git_hook=…, gitignore=…, bookstore=…, toolkits=names, approve_mcp=approve_mcp)   (`    approve_mcp: bool,` 1 occurrence in the signature)
```

### Does NOT Exist
- ~~`mcp_json_entry_remote`~~, ~~`_is_wikitoolkit_entry`~~, ~~`--remote` flags~~, ~~`integration_status()["mcp_transport"]`~~ — created here.
- ~~`"type": "streamable-http"` in `.mcp.json`~~ — Claude Code's key is `"type": "http"` (brainstorm §8, verified 2.1.274).
- ~~`"env"` interpolation for headers~~ — use `${VAR}` syntax inside the header value.
- ~~`wikitoolkit claude install` writing `.mcp.json`~~ — that command (`coding_agents.install`) is untouched; only `parrot claude install` writes `.mcp.json`.
- ~~changing the server key~~ — it stays `"wikitoolkit"` (approvals `mcp__wikitoolkit__*`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_claude.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py#mcp_json_entry",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_install_mcp_json",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_uninstall_mcp_json",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#install_claude_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#integration_status",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py#install"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Without `remote` the written `.mcp.json` must be **byte-identical** to today (AC14) — the existing `test_installer_mcp.py` is the guard.
- Re-running `--remote` is idempotent ("entry already current").
- A foreign `wikitoolkit` entry (neither shape) is never overwritten silently: warn on stderr and skip, mirroring `_is_managed_toolkit_entry`'s warn-and-skip (installer.py:374-382 comments).

---

## Implementation Blueprint

### Steps (in order)
1. `assets.mcp_json_entry_remote` — *why*: entry shape in one place.
2. Installer: entry selection + `_is_wikitoolkit_entry` + uninstall/status — *why*: AC13 lifecycle.
3. `install_claude_integration(remote=)` + CLI flags — *why*: user entry point.
4. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def mcp_json_entry(root: Path) -> dict:' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# AFTER — insert below the whole `mcp_json_entry` function (assets.py:108-116)
def mcp_json_entry_remote(url: str, token_env: str) -> dict:
    """Native Claude Code HTTP entry for a remote wiki mount (FEAT-569).

    Claude Code expands ``${VAR}`` inside ``.mcp.json`` header values (2.1.274+),
    so the token never lands on disk.
    """
    return {"type": "http", "url": url, "headers": {"Authorization": f"Bearer ${{{token_env}}}"}}
```
**Why**: brainstorm-verified shape; the key `wikitoolkit` is chosen by the installer, not here.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def _install_mcp_json(root: Path) -> str:' installer.py) — REPLACE signature with:
def _install_mcp_json(root: Path, *, remote: "WikiRemoteConfig | None" = None) -> str:
# occurrences: 1 (verified: grep -c '    entry = assets.mcp_json_entry(root)' installer.py) — REPLACE (installer.py:~485) with:
    entry = assets.mcp_json_entry_remote(remote.url, remote.token_env) if remote is not None else assets.mcp_json_entry(root)
    existing = servers_peek = None  # FILL IN: after `servers` is resolved below, if "wikitoolkit" in servers and not _is_wikitoolkit_entry(servers["wikitoolkit"]): warn on stderr + return "wikitoolkit entry is foreign — left untouched" — bounded by the warn-and-skip rule (installer.py:374-382)

# occurrences: 1 (verified: grep -c '^def _uninstall_mcp_json(' installer.py) — BEFORE it, insert:
def _is_wikitoolkit_entry(entry: Any) -> bool:
    """True for BOTH managed shapes: stdio (`command` ends with wikitoolkit, args == ["mcp"]) and http (type http + Bearer ${…} header)."""
    if not isinstance(entry, dict):
        return False
    if entry.get("type") == "http":
        auth = (entry.get("headers") or {}).get("Authorization", "")
        return isinstance(entry.get("url"), str) and isinstance(auth, str) and auth.startswith("Bearer ${")
    command = entry.get("command")
    return isinstance(command, str) and command.endswith("wikitoolkit") and entry.get("args") == ["mcp"]

# occurrences: 1 (verified: grep -c '^def install_claude_integration(' installer.py) — add keyword `remote: Optional["WikiRemoteConfig"] = None,` after `approve_mcp: bool = True,` (:777) and change the call at :842 to `actions.append(_install_mcp_json(root, remote=remote))`. Import WikiRemoteConfig into the existing `from parrot.knowledge.wiki.project import (` block (:34).
# integration_status (:985): add `"mcp_transport": ("http" if entry.get("type") == "http" else "stdio") if _is_wikitoolkit_entry(entry) else None` where entry = servers.get("wikitoolkit") from .mcp.json (FILL IN: read how status loads .mcp.json today, ~:1000-1040).
# _uninstall_mcp_json (:582-584): keep `del servers["wikitoolkit"]` — it already removes any shape; just ensure the foreign-entry guard uses _is_wikitoolkit_entry.
```
**Why**: the reconciliation logic (compare, add/update, write) is untouched — only the entry value and the shape predicate change, which is what keeps AC14's byte-identity.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    approve_mcp: bool,' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# Add three options above `def install(` (next to --approve-mcp, cli.py:~101-106):
@click.option("--remote", "use_remote", is_flag=True, help="Register wikitoolkit as a native HTTP MCP pointing at the configured remote (FEAT-569).")
@click.option("--remote-url", default=None, help="Remote wiki mount URL (default: `remote.url` from .parrot/wiki.json).")
@click.option("--token-env", default=None, help="Env var holding the bearer token (default: `remote.token_env` or WIKITOOLKIT_TOKEN).")
# Add `use_remote: bool, remote_url: Optional[str], token_env: Optional[str],` to the signature after `approve_mcp: bool,`.
# In the body, after `config = load_effective_config(root).config` (cli.py:~130):
        remote = None
        if use_remote:
            from parrot.knowledge.wiki.project import WikiRemoteConfig
            if remote_url:
                remote = WikiRemoteConfig(url=remote_url, token_env=token_env or "WIKITOOLKIT_TOKEN")
            elif config.remote is not None:
                remote = config.remote if token_env is None else config.remote.model_copy(update={"token_env": token_env})
            else:
                raise click.ClickException("--remote needs --remote-url or a `remote` block in .parrot/wiki.json")
# and pass `remote=remote` to install_claude_integration(...).
```
**Why**: mirrors how `toolkits_`/`approve_mcp` flow into the installer; the config-driven default means most users run `parrot claude install --remote` with no extra flags.

### FILL IN checklist
- [ ] Foreign-entry warn-and-skip placement inside `_install_mcp_json`.
- [ ] `integration_status` `.mcp.json` read location.
- [ ] Docstrings for the three new CLI options in the `install` help text.

---

## Acceptance Criteria

- [ ] `parrot claude install --remote --remote-url https://h/mcp/w --token-env WT` writes `.mcp.json["mcpServers"]["wikitoolkit"] == {"type":"http","url":"https://h/mcp/w","headers":{"Authorization":"Bearer ${WT}"}}`; re-run → "already current", file unchanged.
- [ ] `--remote` with `remote` in `wiki.json` and no flags uses `config.remote`; with neither → `ClickException`.
- [ ] `parrot claude uninstall` removes the http entry; `integration_status()["mcp_transport"]` is `"http"` / `"stdio"` / `None` accordingly.
- [ ] A foreign `wikitoolkit` entry (e.g. `{"command": "other"}`) is left untouched with a stderr warning.
- [ ] Without `--remote`, `.mcp.json` output is byte-identical to today — `test_installer_mcp.py` passes unchanged.
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_claude.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_claude.py
import json, pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.claude_code.cli import claude
from parrot.knowledge.wiki.claude_code.installer import integration_status
from parrot.knowledge.wiki.project import WikiProjectConfig, WikiRemoteConfig, save_project_config


def _mcp(root): return json.loads((root / ".mcp.json").read_text())["mcpServers"]["wikitoolkit"]


def test_remote_flag_writes_http_entry(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); (tmp_path / ".parrot").mkdir(); save_project_config(tmp_path, WikiProjectConfig(wiki_name="w"))
    args = ["install", "--remote", "--remote-url", "https://h/mcp/w", "--token-env", "WT", "--no-git-hook", "--no-bookstore"]  # FILL IN: exact negative flags (cli.py:57-106)
    assert CliRunner().invoke(claude, args).exit_code == 0
    assert _mcp(tmp_path) == {"type": "http", "url": "https://h/mcp/w", "headers": {"Authorization": "Bearer ${WT}"}}
    before = (tmp_path / ".mcp.json").read_bytes()
    assert CliRunner().invoke(claude, args).exit_code == 0 and (tmp_path / ".mcp.json").read_bytes() == before
    assert integration_status(tmp_path)["mcp_transport"] == "http"
    assert CliRunner().invoke(claude, ["uninstall"]).exit_code == 0 and "wikitoolkit" not in json.loads((tmp_path / ".mcp.json").read_text()).get("mcpServers", {})


def test_remote_from_config_and_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); (tmp_path / ".parrot").mkdir()
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w", remote=WikiRemoteConfig(url="https://cfg/mcp/w")))
    assert CliRunner().invoke(claude, ["install", "--remote"]).exit_code == 0 and _mcp(tmp_path)["url"] == "https://cfg/mcp/w"
    save_project_config(tmp_path, WikiProjectConfig(wiki_name="w"))
    assert CliRunner().invoke(claude, ["install", "--remote"]).exit_code != 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3351 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `_install_mcp_json` (:462-551) and the `install` options (:57-118) in full
4. **Update status** in `sdd/tasks/index/wikitoolkit-http-mcp.json` → `"in-progress"`
5. **Implement** from the blueprint
6. **Verify** acceptance criteria; run the Validation Commands
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
