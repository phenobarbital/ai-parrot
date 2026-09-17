# TASK-3380: Builtin-consumer audit — CLI error, docs, examples, this repo's `.mcp.json`

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3376
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9, driven by design research **S9** (CONFIRM, `risk: high`).

Deleting `BUILTIN_TOOLKITS` (TASK-3368) breaks more than the installers.
`local_cli.py` still calls the three names "built-ins" in its `--list` docstring,
`docs/mcp-local-toolkits.md` tells operators they work without any YAML,
`examples/mcp-toolkits.yaml` and `examples/dev_loop/mcp-toolkits.example.yaml`
demonstrate a config that relies on implicit resolution, and
`examples/dev_loop/mcp_wiring.py` documents merged builtins.

This repo breaks itself too: `.mcp.json` here carries `parrot-browsing`,
`parrot-memory` and `parrot-scraping` entries that resolve through the builtins.
The migration decision is a **hard cut** (spec §1 Non-Goals) — no auto-migration —
so the single migration aid the feature ships is a good error message, and this
repo's own config must be re-established in the same change (AC7).

---

## Scope

- Rewrite `parrot mcp-local`'s unknown-name error to name `parrot toolkits install`,
  and drop "built-in" language from its `--list` docstring.
- Update `docs/mcp-local-toolkits.md`: document the new command, delete the claim
  that three names work without YAML.
- Update both example YAML files to declare their sections explicitly.
- Update `examples/dev_loop/mcp_wiring.py` and its test.
- Re-establish this repo's `.mcp.json` toolkit entries via the new command.
- Run a repo-wide search for remaining implicit-builtin assumptions.

**NOT in scope**: the config/seed changes themselves (TASK-3368/3369), the CLI
(TASK-3376), the cross-host test matrix (TASK-3381).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/local_cli.py` | MODIFY | Unknown-name error + docstring |
| `docs/mcp-local-toolkits.md` | MODIFY | Document `parrot toolkits`; remove builtin claims |
| `examples/mcp-toolkits.yaml` | MODIFY | Declare sections explicitly |
| `examples/dev_loop/mcp-toolkits.example.yaml` | MODIFY | Declare sections explicitly |
| `examples/dev_loop/mcp_wiring.py` | MODIFY | Drop merged-builtins documentation |
| `packages/ai-parrot/tests/flows/dev_loop/test_examples_mcp_wiring.py` | MODIFY | Follow the wiring change |
| `tests/mcp/test_local_cli.py` | MODIFY | Assert the new error text |
| `.mcp.json` | MODIFY | Re-establish this repo's toolkit entries |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:105
from parrot.mcp.toolkit_server import create_toolkit_mcp_server  # verified: local_cli.py:110 (deferred import)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/local_cli.py
def _print_toolkit_list(root: Path, config_path: Path | None = None) -> None:  # line 35
    # docstring at :36-45 says "--list" is fast and side-effect free (KEEP that promise)
    # line 52: `if not cfg.toolkits: click.echo("No toolkits resolvable."); return`
@click.command("mcp-local")                                   # line 62
def mcp_local(name, config_path, include, exclude, list_toolkits) -> None:  # line 82
    # line 96-104 docstring — its Examples block names `memory` and `scraping`
    # line 104: `root = Path.cwd()`
    # line 113-117:
    #     try:
    #         server = create_toolkit_mcp_server(name, root, **overrides)
    #     except (ValueError, ImportError) as exc:
    #         click.echo(f"Error: {exc}", err=True)
    #         sys.exit(1)

# This repo's current .mcp.json managed toolkit entries (to re-establish):
#   parrot-browsing, parrot-memory, parrot-scraping
#   plus non-toolkit servers that must be left alone: wikitoolkit, bookstore,
#   parrot-bounded-source, parrot-sdd-coder
# Entry shape: {"command": <venv>/bin/parrot,
#               "args": ["mcp-local", <name>, "--config", <abs .parrot/mcp-toolkits.yaml>],
#               "cwd": <repo root>, "env": {}}
```

### Does NOT Exist
- ~~an auto-migration path~~ — spec §1 Non-Goals: the hard cut is deliberate. Do
  not add a fallback that silently resurrects the builtins.
- ~~`BUILTIN_TOOLKITS`~~ — deleted by TASK-3368.
- ~~a `--migrate` flag on `parrot toolkits`~~ — not in scope for this feature.
- ~~`docs/mcp-local.md`~~ — the file is `docs/mcp-local-toolkits.md`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/local_cli.py", "action": "MODIFY"},
    {"path": "docs/mcp-local-toolkits.md", "action": "MODIFY"},
    {"path": "examples/mcp-toolkits.yaml", "action": "MODIFY"},
    {"path": "examples/dev_loop/mcp-toolkits.example.yaml", "action": "MODIFY"},
    {"path": "examples/dev_loop/mcp_wiring.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_examples_mcp_wiring.py", "action": "MODIFY"},
    {"path": "tests/mcp/test_local_cli.py", "action": "MODIFY"},
    {"path": ".mcp.json", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/local_cli.py#mcp_local",
    "sym:packages/ai-parrot/src/parrot/mcp/local_cli.py#_print_toolkit_list",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_config.py#load_toolkits_config"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **`--list` must stay import-free.** `_print_toolkit_list` deliberately loads only
  the config models (docstring `:36-45`); do not add a toolkit import while
  editing its text.
- The `.mcp.json` edit must touch **only** the three toolkit entries. `wikitoolkit`,
  `bookstore`, `parrot-bounded-source` and `parrot-sdd-coder` stay exactly as they
  are — regenerate via `parrot toolkits install`, do not hand-edit around them.
- Prefer running the real command over hand-writing JSON, so the entries match
  what the installer would produce.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/toolkits.py` — the command being documented (TASK-3376)
- `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/` — the five templates (TASK-3370)

---

## Implementation Blueprint

### Steps (in order)
1. Fix the `mcp-local` error text — *why*: it is the **only** migration aid the
   hard cut ships, so it has to name the exact command that fixes the failure.
2. Update the docs — *why*: `docs/mcp-local-toolkits.md` currently instructs
   operators to rely on behavior that no longer exists.
3. Update the two example YAMLs and `mcp_wiring.py` — *why*: examples are copied
   verbatim by users; a stale one reintroduces the bug.
4. Re-establish this repo's `.mcp.json` **by running the new command** — *why*:
   hand-written entries drift from what the installer produces.
5. Run the repo-wide search — *why*: AC7 makes "no remaining implicit-builtin
   assumption" a checkable criterion, not a hope.

### `packages/ai-parrot/src/parrot/mcp/local_cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '        click.echo(f"Error: {exc}", err=True)' packages/ai-parrot/src/parrot/mcp/local_cli.py)
# REPLACE the error arm (verified: local_cli.py:115-117) with a message that names
# the fix when the failure is an unknown toolkit name:
    except (ValueError, ImportError) as exc:
        click.echo(f"Error: {exc}", err=True)
        # FILL IN: when the failure is an UNKNOWN NAME (not an import error from a
        # missing distribution), add a second stderr line:
        #   f"No toolkit named {name!r} is configured. Install it with: "
        #   f"parrot toolkits install {name}"
        # Distinguish the two cases so a missing `parrot_tools` does not advise a
        # reinstall that cannot help — bounded by AC7.
        sys.exit(1)
```
**Why**: an operator whose `parrot mcp-local browsing` stops working after the
hard cut has no other signal. Separating "not configured" from "configured but its
distribution is missing" matters because the two have different fixes — the first
is `parrot toolkits install`, the second is `uv pip install ai-parrot-tools`.

```python
# occurrences: 1 (verified: grep -cF 'def _print_toolkit_list(root: Path, config_path: Path | None = None) -> None:' packages/ai-parrot/src/parrot/mcp/local_cli.py)
# In `_print_toolkit_list`'s docstring (verified: local_cli.py:36-45) and in
# `mcp_local`'s docstring (verified: :96-104): remove every use of "built-in".
# Keep the "does NOT import any toolkit class" promise verbatim — it is AC1.
# Update the `--list` help text at :80 from
#   "List resolvable toolkit names (built-ins + config sections) and exit."
# to name only config sections.
# FILL IN: the replacement wording; bounded by AC7 and AC1.
```
**Why**: the word "built-in" is now factually wrong and would send a reader
looking for a constant that no longer exists.

### `docs/mcp-local-toolkits.md` (MODIFY)
```markdown
<!-- FILL IN:
     1. Add a section documenting `parrot toolkits list|status|install|uninstall|
        enable|disable`, including the interactive picker and the non-interactive
        form (`NAMES`, `--host`, `--yes`).
     2. DELETE the passage stating that `scraping` / `browsing` / `memory` work
        with no YAML file — that behavior is gone.
     3. Document the credential posture: templates ship `env: {}` and the DSN is
        inherited from the environment the MCP host passes to `parrot mcp-local`;
        the installer never writes a secret.
     4. Note the hard cut and that existing installs must re-run
        `parrot toolkits install`.
     Bounded by AC7 and AC13. -->
```
**Why**: this document is what an operator reads before touching the config; a
stale claim here costs more than a stale docstring.

### `examples/mcp-toolkits.yaml` + `examples/dev_loop/mcp-toolkits.example.yaml` (MODIFY)
```yaml
# FILL IN: ensure every toolkit the example demonstrates is DECLARED in the file
# (class + kwargs), rather than assumed resolvable. Copy the class paths from the
# packaged templates in parrot/mcp/_toolkit_templates/ so the examples and the
# templates cannot drift. Bounded by AC7.
```
**Why**: these files are copy-paste sources for users; an example that relied on
implicit resolution now produces a config that resolves nothing.

### `examples/dev_loop/mcp_wiring.py` + its test (MODIFY)
```python
# occurrences: verify with `grep -n 'builtin\|scraping\|browsing\|memory' examples/dev_loop/mcp_wiring.py`
# FILL IN: remove the merged-builtins documentation/behavior and point at the
# explicit sections instead; update
# packages/ai-parrot/tests/flows/dev_loop/test_examples_mcp_wiring.py to match.
# Bounded by AC7.
```
**Why**: design research S9 named this file specifically — it documents and tests
merged builtins, so it fails silently-wrong rather than loudly.

### `.mcp.json` (MODIFY)
```bash
# Regenerate this repo's own toolkit entries with the NEW command rather than by
# hand, so they match exactly what the installer produces:
#
#   parrot toolkits install browsing memory scraping --host claude --yes
#
# FILL IN: verify afterwards that `wikitoolkit`, `bookstore`,
# `parrot-bounded-source` and `parrot-sdd-coder` are byte-identical to their
# pre-change values — `parrot toolkits` must not have touched them (AC5).
# Bounded by AC5 and AC7.
```
**Why**: this is the feature's own dogfood check. If running the real command does
not reproduce the three entries, something is wrong with the installer — and
hand-editing the JSON would hide exactly that.

### Repo-wide audit
```bash
# FILL IN: run and resolve every hit:
#   grep -rn "BUILTIN_TOOLKITS" --include='*.py' --include='*.md' --include='*.yaml' .
#   grep -rn "built-in" packages/ai-parrot/src/parrot/mcp/ docs/mcp-local-toolkits.md
# Record in the Completion Note that both return nothing relevant. Bounded by AC7.
```
**Why**: AC7 is only meaningful if the search is actually run and its result
recorded.

### FILL IN checklist
- [ ] `local_cli.py` — unknown-name vs missing-distribution error split; bounded by AC7
- [ ] `local_cli.py` — remove "built-in" from both docstrings and `--list` help; bounded by AC7, AC1
- [ ] `docs/mcp-local-toolkits.md` — four documentation changes; bounded by AC7, AC13
- [ ] both example YAMLs — declare sections explicitly; bounded by AC7
- [ ] `mcp_wiring.py` + its test — drop merged builtins; bounded by AC7
- [ ] `.mcp.json` — regenerate via the real command; verify non-toolkit entries untouched; bounded by AC5, AC7
- [ ] repo-wide grep run and recorded; bounded by AC7

---

## Acceptance Criteria

- [ ] `parrot mcp-local <unconfigured>` names `parrot toolkits install <name>` on stderr
- [ ] A configured toolkit whose distribution is missing gets a *different*,
      accurate message (not a reinstall suggestion)
- [ ] No "built-in" language remains in `parrot/mcp/local_cli.py`
- [ ] `--list` still imports no toolkit class
- [ ] `docs/mcp-local-toolkits.md` documents `parrot toolkits` and no longer claims
      three names work without YAML
- [ ] Both example YAMLs declare every toolkit they demonstrate
- [ ] This repo's `.mcp.json` carries working `parrot-browsing` / `parrot-memory` /
      `parrot-scraping` entries, generated by the new command
- [ ] `wikitoolkit`, `bookstore`, `parrot-bounded-source`, `parrot-sdd-coder`
      entries are byte-identical to their pre-change values
- [ ] `grep -rn BUILTIN_TOOLKITS .` returns nothing

---

## Validation Commands

- `pytest tests/mcp/test_local_cli.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_examples_mcp_wiring.py -q`
- `pytest tests/mcp/test_toolkit_config.py -q`

---

## Test Specification

```python
# tests/mcp/test_local_cli.py
from click.testing import CliRunner
from parrot.cli import cli


def test_unknown_name_names_the_install_command(tmp_path):
    """The hard cut's only migration aid."""
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["mcp-local", "browsing"])
        assert result.exit_code != 0
        assert "parrot toolkits install browsing" in result.output


def test_list_mentions_no_builtins(tmp_path):
    # FILL IN: assert the --list output and help text contain no "built-in"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 9, §1 Non-Goals, design research S9).
2. **Check dependencies** — TASK-3376 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `local_cli.py:113-117` before editing.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria — including running the repo-wide grep.
7. **Move this file** to `sdd/tasks/completed/TASK-3380-builtin-consumer-audit.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below, recording the grep results.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
