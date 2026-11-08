# HOTFIX-agy-permission-hook-2: `parrot sdd install` registers the agy hook and rules

**Feature**: agy-permission-hook — make the SDD command surface usable from the Antigravity CLI
**Spec**: `sdd/briefs/agy-permission-hook.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: HOTFIX-agy-permission-hook-1
**Assigned-to**: unassigned

---

## Context

Task 1 ships `SDD_ALLOW_RULES` and the `parrot sdd hooks agy-permissions --hook` policy. agy only
auto-approves through rules in the user's settings (brief, decision 1-2), so the installer must merge
the managed rules into the user's agy `settings.json` and register the hook in the workspace
`.agents/hooks.json`, mirroring the C32 dangerous-guard wiring for the Claude host.

## Scope

In `packages/ai-parrot/src/parrot/sdd/installer.py`:

- `AGY_HOOK_LINE = "parrot sdd hooks agy-permissions --hook"`, `_AGY_SUFFIX = " sdd hooks agy-permissions --hook"`,
  `AGY_HOOKS_PATH = Path(".agents/hooks.json")`, `AGY_HOOK_NAME = "parrot-sdd-permissions"`, and
  `agy_hook_command(*, portable)` with the same bare/baked rule as `dangerous_hook_command`.
- `agy_settings_paths() -> list[Path]`: every existing file among
  `Path.home()/".gemini/antigravity-cli/settings.json"` and
  `Path.home()/"snap/antigravity-cli/common/.gemini/antigravity-cli/settings.json"`; when neither file
  exists, `[<the non-snap path>]`.
- `_install_agy_permissions(root, receipt, *, portable) -> list[str]`:
  - **Hook:** load `.agents/hooks.json` (missing → `{}`; malformed or not an object → one `warning:`
    line, file untouched, hook step skipped); refuse when the file or a parent resolves outside the repo
    (same symlink check as `_apply_asset`, `installer.py:795`); set the top-level key
    `parrot-sdd-permissions` to `{"PreToolUse": [{"matcher": "run_command", "hooks": [{"type":
    "command", "command": <cmd>, "timeout": 10}]}]}`, keep every other key; write with `indent=2` and
    a trailing newline only when the content changed. Lines: `registered (<form>)`, `updated (<form>)`
    or `already registered`. Record `"agy-permissions"` in `receipt["settings_hooks"]`.
  - **Rules:** for each `agy_settings_paths()` file: load (missing → `{}`; malformed → `warning:` line,
    skip that file); append each `SDD_ALLOW_RULES` entry missing from `permissions.allow` (create the
    containers when absent; never remove, reorder or deduplicate user rules); write `indent=2` plus a
    newline only when something was added. Add only the newly appended rules to `receipt["agy_rules"]`
    (sorted, unique). One action line per file: `<path> — N agy rule(s) added` or `— agy rules present`.
- `_remove_agy_permissions(root, receipt) -> list[str]`: drop the `parrot-sdd-permissions` key (delete
  the file and prune empty parents when the object becomes empty, `_prune_empty_parents`,
  `installer.py:1347`); remove exactly `receipt["agy_rules"]` from every `agy_settings_paths()` file
  (drop `allow`/`permissions` only when they become empty); clear the receipt keys.
- `_agy_permissions_report(root) -> dict`: `{"form": "bare"|"baked"|None, "command": str|None,
  "settings": [str], "missing_rules": int}` (`missing_rules` counted against the first settings path).
- `plan_install(..., agy_permissions: bool = True)`: append
  `PlannedAction(action="agy-permissions", target=".agents/hooks.json")` when `agy_permissions` and
  `"google"` is a selected host. `plan_uninstall`: append `agy-permissions-remove` when `"google"` is
  selected and `"agy-permissions"` is in `receipt["settings_hooks"]`. Add both names to `PlanAction`.
- `install_sdd_integration(..., agy_permissions: bool = True)` dispatches the step;
  `uninstall_sdd_integration` dispatches the removal; `sdd_status` adds `"agy_permissions"`.
- `load_receipt` keeps `agy_rules` (list of strings), like `toolkits` at `installer.py:312`.

In `packages/ai-parrot/src/parrot/sdd/cli.py`: `--no-agy-permissions` flag on `install` (help: "Do not
register the Antigravity (agy) permission hook and rules for the google host."), passed as
`agy_permissions=not no_agy_permissions`.

Docs in `wiki/operations/install/global-runtime.md` (SDD install section): a short "Antigravity (agy)"
paragraph with a `<!-- verify: flag=sdd install:--no-agy-permissions -->` marker: what the google host
install adds (the hook in `.agents/hooks.json` and the managed rules in the user's agy settings), that
destructive commands are still denied or confirmed, that uninstall removes only the rules it added,
and that the snap build cannot run the SDD flow (its confinement hides the project venv and `ssh`), so
install agy with `curl -fsSL https://antigravity.google/cli/install.sh | bash`.

**NOT in scope**: the classifier (task 1); `parrot google install` (wiki installer); writing agy
`permissions.deny` rules.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | agy hook + rules install/uninstall/status, plan actions, receipt key |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `--no-agy-permissions` |
| `packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py` | CREATE | installer tests (fake `HOME`) |
| `wiki/operations/install/global-runtime.md` | MODIFY | agy paragraph + snap caveat |

---

## Codebase Contract (Anti-Hallucination)

### Verified anchors (origin/dev @ f426e44f8d, 2026-11-08)
```
packages/ai-parrot/src/parrot/sdd/installer.py:32    from parrot.launcher import managed_launcher_on_path, script_path
packages/ai-parrot/src/parrot/sdd/installer.py:145   PlanAction = Literal[ … "dangerous-guard", "dangerous-guard-remove", … ]
packages/ai-parrot/src/parrot/sdd/installer.py:278   def load_receipt(root: Path) -> dict[str, Any]:   (307-314: settings_hooks / toolkits normalization)
packages/ai-parrot/src/parrot/sdd/installer.py:344   def guard_hook_command(*, portable: bool | None) -> tuple[str, Literal["bare", "baked"]]:
packages/ai-parrot/src/parrot/sdd/installer.py:361   DANGEROUS_HOOK_LINE = "parrot sdd hooks dangerous-actions --hook"
packages/ai-parrot/src/parrot/sdd/installer.py:366   def dangerous_hook_command(*, portable: bool | None) -> tuple[str, Literal["bare", "baked"]]:
packages/ai-parrot/src/parrot/sdd/installer.py:396   def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]:
packages/ai-parrot/src/parrot/sdd/installer.py:437   def _remove_dangerous_guard(root: Path, receipt: dict[str, Any]) -> list[str]:
packages/ai-parrot/src/parrot/sdd/installer.py:473   def _dangerous_guard_report(root: Path) -> dict[str, Any]:
packages/ai-parrot/src/parrot/sdd/installer.py:523   def plan_install(root, hosts, *, keep_edits=False, hook=GUARD_HOOK_LINE, base_branch=None, dangerous_guard=True, sdd_coder=True)
packages/ai-parrot/src/parrot/sdd/installer.py:568   if dangerous_guard and "claude" in _validate_hosts(hosts):
packages/ai-parrot/src/parrot/sdd/installer.py:709   def plan_uninstall(root: Path, hosts: Sequence[str], *, keep_edits: bool = False) -> list[PlannedAction]:
packages/ai-parrot/src/parrot/sdd/installer.py:745   if "claude" in selected_hosts and "dangerous-actions" in receipt.get("settings_hooks", []):
packages/ai-parrot/src/parrot/sdd/installer.py:795   if target.is_symlink() or not _under(Path(os.path.realpath(target)), Path(os.path.realpath(root))):
packages/ai-parrot/src/parrot/sdd/installer.py:1135  def install_sdd_integration(root, hosts=("claude",), *, …, dangerous_guard=True, sdd_coder=True) -> list[str]:
packages/ai-parrot/src/parrot/sdd/installer.py:1232  elif step.action == "dangerous-guard":
packages/ai-parrot/src/parrot/sdd/installer.py:1347  def _prune_empty_parents(root: Path, path: Path) -> None:
packages/ai-parrot/src/parrot/sdd/installer.py:1459  def uninstall_sdd_integration(root, hosts=("claude",), *, keep_edits=False, dry_run=False) -> list[str]:
packages/ai-parrot/src/parrot/sdd/installer.py:1512  elif step.action == "dangerous-guard-remove":
packages/ai-parrot/src/parrot/sdd/installer.py:1636  def sdd_status(root: Path) -> dict[str, Any]:   (1677: "dangerous_guard": _dangerous_guard_report(root))
packages/ai-parrot/src/parrot/sdd/cli.py:95          @click.option("--no-dangerous-guard", is_flag=True, help=…)   (passed at :133)
packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py:22   @pytest.fixture def repo(tmp_path)   (git init -q -b main; test style to mirror)
wiki/operations/install/global-runtime.md:229        ```bash … parrot sdd install --host claude --dry-run
```

### Does NOT Exist
- No installer code touches `.agents/hooks.json` or any agy `settings.json` today.
- The receipt has no `agy_rules` key yet; `load_receipt` drops unknown keys, so it must be added.

---

## Acceptance Criteria

- [ ] `install_sdd_integration(repo, ("google",))` with a fake `HOME` writes the named hook into
      `.agents/hooks.json` and adds every `SDD_ALLOW_RULES` rule to the agy settings; a second run
      changes no bytes and reports "already registered" / "agy rules present".
- [ ] Foreign hooks in `.agents/hooks.json` and the user's own rules and settings keys survive install
      and uninstall; a rule the user already had is not recorded and is not removed by uninstall.
- [ ] A malformed `.agents/hooks.json` or `settings.json` is never rewritten; install reports a warning.
- [ ] A symlinked `.agents/hooks.json` pointing outside the repo is refused.
- [ ] Both settings paths (non-snap and snap) are updated when both exist.
- [ ] `--no-agy-permissions` and a claude-only install plan no `agy-permissions` step; `--dry-run`
      shows `plan: agy-permissions .agents/hooks.json` and writes nothing (HOME included).
- [ ] `sdd_status` reports the hook form and missing-rule count.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer_agy_permissions.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_installer.py -q`

## Agent Instructions

Read the brief first. Touch only the listed files. Never touch the real `HOME` in tests:
`monkeypatch.setenv("HOME", str(tmp_path / "home"))`.

## Completion Note

<!-- filled in when the task closes -->
