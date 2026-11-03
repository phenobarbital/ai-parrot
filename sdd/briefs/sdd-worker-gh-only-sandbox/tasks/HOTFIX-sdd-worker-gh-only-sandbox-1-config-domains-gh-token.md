# HOTFIX-sdd-worker-gh-only-sandbox-1: Config-driven sandbox domains and host-resolved GH_TOKEN for sdd-worker

**Feature**: sdd-worker-gh-only-sandbox — GitHub only through `gh`, config-driven allowed domains
**Spec**: `sdd/briefs/sdd-worker-gh-only-sandbox.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`parrot sdd launch worker` compiles a strict native sandbox whose only egress source is the
`--sandbox-allow-domain` argv (`native_claude_sandbox.py:745`, `:755`, `:426`). The operator wants
GitHub reachable only through `gh` (`api.github.com`) without typing flags each launch, and `gh`
needs `GH_TOKEN` because its keyring (D-Bus) is unreachable inside the sandbox. See the brief.

## Scope

- In `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` (stdlib only — `tomllib`):
  - Add `load_launch_config(primary: Path) -> tuple[list[str], bool]` (or a small frozen dataclass)
    that reads `[tool.parrot.sdd]` from `primary / "pyproject.toml"`:
    `sandbox_allowed_domains` (list of str, default `[]`, validated with `validate_allowed_domains`)
    and `gh_token` (bool, default `False`). Missing file/table → defaults. Wrong types or malformed
    TOML → `ValueError("Invalid sandbox launch config in <path>: …")`.
  - It MUST be called with the **primary checkout** (`_native_roots(cwd)[2]`), never the worktree
    root: the sandboxed session can write its worktree pyproject.
  - In `_parse_launch_arguments`, accept a launcher-owned `--no-gh-token` flag (not forwarded to
    claude); extend the return value accordingly and update its callers.
  - In `launch_worker`: domains = de-duplicated union of config domains and argv domains (config
    first, order-stable), passed to `plan_native_launch`. If `gh_token` is true and `--no-gh-token`
    was not given and `GH_TOKEN` is not already in `env`: run `gh auth token` on the host
    (`shutil.which("gh")`, `subprocess.run(..., capture_output=True, text=True, timeout=10)`), and on
    success with non-empty stripped stdout set `env["GH_TOKEN"]`. On any failure print
    `launch_worker: WARNING gh_token is enabled but no token could be obtained (<reason>); launching without GH_TOKEN`
    to stderr — `<reason>` is e.g. `gh not on PATH`, `gh exited 1`, `timeout`; never include stdout.
    Do this after mode/settings resolution and before `execvpe`. `ValueError` from the config →
    existing `return 2` path with the message.
  - Never print, log, or put the token in argv.
- In `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py`:
  - `launch(...)` gains `gh_token: bool = True` (False = `--no-gh-token`); when False, append
    `--no-gh-token` to the args handed to `launch_worker` on the direct path and to the tmux child
    command line. `_preflight_sandbox` must validate the union (config + flags) so a bad config
    fails before tmux starts (convert `ValueError` to `LaunchError(2, …)` as the existing code does).
  - `main()` (tmux child) parses `--no-gh-token` and forwards it.
  - Do NOT add `GH_TOKEN` to `_tmux_environment()` — the child's `launch_worker` resolves it.
- In `packages/ai-parrot/src/parrot/sdd/launch_cli.py`: add `--no-gh-token` flag to `worker`, pass
  `gh_token=not no_gh_token`.
- Root `pyproject.toml`: add
  ```toml
  [tool.parrot.sdd]
  # sdd-worker native sandbox: GitHub only through `gh` (api.github.com), never git/SSH to github.com.
  # Read from the PRIMARY checkout only. See docs/dev_loop/claude-native-sandbox.md.
  sandbox_allowed_domains = ["api.github.com"]
  gh_token = true
  ```
  Check first that no `[tool.parrot.sdd]` table exists already (`resolve_sandbox_mode` reads
  `sandbox` from the same table); if it does, add the keys to it.

**NOT in scope**:
- Docs and agent instructions (HOTFIX-sdd-worker-gh-only-sandbox-2).
- Allowing `github.com`, SSH, or git-over-HTTPS from the sandbox.
- The dev-loop dispatcher's `sandbox_allowed_domains` profile field (`flows/dev_loop/models/claude.py:81`).
- `legacy` mode behaviour (domains are already ignored there; token injection may still apply).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | `load_launch_config`, `--no-gh-token`, domain union, GH_TOKEN injection |
| `packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py` | MODIFY | `gh_token` param, forward `--no-gh-token` on both paths, preflight on union |
| `packages/ai-parrot/src/parrot/sdd/launch_cli.py` | MODIFY | `--no-gh-token` flag |
| `pyproject.toml` | MODIFY | `[tool.parrot.sdd]` keys |
| `packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py` | MODIFY | config + token tests |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | flag forwarding tests |

---

## Codebase Contract (Anti-Hallucination)

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py
def validate_allowed_domains(domains: Sequence[str]) -> list[str]:            # line 74
def _native_roots(cwd: Path) -> tuple[Path, Path, Path]:                       # line 135 -> (root, git_dir, primary)
def resolve_sandbox_mode(repo_root: Path) -> str:                              # line 243 (reads [tool.parrot.sdd] sandbox)
def plan_native_launch(cwd: Path, *, allowed_domains: Sequence[str] = ()) -> tuple[str, bool, str, dict[str, Any]]
def _parse_launch_arguments(argv: Sequence[str]) -> tuple[list[str], list[str], bool, bool]:  # line 614
def launch_worker(argv, *, cwd=None, initial_prompt=None, base_env=None) -> int:              # line 726
    domains, forwarded, has_model, has_sources = _parse_launch_arguments(argv)  # line 745
    mode, degraded, reason, settings = plan_native_launch(cwd, allowed_domains=domains)  # line 755
    env = dict(os.environ if base_env is None else base_env)
    os.execvpe(command[0], command, env)

# packages/ai-parrot/src/parrot/flows/dev_loop/feature_launcher.py
def _preflight_sandbox(worktree: Path, allowed_domains: Sequence[str]) -> None:  # line 83
def _tmux_environment(env: Mapping[str, str]) -> list[str]:                      # PARROT_SDD_* + PATH + VIRTUAL_ENV only
def launch(key, *, tmux, detach, sandbox, allowed_domains, no_upstream, claude_args, base_env=None) -> int:  # line 366
    domain_args = [...("--sandbox-allow-domain", domain)]                        # line 410
def main(argv=None) -> int:                                                      # line 481 (tmux child, --in-session)

# packages/ai-parrot/src/parrot/sdd/launch_cli.py
@click.option("--sandbox-allow-domain", "allowed_domains", multiple=True, metavar="HOST")  # line 22
feature_launcher.launch(feature, tmux=..., detach=..., sandbox=..., allowed_domains=..., no_upstream=..., claude_args=..., base_env=base_env)
```

Tests to extend: `test_launch_worker_uses_requested_cwd_and_final_prompt`
(`test_native_claude_sandbox.py:330`), `test_launch_worker_starts_claude_from_base_env`
(`test_sdd_launch.py:746`), `test_tmux_new_session_carries_environment_and_detaches`
(`test_sdd_launch.py:142`). Reuse their fixtures/monkeypatching of `execvpe`, `shutil.which`,
`plan_native_launch`, `_native_roots`.

### Does NOT Exist
- No `load_launch_config`, no `--no-gh-token`, no `sandbox_allowed_domains`/`gh_token` pyproject keys.
- No `[tool.parrot.sdd]` table in the root `pyproject.toml` today (only `[tool.parrot.worktree]`) — verify.

---

## Acceptance Criteria

- [ ] Config domains from the primary checkout's pyproject reach the compiled `allowedDomains`, unioned with flags.
- [ ] A `sandbox_allowed_domains` in the **worktree** pyproject (primary differs) is ignored.
- [ ] Malformed config (non-list, invalid host, non-bool `gh_token`) → exit 2 with a clear message, claude not exec'd.
- [ ] `gh_token = true` → `GH_TOKEN` in the exec env from mocked `gh auth token`; pre-existing `GH_TOKEN` kept and gh not called; `--no-gh-token` → no `GH_TOKEN` and gh not called.
- [ ] gh missing / non-zero / timeout → WARNING on stderr, launch proceeds without `GH_TOKEN`.
- [ ] The token string never appears in captured stdout/stderr, nor in the claude argv, nor in the tmux command.
- [ ] `--no-gh-token` reaches `launch_worker` on both the direct and the tmux-child path.
- [ ] `ruff check` clean on touched files.

## Validation Commands

- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox.py -q`
- `PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_sdd_launch.py -q`

## Agent Instructions

Read the brief first. Implement exactly the scope; commit code only. Do not run `gh` for real in tests.

## Completion Note

Implemented by the sdd-worker itself (sequential fallback): `coder_plan` returned a `complexity_audit_failed`
routing block ("Could not extract task ID from task content") for the `HOTFIX-…` brief task id, so the engine
could not route it and no coder was dispatched. Execution `0d8f8059-…` was opened and closed with no attempts.

- `native_claude_sandbox.py`: `load_launch_config(primary)`, `merge_domains`, `_resolve_gh_token`,
  `--no-gh-token` (5th element of `_parse_launch_arguments`), domain union + `GH_TOKEN` injection in
  `launch_worker`. Config is read from the primary checkout (`_native_roots(cwd)[2]`) only.
- `feature_launcher.py`: `launch(..., gh_token=True)`; config+flag union validated in preflight
  (`ValueError` → `LaunchError(2)`); `--no-gh-token` forwarded on the direct path and the tmux child; `main()` parses it.
- `launch_cli.py`: `--no-gh-token`. `pyproject.toml`: `[tool.parrot.sdd]` keys (no table existed).
- Tests: 110 passed (`test_native_claude_sandbox.py`, `test_sdd_launch.py`); `ruff check` clean.
- Note: `resolve_sandbox_mode` still reads `sandbox` from the worktree pyproject (pre-existing, out of scope).

