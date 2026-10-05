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
- `resolve_binary` (codex/assets.py:54) probes `<root>/.venv/bin/<name>` only — no Windows branch;
- toolkit tables pin an absolute `--config` (codex/assets.py:79, :86) — **FEAT-556 added that pin
  because Codex's server cwd is unreliable** (the docstring at :73-76: "so `parrot mcp-local`
  resolves the toolkit regardless of the cwd Codex starts the server from");
- the bookstore block pins `command = sys.executable` + absolute `cwd` (codex/bookstore.py:43, :45);
- the rules block adds absolute-path prefix rules (codex/assets.py:124-128).

This task adds the Windows branch via `parrot.launcher.script_path` (TASK-4071), a keyword-only
`portable` on every emitter, `--portable/--no-portable` on `parrot codex install`, and the same
mode rule as the Claude host (TASK-4082):
- **requested mode wins**: `--portable` / `--no-portable` land exactly that form (Codex regenerates the
  whole managed block on install, so this is automatic once the emitters take `portable`);
- flag absent → **keep the current form**, inferred from the wikitoolkit table inside the managed
  block (no block / baked table → baked; a fresh install is byte-identical to today);
- **sticky for `parrot toolkits`**: `reconcile_toolkit_tables` — which `mcp/hosts.py::CodexAdapter.reconcile`
  calls (hosts.py:167-170) — preserves the wikitoolkit table verbatim (FEAT-570 AC5) and must emit
  toolkit tables in the same form it finds there. `mcp/hosts.py` is NOT modified.
- Codex ownership is structural (inside the marker block = ours); foreign tables outside the block
  keep being warned-and-omitted (`_toolkit_sections`, codex/installer.py:138-169) — unchanged.

---

## Scope

- `codex/assets.py`: `resolve_binary` via `script_path`; `PORTABLE_TOOLKIT_CONFIG`; `portable=` on
  `toolkit_mcp_block`, `mcp_block`, `rules_block`.
- `codex/bookstore.py`: `portable=` on `mcp_block` (portable: `command = "bookstore"`,
  `args = ["mcp"]`, no `cwd` line) and `install_bookstore`.
- `codex/installer.py`: `_current_portable_mode`, `_wikitoolkit_table_is_portable`;
  `reconcile_toolkit_tables(root, *, portable: Optional[bool] = None)`; `_install_mcp` / `_install_rules`
  take `*, portable: bool = False`; `install_codex_integration(…, portable: Optional[bool] = None)`.
- `codex/cli.py`: `--portable/--no-portable` (default unset).
- Write `packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py`.

**NOT in scope**:
- `mcp/hosts.py` (unchanged — `CodexAdapter.reconcile(root)` → `reconcile_toolkit_tables(root)` is the inference path).
- Making `parrot mcp-local` honour `PARROT_PROJECT` (mcp/local_cli.py:183 uses `Path.cwd()`).
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
| `packages/ai-parrot/tests/knowledge/wiki/test_codex_portable.py` | CREATE | Emission, transitions, stickiness, Windows branch, PARROT_PROJECT root |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: This section contains VERIFIED code references from the actual codebase
> (branch `dev` @ `6c4ca5482`, 2026-10-05).
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
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
MCP_BEGIN = "# >>> parrot-wiki Codex MCP >>>"; MCP_END = "# <<< parrot-wiki Codex MCP <<<"   # lines 15-16
MCP_TABLE = "mcp_servers.wikitoolkit"                                     # line 19
def resolve_binary(root: Path, name: str) -> str:                         # line 54; probe line 56: root / ".venv" / "bin" / name
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str:  # line 62-92
#   command = json.dumps(resolve_binary(root, "parrot")) line 78; config_path = str(root / ".parrot" / "mcp-toolkits.yaml") line 79
#   f"args = {json.dumps(['mcp-local', name, '--config', config_path])}" line 86; env inline table lines 88-90
def mcp_block(root: Path, toolkit_block: str = "") -> str:                # line 95-118; command = json.dumps(resolve_binary(root, "wikitoolkit")) line 106
def rules_block(root: Path) -> str:                                       # line 121-139 (bare patterns + resolved-path patterns)

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/bookstore.py
import sys                                                                # line 6
def mcp_block(root: Path) -> str:                                         # line 37-52
#   f"command = {json.dumps(sys.executable)}" line 43; 'args = ["-m", "parrot.knowledge.bookstore.cli", "mcp"]' line 44
#   f"cwd = {json.dumps(str(root.resolve()))}" line 45; env_vars line 46; timeouts 47-48
def install_bookstore(root: Path) -> list[str]:                           # line 55; _upsert_marker_block(before, mcp_block(root), …) line 73

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _extract_toml_table(text: str, table: str) -> Optional[str]:          # line 110
def _toolkit_sections(cfg: Any, existing_tables: set[str]) -> tuple[dict[str, Any], list[str]]:  # line 138
def reconcile_toolkit_tables(root: Path) -> tuple[list[str], list[str]]:  # line 172; toolkit_block = assets.toolkit_mcp_block(root, sections) line 198 (1st of 2)
#   wikitoolkit_text = _extract_toml_table(block_body, assets.MCP_TABLE) line 204
def _install_mcp(root: Path) -> str:                                      # line 235; toolkit_block = … line 262 (2nd of 2); assets.mcp_block(root, toolkit_block) line 267
def _install_rules(root: Path) -> str:                                    # line 285; assets.rules_block(root) line 290
def install_codex_integration(root, config=None, gitignore=True, bookstore=True) -> list[str]:  # line 316-321
#   save_project_config line 342; _install_mcp(root) line 353; _install_rules(root) line 354; install_bookstore(root) line 360

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py
#   "--bookstore/--no-bookstore" line 58; "--tool-guards/--no-tool-guards" line 64; def install( line 69;
#   `    tool_guards: bool,` line 74; install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore) line 80

# packages/ai-parrot/src/parrot/mcp/hosts.py:167-170 — CodexAdapter.reconcile -> reconcile_toolkit_tables(root)
```

### Does NOT Exist
- ~~Windows venv handling in `codex/`~~ — added here via `script_path` only.
- ~~a `portable` parameter / `--portable` flag in `codex/`~~ — new.
- ~~Codex variable expansion (`${VAR}`) in `config.toml` values~~ — NOT verified; spike S3 (TASK-4069) decides. Never assume it.
- ~~`parrot mcp-local` reading `PARROT_PROJECT`~~ — it uses `Path.cwd()`; a relative `--config` resolves against the server process cwd.
- ~~a per-entry managed-shape check for Codex~~ — ownership is structural (codex/installer.py:180-181); do not add one.

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
    "sym:packages/ai-parrot/src/parrot/mcp/hosts.py#CodexAdapter.reconcile"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# codex/installer.py:200-204 — how reconcile already isolates the wikitoolkit table text;
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
- `print(..., file=sys.stderr)` for warnings stays as today (codex/installer.py:260).

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
   shared-brief STICKY rule; `parrot toolkits` passes through `reconcile_toolkit_tables`.
4. `cli.py`: the tri-state flag — *why*: spec §2 New Public Interfaces.
5. Tests — *why*: spec §4 `test_portable_entries_no_abs_paths`, `test_default_emission_unchanged`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'from typing import TYPE_CHECKING' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# AFTER — `from typing import TYPE_CHECKING` (verified: codex/assets.py:8)

from parrot.launcher import script_path  # created by TASK-4071 (stdlib-only module)

# occurrences: 1 (verified: grep -c 'RULES_PATH = Path(".codex/rules/parrot-wiki.rules")' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# AFTER — `RULES_PATH = Path(".codex/rules/parrot-wiki.rules")` (verified: codex/assets.py:21)
#: Relative toolkit config used by portable toolkit tables (FEAT-633).
PORTABLE_TOOLKIT_CONFIG = ".parrot/mcp-toolkits.yaml"

# occurrences: 1 (verified: grep -c '    venv_binary = root / ".venv" / "bin" / name' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — (verified: codex/assets.py:56)
    venv_binary = script_path(root / ".venv", name)

# occurrences: 1 (verified: grep -c 'def toolkit_mcp_block(root: Path, sections: dict\[str, ToolkitSection\]) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — signature (:62) + lines 78-79 (`    command = json.dumps(resolve_binary(root, "parrot"))`, occurrences 1;
#           `    config_path = str(root / ".parrot" / "mcp-toolkits.yaml")`, occurrences 1). Docstring: add `portable`.
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection], *, portable: bool = False) -> str:
    if portable:
        command = json.dumps("parrot")
        config_path = PORTABLE_TOOLKIT_CONFIG
    else:
        command = json.dumps(resolve_binary(root, "parrot"))
        config_path = str(root / ".parrot" / "mcp-toolkits.yaml")
    # (loop at lines 80-92 unchanged, except:)
    # FILL IN: in portable mode, whether each table also gets a project pin — e.g. an `env`
    # `PARROT_PROJECT` variable reference or `env_vars = ["PARROT_PROJECT"]` pass-through — bounded by
    # spike S3 (TASK-4069) evidence on Codex's server cwd/env and spec §5 (no absolute path anywhere,
    # identical across roots). With no S3 evidence of variable expansion: add nothing.

# occurrences: 1 (verified: grep -c 'def mcp_block(root: Path, toolkit_block: str = "") -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — signature (:95) and `    command = json.dumps(resolve_binary(root, "wikitoolkit"))` (:106, occurrences 1)
def mcp_block(root: Path, toolkit_block: str = "", *, portable: bool = False) -> str:
    command = json.dumps("wikitoolkit" if portable else resolve_binary(root, "wikitoolkit"))

# occurrences: 1 (verified: grep -c 'def rules_block(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE — signature (:121) and wrap the resolved-pattern loop (lines 124-128)
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
#         verified: codex/installer.py:110-135), i.e. just above `def _toolkit_sections(` (:138)
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


def _current_portable_mode(root: Path) -> bool:
    """Infer the current mode from the managed block's wikitoolkit table (FEAT-633, sticky)."""
    # FILL IN: read root/".codex"/"config.toml" if present, isolate the managed block exactly like
    # reconcile_toolkit_tables (lines 200-204) and return _wikitoolkit_table_is_portable(...) —
    # bounded by "no new state file" (shared brief) and never raising.
    raise NotImplementedError

# occurrences: 1 (verified: grep -c 'def reconcile_toolkit_tables(root: Path) -> tuple\[list\[str\], list\[str\]\]:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# REPLACE — signature (:172); docstring gains: "portable: None infers from the preserved wikitoolkit
#           table (sticky — the `parrot toolkits` path via mcp/hosts.py::CodexAdapter.reconcile)."
def reconcile_toolkit_tables(root: Path, *, portable: Optional[bool] = None) -> tuple[list[str], list[str]]:
# MOVE the wikitoolkit_text extraction (lines 200-204) ABOVE the toolkit_block computation (line 198,
# first of 2 occurrences of `    toolkit_block = assets.toolkit_mcp_block(root, sections)`; context:
#     sections, warnings = _toolkit_sections(cfg, existing_tables)
#     toolkit_block = assets.toolkit_mcp_block(root, sections)
#     wikitoolkit_text: Optional[str] = None
# ) and then:
    if portable is None:
        portable = _wikitoolkit_table_is_portable(wikitoolkit_text)
    toolkit_block = assets.toolkit_mcp_block(root, sections, portable=portable)

# occurrences: 1 (verified: grep -c 'def _install_mcp(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# REPLACE — signature (:235), the second `    toolkit_block = assets.toolkit_mcp_block(root, sections)` (:262; context line above:
#           `        print(warning, file=sys.stderr)`) and `        assets.mcp_block(root, toolkit_block),` (:267, occurrences 1)
def _install_mcp(root: Path, *, portable: bool = False) -> str:
    toolkit_block = assets.toolkit_mcp_block(root, sections, portable=portable)
        assets.mcp_block(root, toolkit_block, portable=portable),

# occurrences: 1 (verified: grep -c 'def _install_rules(root: Path) -> str:' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# REPLACE — signature (:285) and `        assets.rules_block(root),` (:290, occurrences 1)
def _install_rules(root: Path, *, portable: bool = False) -> str:
        assets.rules_block(root, portable=portable),

# occurrences: 1 (verified: grep -c '    bookstore: bool = True,' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# AFTER — `    bookstore: bool = True,` in install_codex_integration's signature (verified: codex/installer.py:320)
    portable: Optional[bool] = None,
# Docstring Args: portable — True: bare launcher commands, False: baked absolute paths, None: keep current form.

# occurrences: 1 (verified: grep -c '    save_project_config(root, config)' packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py)
# AFTER — insert below `    save_project_config(root, config)` (verified: codex/installer.py:342) — it only writes
#         .parrot/wiki.json, so inferring after it still precedes every .codex/ write
    if portable is None:
        portable = _current_portable_mode(root)

# REPLACE — call sites (each occurrences 1): :353, :354, :360
    actions.append(_install_mcp(root, portable=portable))
    actions.append(_install_rules(root, portable=portable))
        actions.extend(install_bookstore(root, portable=portable))
```
**Why**: Codex already regenerates the whole managed block from config on install, so passing the
requested mode is "requested wins"; only `reconcile_toolkit_tables` (shared with `parrot toolkits`)
needs inference.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "--tool-guards/--no-tool-guards",' packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py)
# AFTER — insert a new decorator after the option block that starts with `    "--tool-guards/--no-tool-guards",`
#         (verified: codex/cli.py:63-68), i.e. directly above `def install(` (cli.py:69)
@click.option(
    "--portable/--no-portable",
    default=None,
    help="Emit bare launcher commands with no absolute paths (committable .codex/config.toml). "
    "Default: keep the current form (baked absolute paths on a fresh install).",
)

# occurrences: 1 (verified: grep -c '    tool_guards: bool,' packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py)
# AFTER — (verified: codex/cli.py:74)
    portable: Optional[bool],

# occurrences: 1 (verified: grep -c '        actions = install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore)' packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py)
# REPLACE — (verified: codex/cli.py:80)
        actions = install_codex_integration(
            root, config, gitignore=gitignore, bookstore=bookstore, portable=portable
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
from parrot.knowledge.wiki.codex import assets, bookstore
from parrot.knowledge.wiki.codex.installer import install_codex_integration, reconcile_toolkit_tables


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
```
**Why**: a portable toolkit entry has no absolute `--config` and Codex's server cwd is
unreliable (the very reason FEAT-556 pinned `--config` absolutely). `PARROT_PROJECT` is the
spec's root pin (spec §3 M1/M5): when a host adapter sets it in the entry's `env`, the
relative `.parrot/mcp-toolkits.yaml` resolves against the project root regardless of the
process cwd. Without `PARROT_PROJECT` the behavior is byte-for-byte today's (`Path.cwd()`).
Add `import os` next to the existing imports if absent (verify), and mention the variable in
the command's docstring. This also fixes Google's portable toolkit entries (user-global
config, arbitrary cwd) — Gemini's emitter task (TASK-4084) cites this behavior but does not
own the file; this task does.

### FILL IN checklist
- [ ] `assets.py::toolkit_mcp_block` portable project pin — bounded by spike S3 (TASK-4069) evidence; spec §5 (no absolute path, root-independent).
- [ ] `local_cli.py` — whether `--config` given explicitly should ALSO resolve against `PARROT_PROJECT` when relative (recommended: yes, same root) — bounded by FEAT-556's "config pinned regardless of cwd" intent.
- [ ] `installer.py::_current_portable_mode` — lenient read of the managed block; bounded by "no new state file".
- [ ] Google-style docstrings for every changed signature.

---

## Acceptance Criteria

- [ ] `resolve_binary` uses `script_path(root / ".venv", name)`; `grep -c '".venv" / "bin"' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` → 0.
- [ ] `parrot codex install --portable` writes a managed block, bookstore block and rules file with no absolute path in any field and no `sys.executable` (spec §5); output identical for two roots.
- [ ] Without `--portable`, a fresh install is byte-identical to today (spec §5 default unchanged).
- [ ] `--portable` / `--no-portable` land exactly the requested form; flag absent keeps the current form.
- [ ] `reconcile_toolkit_tables(root)` emits portable toolkit tables iff the preserved wikitoolkit table is portable; it still preserves that table verbatim (FEAT-570 AC5); `mcp/hosts.py` unchanged.
- [ ] `parrot mcp-local` resolves the project root from `PARROT_PROJECT` when set, `Path.cwd()` otherwise; a relative `--config` resolves against that root (test with a tmp root + monkeypatched env).
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

---

## Test Specification

See the CREATE block above: `test_portable_entries_no_abs_paths`, `test_default_emission_unchanged`,
`test_portable_transitions_both_ways`, `test_reconcile_sticky`, `test_portable_root_independent`,
`test_windows_scripts_branch`.

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

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
