# TASK-5353: Propagate `host` through `launch()`, the tmux child and `main()`; AGY hook prerequisite

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-5352, TASK-5349
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3, "Launcher integration contract" and "Hook prerequisite". TASK-5351 adds the Google
preflight helpers and TASK-5352 the `agy` exec paths. This task wires them into `feature_launcher.launch()`:
- new `host` parameter, propagated to the foreground path, the tmux child (`--host google`) and `main()`;
- the tmux child no longer always calls `native_claude_sandbox.launch_worker()`;
- the Google worker skips Claude's native preflight and uses `google_worker_sandbox()`;
- before any Google launch (worker, and `launch_session` for brief/fix), the managed `parrot-sdd-permissions`
  hook must be present with the widened matcher (TASK-5349's `stale` flag) and its command must be runnable.

---

## Scope

- `launch(..., host: Literal["claude", "google"] = "claude")` with the Google branch.
- `_require_agy_hooks(checkout)` and its call in `launch()` (Google) and in `launch_session(host="google")`.
- `main()`: `--host` argument; Google dispatches `launch_agy_worker`.
- Tests in `test_sdd_launch.py`.

**NOT in scope**: CLI options (TASK-5354); the hook policy (TASK-5347/5348); installer changes (TASK-5349).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | `host` in `launch()`/`main()`, `_require_agy_hooks`, Google branch |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | foreground/tmux/main propagation, refusals, hook prerequisite |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09). Symbols marked *TASK-53xx* exist once those tasks merge.

### Verified Imports
```python
# feature_launcher.py: host-only imports are done lazily inside functions (the tmux child runs `python -S`),
#   like `from parrot.sdd.scripts import worktree_push_protection` (line 510). Do the same for:
from parrot.sdd.installer import _agy_permissions_report     # installer.py:791 (+ "matcher"/"stale" from TASK-5349)
# tests
from parrot.flows.dev_loop import feature_launcher as launcher
from parrot.sdd.scripts import agy_permissions                # UNATTENDED_ENV from TASK-5348
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py
def launch(key: str, *, tmux: bool, detach: bool, sandbox: str | None, allowed_domains: Sequence[str],
           no_upstream: bool, claude_args: Sequence[str], base_env: Mapping[str, str] | None = None,
           gh_token: bool = True) -> int:                     # line 518 (`    gh_token: bool = True,` is line 528)
    # line 540: `if sandbox is not None:` validates against native_claude_sandbox.SANDBOX_MODES, sets MODE_ENV
    # line 569-578: config_domains via native_claude_sandbox.load_launch_config(primary); effective_domains merged
    # line 579: `    _preflight_sandbox(worktree, effective_domains)`         (Claude-only — skip for Google)
    # lines 580-585: prepare_upstream / stale_base_summary / _enable_push_protection   (keep for Google)
    # lines 586-594: foreground `return native_claude_sandbox.launch_worker([...], cwd=worktree, initial_prompt=..., base_env=env)`
    # lines 595-639: tmux; child argv built at lines 615-631 (`"--in-session", ref.prompt_id, "--cwd", str(worktree), *domain_args, *token_args`)
def main(argv: Sequence[str] | None = None) -> int:          # line 674 — ends with `return native_claude_sandbox.launch_worker(` (line 691)
def launch_session(initial_prompt, *, cwd, claude_args=(), base_env=None, host="claude") -> int:   # TASK-5352
def google_worker_sandbox(sandbox: str | None, allowed_domains: Sequence[str]) -> str:              # TASK-5351
def resolve_agy() -> Path; def require_official_agy(agy: Path) -> None                              # TASK-5351
def launch_agy_worker(agy_args, *, cwd, initial_prompt, base_env=None) -> int                       # TASK-5352
AGY_UNATTENDED_ENV = "PARROT_SDD_AGY_UNATTENDED"                                                    # TASK-5352
# packages/ai-parrot/src/parrot/sdd/installer.py
def _agy_permissions_report(root: Path) -> dict[str, Any]:   # line 791 — "form": "launcher"|"bare"|"baked"|None, "command": str|None,
                                                              #   + "matcher", "stale" (TASK-5349)
_AGY_LAUNCHER = "scripts/sdd/agy_hook.sh"                    # line 503
# packages/ai-parrot/tests/sdd/test_sdd_launch.py
def _primary(tmp_path) -> Path                               # line 46
def test_launch_non_tmux_passes_worktree_and_worker_prompt   # line 325 — pattern for a foreground launch test
def _tmux_new_session(tmp_path, monkeypatch, *, base_env) -> dict   # line 1029 — captures the tmux command
```

### Does NOT Exist
- ~~A `--sandbox snap` value~~ — dropped; snap `agy` is refused (TASK-5351).
- ~~Forwarding `--sandbox-allow-domain` / `--no-gh-token` to agy~~ — launcher-only options never reach AGY.
- ~~Bubblewrap wrapping in `launch_session`~~ — interactive sessions are not wrapped (spec §3 M3).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#launch",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py#main",
    "sym:packages/ai-parrot/src/parrot/sdd/installer.py#_agy_permissions_report"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Default `host="claude"`: every existing launch test must pass unchanged.
- Order for Google: resolve + snap refusal **before** any host preparation (no worktree, push or tmux for a
  snap `agy`); sandbox + hook prerequisite after the worktree is known (checked in that worktree); then the
  usual upstream/push-protection; never `_preflight_sandbox`.
- `--sandbox` for Google: pass `sandbox or os.environ.get(native_claude_sandbox.MODE_ENV)` to
  `google_worker_sandbox`; do not call `resolve_sandbox_mode` (it is the Claude native-mode resolver).
- Runnable hook command: `form == "launcher"` → `<checkout>/scripts/sdd/agy_hook.sh` is a file; `"bare"` →
  `shutil.which("parrot")`; `"baked"` → the first `shlex` word is an executable file.

---

## Implementation Blueprint

### Steps (in order)
1. Add `_require_agy_hooks` below `launch_agy_worker` (TASK-5352) — *why*: shared by worker and session.
2. Call it at the top of the Google branch of `launch_session` (after the snap refusal) — *why*: brief/fix need the hook too.
3. Add `host` to `launch()` and the Google branch — *why*: spec launcher contract.
4. Add `--host` to `main()` — *why*: the tmux child must dispatch agy, not Claude.
5. Write the tests.

### `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` (MODIFY)
```python
# AFTER `launch_agy_worker` (TASK-5352) — insert:
def _require_agy_hooks(checkout: Path) -> None:
    """LaunchError(2) unless the managed parrot-sdd-permissions hook is installed, current and runnable."""
    from parrot.sdd.installer import _agy_permissions_report  # host-only; the tmux child never calls this

    report = _agy_permissions_report(checkout)
    hint = "run `parrot sdd install --host google` in this repository"
    if report.get("command") is None:
        raise LaunchError(2, f"the agy permission hook is not installed in {checkout}/.agents/hooks.json; {hint}")
    if report.get("stale"):
        raise LaunchError(2, f"the agy permission hook matcher is stale ({report.get('matcher')!r}); {hint}")
    # FILL IN: runnable check per form (launcher / bare / baked, see Key Constraints) -> LaunchError(2, ... hint) —
    #   bounded by spec §3 M3 "Hook prerequisite".

# occurrences: 1 (verified: grep -c '    gh_token: bool = True,' feature_launcher.py) — line 528, in launch()'s signature
# AFTER — insert:
    host: Literal["claude", "google"] = "claude",
# FILL IN (launch body): bounded by spec §3 M3 launcher contract —
#   a) at the very top, when host == "google": agy = resolve_agy(); require_official_agy(agy)  (LaunchError propagates);
#      validate `sandbox` with google_worker_sandbox semantics instead of SANDBOX_MODES (keep the Claude path as is);
#   b) replace `    _preflight_sandbox(worktree, effective_domains)` (line 579, occurrences: 1) with
#        if host == "google":
#            google_worker_sandbox(sandbox or os.environ.get(native_claude_sandbox.MODE_ENV), effective_domains)
#            _require_agy_hooks(worktree)
#        else:
#            _preflight_sandbox(worktree, effective_domains)
#   c) foreground: when host == "google" return launch_agy_worker(list(claude_args), cwd=worktree,
#      initial_prompt=f"run {ref.prompt_id}", base_env=env)  — no domain/token args;
#   d) tmux child argv: for google append "--host", "google" and omit domain_args/token_args.

# occurrences: 1 (verified: grep -c 'def main(argv: Sequence\[str\] | None = None) -> int:' feature_launcher.py) — line 674
# FILL IN (main): add parser.add_argument("--host", choices=("claude", "google"), default="claude"); when
#   args.host == "google" return launch_agy_worker(forwarded, cwd=args.cwd or _invocation_dir(),
#   initial_prompt=f"run {args.in_session}") before the Claude `return native_claude_sandbox.launch_worker(`
#   (the second of 2 occurrences of that line, line 691) — bounded by "the tmux child must not unconditionally
#   invoke native_claude_sandbox.launch_worker()".
```
**Why this shape**: the host decision is made once in `launch()` and carried explicitly (`--host`) to the
`python -S` child, which cannot import parrot to re-derive it.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)
```python
# AFTER — append at end of file
def test_unattended_env_name_matches_the_hook() -> None:
    from parrot.sdd.scripts import agy_permissions

    assert launcher.AGY_UNATTENDED_ENV == agy_permissions.UNATTENDED_ENV


# FILL IN tests (one function each; reuse the patterns of test_launch_non_tmux_passes_worktree_and_worker_prompt
# and _tmux_new_session; monkeypatch launcher.resolve_agy, launcher.google_worker_sandbox,
# launcher._require_agy_hooks and launcher.launch_agy_worker where a test is about something else):
#  - google foreground: launch_agy_worker called with cwd=worktree, prompt "run FEAT-768", argv without
#    --sandbox-allow-domain/--no-gh-token; native_claude_sandbox.launch_worker and _preflight_sandbox NOT called
#  - google tmux: child argv contains "--host", "google" and no domain/token args
#  - main(["--in-session", "FEAT-768", "--cwd", wt, "--host", "google"]) calls launch_agy_worker; without
#    --host it still calls native_claude_sandbox.launch_worker
#  - default host unchanged (existing tests pass)
#  - refusals before AGY starts: snap agy (no ensure_feature_worktree call), sandbox "off", explicit and
#    configured domains, failed probe, missing hook (report command None), stale hook (stale True), launcher form
#    whose scripts/sdd/agy_hook.sh is missing
#  - launch_session(host="google") with a missing hook returns 2 without exec
```

### FILL IN checklist
- [ ] `_require_agy_hooks` runnable check; bounded by spec §3 M3
- [ ] `launch()` Google branch (a–d); bounded by spec §3 M3
- [ ] `main()` `--host`; bounded by spec §3 M3
- [ ] the listed tests

---

## Acceptance Criteria

- [ ] `launch(host="google")` refuses a snap `agy` before host prep, skips Claude preflight, applies `google_worker_sandbox` and the hook prerequisite, and launches via `launch_agy_worker` (foreground) or `--host google` (tmux child).
- [ ] `main()` dispatches `launch_agy_worker` for `--host google` and Claude otherwise.
- [ ] Google `launch_session` refuses a missing/stale/unrunnable hook.
- [ ] Default Claude behaviour and all existing tests unchanged; `ruff check` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

---

## Test Specification

See the test block in the Implementation Blueprint.

---

## Agent Instructions

When you pick up this task:

1. **Work in the feature worktree** — never on `base_branch`
   (`parrot sdd worktree ensure --slug sdd-agy-compatibility --feature-id FEAT-847`)
2. **Read the spec** at the path listed above for full context
3. **Check dependencies** — every `Depends-on` task must be `"done"` in `sdd/tasks/index/sdd-agy-compatibility.json`
4. **Verify the Codebase Contract** before writing any code; fix stale entries first
5. **Update status** in the per-spec index → `"in-progress"` (set `started_at`) and commit only that index file
6. **Implement** from the Implementation Blueprint, completing every `# FILL IN:` marker
7. **Verify** all acceptance criteria — run the Validation Commands (prefix `PYTHONPATH=packages/ai-parrot/src` in a worktree)
8. **Commit the code** — stage only the files this task lists
9. **Close the task** with `parrot sdd task close TASK-5353 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

**Completed by**: sdd-worker orchestrator; seat gpt-5.6-terra (codex), 1 attempt
**Date**: 2026-11-09
**Notes**: `host` threaded through launch()/main() in feature_launcher.py with the AGY hook prerequisite; tests in test_sdd_launch.py. Merge-tier validation green (439 passed; asset sync 27 passed). Not line-by-line reviewed by the orchestrator beyond validation and the fidelity gate.

**Deviations from spec**: none
