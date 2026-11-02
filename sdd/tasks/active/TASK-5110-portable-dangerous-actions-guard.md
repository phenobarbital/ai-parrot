# TASK-5110: Portable dangerous-actions guard, installed by `parrot sdd install`

**Feature**: FEAT-633 — Parrot Bootstrap Installer
**Spec**: `sdd/specs/parrot-installer.spec.md` (rev 0.11, amendment C32)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5109 (TASK-4085, TASK-4089, TASK-4509 already done)
**Assigned-to**: unassigned

---

## Context

ai-parrot protects its own sessions with `.claude/hooks/dangerous-actions-blocker.sh` (PreToolUse,
`Bash|Edit|Write`): it blocks `git reset --hard`, force-push to long-lived branches, `git clean -fdx`,
recursive deletes of `/`/`~`, destructive SQL, direct package publication, literal secrets in commands,
and writes to secret files — each block names the safe alternative. The 2026-10-14 amendments proposal
classified it "stays in the repo", so a foreign repo set up with `parrot sdd install` gets none of it.

The bash hook cannot simply be shipped: it needs `bash`, `jq`, `python3`, GNU `grep -E` and `pgrep`; it
**fails open** when `jq` is missing (on a stock Windows host it never blocks anything); it hard-codes
`main|dev|staging|master`; and its fixes name ai-parrot-only tools (`scripts/remove_worktree.py`,
`/release`, `scripts/release.py`, `make distclean`). Spec rev 0.11 amendment C32 is the normative text:
port it to stdlib Python, serve it through the `parrot` launcher like the worktree guard, and register it
in `.claude/settings.json` from the installer — the same protection on Linux, macOS and Windows.

---

## Scope

- Create `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` (stdlib only; it must import
  nothing from `parrot` except, lazily and guarded, `parrot.sdd.config.load_sdd_config`):
  - `evaluate(payload: dict, *, root: Path | None) -> Verdict` — pure; `Verdict` is a small dataclass
    `(decision: Literal["allow", "deny", "warn"], reason: str)`.
  - `main(argv: Sequence[str] | None = None) -> None` — `--hook` required (argparse, like
    `worktree_environment.main`); reads the PreToolUse JSON from stdin; writes exactly one JSON line to
    stdout: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "<BLOCKED … + safe alternative>"}}` for a block, `{"systemMessage": …}`
    for a warning, `{}` to allow. Always exit 0 (the decision is in the JSON, as in the worktree guard).
  - Malformed stdin or an internal error → allow with a `systemMessage` naming the failure (the bash
    hook's documented fail-open, now visible). `PARROT_ALLOW_DANGEROUS=1` → allow, no checks.
- Port every rule of `.claude/hooks/dangerous-actions-blocker.sh` with these changes:
  - **Protected branches** = `{config.base_branch, config.staging_branch, config.hotfix_base, "main", "master"}`
    minus `None`, from `load_sdd_config(root)`; defaults when there is no config or it is invalid.
  - **Quoted-text stripping** keeps the bash semantics (text inside quotes is ignored, except when handed
    to `bash|sh|zsh|dash -c`, `eval`, `ssh`, `pwsh|powershell -Command`, `cmd /c`).
  - **Windows destroyers** (new): `Remove-Item … -Recurse` (any case, `-r`/`-Force` aliases) on a drive
    root or `$HOME`/`~`/`$env:USERPROFILE`; `rd /s` / `rmdir /s` / `del /s` on a drive root; `format X:`.
  - **macOS destroyers** (new): `diskutil eraseDisk|eraseVolume|partitionDisk|zeroDisk|randomDisk`.
  - **Repo-critical deletes**: `.git`, `.venv`, `.claude/worktrees` (drop ai-parrot's `packages/`).
  - **Bare `pip install`** blocks only when `root/uv.lock` exists (the repo is uv-managed).
  - **Messages** name only portable fixes: `git …`, `parrot sdd worktree status`, `/remove-worktree`,
    "publish through your release workflow", `uv add` / `uv pip install`. No `scripts/…`, `make …`, `/release`.
  - **Edit/Write/MultiEdit**: normalize `\` to `/` before matching paths; same secret-file names, `*.pem`,
    `*.key`, `/.ssh/`, `/.venv/`, `/node_modules/`, `/.git/objects/`; `.env.example|.sample|.template|.dist|.test` allowed.
  - **Live sdd-worker warning** on `git merge|pull`: via `psutil` only if importable, else skipped (no `pgrep`).
- Mount it: `VERBS["hooks"]["dangerous-actions"] = ("dangerous_actions", (), "Serve the PreToolUse dangerous-actions guard (--hook).")`
  in `parrot/sdd/cli.py`.
- Launcher fast path: in `parrot/launcher.py`, `DANGEROUS_HOOK_ARGV = ["sdd", "hooks", "dangerous-actions", "--hook"]`
  dispatched in `main_parrot()` next to `SDD_HOOK_ARGV`, so a hook call never imports `parrot.cli`
  (the worktree guard starts in ~0.04 s this way; the full CLI does not).
- Installer (claude host only), in `parrot/sdd/installer.py`:
  - `dangerous_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]` — the same
    bare/baked rule as `guard_hook_command`, but **no shell operators** (no `|| exit 2`): one executable
    plus arguments, so the line runs unchanged under cmd, PowerShell and bash.
  - a `dangerous-guard` plan step (claude host, unless `dangerous_guard=False`) that merges one entry
    `{"matcher": "Bash|Edit|Write|MultiEdit", "hooks": [{"type": "command", "command": <cmd>, "timeout": 10}]}`
    into `.claude/settings.json` `hooks.PreToolUse` — reuse `_load_settings` / `_write_settings` from
    `parrot.knowledge.wiki.claude_code.installer` (lazy import, as `_install_ledger_hooks_step` does);
    upgrade our own entry in place on re-install (bare ↔ baked); never touch foreign entries.
  - skip with `note:` when any existing PreToolUse command contains `dangerous-actions-blocker` (the repo
    already runs its own blocker — ai-parrot itself).
  - record it as `receipt["settings_hooks"] = ["dangerous-actions"]`; `uninstall` removes only our entry
    (matched by the `sdd hooks dangerous-actions --hook` suffix), and only when the receipt recorded it.
  - `install_sdd_integration(..., dangerous_guard: bool = True)`; CLI flag `--no-dangerous-guard`.
  - `sdd_status()` gains `"dangerous_guard": {"form": "bare"|"baked"|None, "command": str | None}`.
- Tests: `test_dangerous_actions.py` (rule table) and `test_installer_dangerous_guard.py` (settings merge).
  Include a parity test that, when `bash` and `jq` are on PATH and the repo-root
  `.claude/hooks/dangerous-actions-blocker.sh` exists, runs the bash hook on the shared cases and asserts
  the same allow/deny verdict (skip otherwise) — it keeps the two implementations from drifting.
- Update `docs/getting-started.md` (what the guard blocks, `PARROT_ALLOW_DANGEROUS=1`, `--no-dangerous-guard`).

**NOT in scope**:
- Replacing ai-parrot's own `.claude/settings.json` registration of the bash hook (follow-up; the parity test covers drift).
- Codex / Google hosts (no equivalent PreToolUse surface wired by the installer today) — the installer prints nothing for them.
- `doctor --sdd` reporting the guard (status only in this task).
- The `sdd-worker-format.sh` registration note (unchanged).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | CREATE | Stdlib port of the blocker: `evaluate()`, `main()` |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | Mount `hooks dangerous-actions`; `--no-dangerous-guard` on `install` |
| `packages/ai-parrot/src/parrot/launcher.py` | MODIFY | `DANGEROUS_HOOK_ARGV` fast path in `main_parrot()` |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `dangerous_hook_command`, `dangerous-guard` plan step, settings merge, receipt, uninstall, status |
| `packages/ai-parrot/tests/sdd/test_dangerous_actions.py` | CREATE | Rule table (Linux/macOS/Windows), quoting, escape hatch, config branches, bash parity |
| `packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py` | CREATE | settings.json merge/upgrade/skip/uninstall, dry-run, status |
| `docs/getting-started.md` | MODIFY | Guard behaviour, escape hatch, opt-out |

---

## Codebase Contract (Anti-Hallucination)

Verified on `origin/feat-FEAT-633-parrot-installer` at `b521bda1e4` (2026-11-03; includes PR #1932 / C33). TASK-5109 edits
`installer.py` / `cli.py` first; re-verify line numbers after it lands.

### Verified Imports
```python
from parrot.sdd.config import load_sdd_config                     # parrot/sdd/config.py:106 (lazy, guarded)
from parrot.knowledge.wiki.claude_code.installer import _load_settings, _write_settings  # :244, :268 (lazy)
from parrot.launcher import parrot_home, script_path              # already imported by installer.py:29
```

### Existing Signatures to Use
```python
# .claude/hooks/dangerous-actions-blocker.sh (repo root, 261 lines) — the rule source to port
#   strip_quoted() :54 · git rules :86-147 · filesystem :150-174 · SQL :179 · publish :187 · pip :195
#   secrets :212 · sdd-worker warn :220 · Edit/Write :229-258 · PARROT_ALLOW_DANGEROUS :19 · jq fail-open :23

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
def main(argv: Sequence[str] | None = None) -> None   # line 571 — argparse --hook required; JSON on stdout
#   deny shape, line 588-594: {"hookSpecificOutput": {"hookEventName": "PreToolUse",
#                              "permissionDecision": "deny", "permissionDecisionReason": ...}}

# packages/ai-parrot/src/parrot/launcher.py
SDD_HOOK_ARGV = ["sdd", "worktree", "guard", "--hook"]   # line 269
def main_parrot() -> int                                # line 272 — fast path inside load()

# packages/ai-parrot/src/parrot/sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]]   # line 124
    "hooks": {"install": ("install_hooks", (), "Install the SDD git hooks.")},   # line 176
_UNMOUNTED: frozenset[str]                                      # mounted == modules with main() minus this
def install(path_, hosts, force, portable, dry_run) -> None    # line 74

# packages/ai-parrot/src/parrot/sdd/installer.py
GUARD_HOOK_LINE / _GUARD_HOOK_SUFFIX                         # lines 64-65
def guard_hook_command(*, portable: bool) -> tuple[str, Literal["bare", "baked"]]  # line 256 — copy its PATH/parrot_home rule
def plan_install(root, hosts, *, force=False, hook=GUARD_HOOK_LINE) -> list[PlannedAction]  # line 310
def _install_ledger_hooks_step(root, receipt) -> list[str]   # line 512 — lazy-import pattern into claude_code.installer
def install_sdd_integration(root, hosts=("claude",), *, force=False, dry_run=False, portable=False) -> list[str]  # line 627
def uninstall_sdd_integration(root, hosts=("claude",), *, dry_run=False) -> list[str]  # line 709
def sdd_status(root: Path) -> dict[str, Any]                 # line 843

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py
def _load_settings(path: Path) -> Optional[dict[str, Any]]   # line 244 — None if absent; RuntimeError if not a JSON object
def _write_settings(path: Path, settings: dict[str, Any]) -> None  # line 268
def _install_settings_hook(root, *, portable=False) -> str   # line 274 — merge/upgrade pattern to follow

# packages/ai-parrot/tests/sdd/test_sdd_cli.py
def test_sdd_cli_mounts_every_helper() -> None               # line 83 — the new module must be mounted
```

### Does NOT Exist
- ~~`parrot.sdd.scripts.dangerous_actions`~~ — created by this task
- ~~`parrot sdd hooks dangerous-actions`~~ — created by this task (today `hooks` has only `install`)
- ~~a settings.json writer in `parrot.sdd.installer`~~ — reuse the claude_code installer's helpers
- ~~`receipt["settings_hooks"]`~~ — new key; older receipts lack it
- ~~`pgrep` / `jq` in the port~~ — never shell out for parsing or process listing

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/sdd/cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/launcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/sdd/installer.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_dangerous_actions.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py", "action": "CREATE"},
    {"path": "docs/getting-started.md", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py#main",
    "sym:packages/ai-parrot/src/parrot/launcher.py#main_parrot",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#guard_hook_command",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#plan_install",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#install_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#uninstall_sdd_integration",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#sdd_status",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_install_ledger_hooks_step",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_load_settings",
    "sym:packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/installer.py#_write_settings",
    "sym:packages/ai-parrot/src/parrot/sdd/config.py#load_sdd_config"
  ]
}
```

---

## Implementation Notes

- Startup cost matters: the hook runs on every tool call. Keep module import stdlib-only; measure
  `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | parrot sdd hooks dangerous-actions --hook`
  and keep it in the same range as `parrot sdd worktree guard --hook` (record both timings in the Completion Note).
- `root` for config/uv.lock lookups = the payload `cwd` walked up to the git top level (no subprocess:
  look for a `.git` entry), falling back to `cwd`.
- Regexes are Python `re`, not ERE; port the intent, not the escaping. One table of `(name, pattern, message)`
  makes the parity test easy.
- Windows paths: compare with `PurePosixPath(path.replace("\\", "/"))`; drive roots `^[A-Za-z]:[\\/]?$`.
- No `print`; JSON goes through `sys.stdout.write(json.dumps(...) + "\n")` like the worktree guard.
- The spec's §4 "27 of 29" mounted-module count in `test_sdd_cli_mounts_every_helper`'s description becomes 28 of 30;
  the test itself compares sets, so it only needs the new mount.

---

## Acceptance Criteria

- [ ] `parrot sdd hooks dangerous-actions --hook` denies `git reset --hard`, `git push --force origin <base_branch>`,
      `rm -rf ~`, `Remove-Item -Recurse -Force C:\`, `rd /s /q C:\`, `format D:`, `diskutil eraseDisk …`,
      `psql -c "DROP TABLE x"`, `twine upload dist/*`, a literal `ghp_…` token, and a Write to `.env`.
- [ ] It allows `echo "git reset --hard"`, `git push --force-with-lease origin feat-x`, `rm -rf build/`,
      `--token "$GH_TOKEN"`, `AKIAIOSFODNN7EXAMPLE`, and a Write to `env/.env.example`.
- [ ] `bash -c "git reset --hard"` and `pwsh -Command "Remove-Item -Recurse C:\"` are denied.
- [ ] Protected branches follow `sdd/config.json` (`base_branch: "trunk"` → force-push to `trunk` denied).
- [ ] `PARROT_ALLOW_DANGEROUS=1` allows everything; malformed stdin → allow + `systemMessage`.
- [ ] The hook path never imports `parrot.cli` (assert with `sys.modules` in a subprocess test).
- [ ] `parrot sdd install` (claude) adds exactly one PreToolUse entry; re-install does not duplicate it;
      `--portable` writes the bare form; foreign entries are kept byte-identical; a `dangerous-actions-blocker`
      entry makes it skip with a `note:`; `--no-dangerous-guard` adds nothing; `--dry-run` writes nothing.
- [ ] Uninstall removes only our entry and only when the receipt recorded it.
- [ ] Bash parity test passes where `bash`+`jq` exist, skips cleanly elsewhere.
- [ ] `test_sdd_cli.py`, `test_installer.py`, `test_launcher_sdd_hook.py`, `test_no_repo_script_refs.py` still pass; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_dangerous_actions.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer_dangerous_guard.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_sdd_cli.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_installer.py -q`
- `pytest packages/ai-parrot/tests/launcher/test_launcher_sdd_hook.py -q`
- `pytest packages/ai-parrot/tests/sdd/test_no_repo_script_refs.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/sdd/test_dangerous_actions.py
import pytest

from parrot.sdd.scripts.dangerous_actions import evaluate


def _bash(cmd: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "."}


@pytest.mark.parametrize("cmd", [
    "git reset --hard origin/dev",
    "git push --force origin dev",
    "rm -rf ~",
    "Remove-Item -Recurse -Force C:\\",
    "rd /s /q C:\\",
    "format D:",
    "diskutil eraseDisk APFS X disk2",
    "bash -c \"git reset --hard\"",
])
def test_denied(cmd: str, tmp_path) -> None:
    assert evaluate(_bash(cmd), root=tmp_path).decision == "deny"


@pytest.mark.parametrize("cmd", [
    "echo \"git reset --hard\"",
    "git push --force-with-lease origin feat-x",
    "rm -rf build/",
])
def test_allowed(cmd: str, tmp_path) -> None:
    assert evaluate(_bash(cmd), root=tmp_path).decision == "allow"


def test_protected_branches_follow_sdd_config(tmp_path) -> None: ...
def test_escape_hatch(monkeypatch, tmp_path) -> None: ...
def test_pip_rule_only_in_uv_repos(tmp_path) -> None: ...
def test_write_to_secret_file_denied_template_allowed(tmp_path) -> None: ...
def test_hook_main_does_not_import_parrot_cli() -> None: ...   # subprocess + sys.modules
def test_parity_with_bash_blocker() -> None: ...                 # skip without bash/jq/repo hook
```

---

## Agent Instructions

When you pick up this task:
1. **Work in the feature worktree** — branch `feat-FEAT-633-parrot-installer` (never on `dev`)
2. **Read the spec** amendment C32 and the bash hook in full before porting
3. **Check dependencies** — TASK-5109 must be `done` in `sdd/tasks/index/parrot-installer.json`
4. **Verify the Codebase Contract** — line numbers will have moved after TASK-5109
5. **Update status** → `"in-progress"`, commit only the index file
6. **Implement**, run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`
7. **Commit the code** — stage only the files listed above
8. **Close the task** with `parrot sdd task close TASK-5110 parrot-installer verified`
9. **Fill in the Completion Note** (include the two hook start-up timings), then commit the staged SDD state

---

## Completion Note
*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
