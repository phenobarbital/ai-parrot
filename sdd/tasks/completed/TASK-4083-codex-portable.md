# TASK-4083: Codex host: Windows script paths + --portable emission (assets, bookstore, installer, cli)

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4071
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 for the **Codex** host (all of (a)–(d); (e) is Google-only). Codex's managed
configuration lives in `<root>/.codex/config.toml` inside a marker block
(`# >>> parrot-wiki Codex MCP >>>`), with a separate bookstore marker block, plus
`<root>/.codex/rules/parrot-wiki.rules`. Today:
- `resolve_binary` (codex/assets.py:55) probes `<root>/.venv/bin/<name>` only — no Windows branch;
- toolkit tables pin an absolute `--config` (codex/assets.py:80, :87) — **FEAT-556 added that pin
  because Codex's server cwd is unreliable** (the docstring at :74-77: "so `parrot mcp-local`
  resolves the toolkit regardless of the cwd Codex starts the server from");
- the bookstore block pins `command = sys.executable` + absolute `cwd` (codex/bookstore.py:43, :45);
- the rules block adds absolute-path prefix rules (codex/assets.py:138-142).
- FEAT-569 (a6340733f) added `parrot codex install --remote`: `mcp_block(…, remote=…)` emits a
  `url` + `bearer_token_env_var` wikitoolkit table (codex/assets.py:111-118) instead of the stdio one.

This task adds the Windows branch via `parrot.launcher.script_path` (TASK-4071), a keyword-only
`portable` on every emitter, `--portable/--no-portable` on `parrot codex install`, and the same
mode rule as the Claude host (TASK-4082):
- **requested mode wins**: `--portable` / `--no-portable` land exactly that form (Codex regenerates the
  whole managed block on install, so this is automatic once the emitters take `portable`);
- flag absent → **keep the current form**, inferred from the stdio wikitoolkit table inside the managed
  block (baked table → baked; a fresh install is byte-identical to today);
- *[spec rev 0.5 C24 / D7]* `--remote` (FEAT-569) composes with `--portable`: `--remote` decides only the
  wikitoolkit table (url table, `codex/assets.py:111-118`). When that table is http, url-only, absent or
  foreign, the mode is inferred from the managed `parrot-*` tables (portable iff `args[-1] == PORTABLE_TOOLKIT_CONFIG`;
  no block / no `parrot-*` table → baked), so a url table cannot turn a portable install baked;
- **sticky for `parrot toolkits`**: `reconcile_toolkit_tables` — which `mcp/hosts.py::CodexAdapter.reconcile`
  calls (hosts.py:167-170) — preserves the wikitoolkit table verbatim (FEAT-570 AC5) and must emit
  toolkit tables in the same form as the `parrot-*` tables it finds there *[rev 0.5]*. `mcp/hosts.py` is NOT modified.
- Codex ownership is structural (inside the marker block = ours); foreign tables outside the block
  keep being warned-and-omitted (`_toolkit_sections`, codex/installer.py:144-175) — unchanged.

---

## Readiness review — 2026-10-19 (dev 9f51c7735)
- Refreshed against dev 9f51c7735: `codex/assets.py`, `installer.py`, `cli.py` anchors shifted (a6340733f `--remote`); blueprint now keeps the FEAT-569 `remote=` plumbing (`mcp_block`/`_install_mcp`/`install_codex_integration` signatures, else-branch-only command replacement, call sites, CLI option/param/kwarg positions); `import os` confirmed in `local_cli.py`; one Validation Command added. `bookstore.py` unchanged.
- Resolved by spec rev 0.5 (2026-10-20):
  - C24 `--remote` × `--portable` — `--remote` decides only the wikitoolkit table; when it is http, url-only, absent or foreign, `_current_portable_mode` infers the mode from the managed `parrot-*` tables (`args[-1] == PORTABLE_TOOLKIT_CONFIG`), and `reconcile_toolkit_tables` uses it; new test `test_remote_portable_sticky`.
  - C24 `mcp/local_cli.py` — stays in this task's scope: the NOT-in-scope and Does-NOT-Exist exclusions are dropped, a Scope bullet is added, and the new test `test_mcp_local_parrot_project_root` covers it.
  - C24 / D7 detail (dev 2026-10-20): `--remote` decides only the `[mcp_servers.wikitoolkit]` table (url table, `codex/assets.py:111-118`). The mode for the toolkit tables, rules and bookstore is the explicit flag or, when absent, `_current_portable_mode`: a stdio wikitoolkit table decides it (`_wikitoolkit_table_is_portable`); an http, url-only, absent or foreign table hands over to `_toolkit_tables_are_portable(block_body)` — the managed block body parsed with `tomllib`, portable iff ANY `[mcp_servers.parrot-<name>]` table has `args[2] == "--config"` and `args[3] == assets.PORTABLE_TOOLKIT_CONFIG` (PR #1746 review). A url table therefore never turns a portable install baked, and a portable install with no `parrot-*` table stays portable on a plain re-install (the stdio table decides).
  - D16 (`mcp/local_cli.py` scope) is resolved by the C24 bullet above — implement it.
- Anchors re-verified on dev 2026-10-20: all unchanged (`resolve_binary` :55, `install_codex_integration` :322).

## Scope

- `codex/assets.py`: `resolve_binary` via `script_path`; `PORTABLE_TOOLKIT_CONFIG`; `portable=` on
  `toolkit_mcp_block`, `mcp_block` (stdio branch only; its FEAT-569 `remote` branch is unchanged), `rules_block`.
- `codex/bookstore.py`: `portable=` on `mcp_block` (portable: `command = "bookstore"`,
  `args = ["mcp"]`, no `cwd` line) and `install_bookstore`.
- `codex/installer.py`: `_current_portable_mode` (*[spec rev 0.5 C24 / D7]* http, url-only, absent or foreign
  wikitoolkit table → mode inferred from the managed `parrot-*` tables via `_toolkit_tables_are_portable`),
  `_wikitoolkit_table_is_portable`;
  `reconcile_toolkit_tables(root, *, portable: Optional[bool] = None)`; `_install_mcp` (keeping its
  `remote` keyword) / `_install_rules` take `*, portable: bool = False`;
  `install_codex_integration(…, remote=None, portable: Optional[bool] = None)`.
- `codex/cli.py`: `--portable/--no-portable` (default unset).
- `mcp/local_cli.py`: `parrot mcp-local` honours `PARROT_PROJECT` as the project root, `Path.cwd()`
  otherwise (*[spec rev 0.5 C24]* in this task's scope).
- Write `packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py`.

**NOT in scope**:
- `mcp/hosts.py` (unchanged — `CodexAdapter.reconcile(root)` → `reconcile_toolkit_tables(root)` is the inference path).
- Claude / Google hosts (TASK-4081/4082, TASK-4084).
- AGENTS.md / skill / conventions blocks (contain no paths).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | Windows branch; `portable=` on toolkit/wikitoolkit/rules emitters |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py` | MODIFY | Portable bookstore block (`bookstore mcp`, no `sys.executable`, no `cwd`) |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | Tri-state mode resolution; sticky `reconcile_toolkit_tables` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` | MODIFY | `--portable/--no-portable` on `parrot codex install` |
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | MODIFY | `parrot mcp-local` honours `PARROT_PROJECT` as the project root (portable `--config` resolution) |
| `packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py` | CREATE | Emission, transitions, stickiness (incl. `--remote` × `--portable`), Windows branch, PARROT_PROJECT root |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (branch `dev` @ `6c4ca5482`, 2026-10-05; line anchors refreshed against `9f51c7735`, 2026-10-19).
> The implementing agent MUST use these exact imports, class names, and method signatures.
> **DO NOT** invent, guess, or assume any import, attribute, or method not listed here.
> If you need something not listed, VERIFY it exists first with `grep` or `read`.

### Verified Imports
```python
from parrot.launcher import script_path   # CREATED BY TASK-4071 — script_path(venv: Path, name: str) -> Path
from parrot.knowledge.wiki.codex import assets                            # codex/installer.py:11
from parrot.knowledge.wiki.codex.installer import (                       # test-side
    install_codex_integration, reconcile_toolkit_tables, _install_mcp,
)
from parrot.knowledge.wiki.codex.cli import codex                         # codex/cli.py:37 (click group)
from parrot.knowledge.wiki.codex import bookstore                         # codex/bookstore.py
import tomllib                                                            # stdlib; already used in codex/installer.py:7
from parrot.knowledge.wiki.project import WikiRemoteConfig                # codex/installer.py:14 (already imported, FEAT-569); codex/assets.py:11 (TYPE_CHECKING)
from parrot.mcp.local_cli import mcp_local                                # mcp/local_cli.py:136-164 (click command "mcp-local")
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
MCP_BEGIN = "# >>> parrot-wiki Codex MCP >>>"; MCP_END = "# <<< parrot-wiki Codex MCP <<<"   # lines 16-17
MCP_TABLE = "mcp_servers.wikitoolkit"                                     # line 20
def resolve_binary(root: Path, name: str) -> str:                         # line 55; probe line 57: root / ".venv" / "bin" / name
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str:  # line 63-93
#   command = json.dumps(resolve_binary(root, "parrot")) line 79; config_path = str(root / ".parrot" / "mcp-toolkits.yaml") line 80
#   f"args = {json.dumps(['mcp-local', name, '--config', config_path])}" line 87; env inline table lines 89-91
def mcp_block(root: Path, toolkit_block: str = "", *, remote: "WikiRemoteConfig | None" = None) -> str:  # line 96-132 (FEAT-569)
#   if remote is not None: url/bearer_token_env_var table lines 111-118;
#   else: command = json.dumps(resolve_binary(root, "wikitoolkit")) line 120 (8-space indent), stdio table 121-127
def rules_block(root: Path) -> str:                                       # line 135-153 (bare patterns + resolved-path patterns)

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py
import sys                                                                # line 6
def mcp_block(root: Path) -> str:                                         # line 37-52
#   f"command = {json.dumps(sys.executable)}" line 43; 'args = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]' line 44
#   f"cwd = {json.dumps(str(root.resolve()))}" line 45; env_vars line 46; timeouts 47-48
def install_bookstore(root: Path) -> list[str]:                           # line 55; _upsert_marker_block(before, mcp_block(root), …) line 73

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _extract_toml_table(text: str, table: str) -> Optional[str]:          # line 116
def _toolkit_sections(cfg: Any, existing_tables: set[str]) -> tuple[dict[str, Any], list[str]]:  # line 144
def reconcile_toolkit_tables(root: Path) -> tuple[list[str], list[str]]:  # line 178; toolkit_block = assets.toolkit_mcp_block(root, sections) line 204 (1st of 2)
#   wikitoolkit_text = _extract_toml_table(block_body, assets.MCP_TABLE) line 210
def _install_mcp(root: Path, *, remote: Optional[WikiRemoteConfig] = None) -> str:  # line 241 (FEAT-569); toolkit_block = … line 268 (2nd of 2);
#   assets.mcp_block(root, toolkit_block, remote=remote) line 273
def _install_rules(root: Path) -> str:                                    # line 291; assets.rules_block(root) line 296
def install_codex_integration(root, config=None, gitignore=True, bookstore=True, remote=None) -> list[str]:  # line 322-328
#   save_project_config line 349; _install_mcp(root, remote=remote) line 360; _install_rules(root) line 361; install_bookstore(root) line 367

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py
#   "--bookstore/--no-bookstore" line 58; "--tool-guards/--no-tool-guards" line 64;
#   "--remote" / "--remote-url" / "--token-env" options lines 69-85 (FEAT-569); def install( line 86;
#   `    token_env: Optional[str],` line 94;
#   install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore, remote=remote) line 112

# packages/ai-parrot/src/parrot/mcp/hosts.py:167-170 — CodexAdapter.reconcile -> reconcile_toolkit_tables(root)

# packages/ai-parrot/src/parrot/mcp/local_cli.py
import os                                                                 # line 18 (already imported)
def _print_toolkit_list(root: Path, config_path: Path | None = None) -> None:  # line 110 (the `--list` path)
def mcp_local(name, config_path, include, exclude, list_toolkits) -> None:  # line 164; `--config` click.Path option line 139;
#   root = Path.cwd() line 183; _print_toolkit_list(root, config_path) line 186
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py:90 — load_toolkits_config(root, config_path=None):
#   an explicit config_path is used as given (Path(config_path)), so a relative one resolves against the process cwd
```

### Does NOT Exist
- ~~Windows venv handling in `codex/`~~ — added here via `script_path` only.
- ~~a `portable` parameter / `--portable` flag in `codex/`~~ — new.
- ~~Codex variable expansion (`${VAR}`) in `config.toml` values~~ — NOT verified; spike S3 (TASK-4069) decides. Never assume it.
- ~~a per-entry managed-shape check for Codex~~ — ownership is structural (codex/installer.py:186-187); do not add one.
- ~~`_wikitoolkit_table_is_portable`, `_toolkit_tables_are_portable`, `_current_portable_mode`~~ — new private helpers *[rev 0.5]*.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/src/parrot/mcp/local_cli.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#resolve_binary",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#toolkit_mcp_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#mcp_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#rules_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#MCP_TABLE",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py#MCP_BEGIN",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py#mcp_block",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py#install_bookstore",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_extract_toml_table",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_toolkit_sections",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#reconcile_toolkit_tables",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_install_mcp",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#_install_rules",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py#install_codex_integration",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py#install",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py#codex",
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#CodexAdapter.reconcile",
    "sym:packages/ai-parrot/src/parrot/mcp/local_cli.py#mcp_local"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# codex/installer.py:206-210 — how reconcile already isolates the wikitoolkit table text;
# the stickiness rule parses exactly this text:
if assets.MCP_BEGIN in before:
    _, _, rest = before.partition(assets.MCP_BEGIN)
    block_body = rest.partition(assets.MCP_END)[0] if assets.MCP_END in rest else rest
    wikitoolkit_text = _extract_toml_table(block_body, assets.MCP_TABLE)
```

### Key Constraints
- Default output (no `portable`) is byte-identical to today on POSIX — the existing test
  `tests/knowledge/wiki/test_codex_toolkit_reconcile.py` monkeypatches `assets.resolve_binary(root, name)`,
  so keep that signature exactly.
- Portable output contains no absolute path in `command`, `args`, `cwd` or `env` (spec §5) and is
  identical for two different roots.
- **Codex cwd is unreliable** — that is why FEAT-556 pinned `--config`. A relative
  `.parrot/mcp-toolkits.yaml` only works if Codex starts project-scoped servers in the project root.
  Spike S3 (TASK-4069, `sdd/state/FEAT-633/spikes/`) decides the portable `--config`/`env` shape;
  until then the blueprint leaves it as a bounded FILL IN (shared brief: emit a `PARROT_PROJECT`
  variable reference ONLY if the host expands variables, otherwise omit `cwd` and rely on the cwd).
- Inference parses the preserved wikitoolkit table with `tomllib`; a parse failure means "baked"
  (never raise from inference — `_validate_toml` already guards real corruption).
- *[spec rev 0.5 C24 / D7]* When the managed block's wikitoolkit table is http, url-only (no `command`),
  absent or foreign, inference parses the managed block body with `tomllib` and reads its `parrot-*`
  tables instead (`_toolkit_tables_are_portable(block_body)`; portable iff
  `args[-1] == PORTABLE_TOOLKIT_CONFIG`). **Resolved (PR #1746 review, 2026-10-20)**: if **any** managed `parrot-*` table is portable, the
  mode is portable, because the user opted in at some point and the mode is sticky; the reconcile then
  rewrites every managed table in that mode. With no managed `parrot-*` table the mode is baked, so a fresh
  install stays baked (spec default).
- `print(..., file=sys.stderr)` for warnings stays as today (codex/installer.py:266).
- `--remote` (FEAT-569) keeps its own wikitoolkit table: `portable` only changes the stdio (else)
  branch of `mcp_block`; every call that passes `remote=remote` today keeps it.
  *[rev 0.5]* D7: with `--remote`, toolkit tables, rules and bookstore still follow the resolved mode.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/hosts.py:120-173` — CodexAdapter (toolkit-only, structural ownership).
- `tests/knowledge/wiki/test_codex_toolkit_reconcile.py` — FEAT-570 AC5 behaviour that must hold.

---

## Implementation Blueprint

### Steps (in order)
1. `assets.py`: import `script_path`, rewrite the probe, add `PORTABLE_TOOLKIT_CONFIG`, add `portable`
   to the three emitters — *why*: spec §3 M5(a)/(b).
2. `bookstore.py`: portable block + `install_bookstore(portable=)` — *why*: spec §5 "bookstore carries
   no `sys.executable`" in portable mode.
3. `installer.py`: inference helpers, sticky `reconcile_toolkit_tables`, thread `portable` — *why*:
   shared-brief STICKY rule; `parrot toolkits` passes through `reconcile_toolkit_tables`; spec rev 0.5
   C24 (`--remote` × `--portable`: `parrot-*` inference).
4. `cli.py`: the tri-state flag — *why*: spec §2 New Public Interfaces.
5. `local_cli.py`: `PARROT_PROJECT` root — *why*: spec rev 0.5 C24 keeps it in this task's scope.
6. Tests — *why*: spec §4 `test_portable_entries_no_abs_paths`, `test_default_emission_unchanged`;
   C24 `test_remote_portable_sticky`, `test_mcp_local_parrot_project_root`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from typing import TYPE_CHECKING' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# AFTER — `from typing import TYPE_CHECKING` (verified: codex/assets.py:8)

from parrot.launcher import script_path  # created by TASK-4071 (stdlib-only module)

# occurrences: 1 (verified: grep -c 'RULES_PATH = Path(".codex/rules/parrot-wiki.rules")' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# AFTER — `RULES_PATH = Path(".codex/rules/parrot-wiki.rules")` (verified: codex/assets.py:22)
#: Relative toolkit config used by portable toolkit tables (FEAT-633).
PORTABLE_TOOLKIT_CONFIG = ".parrot/mcp-toolkits.yaml"

# occurrences: 1 (verified: grep -c '    venv_binary = root / ".venv" / "bin" / name' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — (verified: codex/assets.py:57)
    venv_binary = script_path(root / ".venv", name)

# occurrences: 1 (verified: grep -c 'def toolkit_mcp_block(root: Path, sections: dict\[str, ToolkitSection\]) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — signature (:63) + lines 79-80 (`    command = json.dumps(resolve_binary(root, "parrot"))`, occurrences 1;
#           `    config_path = str(root / ".parrot" / "mcp-toolkits.yaml")`, occurrences 1). Docstring: add `portable`.
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection], *, portable: bool = False) -> str:
    if portable:
        command = json.dumps("parrot")
        config_path = PORTABLE_TOOLKIT_CONFIG
    else:
        command = json.dumps(resolve_binary(root, "parrot"))
        config_path = str(root / ".parrot" / "mcp-toolkits.yaml")
    # (loop at lines 81-93 unchanged, except:)
    # FILL IN: in portable mode, whether each table also gets a project pin — e.g. an `env`
    # `PARROT_PROJECT` variable reference or `env_vars = ["PARROT_PROJECT"]` pass-through — bounded by
    # spike S3 (TASK-4069) evidence on Codex's server cwd/env and spec §5 (no absolute path anywhere,
    # identical across roots). With no S3 evidence of variable expansion: add nothing.

# occurrences: 1 (verified: grep -c 'def mcp_block(root: Path, toolkit_block: str = "", \*, remote: "WikiRemoteConfig | None" = None) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — signature (:96; keep `remote`, FEAT-569) and the ELSE-branch line only
#           `        command = json.dumps(resolve_binary(root, "wikitoolkit"))` (8-space indent, :120, occurrences 1);
#           the `if remote is not None:` branch (:111-118) stays unchanged
def mcp_block(
    root: Path, toolkit_block: str = "", *, remote: "WikiRemoteConfig | None" = None, portable: bool = False
) -> str:
        command = json.dumps("wikitoolkit" if portable else resolve_binary(root, "wikitoolkit"))

# occurrences: 1 (verified: grep -c 'def rules_block(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — signature (:135) and wrap the resolved-pattern loop (lines 138-142)
def rules_block(root: Path, *, portable: bool = False) -> str:
    """Return allow rules for every supported WikiToolkit CLI surface.

    Portable mode emits only the bare-name patterns (no machine-specific path).
    """
    patterns = [["wikitoolkit"], ["parrot", "wiki"]]
    if not portable:
        resolved_wiki = resolve_binary(root, "wikitoolkit")
        resolved_parrot = resolve_binary(root, "parrot")
        for pattern in ([resolved_wiki], [resolved_parrot, "wiki"]):
            if pattern not in patterns:
                patterns.append(pattern)
    # (rest unchanged)
```

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def mcp_block(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py)
# REPLACE — whole function (verified: codex/bookstore.py:37-52; anchor
#           `            f"command = {json.dumps(sys.executable)}",` at :43, occurrences 1)
def mcp_block(root: Path, *, portable: bool = False) -> str:
    """Managed bookstore MCP table.

    Baked (default): the installer interpreter + explicit target cwd (unchanged).
    Portable (FEAT-633): the ``bookstore`` console script, no ``sys.executable`` and no ``cwd``.
    """
    if portable:
        head = ['command = "bookstore"', 'args = ["mcp"]']
    else:
        head = [
            f"command = {json.dumps(sys.executable)}",
            'args = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]',
            f"cwd = {json.dumps(str(root.resolve()))}",
        ]
    return "\n".join(
        [
            MCP_BEGIN,
            "[mcp_servers.bookstore]",
            *head,
            'env_vars = ["PARROT_LIBRARY_DIR", "PARROT_HOME", ' '"PARROT_BOOKSTORE_LLM", "PARROT_BOOKSTORE_LLM_LIGHT"]',
            "startup_timeout_sec = 30",
            "tool_timeout_sec = 180",
            MCP_END,
            "",
        ]
    )

# occurrences: 1 (verified: grep -c 'def install_bookstore(root: Path) -> list\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py)
# REPLACE — signature (:55) and `        after = _upsert_marker_block(before, mcp_block(root), MCP_BEGIN, MCP_END)` (:73, occurrences 1)
def install_bookstore(root: Path, *, portable: bool = False) -> list[str]:
        after = _upsert_marker_block(before, mcp_block(root, portable=portable), MCP_BEGIN, MCP_END)
```
**Why**: the baked lines are reproduced verbatim (default unchanged); ownership stays structural, so
no detection change is needed — the marker block is replaced wholesale (requested mode wins).

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'def _extract_toml_table(text: str, table: str) -> Optional\[str\]:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# AFTER — insert below the end of `_extract_toml_table` (its last line `    return "".join(lines[start:end])`,
#         verified: codex/installer.py:116-141), i.e. just above `def _toolkit_sections(` (:144)
def _wikitoolkit_table_is_portable(table_text: Optional[str]) -> bool:
    """Whether a preserved ``[mcp_servers.wikitoolkit]`` table uses the bare portable command."""
    if not table_text:
        return False
    try:
        doc = tomllib.loads(table_text)
    except tomllib.TOMLDecodeError:
        return False
    entry = doc.get("mcp_servers", {}).get("wikitoolkit", {})
    return isinstance(entry, dict) and entry.get("command") == "wikitoolkit"


def _toolkit_tables_are_portable(block_body: Optional[str]) -> bool:  # [rev 0.5] D7 sub-step
    """Portable iff ANY managed ``parrot-*`` table uses the relative config (PR #1746 review: sticky).

    Used only when the wikitoolkit table cannot decide (http, url-only, absent or foreign).
    """
    if not block_body:
        return False
    try:
        servers = tomllib.loads(block_body).get("mcp_servers", {})
    except tomllib.TOMLDecodeError:
        return False
    tables = [entry for key, entry in servers.items() if key.startswith("parrot-") and isinstance(entry, dict)]
    return any(
        isinstance(t.get("args"), list) and len(t["args"]) >= 4 and t["args"][2] == "--config"
        and t["args"][3] == assets.PORTABLE_TOOLKIT_CONFIG
        for t in tables
    )


def _current_portable_mode(root: Path) -> bool:
    """Infer the current mode from the managed block (FEAT-633, sticky).

    A stdio wikitoolkit table (one with a ``command``) decides it via
    :func:`_wikitoolkit_table_is_portable`. When that table is http, url-only, absent or foreign
    (spec rev 0.5 C24 / D7 — ``--remote`` decides only that table), the mode is inferred from the
    managed ``parrot-*`` tables via :func:`_toolkit_tables_are_portable`.
    """
    # FILL IN: read root/".codex"/"config.toml" if present, isolate the managed block body exactly like
    # reconcile_toolkit_tables (lines 206-210). Stdio wikitoolkit table → _wikitoolkit_table_is_portable(...);
    # otherwise return _toolkit_tables_are_portable(block_body) — bounded by spec rev 0.5 C24 / D7,
    # "no new state file" (shared brief) and never raising. Mixed managed tables → portable if ANY is portable; none → False (Key Constraints, resolved).
    raise NotImplementedError

# occurrences: 1 (verified: grep -c 'def reconcile_toolkit_tables(root: Path) -> tuple\[list\[str\], list\[str\]\]:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# REPLACE — signature (:178); docstring gains: "portable: None infers via _current_portable_mode
#           (sticky, spec rev 0.5 C24 / D7 — the `parrot toolkits` path via mcp/hosts.py::CodexAdapter.reconcile)."
def reconcile_toolkit_tables(root: Path, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]:
# REPLACE the toolkit_block computation (line 204, first of 2 occurrences of
# `    toolkit_block = assets.toolkit_mcp_block(root, sections)`; context:
#     sections, warnings = _toolkit_sections(cfg, existing_tables)
#     toolkit_block = assets.toolkit_mcp_block(root, sections)
#     wikitoolkit_text: Optional[str] = None
# ) with — the wikitoolkit_text extraction (lines 206-210) stays where it is:
    if portable is None:
        portable = _current_portable_mode(root)  # reads config.toml before this function writes it
    toolkit_block = assets.toolkit_mcp_block(root, sections, portable=portable)

# occurrences: 1 (verified: grep -c 'def _install_mcp(root: Path, \*, remote: Optional\[WikiRemoteConfig\] = None) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# REPLACE — signature (:241; keep `remote`, FEAT-569), the second `    toolkit_block = assets.toolkit_mcp_block(root, sections)` (:268; context line above:
#           `        print(warning, file=sys.stderr)`) and `        assets.mcp_block(root, toolkit_block, remote=remote),` (:273, occurrences 1)
def _install_mcp(root: Path, *, remote: Optional[WikiRemoteConfig] = None, portable: bool = False) -> str:
    toolkit_block = assets.toolkit_mcp_block(root, sections, portable=portable)
        assets.mcp_block(root, toolkit_block, remote=remote, portable=portable),

# occurrences: 1 (verified: grep -c 'def _install_rules(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# REPLACE — signature (:291) and `        assets.rules_block(root),` (:296, occurrences 1)
def _install_rules(root: Path, *, portable: bool = False) -> str:
        assets.rules_block(root, portable=portable),

# occurrences: 1 (verified: grep -c '    remote: Optional\[WikiRemoteConfig\] = None,' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# AFTER — `    remote: Optional[WikiRemoteConfig] = None,` in install_codex_integration's signature
#         (verified: codex/installer.py:327; it follows `    bookstore: bool = True,` at :326)
    portable: Optional[bool] = None,
# Docstring Args: portable — True: bare launcher commands, False: baked absolute paths, None: keep current form
#   (inferred from the managed parrot-* tables, never the wikitoolkit table — [rev 0.5] D7).

# occurrences: 1 (verified: grep -c '    save_project_config(root, config)' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# AFTER — insert below `    save_project_config(root, config)` (verified: codex/installer.py:349) — it only writes
#         .parrot/wiki.json, so inferring after it still precedes every .codex/ write
    if portable is None:
        portable = _current_portable_mode(root)

# REPLACE — call sites (each occurrences 1): :360 (already passes `remote=remote` — keep it), :361, :367
    actions.append(_install_mcp(root, remote=remote, portable=portable))
    actions.append(_install_rules(root, portable=portable))
        actions.extend(install_bookstore(root, portable=portable))
```
**Why**: Codex already regenerates the whole managed block from config on install, so passing the
requested mode is "requested wins"; only `reconcile_toolkit_tables` (shared with `parrot toolkits`)
needs inference.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "--token-env",' packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py)
# AFTER — insert a new decorator after the option block that starts with `    "--token-env",`
#         (verified: codex/cli.py:81-85, the last of the FEAT-569 `--remote`/`--remote-url`/`--token-env` options),
#         i.e. directly above `def install(` (cli.py:86)
@click.option(
    "--portable/--no-portable",
    default=None,
    help="Emit bare launcher commands with no absolute paths (committable .codex/config.toml). "
    "Default: keep the current form (baked absolute paths on a fresh install).",
)

# occurrences: 1 (verified: grep -c '    token_env: Optional\[str\],' packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py)
# AFTER — (verified: codex/cli.py:94)
    portable: Optional[bool],

# occurrences: 1 (verified: grep -c '        actions = install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore, remote=remote)' packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py)
# REPLACE — (verified: codex/cli.py:112); keep `remote=remote` (FEAT-569)
        actions = install_codex_integration(
            root, config, gitignore=gitignore, bookstore=bookstore, remote=remote, portable=portable
        )
```

### `packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py` (CREATE)
```python
"""FEAT-633 TASK-4083 — Codex: Windows script paths + portable emission + stickiness."""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Any, Iterator

import pytest
from click.testing import CliRunner
from parrot.knowledge.wiki.codex import assets, bookstore
from parrot.knowledge.wiki.codex.installer import install_codex_integration, reconcile_toolkit_tables
from parrot.knowledge.wiki.project import WikiRemoteConfig  # [rev 0.5] C24 / D7
from parrot.mcp.local_cli import mcp_local


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    for name in ("wikitoolkit", "parrot"):
        (venv_bin / name).write_text("")
    (tmp_path / ".parrot").mkdir()
    (tmp_path / ".parrot" / "mcp-toolkits.yaml").write_text(
        "toolkits:\n  memory:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: true\n"
    )
    return tmp_path


def _servers(root: Path) -> dict:
    return tomllib.loads((root / ".codex" / "config.toml").read_text())["mcp_servers"]


def test_portable_entries_no_abs_paths(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    for text in _strings(_servers(root)):
        assert not os.path.isabs(text) and str(root) not in text, text
    block = tomllib.loads(bookstore.mcp_block(root, portable=True).split("\n", 1)[1])
    assert block["mcp_servers"]["bookstore"]["command"] == "bookstore"
    assert "cwd" not in block["mcp_servers"]["bookstore"] and sys.executable not in str(block)
    assert str(root) not in (root / assets.RULES_PATH).read_text()


def test_default_emission_unchanged(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False)
    servers = _servers(root)
    assert servers["wikitoolkit"]["command"] == str(root / ".venv" / "bin" / "wikitoolkit")
    assert servers["parrot-memory"]["args"][-1] == str(root / ".parrot" / "mcp-toolkits.yaml")


def test_portable_transitions_both_ways(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    assert _servers(root)["wikitoolkit"]["command"] == "wikitoolkit"
    install_codex_integration(root, gitignore=False, bookstore=False, portable=False)
    assert _servers(root)["wikitoolkit"]["command"] == str(root / ".venv" / "bin" / "wikitoolkit")


def test_reconcile_sticky(root: Path) -> None:
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    install_codex_integration(root, gitignore=False, bookstore=False)  # flag absent → keep portable
    assert _servers(root)["wikitoolkit"]["command"] == "wikitoolkit"
    with (root / ".parrot" / "mcp-toolkits.yaml").open("a") as fh:  # a toolkit added later by `parrot toolkits`
        fh.write("  scraping:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: true\n")
    reconcile_toolkit_tables(root)  # the `parrot toolkits` path (mcp/hosts.py::CodexAdapter.reconcile)
    assert _servers(root)["parrot-scraping"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_remote_portable_sticky(root: Path) -> None:
    """Spec rev 0.5 C24: --remote decides only the wikitoolkit table; the mode comes from the parrot-* tables."""
    remote = WikiRemoteConfig(url="https://h/mcp/w", token_env="WT")
    install_codex_integration(root, gitignore=False, bookstore=False, remote=remote, portable=True)
    assert "url" in _servers(root)["wikitoolkit"] and "command" not in _servers(root)["wikitoolkit"]
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    install_codex_integration(root, gitignore=False, bookstore=False, remote=remote)  # flag absent → keep portable
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    assert str(root) not in (root / assets.RULES_PATH).read_text()
    with (root / ".parrot" / "mcp-toolkits.yaml").open("a") as fh:  # a toolkit added later by `parrot toolkits`
        fh.write("  scraping:\n    class: tests.mcp.stub_toolkit.StubToolkit\n    enabled: true\n")
    reconcile_toolkit_tables(root)  # the mcp/hosts.py::CodexAdapter.reconcile path
    assert _servers(root)["parrot-scraping"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_mcp_local_parrot_project_root(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec rev 0.5 C24 (local_cli.py in scope): `parrot mcp-local` takes its root from PARROT_PROJECT."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PARROT_PROJECT", str(root))
    result = CliRunner().invoke(mcp_local, ["--list"])
    assert result.exit_code == 0, result.output
    assert "memory" in result.output
    monkeypatch.delenv("PARROT_PROJECT")
    assert "memory" not in CliRunner().invoke(mcp_local, ["--list"]).output  # falls back to Path.cwd()


def test_mcp_local_relative_config_resolves_against_root(root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A relative explicit ``--config`` resolves against the PARROT_PROJECT root, not the process cwd."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PARROT_PROJECT", str(root))
    result = CliRunner().invoke(mcp_local, ["--config", ".parrot/mcp-toolkits.yaml", "--list"])
    assert result.exit_code == 0, result.output
    assert "memory" in result.output


def test_remote_does_not_reset_portable_mode(root: Path) -> None:
    """[rev 0.5] D7: --remote decides only the wikitoolkit table; the mode comes from the parrot-* tables."""
    install_codex_integration(root, gitignore=False, bookstore=False, portable=True)
    remote = WikiRemoteConfig(url="https://h/mcp/w", token_env="WT")
    install_codex_integration(root, gitignore=False, bookstore=False, remote=remote)  # flag absent
    assert _servers(root)["wikitoolkit"]["url"] == "https://h/mcp/w"
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG
    assert str(root) not in (root / assets.RULES_PATH).read_text()
    reconcile_toolkit_tables(root)
    assert _servers(root)["parrot-memory"]["args"][-1] == assets.PORTABLE_TOOLKIT_CONFIG


def test_portable_root_independent(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert assets.mcp_block(a, portable=True) == assets.mcp_block(b, portable=True)
    assert bookstore.mcp_block(a, portable=True) == bookstore.mcp_block(b, portable=True)


def test_windows_scripts_branch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(assets, "script_path", lambda venv, name: venv / "Scripts" / f"{name}.exe")
    exe = tmp_path / ".venv" / "Scripts" / "parrot.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    assert assets.resolve_binary(tmp_path, "parrot") == str(exe)
```

### `packages/ai-parrot/src/parrot/mcp/local_cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    root = Path.cwd()' packages/ai-parrot/src/parrot/mcp/local_cli.py)
# REPLACE — the line `    root = Path.cwd()` (verified: packages/ai-parrot/src/parrot/mcp/local_cli.py:183)
    root = Path(os.environ.get("PARROT_PROJECT") or Path.cwd())
    if config_path is not None and not config_path.is_absolute():
        config_path = root / config_path  # resolved in the PR #1746 review (2026-10-20): same root as the default
```
**Why**: a portable toolkit entry has no absolute `--config` and Codex's server cwd is
unreliable (the very reason FEAT-556 pinned `--config` absolutely). `PARROT_PROJECT` is the
spec's root pin (spec §3 M1/M5): when a host adapter sets it in the entry's `env`, the
relative `.parrot/mcp-toolkits.yaml` resolves against the project root regardless of the
process cwd. Without `PARROT_PROJECT` the behavior is byte-for-byte today's (`Path.cwd()`).
`import os` is already present (verified: local_cli.py:18); mention the variable in
the command's docstring. This also fixes Google's portable toolkit entries (user-global
config, arbitrary cwd) — Gemini's emitter task (TASK-4084) cites this behavior but does not
own the file; this task does.

### FILL IN checklist
- [ ] `assets.py::toolkit_mcp_block` portable project pin — bounded by spike S3 (TASK-4069) evidence; spec §5 (no absolute path, root-independent).
- [x] `local_cli.py` — a relative explicit `--config` resolves against the same root (`PARROT_PROJECT`, else `Path.cwd()`); resolved in the PR #1746 review (2026-10-20), matching the acceptance criterion.
- [ ] `installer.py::_current_portable_mode` — lenient read of the managed block, `parrot-*` inference for an http/url-only/absent/foreign wikitoolkit table; bounded by spec rev 0.5 C24 and "no new state file".
- [ ] Google-style docstrings for every changed signature.

---

## Acceptance Criteria

- [ ] `resolve_binary` uses `script_path(root / ".venv", name)`; `grep -c '".venv" / "bin"' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` → 0.
- [ ] `parrot codex install --portable` writes a managed block, bookstore block and rules file with no absolute path in any field and no `sys.executable` (spec §5); output identical for two roots.
- [ ] Without `--portable`, a fresh install is byte-identical to today (spec §5 default unchanged).
- [ ] `--portable` / `--no-portable` land exactly the requested form; flag absent keeps the current form.
- [ ] `reconcile_toolkit_tables(root)` emits portable toolkit tables iff the inferred mode is portable; it still preserves the wikitoolkit table verbatim (FEAT-570 AC5); `mcp/hosts.py` unchanged.
- [ ] *[spec rev 0.5 C24]* `--remote` decides only the wikitoolkit table: when it is http, url-only, absent or foreign, the mode is inferred from the managed `parrot-*` tables, so `--remote --portable` followed by a plain `--remote` re-install or `parrot toolkits` stays portable (`test_remote_portable_sticky`).
- [ ] *[rev 0.5 D7]* `parrot codex install --remote` without `--portable/--no-portable` over a portable install keeps toolkit tables and rules portable (`test_remote_does_not_reset_portable_mode`).
- [ ] `parrot mcp-local` resolves the project root from `PARROT_PROJECT` when set, `Path.cwd()` otherwise; a relative `--config` resolves against that root (test with a tmp root + monkeypatched env — `test_mcp_local_parrot_project_root`).
- [ ] Existing Codex suites pass; `ruff check` clean on the five modified files.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_codex_installer_conventions.py -q`
- `pytest tests/knowledge/wiki/test_codex_toolkit_reconcile.py -q`
- `pytest tests/knowledge/wiki/test_codex_installer_toolkit_entries.py -q`
- `pytest tests/knowledge/wiki/test_codex_integration.py -q`
- `pytest tests/knowledge/wiki/test_codex_bookstore.py -q`
- `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_remote_codex.py -q`

---

## Test Specification

See the CREATE block above: `test_portable_entries_no_abs_paths`, `test_default_emission_unchanged`,
`test_portable_transitions_both_ways`, `test_reconcile_sticky`, `test_remote_portable_sticky`,
`test_mcp_local_parrot_project_root`, `test_portable_root_independent`, `test_windows_scripts_branch`,
*[rev 0.5]* `test_remote_does_not_reset_portable_mode` (D7).

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`python -m scripts.sdd.ensure_worktree --slug parrot-installer --feature-id FEAT-633`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in the
   per-spec index `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
5. **Update status** in `sdd/tasks/index/parrot-installer.json` → `"in-progress"`
   (set `started_at`) and commit only that index file
6. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
7. **Verify** all acceptance criteria are met — run the Validation Commands
8. **Commit the code** — stage only the files this task lists (never `git add .` / `-A`)
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4083 parrot-installer verified`
   — it moves this file to `sdd/tasks/completed/` and marks it `"done"` in the
   index; never move or copy the file by hand
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-5-5)
**Date**: 2026-10-26
**Notes**: Implemented per blueprint: script_path in resolve_binary, PORTABLE_TOOLKIT_CONFIG, portable= on toolkit/mcp/rules/bookstore emitters, tri-state --portable/--no-portable, _current_portable_mode + sticky reconcile_toolkit_tables, PARROT_PROJECT root (+ relative --config) in mcp-local. FILL IN (S3 project pin): nothing added (no evidence of variable expansion). Tests: new 9 + codex suites all pass (17 + 37), ruff clean. Test groups must run separately (packages/ai-parrot/tests vs tests/ conftest clash, pre-existing).

**Deviations from spec**: _current_portable_mode: a bare 'wikitoolkit' command is ambiguous (baked fallback when no venv binary resolves, as in test_codex_toolkit_reconcile), so when managed parrot-* tables exist they decide; otherwise the bare command means portable.
