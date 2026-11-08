# TASK-5354: `--host claude|google` on `parrot sdd launch worker|brief|fix`

**Feature**: FEAT-847 — SDD Antigravity CLI (AGY) Operational Compatibility
**Spec**: `sdd/specs/sdd-agy-compatibility.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-5353
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3 (Responsibility + "Define and test CLI option placement for brief and fix"). The Click
commands in `launch_cli.py` are the operator entry point. `worker` already parses options before its
`claude_args`; `brief` and `fix` use passthrough parsing (`allow_interspersed_args=False`), so an option is
only recognised **before** the first positional argument. `--host` defaults to
`os.environ.get("PARROT_SDD_HOST", "claude")`.

---

## Scope

- `worker`: `--host` option, passed to `feature_launcher.launch(host=...)`.
- `brief` / `fix`: `--host` option consumed only before SOURCE / the first skill argument; `_session` passes
  `host` to `feature_launcher.launch_session(...)` and maps refusals to exit codes.
- Tests, including the spec's `test_launch_cli_google_host` end-to-end check.

**NOT in scope**: launcher internals (TASK-5351…5353); new `--sandbox` values (none — the snap backend was dropped).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/launch_cli.py` | MODIFY | `--host` on worker/brief/fix |
| `packages/ai-parrot/tests/sdd/test_sdd_launch.py` | MODIFY | option placement, env default, google exec argv |

---

## Codebase Contract (Anti-Hallucination)

> Verified on `dev` @ `ae3b48c7f3` (2026-11-09).

### Verified Imports
```python
# launch_cli.py lines 3-7
import os
import click
# tests (test_sdd_launch.py:12-14)
from click.testing import CliRunner
from parrot.cli import cli as devloop
from parrot.flows.dev_loop import feature_launcher as launcher
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/sdd/launch_cli.py
_PASSTHROUGH = {"ignore_unknown_options": True, "allow_interspersed_args": False}           # line 9
@launch.command("worker", context_settings={"ignore_unknown_options": True})                 # line 17
@click.option("--sandbox", type=click.Choice(["required", "preferred", "off", "legacy"]), default=None)  # line 21
def worker(ctx, feature, use_tmux, detach, sandbox, allowed_domains, no_upstream, no_gh_token, claude_args) -> None:  # line 27
    # base_env snapshot BEFORE `from parrot.flows.dev_loop import feature_launcher` (lines 43-44) — keep that order
def _session(ctx: click.Context, prompt_words: list[str]) -> None:                           # line 64
    # line 74: ctx.exit(feature_launcher.launch_session(" ".join(prompt_words), cwd=cwd, base_env=base_env))
@launch.command("brief", context_settings=_PASSTHROUGH, add_help_option=False)               # line 77
def brief(ctx, source, rest) -> None:  _session(ctx, ["/sdd-brief", source, *rest])          # line 81
@launch.command("fix", context_settings=_PASSTHROUGH, add_help_option=False)                 # line 86
def fix(ctx, rest) -> None:  _session(ctx, ["/sdd-fix", *rest])                              # line 89
# feature_launcher (TASK-5352/5353): launch(..., host=...), launch_session(..., host=...), LaunchError(.exit_code)
# packages/ai-parrot/tests/sdd/test_sdd_launch.py
def _capture_exec(monkeypatch, tmp_path) -> dict[str, object]:   # line 1199
def test_launch_brief_and_fix_exec_slash_command(...)            # line 1223 — must keep passing (default host)
```

### Does NOT Exist
- ~~`--sandbox snap`~~ — not a value; do not add it.
- ~~A `PARROT_SDD_HOST` read inside `feature_launcher`~~ — only the CLI reads it (Click `envvar`).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/sdd/launch_cli.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/sdd/test_sdd_launch.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/sdd/launch_cli.py#worker",
    "sym:packages/ai-parrot/src/parrot/sdd/launch_cli.py#brief",
    "sym:packages/ai-parrot/src/parrot/sdd/launch_cli.py#fix",
    "sym:packages/ai-parrot/src/parrot/sdd/launch_cli.py#_session"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Use `click.option("--host", type=click.Choice(["claude", "google"]), default="claude", envvar="PARROT_SDD_HOST", show_envvar=True)`
  — Click validates the env value through the Choice, which gives the spec's default without hand-rolled parsing.
- Keep the `base_env = dict(os.environ)` snapshot as the first statement that touches the environment, before
  importing `parrot.flows` (navconfig loads `.env` secrets on import).
- Placement for `brief`/`fix`: `parrot sdd launch brief --host google NAV-1 --no-interview` sets the host;
  `parrot sdd launch brief NAV-1 --host google` leaves `--host google` in the skill arguments (passthrough).

---

## Implementation Blueprint

### Steps (in order)
1. Add a module-level `_HOST_OPTION` decorator factory and apply it to the three commands — *why*: one definition, same env default.
2. Thread `host` into `launch()` and `_session()` — *why*: spec contract.
3. Write the tests.

### `packages/ai-parrot/src/parrot/sdd/launch_cli.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -c '_PASSTHROUGH = {"ignore_unknown_options": True, "allow_interspersed_args": False}' launch_cli.py) — line 9
# AFTER — insert:
def _host_option() -> Callable[[F], F]:
    """``--host claude|google`` (default ``$PARROT_SDD_HOST`` or ``claude``) — FEAT-847."""
    return click.option(
        "--host",
        type=click.Choice(["claude", "google"]),
        default="claude",
        envvar="PARROT_SDD_HOST",
        show_envvar=True,
        help="Agent CLI to launch: Claude Code or Google Antigravity (agy).",
    )
# FILL IN: typing for _host_option (from typing import Callable, TypeVar; F = TypeVar("F", bound=Callable[..., Any]))
#   or drop the annotation in favour of a plain module-level decorator object — bounded by ruff/strict typing.

# worker (line 17 decorator stack): add `@_host_option()` above `@click.argument("claude_args", ...)`, a `host: str`
#   parameter, and pass `host=host` to feature_launcher.launch(...).
# _session (line 64): signature `_session(ctx: click.Context, prompt_words: list[str], host: str = "claude")`; call
#   feature_launcher.launch_session(" ".join(prompt_words), cwd=cwd, base_env=base_env, host=host).
# brief / fix: add `@_host_option()` ABOVE their `@click.argument(...)` lines, a `host: str` parameter, and pass it.
# FILL IN: confirm with a test that _PASSTHROUGH still lets unknown skill flags through and that `--host` after the
#   first positional stays in `rest` — bounded by spec §3 M3 "option placement".
```
**Why this shape**: the Click option is the only place that knows about `PARROT_SDD_HOST`; the launcher
receives an explicit `host`, which keeps the `python -S` tmux child deterministic.

### `packages/ai-parrot/tests/sdd/test_sdd_launch.py` (MODIFY)
```python
# AFTER — append at end of file
@pytest.mark.parametrize(
    ("argv", "host", "prompt"),
    [
        (["sdd", "launch", "brief", "--host", "google", "NAV-1", "--no-interview"], "google", "/sdd-brief NAV-1 --no-interview"),
        (["sdd", "launch", "brief", "NAV-1", "--host", "google"], "claude", "/sdd-brief NAV-1 --host google"),
        (["sdd", "launch", "fix", "--host", "google", "--top", "2"], "google", "/sdd-fix --top 2"),
    ],
)
def test_brief_fix_host_placement(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, argv: list[str], host: str, prompt: str) -> None:
    seen: dict[str, object] = {}
    monkeypatch.delenv("PARROT_SDD_HOST", raising=False)
    monkeypatch.setattr(launcher, "_invocation_dir", lambda: _primary(tmp_path))
    monkeypatch.setattr(launcher, "launch_session", lambda prompt, **kw: seen.update(prompt=prompt, **kw) or 0)
    result = CliRunner().invoke(devloop, argv)
    assert result.exit_code == 0, result.output
    assert seen["prompt"] == prompt and seen["host"] == host


# FILL IN tests (one function each):
#  - worker --host google -> feature_launcher.launch called with host="google" (monkeypatch launcher.launch);
#    default -> host="claude"; PARROT_SDD_HOST=google -> "google"; PARROT_SDD_HOST=bogus -> exit 2 (usage error)
#  - test_launch_cli_google_host: end to end with a mocked agy (which -> "/home/u/.local/bin/agy"), the launcher's
#    host prep and hook prerequisite monkeypatched: worker --host google execs argv containing
#    "--dangerously-skip-permissions" with PARROT_SDD_AGY_UNATTENDED=1 and backend bubblewrap in env;
#    brief/fix --host google exec argv WITHOUT that flag and env WITHOUT both variables; no argv contains "--mode"
#  - existing test_launch_brief_and_fix_exec_slash_command still passes (default Claude)
```

### FILL IN checklist
- [ ] `_host_option` typing; bounded by ruff
- [ ] placement assertion; bounded by spec §3 M3
- [ ] the listed tests

---

## Acceptance Criteria

- [ ] `parrot sdd launch worker|brief|fix` accept `--host claude|google`, defaulting to `$PARROT_SDD_HOST` or `claude`.
- [ ] For `brief`/`fix`, `--host` is consumed only before the first positional; later occurrences remain skill arguments.
- [ ] `worker --host google` execs agy with `--dangerously-skip-permissions` + unattended env; `brief`/`fix --host google` exec it without them; no `--mode auto`.
- [ ] Existing launch CLI tests pass; `ruff check` clean.

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
9. **Close the task** with `parrot sdd task close TASK-5354 sdd-agy-compatibility verified`
10. **Fill in the Completion Note** below, then commit the staged SDD state

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
