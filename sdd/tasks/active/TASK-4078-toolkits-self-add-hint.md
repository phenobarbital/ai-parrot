# TASK-4078: Toolkit inventory carries install metadata; `parrot toolkits` hints `parrot self add`

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-4077
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4 (second half) and §5: "`parrot toolkits install` offers `parrot self add`
when the distribution is missing". Today `parrot toolkits list` only appends
`" (missing)"` to the Deps cell (cli/toolkits.py:134) and the interactive picker appends
`" (missing distribution)"` (cli/toolkits.py:63) — neither tells the operator how to fix
it. TASK-4077 added `requires_pip` / `post_install` / `requires_env` to `ToolkitTemplate`;
this task threads them into `ToolkitRow` (so `parrot self doctor`, TASK-4080, can read
`requires_env` from `inventory()`) and prints the `parrot self add <name>` hint at the
three user-facing sites.

---

## Scope

- Add `requires_pip`, `post_install`, `requires_env` (`tuple[str, ...] = ()`) to
  `ToolkitRow` and fill them in `inventory()` from the template (TASK-4077 fields).
- `parrot toolkits list`: after the table, print one hint line per row whose
  `requires_dist` is unmet: `<name>: missing distribution — run: parrot self add <name>`.
- Interactive picker title: `(missing distribution — parrot self add <name>)`.
- `parrot toolkits install`: after the report, for every selected name whose
  distribution is missing, print `ℹ <name>: distribution missing — run: parrot self add <name>`
  (and `--here` to install into the project venv instead).
- Tests in the existing CLI test file.

**NOT in scope**: implementing `parrot self add` (TASK-4079/4080); doctor checks
(TASK-4080); changing `dist_available()` semantics (still import-name probing via
`find_spec` — `requires_pip` is never probed, spec §3 M4); auto-installing anything.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` | MODIFY | `ToolkitRow` gains 3 fields; `inventory()` fills them |
| `packages/ai-parrot/src/parrot/cli/toolkits.py` | MODIFY | `self add` hints in list / picker / install |
| `packages/ai-parrot/tests/cli/test_toolkits_cli.py` | MODIFY | Hint tests + row-field test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_install import ToolkitRow, ToolkitState, dist_available, inventory, install_toolkits  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_install.py:38,32,60,94,152
from parrot.mcp.toolkit_seed import load_template  # verified: packages/ai-parrot/src/parrot/mcp/toolkit_seed.py:63 (already imported by toolkit_install.py:20-29)
from parrot.cli import cli  # verified: packages/ai-parrot/src/parrot/cli/__init__.py:104 (used by tests/cli/test_toolkits_cli.py:9)
from click.testing import CliRunner
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_install.py
class ToolkitRow(BaseModel):                                   # line 38
    requires_dist: tuple[str, ...] = ()                        # line 46
    dist_available: bool = True                                # line 47
def dist_available(requires_dist: Sequence[str]) -> bool:      # line 60 (find_spec only — never imports)
def _resolve_hosts(root, hosts) -> list[HostKind]:             # line 76 — NOTE: hosts=[] is falsy ⇒ detect_hosts(root)
def inventory(root: Path, hosts: Sequence[HostKind] | None = None) -> list[ToolkitRow]:  # line 94
    template = load_template(name)                             # line 110
                requires_dist=template.requires_dist,          # line 130
                dist_available=dist_available(template.requires_dist),  # line 131

# packages/ai-parrot/src/parrot/cli/toolkits.py
def _resolve_names(root, names, hosts) -> list[str]:           # line 38; picker title at line 63:
#   title=f"{row.name} — {row.summary}" + ("" if row.dist_available else " (missing distribution)"),
@toolkits.command("list") def list_(hosts_) -> None:           # line 104-106
#   if row.requires_dist and not row.dist_available:           # line 134
#   Console(width=200).print(table)                            # line 139
@toolkits.command() def install(names, hosts_, yes) -> None:   # line 160-164
#   from parrot.mcp.toolkit_install import install_toolkits    # line 166 (lazy import)
#   _render(report)                                            # line 182 (4 occurrences in file: 182/212/234/256)
#   click.echo("  ℹ Start a new session for the MCP servers to appear.")  # line 183
```
```python
# TASK-4077 (dependency) — packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
class ToolkitTemplate(BaseModel):
    requires_pip: tuple[str, ...] = ()
    post_install: tuple[str, ...] = ()
    requires_env: tuple[str, ...] = ()
```
- Existing tests that must stay green: `packages/ai-parrot/tests/cli/test_toolkits_cli.py`
  (6 tests, lines 12-55+), `packages/ai-parrot/tests/mcp/test_toolkit_install.py`.

### Does NOT Exist
- ~~`ToolkitRow.requires_pip` / `.post_install` / `.requires_env`~~ — added here.
- ~~`parrot self` command~~ — created by TASK-4080; this task only prints the hint text.
- ~~a `--self-add` / auto-install flag on `parrot toolkits install`~~ — never add one (spec non-goal: no implicit dependency changes).
- ~~`parrot status`~~ for this purpose — taken by agentd.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_install.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/cli/toolkits.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/cli/test_toolkits_cli.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#ToolkitRow",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#dist_available",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#inventory",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_install.py#install_toolkits",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#load_template",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#list_",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#install",
    "sym:packages/ai-parrot/src/parrot/cli/toolkits.py#_resolve_names"
  ]
}
```

---

## Implementation Notes

### Pattern to Follow
```python
# packages/ai-parrot/src/parrot/cli/toolkits.py:174-175 — existing yellow advisory line style
click.secho(f"  ⚠ {warning}", fg="yellow")
```

### Key Constraints
- `inventory()` must keep importing no toolkit class (AC1 of FEAT-570,
  `test_inventory_imports_no_toolkit_class`) — the new fields are plain template data.
- Hints go through `click.echo`/`click.secho` (CLI output), never `print`.
- Keep the Deps cell's existing `" (missing)"` suffix — a full sentence in a Rich cell
  wraps/truncates; the actionable hint is a separate line after the table.
- In `install`, compute missingness with `load_template(name)` +
  `dist_available(template.requires_dist)` (lazy-imported inside the command, like line 166)
  — cheaper than a full `inventory()` (no host inspection) and monkeypatchable in tests.

### References in Codebase
- `packages/ai-parrot/src/parrot/cli/toolkits.py:104-183`
- `packages/ai-parrot/src/parrot/mcp/toolkit_install.py:94-136`

---

## Implementation Blueprint

### Steps (in order)
1. Add the three fields to `ToolkitRow` and pass them in `inventory()` — *why*: doctor (TASK-4080) reads `requires_env` from rows.
2. Add a module-level `_self_add_hint(name)` helper in `cli/toolkits.py` — *why*: one wording for all three sites, asserted by tests.
3. Patch the picker title, the `list` footer and the `install` epilogue — *why*: spec §5 "offers `parrot self add` when the distribution is missing".
4. Add tests — *why*: spec §4 `test_toolkits_install_offers_self_add`.

### `packages/ai-parrot/src/parrot/mcp/toolkit_install.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    dist_available: bool = True' packages/ai-parrot/src/parrot/mcp/toolkit_install.py)
# AFTER — insert below `    dist_available: bool = True` (verified: toolkit_install.py:47)
    requires_pip: tuple[str, ...] = ()
    post_install: tuple[str, ...] = ()
    requires_env: tuple[str, ...] = ()
```
```python
# occurrences: 1 (verified: grep -c '                dist_available=dist_available(template.requires_dist),' packages/ai-parrot/src/parrot/mcp/toolkit_install.py)
# AFTER — insert below `                dist_available=dist_available(template.requires_dist),` (verified: toolkit_install.py:131)
                requires_pip=template.requires_pip,  # TASK-4077 field
                post_install=template.post_install,  # TASK-4077 field
                requires_env=template.requires_env,  # TASK-4077 field
```

### `packages/ai-parrot/src/parrot/cli/toolkits.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c 'yes_option = click.option("--yes", is_flag=True, default=False, help="Skip the confirmation prompt.")' packages/ai-parrot/src/parrot/cli/toolkits.py)
# AFTER — insert below the `yes_option = ...` line (verified: cli/toolkits.py:23)


def _self_add_hint(name: str) -> str:
    """Return the actionable fix for a toolkit whose distribution is not importable.

    Args:
        name: Toolkit template name.

    Returns:
        The one-line hint shared by `list`, the picker and `install`.
    """
    return f"run: parrot self add {name}"
```
```python
# occurrences: 1 (verified: grep -c 'title=f"{row.name} — {row.summary}" + ("" if row.dist_available else " (missing distribution)"),' packages/ai-parrot/src/parrot/cli/toolkits.py)
# REPLACE — the picker title line (verified: cli/toolkits.py:63) with:
            title=f"{row.name} — {row.summary}"
            + ("" if row.dist_available else f" (missing distribution — {_self_add_hint(row.name)})"),
```
```python
# occurrences: 1 (verified: grep -c '    Console(width=200).print(table)' packages/ai-parrot/src/parrot/cli/toolkits.py)
# AFTER — insert below `    Console(width=200).print(table)` (verified: cli/toolkits.py:139); the
# `if row.requires_dist and not row.dist_available:` cell suffix at :134 stays unchanged
    for row in rows:
        if row.requires_dist and not row.dist_available:
            click.secho(f"  ℹ {row.name}: missing distribution — {_self_add_hint(row.name)}", fg="yellow")
```
```python
# occurrences: 1 (verified: grep -c '    click.echo("  ℹ Start a new session for the MCP servers to appear.")' packages/ai-parrot/src/parrot/cli/toolkits.py)
# AFTER — insert below that line (verified: cli/toolkits.py:183), inside `install`
    from parrot.mcp.toolkit_install import dist_available, load_template  # lazy, like line 166

    for name in selected:
        template = load_template(name)  # selected names already passed preflight in install_toolkits
        if template.requires_dist and not dist_available(template.requires_dist):
            click.secho(
                f"  ℹ {name}: distribution missing — {_self_add_hint(name)} "
                f"(or `parrot self add {name} --here` for the project venv)",
                fg="yellow",
            )
```
**Why**: `load_template` is re-exported through `toolkit_install`'s own import
(toolkit_install.py:20-29) — import it from there or from `parrot.mcp.toolkit_seed`
(FILL IN: pick one; both verified). The hint is advisory only: never install anything here.

### `packages/ai-parrot/tests/cli/test_toolkits_cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '        assert "absent" in _state_for("google")' packages/ai-parrot/tests/cli/test_toolkits_cli.py)
# AFTER — append below `        assert "absent" in _state_for("google")` (verified: test_toolkits_cli.py:78, last line of the file)


def test_toolkits_install_offers_self_add(tmp_path, monkeypatch):
    """Spec §4 — a missing distribution prints the `parrot self add <name>` hint after install."""
    monkeypatch.setattr("parrot.mcp.toolkit_install.dist_available", lambda _dists: False)
    with CliRunner().isolated_filesystem(temp_dir=tmp_path):
        result = CliRunner().invoke(cli, ["toolkits", "install", "scraping", "--yes"])
        assert result.exit_code == 0, result.output
        assert "parrot self add scraping" in result.output


def test_list_hints_self_add_for_missing_dist(tmp_path, monkeypatch):
    # FILL IN: patch dist_available → False, run `toolkits list`, assert the footer hint for a
    # template with requires_dist (e.g. querysource) — bounded by spec §5
    raise NotImplementedError


def test_no_hint_when_dist_available(tmp_path, monkeypatch):
    # FILL IN: patch dist_available → True; `install memory --yes` output has no "parrot self add" — bounded by AC
    raise NotImplementedError


def test_inventory_rows_carry_install_metadata(tmp_path):
    from parrot.mcp.toolkit_install import inventory

    rows = {row.name: row for row in inventory(tmp_path, hosts=[])}
    assert rows["scraping"].requires_pip == ("ai-parrot-tools[scraping]",)  # TASK-4077 values
    assert rows["querysource"].requires_env == ("PG_USER", "PG_PWD")
```
**Why**: `install` lazily imports `dist_available` from the module at call time, so
patching the module attribute reaches it. `install` with no `--host` and no host config in
the tmp dir still seeds the yaml (precedent: `test_install_hostless_still_seeds_yaml`).

### FILL IN checklist
- [ ] `cli/toolkits.py::install` — import `load_template` from `toolkit_install` or `toolkit_seed`; bounded by the Verified Imports
- [ ] `test_toolkits_cli.py::test_list_hints_self_add_for_missing_dist` — bounded by spec §5
- [ ] `test_toolkits_cli.py::test_no_hint_when_dist_available` — bounded by AC "no hint when present"

---

## Acceptance Criteria

- [ ] `ToolkitRow` carries `requires_pip` / `post_install` / `requires_env`, filled by `inventory()`.
- [ ] `parrot toolkits install <name>` prints `parrot self add <name>` when the template's `requires_dist` is not importable (spec §5, `test_toolkits_install_offers_self_add`).
- [ ] `parrot toolkits list` prints the same hint after the table; the picker title includes it.
- [ ] No hint when the distribution is available; nothing is ever installed by these commands.
- [ ] `inventory()` still imports no toolkit class (`test_inventory_imports_no_toolkit_class` green).
- [ ] `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_install.py packages/ai-parrot/src/parrot/cli/toolkits.py` clean.

---

## Validation Commands

Run from the feature worktree with `PYTHONPATH=packages/ai-parrot/src` (the shared venv is
editable-installed against the main checkout).

- `pytest packages/ai-parrot/tests/cli/test_toolkits_cli.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_toolkit_install.py -q`

---

## Test Specification

See the MODIFY block for `packages/ai-parrot/tests/cli/test_toolkits_cli.py`:
`test_toolkits_install_offers_self_add` (spec §4 name), list/no-hint variants, and the
row-field test.

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
9. **Close the task** with `scripts/sdd/close_task.sh TASK-4078 parrot-installer verified`
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
