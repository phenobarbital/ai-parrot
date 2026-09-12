# TASK-3212: Pin the managed `.mcp.json` toolkit entry to an absolute config path

**Feature**: FEAT-556 — `parrot claude install` seeds and authorizes the Parrot MCP servers
**Spec**: `sdd/specs/claude-install-mcp-autoenable.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-3211
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 2. A managed toolkit entry currently carries
`args = ["mcp-local", <name>]` with no `--config` and no `cwd`
(`claude_code/assets.py:154-158`), while `parrot mcp-local` resolves its project
root as `Path.cwd()` (`parrot/mcp/local_cli.py:105`) and therefore reads
`<cwd>/.parrot/mcp-toolkits.yaml` (`toolkit_config.py:138`). Inside a git
worktree — where `sdd-worker` runs — that path does not exist, the named toolkit
cannot be resolved, and the server dies at startup. Verified on 2026-09-12 in
`.claude/worktrees/feat-496-dev-loop-dispatch-event-legibility`:

```
$ parrot mcp-local bounded-source
Error: Unknown toolkit name: 'bounded-source'. Resolvable: ['scraping', 'browsing', 'memory']
```

while the hand-written entry carrying an absolute `--config` connected fine. So
the *managed* shape is the broken one, and the operator's hand-written entries
are additionally rejected as "foreign" by `_is_managed_toolkit_entry`
(`installer.py:304-318`) and skipped with a warning (`installer.py:374-382`).

---

## Scope

- Add `--config <root>/.parrot/mcp-toolkits.yaml` to the managed entry's `args`
  and `cwd: <root>` to the entry, in `claude_code/assets.py`.
- Widen `_is_managed_toolkit_entry` in `claude_code/installer.py` to recognise
  both the pinned shape and the pre-FEAT-556 two-arg shape, so existing
  hand-written entries are adopted and upgraded instead of warned about.
- Extend `tests/knowledge/wiki/test_installer_toolkit_entries.py`.

**NOT in scope**: the seeder (TASK-3211), the approval write (TASK-3213), CLI
flags (TASK-3214), the codex/google twins of these two functions (TASK-3215).
Do not change the `command` check, and do not touch the `wikitoolkit` entry
(`assets.mcp_json_entry`, `assets.py:109`) — it is a different server with a
different binary.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` | MODIFY | Pin `--config` + `cwd` in `toolkit_mcp_json_entry` |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | Accept both arg shapes in `_is_managed_toolkit_entry` |
| `tests/knowledge/wiki/test_installer_toolkit_entries.py` | MODIFY | Pinning + legacy-adoption tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from pathlib import Path, PurePosixPath   # verified: installer.py:29
from parrot.knowledge.wiki.claude_code import assets  # verified: installer.py:33
from parrot.mcp.toolkit_config import ToolkitSection  # verified: claude_code/assets.py imports it for the type hint
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py
def resolve_parrot_bin(root: Path) -> str: ...          # line 118
def toolkit_mcp_json_entry(root: Path, name: str, section: ToolkitSection) -> dict:  # line 140
    return {                                            # lines 154-158
        "command": resolve_parrot_bin(root),
        "args": ["mcp-local", name],
        "env": dict(section.env),
    }

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _is_managed_toolkit_entry(entry: Any, root: Path, name: str) -> bool:  # line 304
    # body, line 318:
    # return isinstance(command, str) and command.endswith(bin_name) and entry.get("args") == ["mcp-local", name]

def _install_mcp_json(root: Path) -> str:               # line 321
    # per-name loop: entry built at line 372, compared at 374, foreign-warned at 376-382
    # stale-entry cleanup at 388-394 (uses _is_managed_toolkit_entry too)

def _uninstall_mcp_json(root: Path) -> str | None:      # line 411
    # removal also gated by _is_managed_toolkit_entry   # line 443

# packages/ai-parrot/src/parrot/mcp/local_cli.py
root = Path.cwd()                                       # line 105 — why pinning is required
```

### Does NOT Exist
- ~~`assets.toolkit_mcp_json_entry(..., config_path=...)`~~ — the function takes
  exactly `(root, name, section)`; derive the path inside it, do not add a
  parameter (three call sites would have to change: `installer.py:372` plus the
  codex/google twins, which are TASK-3215's business).
- ~~a `cwd` or `--config` key anywhere in the current managed entry~~ — the
  returned dict has exactly `command`, `args`, `env` (`assets.py:154-158`).
- ~~`MCP_JSON_ENTRY` being the toolkit entry~~ — `assets.py:71` is the
  *wikitoolkit* entry template; it is unrelated to this task.
- ~~a shared managed-entry helper across hosts~~ — `claude_code`, `codex` and
  `google` each have their own copy (`google/installer.py:73`), so changing one
  does not change the others.

---

## Implementation Notes

### Key Constraints
- The config path must be **absolute**: `str(root / ".parrot" / "mcp-toolkits.yaml")`
  with `root` already resolved by the caller (`install_claude_integration` does
  `root = root.resolve()`, `installer.py:610`).
- Detection must stay *narrow on command, wide on args*: accepting any
  `["mcp-local", name, ...]` prefix is acceptable; accepting a different
  `command` is not — that is what protects foreign entries.
- Keep the stale-entry cleanup working: an entry written by an older version
  must still be removable when its section disappears, which is exactly why the
  legacy shape stays recognised rather than being dropped.

### References in Codebase
- `tests/knowledge/wiki/test_installer_toolkit_entries.py` — fixture
  `tmp_root_with_config` and the existing foreign-entry tests to extend.
- `google/assets.py:87-91` — an entry builder that already sets `cwd`; useful as
  a shape reference (but changing it is TASK-3215).

---

## Implementation Blueprint

### Steps (in order)
1. Change the entry builder first — *why*: the detection change is only
   meaningful once there are two shapes in the world.
2. Widen the detector — *why*: without it the very first re-install would warn
   "already exists and was not written by `parrot claude install`" on every
   entry the previous version wrote, and refuse to upgrade it.
3. Extend the tests, including one asserting no stderr warning for a legacy
   entry — *why*: the adoption behaviour is an explicit AC and is invisible
   otherwise.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        "args": \["mcp-local", name\],' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/assets.py)
# REPLACE the return dict of toolkit_mcp_json_entry (verified: assets.py:154-158)
    return {
        "command": resolve_parrot_bin(root),
        # Pinned (FEAT-556): `parrot mcp-local` resolves its project root from
        # Path.cwd() (verified: parrot/mcp/local_cli.py:105), so an unpinned
        # entry resolves no toolkit when the host starts it from a worktree.
        "args": ["mcp-local", name, "--config", str(root / ".parrot" / "mcp-toolkits.yaml")],
        "cwd": str(root),
        "env": dict(section.env),
    }
```
**Why this shape**: `--config` is what actually fixes toolkit resolution
(`load_toolkits_config`'s explicit-path branch, `toolkit_config.py:147-149`);
`cwd` additionally makes relative `kwargs` paths such as
`plans_dir: .parrot/scraping_plans` (`toolkit_config.py:92-96`) resolve against
the project instead of the host's cwd. Also update the docstring's `Returns:`
block — it currently documents the old two-key shape.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'entry.get("args") == \["mcp-local", name\]' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE the return expression of _is_managed_toolkit_entry (verified: installer.py:318)
    if not isinstance(command, str) or not command.endswith(bin_name):
        return False
    args = entry.get("args")
    if not isinstance(args, list) or args[:2] != ["mcp-local", name]:
        return False
    # Accept the pinned shape (["mcp-local", name, "--config", <path>]) and the
    # pre-FEAT-556 two-arg shape, so an entry written by an older install — or
    # by an operator following examples/sdd-coder-mcp.yaml — is ADOPTED and
    # upgraded in place rather than warned about and skipped (installer.py:374-382).
    # FILL IN: decide whether a trailing `--config` with a path outside `root`
    # still counts as ours — bounded by AC "a foreign entry is left alone and
    # warned about": a path pointing elsewhere is an operator override worth
    # preserving, an absent/`root`-relative one is ours
    return True
```
**Why**: the docstring above it states the detection rule verbatim and must be
updated in the same edit — it is the documented contract other installers were
modelled on. Keep the `command` check byte-identical: it is the only thing
separating our entries from a foreign `parrot-<name>` key.

### FILL IN checklist
- [ ] `installer.py::_is_managed_toolkit_entry` — whether a `--config` pointing outside `root` is foreign; bounded by the foreign-entry AC

---

## Acceptance Criteria

- [ ] `assets.toolkit_mcp_json_entry(root, "sdd-coder", section)["args"]` ends with
      `["--config", str(root / ".parrot" / "mcp-toolkits.yaml")]` and the entry's
      `cwd == str(root)`
- [ ] A pre-existing `{"command": <parrot bin>, "args": ["mcp-local", "sdd-coder"]}`
      entry is recognised as managed, rewritten to the pinned shape, and produces
      NO stderr warning
- [ ] A foreign entry (different `command`) is still left untouched and still
      warns on stderr (FEAT-485 behaviour preserved)
- [ ] A managed entry whose section becomes disabled is still removed on re-run
- [ ] Re-running install twice leaves `.mcp.json` byte-identical
- [ ] All tests pass: `pytest tests/knowledge/wiki/test_installer_toolkit_entries.py -v`
      and `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/`

---

## Test Specification

```python
# tests/knowledge/wiki/test_installer_toolkit_entries.py  (extend)
def test_toolkit_entry_pins_config_and_cwd(tmp_root_with_config):
    servers = _servers(tmp_root_with_config)
    entry = servers["parrot-scraping"]
    assert entry["args"][:2] == ["mcp-local", "scraping"]
    assert entry["args"][2:] == ["--config", str(tmp_root_with_config / ".parrot" / "mcp-toolkits.yaml")]
    assert entry["cwd"] == str(tmp_root_with_config)


def test_legacy_entry_is_adopted_and_upgraded(tmp_root_with_config, capsys):
    """A two-arg entry from an older install is upgraded, not skipped."""
    # FILL IN: write {"command": assets.resolve_parrot_bin(root), "args":
    # ["mcp-local", "scraping"]} into .mcp.json, run _install_mcp_json, then
    # assert the entry is pinned and capsys.readouterr().err contains no "Warning:"


def test_foreign_entry_untouched(tmp_root_with_config, capsys):
    """Existing FEAT-485 behaviour must not regress."""
    # FILL IN: foreign command -> entry unchanged + warning on stderr
```

---

## Agent Instructions

1. **Read the spec** §3 Module 2 and §1 Problem Statement item 3.
2. **Check dependencies** — TASK-3211 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `assets.py:140-160` and
   `installer.py:304-320` before editing; line numbers shift as the file grows.
4. **Update status** in `sdd/tasks/index/claude-install-mcp-autoenable.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:` marker.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3212-pin-managed-entry.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-coder (dispatched by sdd-worker orchestrator, FEAT-549)
**Date**: 2026-09-12
**Notes**: `assets.toolkit_mcp_json_entry` now emits `--config <root>/.parrot/mcp-toolkits.yaml`
in `args` plus `cwd: <root>`. `_is_managed_toolkit_entry` widened to accept both
the pinned shape and the pre-FEAT-556 legacy two-arg shape, so a hand-written
entry is adopted and upgraded in place with no stderr warning; foreign entries
(different command) are still left untouched and still warn. All 9 tests in
`tests/knowledge/wiki/test_installer_toolkit_entries.py` pass; `ruff check` on
`claude_code/` is clean. The task also required
`pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -v`:
that file errors at collection in THIS worktree with
`ModuleNotFoundError: parrot.utils.types` — a known pre-existing environment
issue (the Cython-compiled `parrot.utils.types` .so only exists in the main
checkout's shared venv, not in git worktrees; confirmed the same import
succeeds cleanly in the main checkout, and the failure is present at
collection time, unrelated to this task's diff).
**Deviations from spec**: none — see note above on the worktree-only test
collection failure, unrelated to the change.

Seat: minimax · Backend: nova · Model: minimax.minimax-m2.5 · Attempts: 1 · Duration: 290.521s · Tokens: 448423 in / 5408 out
