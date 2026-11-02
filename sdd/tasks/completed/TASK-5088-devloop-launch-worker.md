# TASK-5088: `parrot devloop launch-worker <FEAT> [--tmux]` — host-prepared feature launcher

**Feature**: FEAT-768 — Native Claude sandbox for SDD execution
**Spec**: `sdd/specs/sdd-claude-native-sandbox.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-5086, TASK-5087
**Assigned-to**: unassigned

---

## Context

Spec §2 policy 13, AC16 and AC17 (rev 0.4). `scripts/sdd/launch_worker.sh` only opens an `sdd-worker`
console in the current worktree: the operator still creates the worktree, sets the upstream from a host
shell (a native session cannot write Git config), types `run FEAT-xxx`, and juggles one terminal per feature.
The operator runs several features at once and asked (2026-11-01) for one command that does the host
preparation and can park each feature in its own tmux session. It lives in `parrot devloop` because
`parrot sdd` only exists on the unmerged FEAT-633 branch; FEAT-633 may later alias it, nothing more.

---

## Scope

### `native_claude_sandbox.py`
- `launch_worker(argv: Sequence[str], *, cwd: Path | None = None, initial_prompt: str | None = None) -> int`:
  `cwd` defaults to `Path.cwd()` and replaces every `Path.cwd()` use inside the function; when `cwd` is given,
  `os.chdir(cwd)` immediately before `os.execvpe`. `initial_prompt`, when given, is appended as the **last**
  argv element of the `claude` command (after `--settings` and the forwarded args; if the forwarded args contain
  `--`, append it after them). Existing callers (`main()`, `launch_worker.sh`) are unchanged.

### New `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (stdlib only)
- `@dataclass(frozen=True) class FeatureRef: feature_id: str; slug: str; spec: str; index: str` (paths relative to the primary checkout).
- `class LaunchError(Exception)` with `exit_code: int` (1 host prerequisite / external failure, 2 caller input / policy).
- `resolve_primary_checkout(cwd: Path) -> Path` via `worktree_environment.repository_paths(cwd)` → `git_dir.parent`;
  no Git → `LaunchError(2)`.
- `resolve_feature(primary: Path, key: str) -> FeatureRef`: scan `primary / "sdd/tasks/index/*.json"` (skip
  `_orphans.json`, skip unreadable files), match `key` case-insensitively against the header's `feature_id`
  exactly or `feature` exactly; zero or several matches → `LaunchError(2)` naming the key.
- `ensure_feature_worktree(primary: Path, ref: FeatureRef) -> Path`: run
  `[sys.executable, "-m", "scripts.sdd.ensure_worktree", "--slug", ref.slug, "--feature-id", ref.feature_id,
  "--spec", ref.spec, "--index", ref.index, "--json"]` with `cwd=primary`; parse the JSON `path`; nonzero →
  `LaunchError(1)` carrying the subprocess stderr. (FEAT-633 will repoint this to its packaged runner — leave a
  one-line comment saying so.)
- `prepare_upstream(worktree: Path) -> str` (returns a one-line status for stderr): branch =
  `git rev-parse --abbrev-ref HEAD`; `git ls-remote --heads origin <branch>`:
  - remote absent → `git push -u origin <branch>`.
  - remote present → `git fetch origin <branch>`; local == remote → set upstream if missing; local strict
    ancestor of remote → `git merge --ff-only origin/<branch>` then set upstream; remote ancestor of local →
    set upstream (local is ahead, the worker pushes); diverged → `LaunchError(2, "… diverged from origin/<branch>; reconcile it before launching")`.
  - any git failure (network) → `LaunchError(1)`; `--no-upstream` skips this step entirely.
- `tmux_session_name(feature_id: str) -> str` = `f"sdd-{feature_id}"`.
- `tmux_session_exists(name: str) -> bool` = `tmux has-session -t ={name}` exit 0 (False when `tmux` is not on PATH).
- `launch(key: str, *, tmux: bool, detach: bool, sandbox: str | None, allowed_domains: Sequence[str],
  no_upstream: bool, claude_args: Sequence[str]) -> int`:
  1. `sandbox` given → validate against `native_claude_sandbox.SANDBOX_MODES` (`LaunchError(2)` otherwise) and
     set `os.environ[MODE_ENV]` for this process (mode semantics are TASK-4908/5086's; this flag is the env var).
  2. resolve primary + feature; if `tmux_session_exists(name)`: with `tmux` → attach (step 5) without any host
     prep; without `tmux` → `LaunchError(2, f"a worker for {id} already runs in tmux session {name}; use --tmux to attach")`.
  3. `ensure_feature_worktree`, then `prepare_upstream` unless `no_upstream`; print each status line to stderr.
  4. not `tmux` → `return native_claude_sandbox.launch_worker([*domain_args, *claude_args], cwd=worktree,
     initial_prompt=f"run {ref.feature_id}")`.
  5. `tmux`: `sandbox_platform() == "windows"` → `LaunchError(1, "--tmux is not available on native Windows")`;
     `tmux` not on PATH → `LaunchError(1)`. Create (if absent) with
     `tmux new-session -d -s <name> -c <worktree> -e PARROT_SDD_SANDBOX_MODE=<value> -- <sys.executable> -m parrot.flows.dev_loop.feature_launcher --in-session <FEAT-ID> [--sandbox-allow-domain H]... [-- claude args]`
     passing **every** `PARROT_SDD_*` variable present in `os.environ` (and `PATH`, `VIRTUAL_ENV`) as `-e` pairs —
     a running tmux server does not inherit the client environment. Then, unless `detach`: inside `$TMUX` →
     `tmux switch-client -t <name>`, else `os.execvp("tmux", ["tmux", "attach-session", "-t", name])`. With
     `detach` print `attach with: tmux attach -t <name>` and return 0.
- `main(argv: Sequence[str] | None = None) -> int`: argparse with the hidden `--in-session <FEAT-ID>` mode used by
  the tmux child: no resolution/prep, just `launch_worker([...], cwd=Path.cwd(), initial_prompt=f"run {id}")`.
  `if __name__ == "__main__": raise SystemExit(main())`.

### New `packages/ai-parrot/src/parrot/cli/devloop/launch_worker.py`
- `@click.command("launch-worker", context_settings={"ignore_unknown_options": True})` with
  `FEATURE` argument, `--tmux`, `--detach` (only meaningful with `--tmux`; error otherwise),
  `--sandbox [required|preferred|off|legacy]`, `--sandbox-allow-domain HOST` (multiple), `--no-upstream`, and
  `CLAUDE_ARGS` (`nargs=-1, type=click.UNPROCESSED`) after `--`. Body imports `feature_launcher` lazily, calls
  `launch(...)`, maps `LaunchError` to `click.echo(f"launch-worker: {exc}", err=True)` + `ctx.exit(exc.exit_code)`.
- Register in `parrot/cli/devloop/__init__.py` with one `devloop.add_command(launch_worker_cmd)` line after the
  existing commands; the module's top-level imports are `click` only (the `parrot devloop --help` no-conf-import
  test must stay green).

**NOT in scope**: deprecating `launch_worker.sh` and all docs (TASK-5089); brief/hotfix worktrees (`/sdd-brief`
keys — the command takes FEAT ids / feature slugs only); a `parrot sdd` alias (FEAT-633); killing or listing
tmux sessions; any change to sandbox semantics.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py` | MODIFY | `launch_worker(..., cwd=, initial_prompt=)` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | CREATE | resolution, worktree + upstream prep, tmux orchestration, `--in-session` entry |
| `packages/ai-parrot/src/parrot/cli/devloop/launch_worker.py` | CREATE | click command |
| `packages/ai-parrot/src/parrot/cli/devloop/__init__.py` | MODIFY | `devloop.add_command(launch_worker_cmd)` |
| `packages/ai-parrot/tests/cli/devloop/test_launch_worker_cmd.py` | CREATE | launcher + CLI tests |
| `packages/ai-parrot/tests/cli/devloop/test_click_wiring.py` | MODIFY | `launch-worker` listed in `devloop --help`, no conf import |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | `cwd`/`initial_prompt` argv placement |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.flows.dev_loop import native_claude_sandbox, worktree_environment   # verified: dispatchers/claude.py uses this exact import
import click                                                                     # parrot/cli/devloop/__init__.py:13
from click.testing import CliRunner                                              # used by tests/cli/devloop/test_click_wiring.py
```

### Existing Signatures to Use
```text
native_claude_sandbox.py: MODE_ENV, SANDBOX_MODES, launch_worker(argv) (620), main() (662); TASK-5087 adds sandbox_platform()
worktree_environment.py: def repository_paths(cwd: Path) -> tuple[Path, Path | None]   (54) — second item is the common git dir
scripts/sdd/ensure_worktree.py: main() (289) — flags --slug --feature-id --spec --index --json; with --json prints
  {"name", "path", "worktree_path", "base_ref", "created", "native": {...}} on stdout, warnings on stderr; exit 1 on error
per-spec index header keys: feature, feature_id, spec, type, base_branch (sdd/tasks/index/<slug>.json)
parrot/cli/devloop/__init__.py: @click.group devloop (56-65); @devloop.command("run") (68); @devloop.command("revise") (184)
packages/ai-parrot/tests/cli/devloop/test_click_wiring.py: test_devloop_help_no_conf_import (11), test_lazygroup_resolves_devloop (60)
tmux 3.4 on the maintainer host: `new-session -e VAR=value` exists since tmux 3.0
```

### Does NOT Exist
- ~~a feature-id → index resolver in `scripts/sdd/` or `parrot/flows/dev_loop/`~~ (`task_scheduler.resolve_index_path` takes a slug, not an id) — write `resolve_feature`.
- ~~`parrot sdd` on dev~~ — it is FEAT-633-only; do not create `parrot/sdd/cli.py`.
- ~~a `--prompt` / `--initial-prompt` CLI flag on `launch_worker.sh`~~ — the prompt is a keyword argument of `launch_worker`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/devloop/launch_worker.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/cli/devloop/__init__.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/cli/devloop/test_launch_worker_cmd.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/cli/devloop/test_click_wiring.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/native_claude_sandbox.py#launch_worker",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/worktree_environment.py#repository_paths",
    "sym:packages/ai-parrot/src/parrot/cli/devloop/__init__.py#devloop"
  ]
}
```

---

## Implementation Notes

- All git/tmux/ensure_worktree subprocesses go through one module-level `_run(argv, *, cwd) -> subprocess.CompletedProcess[str]`
  (`check=False, capture_output=True, text=True`) so tests monkeypatch a single seam.
- Host prep happens in the **client** process, before tmux; the tmux child (`--in-session`) never touches Git config.
- Never auto-resolve a diverged branch, never `reset`, never force-push.
- `run <FEAT-ID>` is the exact initial prompt (the sdd-worker agent's documented trigger).
- stdout stays clean (tmux/claude own the terminal); every status line goes to stderr with the `launch-worker:` prefix.

---

## Acceptance Criteria

- [ ] `resolve_feature` matches by `feature_id` or `feature`, case-insensitively, and errors (exit 2) on none/ambiguous.
- [ ] The worktree comes from `ensure_worktree --json`; its failure is exit 1 with the stderr.
- [ ] Upstream: absent remote → `push -u`; behind → ff-only; ahead/equal → upstream set; diverged → exit 2, no git mutation.
- [ ] Non-tmux launch calls `launch_worker(..., cwd=<worktree>, initial_prompt="run FEAT-…")`; the prompt is the last claude argv element.
- [ ] `--tmux` creates `sdd-<FEAT-ID>` with `-c <worktree>` and `-e` pairs for every `PARROT_SDD_*` var, then attaches (or `switch-client` inside `$TMUX`, or prints the attach hint with `--detach`); an existing session is attached with no host prep.
- [ ] A non-tmux launch is refused (exit 2) while `sdd-<FEAT-ID>` exists; `--tmux` on native Windows / without tmux → exit 1.
- [ ] `--sandbox legacy` reaches the child as `PARROT_SDD_SANDBOX_MODE=legacy`; an invalid value → exit 2.
- [ ] `parrot devloop --help` lists `launch-worker` and still imports no `parrot.conf`.
- [ ] `ruff check` clean on changed Python files; all Validation Commands green.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/cli/devloop/test_launch_worker_cmd.py -q`
- `pytest packages/ai-parrot/tests/cli/devloop/test_click_wiring.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `pytest tests/sdd/test_launch_worker.py -q`

---

## Test Specification

Unit tests only — no real tmux server, no real network. A `tmp_path` primary checkout with
`sdd/tasks/index/{a,b,_orphans}.json` headers drives `resolve_feature`. Monkeypatch `feature_launcher._run`
with a scripted fake (records argv, returns canned `CompletedProcess`) for ensure_worktree/git/tmux, and
`native_claude_sandbox.launch_worker` / `os.execvp` with recorders. Assert exact argv for `new-session`
(including `-e` pairs), the diverged no-mutation path (no `merge`/`push` recorded), and the refusal paths.
CLI via `CliRunner().invoke(devloop, ["launch-worker", ...])`. For the argv placement test in
`test_native_claude_sandbox.py`, call `launch_worker` in-process with `os.execvpe` monkeypatched.

---

## Agent Instructions

1. Work only in the worktree you are given; commit only the files in the table.
2. Verify every Codebase Contract entry before editing; stop and report if one is stale.
3. Run the Validation Commands with `PYTHONPATH=packages/ai-parrot/src`.

---

## Completion Note


- Task: TASK-5088
- Feature: sdd-claude-native-sandbox
- Implementation SHA: 888566aca56d655411b0cb6d4579046e836fd020
- Closed at (UTC): 2026-11-01T01:10:00+00:00
- Fix commits: 888566aca56d655411b0cb6d4579046e836fd020

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 1 |
| feedback | coder-feedback:e5397cd254e923b15e8b3cbb (leaked-process-environment-in-tests), coder-feedback:681c952546935e6692225669 (acceptance-criteria-untested) |
| residual_lint | 1 residual (E402 late import in parrot/cli/devloop/__init__.py, required by spec placement) left for /sdd-done |
| review | first merge-tier run red (4 test_dispatcher failures from PARROT_SDD_SANDBOX_MODE leaked by launcher tests); --tmux --detach ignored on an existing session; 7 AC paths untested. Fixed by orchestrator in 888566aca5 (detach honoured, env restore fixture, 14 new tests). |
| seat_summary | Seat: gpt-5.6-terra · Backend: codex · Model: gpt-5.6-terra · Attempts: 1 · Duration: 130.8s · Tokens: n/a |
| validation | merge tier re-run: 288 passed/1 skipped |
