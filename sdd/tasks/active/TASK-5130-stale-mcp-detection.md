# TASK-5130: Stale MCP toolkit entry detection (`parrot/mcp/toolkit_stale.py`, read side)

**Feature**: FEAT-795 — `parrot sdd uninstall --stalled` — remove stale and hand-copied SDD files
**Spec**: `sdd/specs/parrot-sdd-install-remove.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec G8, §2 "Stale MCP toolkit entries (G8, M6)" and §3 Module 6. Config files mix parrot toolkit entries with
`wikitoolkit`, `bookstore` and third-party servers. The toolkit installers only ever delete *managed, non-enabled*
entries, so an entry for a toolkit that no longer exists, or one hand-copied from another repository (classified
"foreign" because its `--config` is outside `root`), survives forever. Observed 2026-11-03: flowtask carries
`parrot-memory` in `.mcp.json` and in its codex block although `memory` is not declared in its
`.parrot/mcp-toolkits.yaml`.

This task is the **read-only** half: the model, the shape test and `find_stale_mcp_entries()`. TASK-5131 adds
removal to the same file.

---

## Scope

- Create `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` with `StaleMcpReason`, `StaleMcpEntry`,
  `is_parrot_toolkit_entry()` and `find_stale_mcp_entries()`.
- Files per host: `claude` → `<root>/.mcp.json`; `codex` → `<root>/.codex/config.toml` (every
  `[mcp_servers.parrot-<name>]` table, inside or outside the managed marker block); `google` →
  `<root>/.agents/plugins/parrot/mcp_config.json` (repo-scoped) **and** the user-global Gemini file
  (`toolkit_config_paths(root, gemini_config)[0]`).
- Reasons, one per entry, precedence `retired-toolkit` > `foreign-repo` > `undeclared` > `missing-repo`:
  - `retired-toolkit` (any file): `<name>` not in `available_templates()`.
  - `foreign-repo` (repo-scoped files only): `args[2] == "--config"` and `args[3]` is an absolute path not under
    `root` (resolved containment, same rule as the installers).
  - `undeclared` (repo-scoped files only): `<name>` is not an **enabled** section of
    `load_toolkits_config(root)`. Skip this reason entirely (log a warning) when the config cannot be loaded.
  - `missing-repo` (global file only): `--config` is absolute and its repository folder
    (`Path(args[3]).parent.parent`) does not exist.
- A file that cannot be parsed is skipped with a `logger.warning`, never raises.
- Write the detection tests in a new `packages/ai-parrot/tests/mcp/test_toolkit_stale.py`.

**NOT in scope**: writing/removing anything, Claude approvals, `--keep` (TASK-5131); installer/CLI wiring
(TASK-5132/5135). Never treat a key that is not `parrot-<name>` or not `parrot mcp-local <name>` as a candidate.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` | CREATE | Model + shape test + read-only finder |
| `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` | CREATE | Detection tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_seed import available_templates, seed_toolkit_sections  # verified: toolkit_seed.py:53, :335
from parrot.mcp.toolkit_seed import set_section_enabled  # verified: toolkit_seed.py:270 (tests only)
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:90
from parrot.knowledge.wiki.google.installer import _load_mcp_config, toolkit_config_paths  # verified: google/installer.py:46, :206
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
def available_templates() -> tuple[str, ...]                     # line 53 — packaged template names (sorted)
def set_section_enabled(root: Path, name: str, enabled: bool) -> bool   # line 270
def seed_toolkit_sections(root: Path, names: Sequence[str]) -> SeedResult  # line 335 — writes .parrot/mcp-toolkits.yaml
# packages/ai-parrot/src/parrot/mcp/toolkit_config.py
def load_toolkits_config(root: Path, config_path: Path | None = None) -> MCPToolkitsConfig  # line 90
#   .toolkits: dict[str, ToolkitSection]; section.enabled: bool; raises ValueError on a malformed file
# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def _load_mcp_config(path: Path) -> dict[str, Any]   # line 46 — missing/empty -> {"mcpServers": {}};
                                                     #   unparsable -> RuntimeError; always has an "mcpServers" dict
def toolkit_config_paths(root: Path, mcp_path: Optional[Path] = None) -> tuple[Path, ...]  # line 206
#   -> (global ~/.gemini/config/mcp_config.json via assets.default_mcp_config_path(), root/.agents/plugins/parrot/mcp_config.json)
# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
def default_mcp_config_path() -> Path               # line 65 — tests monkeypatch this module attribute
PORTABLE_TOOLKIT_CONFIG = ".parrot/mcp-toolkits.yaml"  # google/assets.py:23 (relative = portable form)
```
Shape test the installers use (`claude_code/installer.py:661`, `google/installer.py:101`): `command` basename is
`parrot` and `args[:2] == ["mcp-local", name]`; they ADD a containment check that this task must NOT add.
Codex table naming in `.codex/config.toml`: `[mcp_servers.parrot-<name>]` — `tomllib.loads(text)["mcp_servers"]`
is a dict keyed `parrot-<name>`.

### Does NOT Exist
- ~~`parrot.mcp.toolkit_stale`~~ — created by this task.
- ~~a public "is parrot toolkit shape" helper for every host~~ — only google's private `_is_parrot_toolkit_shape`
  (google/installer.py:137); define `is_parrot_toolkit_entry` here instead of importing a private cross-host name.
- ~~`parrot toolkits` verb that removes stale entries~~ — none.
- ~~`load_toolkits_config(...).enabled_names`~~ — no such attribute; filter `cfg.toolkits.items()` on `section.enabled`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_stale.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/mcp/test_toolkit_stale.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#seed_toolkit_sections",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#set_section_enabled",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#_load_mcp_config",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py#toolkit_config_paths"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **The global Gemini file is shared by every repository**: only `retired-toolkit` and `missing-repo` apply there.
  A portable entry (relative `--config`) in it is never stale for being disabled here.
- Resolve the global path only through `toolkit_config_paths(root, gemini_config)` — it calls
  `assets.default_mcp_config_path()` through the module attribute, which tests monkeypatch.
- Display path in `StaleMcpEntry.file`: repo-relative posix for repo files; `~/<rel>` when the global file is under
  `Path.home()`, else its absolute string. TASK-5131 maps `file` back to a real path, so keep a private
  `_McpFile` record (host, real path, display, format, scope) and return it from `_mcp_files()`.
- `logger = logging.getLogger(__name__)`; never raise for a broken config file.

---

## Implementation Blueprint

### Steps (in order)
1. Write the model and `is_parrot_toolkit_entry` exactly as below — *why*: TASK-5131 and the installer depend on
   these names and fields.
2. Implement `_mcp_files()` and `_read_servers()` — *why*: one place maps hosts→files and parses JSON/TOML, so
   TASK-5131 reuses them for removal.
3. Implement `_reason()` with the precedence — *why*: one reason per entry keeps reports and `--keep` simple.
4. Write the tests — *why*: they pin the four reasons and the "never touch" rules (AC-1..AC-6).

### `packages/ai-parrot/src/parrot/mcp/toolkit_stale.py` (CREATE)
```python
"""Stale `parrot-<name>` MCP toolkit entries across the three hosts' config files (FEAT-795 M6)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic import BaseModel

from parrot.knowledge.wiki.google.installer import _load_mcp_config, toolkit_config_paths
from parrot.mcp.toolkit_config import load_toolkits_config
from parrot.mcp.toolkit_seed import available_templates

logger = logging.getLogger(__name__)

StaleMcpReason = Literal["retired-toolkit", "undeclared", "foreign-repo", "missing-repo"]
_HOSTS: tuple[str, ...] = ("claude", "codex", "google")


class StaleMcpEntry(BaseModel):
    """One stale toolkit entry: ``host``, display ``file``, ``key`` ("parrot-<name>"), ``reason``, ``detail``."""

    host: Literal["claude", "codex", "google"]
    file: str
    key: str
    reason: StaleMcpReason
    detail: str


@dataclass(frozen=True)
class _McpFile:
    """One config file to scan: real ``path``, display name, ``fmt`` json|toml, ``scope`` repo|global."""

    host: str
    path: Path
    display: str
    fmt: Literal["json", "toml"]
    scope: Literal["repo", "global"]


def is_parrot_toolkit_entry(key: str, entry: Any) -> bool:
    """``key`` is "parrot-<name>", ``command`` basename is "parrot" and ``args[:2] == ["mcp-local", name]``.
    No containment check (that is what separates it from the installers' ``_is_managed_toolkit_entry``)."""
    if not key.startswith("parrot-") or not isinstance(entry, dict):
        return False
    name = key[len("parrot-") :]
    command, args = entry.get("command"), entry.get("args")
    if not isinstance(command, str) or not isinstance(args, list):
        return False
    basename = command.replace("\\", "/").rsplit("/", 1)[-1]
    basename = basename[:-4] if basename.lower().endswith(".exe") else basename
    return basename == "parrot" and args[:2] == ["mcp-local", name]


def _mcp_files(root: Path, hosts: Sequence[str], gemini_config: Path | None) -> list[_McpFile]:
    """The config files of ``hosts`` (missing files included — readers treat them as empty)."""
    # FILL IN: claude -> _McpFile("claude", root/".mcp.json", ".mcp.json", "json", "repo");
    #   codex -> (root/".codex"/"config.toml", ".codex/config.toml", "toml", "repo");
    #   google -> global, plugin = toolkit_config_paths(root, gemini_config): plugin as repo scope (display
    #   ".agents/plugins/parrot/mcp_config.json"), global as "global" scope with the `~/` display rule.
    raise NotImplementedError


def _read_servers(item: _McpFile) -> dict[str, Any] | None:
    """``{key: entry}`` of the file's MCP servers; ``{}`` when absent; ``None`` (logged) when unparsable."""
    # FILL IN: json -> _load_mcp_config(item.path)["mcpServers"], catching RuntimeError -> warning + None.
    #   toml -> {} if missing; tomllib.loads(text).get("mcp_servers", {}) (dict check), catching
    #   tomllib.TOMLDecodeError / OSError -> warning + None.
    raise NotImplementedError


def _reason(
    root: Path, item: _McpFile, name: str, args: list[Any], templates: set[str], enabled: set[str] | None
) -> tuple[StaleMcpReason, str] | None:
    """The single highest-precedence reason for one parrot toolkit entry, or ``None`` when it is not stale.
    ``enabled`` is ``None`` when the repo's toolkit config could not be loaded (then `undeclared` never fires)."""
    # FILL IN: precedence retired-toolkit > foreign-repo > undeclared > missing-repo, scopes per spec §2 table.
    #   config = args[3] when len(args) >= 4 and args[2] == "--config" else None. foreign-repo: repo scope, config
    #   absolute, and root.resolve() is neither Path(config).resolve() nor one of its parents. missing-repo: global
    #   scope, config absolute and not Path(config).parent.parent.is_dir(). Details are short human sentences.
    raise NotImplementedError


def find_stale_mcp_entries(
    root: Path, hosts: Sequence[str], *, gemini_config: Path | None = None
) -> list[StaleMcpEntry]:
    """Read-only. Files per host and reasons per spec §2. ``gemini_config`` overrides
    ``google.assets.default_mcp_config_path()`` (tests never touch the real home). An unparsable file is
    skipped. Sorted by (file, key).

    Raises:
        ValueError: an unknown host.
    """
    unknown = sorted(set(hosts) - set(_HOSTS))
    if unknown:
        raise ValueError(f"unknown host(s): {', '.join(unknown)}")
    templates = set(available_templates())
    try:
        cfg = load_toolkits_config(root)
        enabled: set[str] | None = {name for name, section in cfg.toolkits.items() if section.enabled}
    except ValueError as exc:
        logger.warning("toolkit config unreadable (%s); `undeclared` entries are not reported", exc)
        enabled = None
    found: list[StaleMcpEntry] = []
    # FILL IN: for item in _mcp_files(...): servers = _read_servers(item); skip None; for key, entry in
    #   servers.items() where is_parrot_toolkit_entry(key, entry): r = _reason(...); append StaleMcpEntry when r.
    return sorted(found, key=lambda e: (e.file, e.key))
```
**Why this shape**: the shape test is fully written (spec-fixed, security-relevant: it is what keeps
`wikitoolkit`/`bookstore`/foreign servers safe); host→file mapping and parsing are isolated so TASK-5131 can
re-read and rewrite the same files.

### `packages/ai-parrot/tests/mcp/test_toolkit_stale.py` (CREATE)
```python
"""FEAT-795 M6 — stale `parrot-<name>` MCP toolkit entries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parrot.mcp.toolkit_seed import seed_toolkit_sections, set_section_enabled
from parrot.mcp.toolkit_stale import find_stale_mcp_entries, is_parrot_toolkit_entry


def _entry(name: str, config: str) -> dict:
    return {"command": "/venv/bin/parrot", "args": ["mcp-local", name, "--config", config]}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo with `browsing` enabled and `scraping` disabled in .parrot/mcp-toolkits.yaml."""
    root = tmp_path / "repo"
    root.mkdir()
    seed_toolkit_sections(root, ["browsing", "scraping"])
    set_section_enabled(root, "scraping", False)
    return root


@pytest.fixture
def gemini(tmp_path: Path) -> Path:
    path = tmp_path / "gemini_home" / "mcp_config.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    return path


# FILL IN: tests (pass gemini_config=gemini to every call):
#   test_shape_test (wikitoolkit, bookstore, `parrot-x` running python, wrong args -> False; real shape -> True),
#   test_undeclared_entry_in_mcp_json (`parrot-scraping` pinned inside repo -> undeclared; `parrot-browsing` -> none),
#   test_retired_toolkit_any_file (`parrot-oldkit` in .mcp.json and in the global file -> retired-toolkit),
#   test_foreign_repo_pinned_config (`--config /other/repo/.parrot/mcp-toolkits.yaml` -> foreign-repo),
#   test_global_portable_entry_not_undeclared (relative `.parrot/mcp-toolkits.yaml`, `scraping` -> not stale),
#   test_global_missing_repo (absolute config under tmp_path/"gone" -> missing-repo),
#   test_codex_tables_inside_and_outside_block (both tables found; wikitoolkit table ignored),
#   test_unparsable_file_skipped (".mcp.json" = "{nope" -> no raise, nothing from that file),
#   test_host_filter (hosts=("claude",) never reads codex/google), test_unknown_host_raises.
```

### FILL IN checklist
- [ ] `_mcp_files` — host→file mapping, `~/` display rule.
- [ ] `_read_servers` — JSON via `_load_mcp_config`, TOML via `tomllib`; warn + `None` on parse errors.
- [ ] `_reason` — four reasons, scopes and precedence; bounded by AC-2..AC-5.
- [ ] `find_stale_mcp_entries` loop.
- [ ] the 10 tests listed.

---

## Acceptance Criteria

- [ ] AC-1: only `parrot-<name>` keys running `parrot mcp-local <name>` are ever reported; `wikitoolkit`,
      `bookstore` and foreign-shaped `parrot-*` entries never.
- [ ] AC-2: `retired-toolkit` in any file (global included) for a name with no packaged template.
- [ ] AC-3: `foreign-repo` / `undeclared` only in repo-scoped files; a disabled toolkit counts as undeclared.
- [ ] AC-4: a portable entry in the global file is never stale for being disabled in this repo.
- [ ] AC-5: `missing-repo` only in the global file, when the pinned repository folder is gone.
- [ ] AC-6: an unparsable file is skipped with a warning; unknown host → `ValueError`; the real `~/.gemini` is never read in tests.
- [ ] `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_stale.py packages/ai-parrot/tests/mcp/test_toolkit_stale.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/mcp/test_toolkit_stale.py -q`

---

## Test Specification

See the blueprint test file; names follow spec §4 "Unit Tests (`tests/mcp/test_toolkit_stale.py`)" for the
detection rows. Removal rows (`test_claude_approvals_dropped`, `test_keep_matches_file_key`, `test_reregister_note`,
`test_dry_run_mcp_writes_nothing`) belong to TASK-5131.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug parrot-sdd-install-remove --feature-id FEAT-795`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/parrot-sdd-install-remove.json`
4. **Verify the Codebase Contract** before writing any code; fix the contract first if anything moved
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the blueprint; complete every `# FILL IN:`; never change a signature or path it fixes
7. **Verify** — run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5130 parrot-sdd-install-remove verified`
10. **Fill in the Completion Note**, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none
