# TASK-3214: Wire seeding + approval into `parrot claude install` (CLI and step order)

**Feature**: FEAT-556 — `parrot claude install` seeds and authorizes the Parrot MCP servers
**Spec**: `sdd/specs/claude-install-mcp-autoenable.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3213
**Assigned-to**: unassigned

---

## Context

Implements spec §3 Module 4. TASK-3211 built the seeder, TASK-3212 pinned the
entry shape and TASK-3213 wrote the approval function — but nothing calls the
seeder or the approval yet. This task exposes both on the CLI and fixes the step
order inside `install_claude_integration`, which is part of the contract:
seeding must run BEFORE `_install_mcp_json` (`installer.py:630`) so the new
sections produce entries, and approval must run AFTER it so the managed-name set
is final.

§8 Q1 is resolved: `--toolkits` defaults to **empty** (opt-in), with
`--all-toolkits` as the "seed everything shipped" shortcut, so running
`parrot claude install` in an unrelated repo never registers a model-seat
orchestrator. The output must name both flags and the available templates, or
the feature is undiscoverable.

---

## Scope

- Extend `install_claude_integration` with `toolkits: Sequence[str] = ()` and
  `approve_mcp: bool = True`, calling `seed_toolkit_sections` before
  `_install_mcp_json` and `_install_mcp_approval` after it.
- Add `--toolkits`, `--all-toolkits` and `--approve-mcp/--no-approve-mcp` to the
  `parrot claude install` command.
- Print a one-line hint naming `--toolkits` / `--all-toolkits` and the available
  template names when no toolkit flag was given.
- Tell the operator that a new Claude Code session is needed for the servers to
  appear.
- Extend `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` and
  `tests/knowledge/wiki/test_cli.py`-style CLI coverage.

**NOT in scope**: codex/google CLIs (TASK-3215). Do not change the existing
`--git-hook` / `--gitignore` / `--build` / `--bookstore` / `--tool-guards`
semantics, and do not reorder the steps that already exist beyond inserting the
two new ones.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` | MODIFY | New kwargs + two new ordered steps |
| `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` | MODIFY | Three new options, hint + session note |
| `packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py` | MODIFY | End-to-end install ordering tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import click                                                  # verified: claude_code/cli.py:10 region
from parrot.knowledge.wiki.claude_code.installer import install_claude_integration  # verified: claude_code/cli.py imports it for the command
from parrot.knowledge.wiki.project import WikiConfigError, WikiProjectConfig, load_effective_config  # verified: installer.py:40-46
from parrot.mcp.toolkit_seed import available_templates, seed_toolkit_sections    # created by TASK-3211
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def install_claude_integration(                       # line 589
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    git_hook: bool = True,
    gitignore: bool = True,
    bookstore: bool = True,
) -> list[str]: ...
    # root = root.resolve()                           # line 610
    # save_project_config(root, config)               # line 625
    # actions.append(_install_claude_md(root))        # line 627
    # actions.append(_install_settings_hook(root))    # line 628
    # actions.extend(_install_permissions(root))      # line 629
    # actions.append(_install_mcp_json(root))         # line 630  <-- seed BEFORE, approve AFTER
    # actions.append(_install_slash_command(root))    # line 631
    # if git_hook: ... if gitignore: ... if bookstore: ...  # lines 632-639

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py
@claude.command()                                     # line 54
@path_option                                          # line 55
# options: --git-hook/--no-git-hook (57), --gitignore/--no-gitignore (63),
#          --build/--no-build (69), --bookstore/--no-bookstore (76),
#          --tool-guards/--no-tool-guards (82)
def install(path_, git_hook, gitignore, build_now, bookstore, tool_guards) -> None:  # line 87
    #   root = _resolve_root(path_)
    #   actions = install_claude_integration(root, config, git_hook=..., gitignore=..., bookstore=...)
    #   for action in actions: click.echo(f"  ✓ {action}")
```

### Does NOT Exist
- ~~a `--toolkits` option on any `parrot <host> install` command~~ — this task
  introduces the first one.
- ~~`install_claude_integration(..., seed=...)`~~ — the parameter names fixed by
  spec §3 Module 4 are `toolkits` and `approve_mcp`; use them verbatim, they are
  mirrored by TASK-3215.
- ~~a CLI helper that splits comma lists~~ — there is no existing utility; do
  the split in the command body (`[n.strip() for n in value.split(",") if n.strip()]`).
- ~~`click.option(..., multiple=True)` usage elsewhere in this CLI~~ — the file
  uses flag pairs and simple values only; a comma-separated string keeps the
  surface consistent with `--path`.

---

## Implementation Notes

### Key Constraints
- Keyword-only defaults: the new parameters must not break the existing
  positional call sites (`cli.py` passes `root, config` positionally).
- `--toolkits` and `--all-toolkits` combine as a union; `--all-toolkits` alone
  means `available_templates()`.
- Seeding failure must not be silent: let `ValueError` from the seeder surface
  as a `click.ClickException` like the existing `RuntimeError`/`WikiConfigError`
  handling does.
- `approve_mcp=True` is the default (it is the whole point of the feature); the
  negative flag exists for operators who manage approvals themselves.

### References in Codebase
- `cli.py:87-112` — the command body, its exception mapping, and the
  `  ✓ {action}` echo loop to extend.
- `installer.py:627-639` — the step list to insert into.

---

## Implementation Blueprint

### Steps (in order)
1. Extend `install_claude_integration`'s signature and step list — *why*: the
   CLI is a thin wrapper; putting the ordering rule in the installer means
   codex/google (TASK-3215) and any programmatic caller inherit it.
2. Add the CLI options and resolve `--all-toolkits` into the name list — *why*:
   the installer takes names, not flags, so flag interpretation belongs here.
3. Add the hint + session note to the output — *why*: §8 Q1 chose opt-in, which
   is only acceptable if the install tells the operator what to opt into.
4. Extend the install tests, asserting a single pass produces the entry — *why*:
   the ordering bug (seed after reconcile) would otherwise only show up as "run
   install twice and it works".

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY — signature)
```python
# occurrences: 1 (verified: grep -c '^def install_claude_integration(' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# REPLACE the signature and extend the docstring Args (verified: installer.py:589-607)
def install_claude_integration(
    root: Path,
    config: Optional[WikiProjectConfig] = None,
    git_hook: bool = True,
    gitignore: bool = True,
    bookstore: bool = True,
    toolkits: Sequence[str] = (),
    approve_mcp: bool = True,
) -> list[str]:
    """Install the wiki ↔ Claude Code integration into a repository.

    Args:
        ...existing args...
        toolkits: Toolkit template names to seed into
            `.parrot/mcp-toolkits.yaml` before `.mcp.json` reconciliation.
            Empty seeds nothing (spec §8 Q1: opt-in).
        approve_mcp: Authorize the managed servers in
            `.claude/settings.local.json` after reconciliation.

    Returns:
        Human-readable list of actions performed.
    """
```
**Why this shape**: `Sequence[str]` (not `list`) keeps a tuple default immutable;
`approve_mcp=True` makes the fix apply to every existing caller without their
having to opt in, which is what the feature promises.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py` (MODIFY — steps)
```python
# occurrences: 1 (verified: grep -c '    actions.append(_install_mcp_json(root))' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py)
# BEFORE — insert above `    actions.append(_install_mcp_json(root))` (verified: installer.py:630)
    if toolkits:
        from parrot.mcp.toolkit_seed import seed_toolkit_sections

        seeded = seed_toolkit_sections(root, toolkits)
        # FILL IN: turn `seeded` (SeedResult) into one or more action strings —
        # report created_file, added, skipped and unknown distinctly; bounded by
        # the existing phrasing style (".parrot/mcp-toolkits.yaml — ...") and by
        # AC "its output names the available template names"
# AFTER — insert below `    actions.append(_install_mcp_json(root))` (verified: installer.py:630)
    if approve_mcp:
        actions.append(_install_mcp_approval(root))
```
**Why**: this is the ordering contract from spec §2 — seed first so
`_install_mcp_json` sees the sections, approve after so
`_managed_server_names` (which re-reads the config) includes them. Do not move
either call past `_install_slash_command`.

### `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '    "--tool-guards/--no-tool-guards",' packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/cli.py)
# AFTER — insert below the `--tool-guards/--no-tool-guards` option block (verified: cli.py:82-86)
@click.option(
    "--toolkits",
    "toolkits_",
    default="",
    help="Comma-separated toolkit sections to seed into .parrot/mcp-toolkits.yaml (e.g. sdd-coder,bounded-source).",
)
@click.option(
    "--all-toolkits",
    "all_toolkits",
    is_flag=True,
    default=False,
    help="Seed every toolkit template shipped with this release.",
)
@click.option(
    "--approve-mcp/--no-approve-mcp",
    default=True,
    show_default=True,
    help="Authorize the managed MCP servers in .claude/settings.local.json.",
)
```
**Why**: mirrors the existing option style exactly (flag pair with
`show_default` for the boolean, plain value for the list), so `--help` reads
uniformly.
**FILL IN** in the command body: add the three parameters to `def install(...)`,
resolve them (`names = sorted({*split(toolkits_)} | set(available_templates() if all_toolkits else ()))`),
pass `toolkits=names, approve_mcp=approve_mcp`, map a seeder `ValueError` to
`click.ClickException`, and after the action loop echo (a) the
`--toolkits`/`--all-toolkits` hint with `", ".join(available_templates())` when
`not names`, and (b) the "start a new Claude Code session for the MCP servers to
appear" note when `names or approve_mcp` — bounded by AC "its output names
`--toolkits` / `--all-toolkits` with the available template names".

### FILL IN checklist
- [ ] `installer.py::install_claude_integration` — SeedResult → action strings; bounded by the existing phrasing style
- [ ] `cli.py::install` — parameters, flag resolution, exception mapping, hint + session note

---

## Acceptance Criteria

- [ ] `install_claude_integration(root, toolkits=["sdd-coder"])` produces both the
      YAML section and the `parrot-sdd-coder` entry in ONE pass
- [ ] The same call adds the managed names to `enabledMcpjsonServers`
- [ ] `approve_mcp=False` writes no `enabledMcpjsonServers`
- [ ] No toolkit flag → no `.parrot/mcp-toolkits.yaml` is created, and the output
      names `--toolkits` / `--all-toolkits` plus the available template names
- [ ] `--all-toolkits` seeds exactly `available_templates()`
- [ ] The output tells the operator a new Claude Code session is needed
- [ ] A seeder `ValueError` surfaces as a `click.ClickException`, not a traceback
- [ ] Existing flags are unchanged; existing positional call sites still work
- [ ] All tests pass: `pytest packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py -v`
      and `pytest tests/knowledge/wiki/test_claude_code.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/`

---

## Test Specification

```python
# packages/ai-parrot/tests/knowledge/wiki/test_installer_mcp.py  (extend)
import json

from parrot.knowledge.wiki.claude_code.installer import install_claude_integration


class TestSeedingAndApproval:
    def test_install_seeds_before_reconciliation(self, repo_root):
        install_claude_integration(repo_root, toolkits=["bounded-source"], bookstore=False)
        servers = json.loads((repo_root / ".mcp.json").read_text())["mcpServers"]
        assert "parrot-bounded-source" in servers
        assert (repo_root / ".parrot" / "mcp-toolkits.yaml").exists()

    def test_toolkits_default_is_empty(self, repo_root):
        install_claude_integration(repo_root, bookstore=False)
        assert not (repo_root / ".parrot" / "mcp-toolkits.yaml").exists()

    def test_install_no_approve_flag_skips_approval(self, repo_root):
        install_claude_integration(repo_root, approve_mcp=False, bookstore=False)
        local = json.loads((repo_root / ".claude" / "settings.local.json").read_text())
        assert "enabledMcpjsonServers" not in local

    def test_all_toolkits_seeds_every_template(self, repo_root):
        # FILL IN: call with the CLI's resolution (or available_templates()) and
        # assert every template name appears in the seeded YAML
```
CLI-level coverage (options present, hint printed, ClickException on a seeder
error) follows the `click.testing.CliRunner` style already used for
`parrot claude` commands in `tests/knowledge/wiki/test_cli.py`.

---

## Agent Instructions

1. **Read the spec** §2 Overview (the ordering contract) and §3 Module 4.
2. **Check dependencies** — TASK-3213 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `installer.py:589-641` and
   `cli.py:54-112`; both files were edited by TASK-3212/3213, so line numbers
   have shifted.
4. **Update status** in `sdd/tasks/index/claude-install-mcp-autoenable.json` → `"in-progress"`.
5. **Implement** from the blueprint; complete every `# FILL IN:` marker.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3214-install-cli-orchestration.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5), after a fidelity_violation from the
automated `parrot-sdd-coder` dispatch (qwen/nova seat) — that attempt correctly
implemented installer.py/cli.py per the blueprint but also modified an unlisted
file (`tests/knowledge/wiki/test_claude_code.py`), so it was not merged. This
implementation was written directly in the worktree, using that attempt's
installer.py/cli.py diff as a verified-correct reference.
**Date**: 2026-09-13
**Notes**: `install_claude_integration` gained `toolkits: Sequence[str] = ()` and
`approve_mcp: bool = True`, seeding `.parrot/mcp-toolkits.yaml` before
`_install_mcp_json` and calling `_install_mcp_approval` after it. `parrot claude
install` gained `--toolkits`, `--all-toolkits` and `--approve-mcp/--no-approve-mcp`,
plus a discoverability hint (available template names) when no toolkit flag is
given and a "restart Claude Code session" note. All 10 new tests in
`test_installer_mcp.py` (TestSeedingAndApproval, TestInstallCLIToolkitOptions)
pass; `ruff check` clean; `black` applied.

**Deviations from spec**: `approve_mcp=True` by default (per spec) changes the
action count of every `install_claude_integration()` call, which broke a
pre-existing assertion in `tests/knowledge/wiki/test_claude_code.py`
(`test_fresh_install_writes_all_artifacts`, `len(actions) == 8`) — a file NOT
in this task's Files-to-Modify list. Updated the one assertion (8 → 9) to keep
the suite green; no other change was made to that file. Flagging per Cardinal
Rule 4 rather than silently expanding scope.

Pre-existing, unrelated failures observed in both the pre-task baseline and
after this change (confirmed via `git stash`): `test_install_creates_mcp_json`,
`test_install_idempotent`, `test_install_updates_stale_entry` in
`test_installer_mcp.py::TestMCPJsonInstall` — caused by a global
`~/.parrot/mcp-toolkits.yaml` on this machine seeding `browsing`/`memory`/
`scraping` toolkit sections and resolving `wikitoolkit`'s command to an
absolute venv path. Not touched; out of this task's scope.
