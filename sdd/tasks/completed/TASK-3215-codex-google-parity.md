# TASK-3215: codex / google installer parity — seeding flag and pinned entry shape

**Feature**: FEAT-556 — `parrot claude install` seeds and authorizes the Parrot MCP servers
**Spec**: `sdd/specs/claude-install-mcp-autoenable.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3212
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 5 (§8 Q2, resolved 2026-09-13: in scope for this
feature). `parrot codex install` and `parrot google install` reconcile their own
MCP config from the same `load_toolkits_config` (`codex/installer.py:122,130`;
`google/installer.py:114,136`), so they inherit both FEAT-556 problems:

- neither can see a toolkit that has no section, and neither seeds one;
- codex's TOML tables carry neither `--config` nor `cwd`
  (`codex/assets.py:77-81`), so a codex session started outside the project root
  reproduces the Claude worktree failure exactly. Google's entries already set
  `cwd` (`google/assets.py:90`) but still lack `--config`, so pinning makes the
  two consistent and independent of host cwd handling.

Approval is NOT part of this task: `enabledMcpjsonServers` is a Claude Code
concept (spec §1 Non-Goals).

---

## Scope

- Pin `--config <root>/.parrot/mcp-toolkits.yaml` into the `args` of the codex
  TOML tables and the Google MCP entries; keep Google's existing `cwd`.
- Widen `google/installer.py::_is_managed_toolkit_entry` to accept both the
  pinned and the pre-FEAT-556 two-arg shapes.
- Add `--toolkits` / `--all-toolkits` to `parrot codex install` and
  `parrot google install`, passing them through to their integration functions,
  which seed before their own MCP reconciliation.
- Extend `tests/knowledge/wiki/test_codex_installer_toolkit_entries.py` and
  `tests/knowledge/wiki/test_google_installer_toolkit_entries.py`.

**NOT in scope**: any approval write for either host; no `cwd` key in the codex
TOML table (its support in the codex config schema is unverified — `--config`
makes it unnecessary); no change to codex's marker-block regeneration strategy.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` | MODIFY | `--config` in the TOML table's `args` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py` | MODIFY | `toolkits` kwarg + seeding before `_install_mcp` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/codex/cli.py` | MODIFY | `--toolkits` / `--all-toolkits` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` | MODIFY | `--config` in the entry's `args` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` | MODIFY | Accept both arg shapes; `toolkits` kwarg + seeding |
| `packages/ai-parrot/src/parrot/knowledge/wiki/google/cli.py` | MODIFY | `--toolkits` / `--all-toolkits` |
| `tests/knowledge/wiki/test_codex_installer_toolkit_entries.py` | MODIFY | Pinned-args + seeding tests |
| `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` | MODIFY | Pinned-args + legacy-adoption tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config   # verified: codex/installer.py:122, google/installer.py:114
from parrot.mcp.toolkit_seed import available_templates, seed_toolkit_sections  # created by TASK-3211
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py
def toolkit_mcp_block(root: Path, sections: dict[str, ToolkitSection]) -> str:   # line 60
    command = json.dumps(resolve_binary(root, "parrot"))                          # line 73
    #   f"[mcp_servers.parrot-{name}]"                                            # line 78
    #   f"command = {command}"                                                    # line 79
    #   f"args = {json.dumps(['mcp-local', name])}"                               # line 80  <-- pin here
    #   env rendered as an inline TOML table when section.env                      # lines 82-84

# packages/ai-parrot/src/parrot/knowledge/wiki/codex/installer.py
def _install_mcp(root: Path) -> str:          # line 111 — regenerates the whole managed block from config,
    #   path = root / ".codex" / "config.toml"                 # line 125
    #   cfg = load_toolkits_config(root)                       # line 130
    #   skips sections whose table exists OUTSIDE the managed block (warn)  # lines 136-145
    #   _validate_toml(path, after) before writing             # line 158

# packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py
def default_mcp_config_path() -> Path:        # line 59 — ~/.gemini/config/mcp_config.json (USER-level, not repo)
def toolkit_mcp_entries(root: Path, sections: dict[str, ToolkitSection]) -> dict[str, dict[str, Any]]:  # line 81
    entry = {"command": parrot_bin, "args": ["mcp-local", name], "cwd": str(root.resolve())}  # lines 87-91  <-- pin args here
    #   entry["env"] = dict(section.env) when section.env      # lines 92-93

# packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool:   # line 73
    #   return ... and entry.get("args") == ["mcp-local", name]             # line 78
def _install_mcp(root: Path, mcp_path: Optional[Path] = None) -> list[str]: # line 113
    #   enabled_toolkits filter                                            # line 137
    #   desired_toolkits = assets.toolkit_mcp_entries(root, enabled_toolkits)  # line 138
    #   foreign warn-and-skip                                              # lines 148-155
    #   stale cleanup via _is_managed_toolkit_entry                         # lines 161-167

# CLI shapes to mirror
# codex/cli.py:69   def install(path_, gitignore, build_now, bookstore, tool_guards) -> None
# codex/cli.py:74   actions = install_codex_integration(root, config, gitignore=gitignore, bookstore=bookstore)
# google/cli.py:63  def install(path_, gitignore, build_now, bookstore) -> None
# google/cli.py:68  actions = install_google_integration(root, config, gitignore=gitignore, bookstore=bookstore)
```

### Does NOT Exist
- ~~a shared entry-builder or managed-entry detector across hosts~~ — each host
  package has its own copy; `claude_code`'s change (TASK-3212) does NOT
  propagate here.
- ~~`cwd` support in the codex `[mcp_servers.*]` TOML table~~ — unverified in the
  codex config schema; do not add it. `--config` is the fix.
- ~~a repo-local Google MCP config~~ — `default_mcp_config_path()` is
  `~/.gemini/config/mcp_config.json` (`google/assets.py:59-61`), a USER-level
  file; tests must pass an explicit `mcp_path` (the `_install_mcp(root, mcp_path=...)`
  parameter exists for exactly that, `google/installer.py:113`).
- ~~`install_codex_integration(..., approve_mcp=...)`~~ — approval is
  Claude-only; do not add the parameter to either host.

---

## Implementation Notes

### Key Constraints
- Codex writes TOML and validates it (`_validate_toml`, `codex/installer.py:158`):
  the rendered `args` must stay a valid TOML array — keep using `json.dumps`
  on the whole list rather than hand-building the string.
- Google's user-level config means a test MUST pass `mcp_path` into
  `_install_mcp`, never let it touch `~/.gemini`.
- Mirror TASK-3212's decision exactly (absolute `--config` derived from `root`);
  do not invent a different path or make it configurable.
- Seeding runs before each host's own `_install_mcp`, same ordering rule as
  TASK-3214.

### References in Codebase
- `TASK-3212` (completed) — the Claude-side change this mirrors; read its
  diff before starting so the two shapes stay consistent.
- `tests/knowledge/wiki/test_codex_installer_toolkit_entries.py`,
  `tests/knowledge/wiki/test_google_installer_toolkit_entries.py` — the
  existing per-host entry tests to extend.

---

## Implementation Blueprint

### Steps (in order)
1. Pin both entry builders — *why*: they are the actual bug; the CLI work is
   additive on top.
2. Widen Google's detector — *why*: without it, the first re-install warns on
   every entry the previous version wrote and refuses to upgrade it (codex needs
   no such change: it regenerates its whole managed block from config, so old
   tables inside the markers are simply replaced).
3. Thread `toolkits` through both integration functions, seeding before
   `_install_mcp` — *why*: a host that cannot see a section cannot emit it.
4. Add the two CLI options to each command — *why*: parity with
   `parrot claude install`.
5. Extend both test modules — *why*: each host renders a different format, so
   one shared test cannot cover both.

### `packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'f"args = {json.dumps(\[.mcp-local., name\])}",' packages/ai-parrot/src/parrot/knowledge/wiki/codex/assets.py)
# REPLACE the args line inside toolkit_mcp_block's table builder (verified: codex/assets.py:80)
            f"args = {json.dumps(['mcp-local', name, '--config', str(root / '.parrot' / 'mcp-toolkits.yaml')])}",
```
**Why**: `parrot mcp-local` resolves its root from `Path.cwd()`
(`parrot/mcp/local_cli.py:105`), so an unpinned table cannot resolve the toolkit
when codex starts the server from anywhere but the project root. `json.dumps` on
the whole list keeps the value a valid TOML array, which `_validate_toml`
(`codex/installer.py:158`) will check. Update the docstring's description of the
rendered table in the same edit.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '            "args": \["mcp-local", name\],' packages/ai-parrot/src/parrot/knowledge/wiki/google/assets.py)
# REPLACE the args entry inside toolkit_mcp_entries (verified: google/assets.py:89)
            "args": ["mcp-local", name, "--config", str(root.resolve() / ".parrot" / "mcp-toolkits.yaml")],
```
**Why**: keeps the existing `cwd` (line 90) untouched — belt and braces — while
making resolution explicit. Use `root.resolve()` here because the neighbouring
`cwd` already does, so both strings agree.

### `packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'entry.get("args") == \["mcp-local", name\]' packages/ai-parrot/src/parrot/knowledge/wiki/google/installer.py)
# REPLACE the return expression of _is_managed_toolkit_entry (verified: google/installer.py:78)
    if not isinstance(command, str) or not command.endswith(bin_name):
        return False
    args = entry.get("args")
    # Accept the pinned shape and the pre-FEAT-556 two-arg shape so an entry
    # written by an older install is adopted and upgraded, not warned about
    # (google/installer.py:148-155).
    return isinstance(args, list) and args[:2] == ["mcp-local", name]
```
**Why**: same rule as the Claude side (TASK-3212) — narrow on `command`, wide on
`args`. Foreign entries still differ by `command` and stay protected.

### `packages/ai-parrot/src/parrot/knowledge/wiki/{codex,google}/installer.py` (MODIFY — seeding)
```python
# FILL IN (both hosts): add `toolkits: Sequence[str] = ()` to
# install_codex_integration / install_google_integration, and immediately BEFORE
# their `_install_mcp(...)` call do:
#     if toolkits:
#         from parrot.mcp.toolkit_seed import seed_toolkit_sections
#         seeded = seed_toolkit_sections(root, toolkits)
#         <append action strings, same phrasing as TASK-3214>
# — bounded by the ordering rule in spec §2 (seed BEFORE reconciliation) and by
# the parameter name `toolkits` fixed in TASK-3214; anchor each insertion on the
# verbatim `_install_mcp(` call line in that file and state its occurrence count
# in your commit, since the exact line differs per host
```
**Why**: the parameter name must match the Claude installer so a caller can
treat the three the same way; the seeding call itself is identical because
`seed_toolkit_sections` is tool-agnostic by design (TASK-3211).

### `packages/ai-parrot/src/parrot/knowledge/wiki/{codex,google}/cli.py` (MODIFY)
```python
# FILL IN (both hosts): copy the `--toolkits` and `--all-toolkits` option blocks
# from claude_code/cli.py (added by TASK-3214) verbatim — help text included —
# add the parameters to each `def install(...)`, resolve them the same way, and
# pass `toolkits=names`. Do NOT add --approve-mcp: approval is Claude-only
# (spec §1 Non-Goals). Bounded by AC "`parrot codex install --toolkits <name>`
# and `parrot google install --toolkits <name>` seed the same YAML".
```
**Why**: identical flags across hosts is the whole point of parity; diverging
help text would make `--help` read as three different features.

### FILL IN checklist
- [ ] `codex/installer.py` + `google/installer.py` — `toolkits` kwarg and the pre-`_install_mcp` seeding call; bounded by spec §2 ordering
- [ ] `codex/cli.py` + `google/cli.py` — the two options, parameters, resolution and pass-through; no approval flag

---

## Acceptance Criteria

- [ ] The rendered codex TOML table's `args` include
      `--config <root>/.parrot/mcp-toolkits.yaml`, and the resulting
      `config.toml` still passes `_validate_toml`
- [ ] A Google managed entry carries both the `--config` arg and its
      pre-existing `cwd`
- [ ] A pre-FEAT-556 Google entry (`args == ["mcp-local", <name>]`) is adopted
      and upgraded, with no stderr warning
- [ ] A foreign entry / a table outside the managed block is still left alone and
      still warns, for both hosts
- [ ] `parrot codex install --toolkits <name>` and
      `parrot google install --toolkits <name>` seed
      `.parrot/mcp-toolkits.yaml` and emit that server in their own format, in
      one pass
- [ ] `--all-toolkits` works on both hosts; neither host gained an approval flag
- [ ] No Google test writes to `~/.gemini` (every call passes `mcp_path`)
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_codex_installer_toolkit_entries.py tests/knowledge/wiki/test_google_installer_toolkit_entries.py -v`
      plus `pytest tests/knowledge/wiki/test_codex_integration.py tests/knowledge/wiki/test_google_integration.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/codex/ packages/ai-parrot/src/parrot/knowledge/wiki/google/`

---

## Test Specification

```python
# tests/knowledge/wiki/test_codex_installer_toolkit_entries.py  (extend)
def test_codex_table_pins_config(tmp_path):
    """The rendered table carries an absolute --config and still parses as TOML."""
    # FILL IN: render via assets.toolkit_mcp_block(root, {name: section}); assert
    # "--config" and the absolute path appear; parse the text with tomllib and
    # assert args[-2:] == ["--config", str(root / ".parrot" / "mcp-toolkits.yaml")]


def test_codex_install_seeds_toolkits(tmp_path):
    # FILL IN: install_codex_integration(root, toolkits=["bounded-source"]) ->
    # .parrot/mcp-toolkits.yaml exists AND [mcp_servers.parrot-bounded-source]
    # is in the managed block


# tests/knowledge/wiki/test_google_installer_toolkit_entries.py  (extend)
def test_google_entry_pins_config_keeps_cwd(tmp_path):
    # FILL IN: entries = assets.toolkit_mcp_entries(root, {name: section});
    # assert "--config" in entry["args"] and entry["cwd"] == str(root.resolve())


def test_google_legacy_entry_adopted(tmp_path, capsys):
    # FILL IN: pre-write a two-arg entry into an explicit mcp_path, run
    # _install_mcp(root, mcp_path=...), assert the entry is pinned and no
    # "Warning:" reached stderr
```

---

## Agent Instructions

1. **Read the spec** §3 Module 5 and §8 Q2.
2. **Check dependencies** — TASK-3212 must be in `sdd/tasks/completed/`; read its
   diff so both hosts mirror its decision exactly.
3. **Verify the Codebase Contract** — re-read `codex/assets.py:60-86`,
   `google/assets.py:81-95` and `google/installer.py:73-78` before editing.
4. **Update status** in `sdd/tasks/index/claude-install-mcp-autoenable.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:` marker.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3215-codex-google-parity.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (orchestrator itself — attempt 3, after two
dispatched coder attempts failed: codex-spark hit the 1800s wall-clock cap,
qwen's retry left the sub-worktree dirty/uncommitted)
**Date**: 2026-09-13
**Notes**: Pinned `--config <root>/.parrot/mcp-toolkits.yaml` into codex's
TOML `args` (`toolkit_mcp_block`) and google's entry `args`
(`toolkit_mcp_entries`, keeping its pre-existing `cwd`). Widened google's
`_is_managed_toolkit_entry` to accept both the pinned and pre-FEAT-556
two-arg shapes (mirrors TASK-3212 exactly; codex needs no such change since
it regenerates its whole managed block). Threaded a
`toolkits: Sequence[str] = ()` kwarg through `install_codex_integration` /
`install_google_integration` that seeds `.parrot/mcp-toolkits.yaml` via
`seed_toolkit_sections` immediately before each host's own `_install_mcp`
call. Added matching `--toolkits` / `--all-toolkits` CLI options to both
`parrot codex install` and `parrot google install` (verbatim help text from
the spec's Module 4 skeleton); no approval flag on either (Claude-only).
Updated the two existing entry-shape assertions in
`test_codex_installer_toolkit_entries.py` /
`test_google_installer_toolkit_entries.py` that asserted the old unpinned
`args`, and added the blueprint's new tests
(`test_codex_table_pins_config`, `test_codex_install_seeds_toolkits`,
`test_google_entry_pins_config_keeps_cwd`, `test_google_legacy_entry_adopted`).
All 28 tests across the 4 required test files pass
(`test_codex_installer_toolkit_entries.py` 10,
`test_google_installer_toolkit_entries.py` 6,
`test_codex_integration.py` 6, `test_google_integration.py` 6); `ruff check`
on `codex/`, `google/`, and both touched test files is clean.
**Deviations from spec**: none

Seat: sdd-worker (native, attempt 3) · Backend: n/a · Model: n/a · Attempts: 1 · Duration: n/a · Tokens: n/a
(Prior failed dispatches: codex-spark/gpt-5.3-codex-spark 1801.7s wall-clock-cap failure; qwen/qwen.qwen3-coder-480b-a35b-instruct 306.96s dirty_task_worktree failure — 2726395 in / 11413 out tokens, not merged)
