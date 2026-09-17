# TASK-3366: `parrot codex install --remote` — `url` + `bearer_token_env_var` table (M7b)

**Feature**: FEAT-569 — wikitoolkit remote (Streamable HTTP) MCP
**Spec**: `sdd/specs/wikitoolkit-http-mcp.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3351
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 7 (Codex part), AC13. Codex reads `[mcp_servers.<name>]` tables
from the project `.codex/config.toml`; for a remote server the keys are `url`
and `bearer_token_env_var` (verified in brainstorm §8). Codex documents **no**
custom-header key, so a native registration cannot send `X-Wiki-Actor` — the
stdio pass-through (TASK-3364) remains the recommended Codex path and the docs
say so. This task makes the native option available for teams that accept the
server's `default_actor`.

---

## Scope

- `codex/assets.mcp_block(root, toolkit_block="", *, remote: WikiRemoteConfig | None = None)`: when `remote` is given the `[mcp_servers.wikitoolkit]` table has `url = "<url>"`, `bearer_token_env_var = "<token_env>"`, `default_tools_approval_mode = "approve"` and **no** `command`/`args`.
- `codex/installer._install_mcp(root, *, remote=None)` and `install_codex_integration(..., remote=None)` thread it; status/uninstall unchanged (the managed marker block is regenerated wholesale).
- CLI `parrot codex install --remote [--remote-url] [--token-env]` (same semantics as TASK-3365).
- Tests (`tomllib` round-trip of the generated block).

**NOT in scope**: Claude (TASK-3365), header injection for Codex (does not exist), docs (TASK-3367).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | `mcp_block(remote=)` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | `_install_mcp(remote=)`, `install_codex_integration(remote=)` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` | MODIFY | `--remote`, `--remote-url`, `--token-env` |
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_codex.py` | CREATE | Tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import json, tomllib
from parrot.knowledge.wiki.codex import assets                                     # installer.py:11
from parrot.knowledge.wiki.codex.assets import MCP_BEGIN, MCP_END, MCP_TABLE, mcp_block, resolve_binary, toolkit_mcp_block   # assets.py:15, :16, :19, :93, :52, :60
from parrot.knowledge.wiki.codex.installer import install_codex_integration, _install_mcp   # installer.py:202, :110
from parrot.knowledge.wiki.project import WikiRemoteConfig, load_effective_config  # TASK-3351; installer.py:12 already imports load_effective_config
from parrot.knowledge.wiki.codex.cli import codex as codex_group                    # codex/cli.py (group); install() :81
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
MCP_BEGIN = "# >>> parrot-wiki Codex MCP >>>"; MCP_END = "# <<< parrot-wiki Codex MCP <<<"   # :15-16
MCP_TABLE = "mcp_servers.wikitoolkit"                                                     # :19
def resolve_binary(root: Path, name: str) -> str                                          # :52
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str             # :60
def mcp_block(root: Path, toolkit_block: str = "") -> str:                                # :93-116 (anchor 1×) — lines: MCP_BEGIN / f"[{MCP_TABLE}]" / f"command = {json.dumps(resolve_binary(root,'wikitoolkit'))}" / 'args = ["mcp"]' / 'default_tools_approval_mode = "approve"' / (toolkit_block) / MCP_END
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _install_mcp(root: Path) -> str                                                       # :110-168 (anchor `^def _install_mcp(` 1×) — `toolkit_block = assets.toolkit_mcp_block(root, sections)` (1×) then `assets.mcp_block(root, toolkit_block),` (1×) inside _upsert_marker_block(...)
def install_codex_integration(root, config=None, gitignore=True, bookstore=True, toolkits=()) -> list[str]   # :202-208 (anchor 1×) — `actions.append(_install_mcp(root))` at :254
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py
install(path_, gitignore, build_now, bookstore, tool_guards, toolkits_, all_toolkits) :81 — options :44-80; body calls `install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore, toolkits=toolkits)` (:100, 1×)
```

### Does NOT Exist
- ~~Codex `http_headers` / `env_http_headers` keys~~ — not documented (brainstorm §8); do not emit any header key.
- ~~`transport = "http"` key in Codex tables~~ — `url` alone selects the HTTP transport.
- ~~`mcp_block(..., url=...)`~~ — the parameter is `remote: WikiRemoteConfig | None`.
- ~~per-table tracking for uninstall~~ — the whole marker block is regenerated/removed (installer.py:110-120 docstring).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py", "action": "MODIFY" },
    { "path": "packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_codex.py", "action": "CREATE" }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#mcp_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_install_mcp",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#install_codex_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py#install"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Default (`remote=None`) output byte-identical to today (AC14) — `test_codex_installer_conventions.py` guards it.
- Values must be TOML-escaped via `json.dumps` (already the pattern for `command`).
- The installer's `_validate_toml` runs on the result — keep the block valid TOML.

---

## Implementation Blueprint

### Steps (in order)
1. `mcp_block(remote=)` — *why*: block shape in one place.
2. Thread through `_install_mcp` and `install_codex_integration` — *why*: reconciliation stays wholesale.
3. CLI flags — *why*: parity with Claude.
4. Tests; `ruff check`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def mcp_block(root: Path, toolkit_block: str = "") -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE the signature (assets.py:93) with:
def mcp_block(root: Path, toolkit_block: str = "", *, remote: "WikiRemoteConfig | None" = None) -> str:
# REPLACE the `lines = [...]` construction (assets.py:~104-110) with:
    if remote is not None:
        lines = [MCP_BEGIN, f"[{MCP_TABLE}]", f"url = {json.dumps(remote.url)}",
                 f"bearer_token_env_var = {json.dumps(remote.token_env)}", 'default_tools_approval_mode = "approve"']
    else:
        command = json.dumps(resolve_binary(root, "wikitoolkit"))
        lines = [MCP_BEGIN, f"[{MCP_TABLE}]", f"command = {command}", 'args = ["mcp"]', 'default_tools_approval_mode = "approve"']
# Add `from parrot.knowledge.wiki.project import WikiRemoteConfig` under TYPE_CHECKING (assets.py:8 already has `from typing import TYPE_CHECKING`).
```
**Why**: the `else` branch is today's code verbatim (AC14); the remote branch uses the two Codex keys verified in the brainstorm and nothing else.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '^def _install_mcp(root: Path) -> str:' installer.py) — REPLACE signature with:
def _install_mcp(root: Path, *, remote: Optional["WikiRemoteConfig"] = None) -> str:
# occurrences: 1 (verified: grep -c '        assets.mcp_block(root, toolkit_block),' installer.py) — REPLACE with:
        assets.mcp_block(root, toolkit_block, remote=remote),
# occurrences: 1 (verified: grep -c '^def install_codex_integration(' installer.py) — add `remote: Optional["WikiRemoteConfig"] = None,` after `toolkits: Sequence[str] = (),` (:207) and change `actions.append(_install_mcp(root))` (:254, 1×) to `actions.append(_install_mcp(root, remote=remote))`.
# Extend the existing import (installer.py:12) with WikiRemoteConfig.
```
**Why**: the marker block is regenerated wholesale on every run, so switching shapes needs no migration logic.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore, toolkits=toolkits)' codex/cli.py)
# Add options above `def install(` (next to the existing ones, cli.py:44-80):
@click.option("--remote", "use_remote", is_flag=True, help="Register wikitoolkit as a native HTTP MCP (url + bearer_token_env_var). NOTE: Codex cannot send X-Wiki-Actor; the stdio pass-through is recommended.")
@click.option("--remote-url", default=None, help="Remote wiki mount URL (default: remote.url from .parrot/wiki.json).")
@click.option("--token-env", default=None, help="Env var with the bearer token (default: remote.token_env or WIKITOOLKIT_TOKEN).")
# Signature: add `use_remote: bool, remote_url: Optional[str], token_env: Optional[str],`. Body: same `remote = …` resolution block as TASK-3365 (ClickException when --remote has no source), then:
        actions = install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore, toolkits=toolkits, remote=remote)
```
**Why**: identical UX to the Claude installer so docs can describe one flow.

### FILL IN checklist
- [ ] `remote` resolution block copied from TASK-3365 (or shared helper in `project.py` if both tasks agree — keep it duplicated if TASK-3365 is not merged yet).
- [ ] Help text mentions the header limitation (AC16 pointer).

---

## Acceptance Criteria

- [ ] `parrot codex install --remote --remote-url https://h/mcp/w --token-env WT` produces a `.codex/config.toml` whose parsed `mcp_servers.wikitoolkit == {"url": "https://h/mcp/w", "bearer_token_env_var": "WT", "default_tools_approval_mode": "approve"}` (no `command`/`args`); re-run reports "already current".
- [ ] `--remote` without a source → `ClickException`; with `remote` in `wiki.json` uses it.
- [ ] `parrot codex uninstall` removes the managed block entirely.
- [ ] Without `--remote`, the block is byte-identical to today (`test_codex_installer_conventions.py` passes).
- [ ] `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_codex.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_codex_installer_conventions.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_codex.py
import tomllib, pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.codex.cli import codex
from parrot.knowledge.wiki.project import WikiProjectConfig, save_project_config


def _table(root):
    return tomllib.loads((root / ".codex" / "config.toml").read_text())["mcp_servers"]["wikitoolkit"]


def test_remote_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); (tmp_path / ".parrot").mkdir(); save_project_config(tmp_path, WikiProjectConfig(wiki_name="w"))
    args = ["install", "--remote", "--remote-url", "https://h/mcp/w", "--token-env", "WT", "--no-bookstore"]  # FILL IN: exact negative flags (codex/cli.py:44-80)
    assert CliRunner().invoke(codex, args).exit_code == 0
    assert _table(tmp_path) == {"url": "https://h/mcp/w", "bearer_token_env_var": "WT", "default_tools_approval_mode": "approve"}
    before = (tmp_path / ".codex" / "config.toml").read_bytes()
    r = CliRunner().invoke(codex, args); assert r.exit_code == 0 and "already current" in r.output
    assert (tmp_path / ".codex" / "config.toml").read_bytes() == before


def test_remote_missing_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path); (tmp_path / ".parrot").mkdir(); save_project_config(tmp_path, WikiProjectConfig(wiki_name="w"))
    assert CliRunner().invoke(codex, ["install", "--remote"]).exit_code != 0
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-3351 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — read `mcp_block` (:93-116) and `_install_mcp` (:110-168) in full
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
