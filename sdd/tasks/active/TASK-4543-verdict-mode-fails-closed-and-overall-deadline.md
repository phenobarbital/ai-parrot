# TASK-4543: `--verdict` fails closed on registry/adapter errors and honours an overall deadline

**Feature**: FEAT-709 — Language-agnostic validation runners and an engine-owned task-tier gate
**Spec**: `sdd/specs/language-agnostic-validation-runners.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-4542
**Assigned-to**: unassigned
**Discovered-from**: `issue:7e23927a1fa6`

---

## Context

`--verdict` has one contract: **print exactly one compact verdict JSON object on
stdout and nothing else** (`_write_verdict`, `select_tests.py:119-123`). The
engine's validation capability binds it through
`test_scope/guard.py:21`:

```python
VERDICT_ARGV = ("python", "scripts/sdd/select_tests.py", "--tier", "task", "--run", "--verdict")
```

Two inputs break that contract today:

1. **Registry / adapter errors escape.** `load_registry()` raises `ValueError` on
   malformed `.parrot/test_runners.toml` (`runners/registry.py:125-160`) and
   `adapter_for_kind()` raises `KeyError` for an unknown kind or
   `ModuleNotFoundError` for a missing builtin module (`registry.py:31-44`).
   Neither is caught. Note the **first** failure point is not
   `_run_verdict_mode`: `main()` calls `kernel.plan_tests(...)`
   (`select_tests.py:315`) which itself does `registry = registry or
   load_registry(worktree)` (`select.py:154`) and `registry.adapter_for_kind(kind)`
   (`select.py:165`). So the traceback happens *before* verdict mode is entered,
   and the caller gets a non-zero exit with empty stdout instead of a
   `status: "blocked"` verdict.
2. **No overall deadline.** Each invocation gets `timeout_s or
   registry.timeout_for(runner)` (`select_tests.py:202`), but a chain of
   invocations has no aggregate cap. Spec S9 requires exactly this —
   *"Per-invocation timeout + overall cap; only unfinished invocations
   `timed_out`; finished evidence kept"* — and `ValidationSupervisor._supervise`
   already implements it (`background.py:683-1013`: one `deadline`, a per-runner
   `min(deadline, now + timeout_for(kind))`, and a synthesized exit-124 report for
   invocations that never start). The CLI path never got the same treatment.

---

## Scope

- Catch `ValueError` / `KeyError` / `ModuleNotFoundError` around the plan
  construction in `main()`; under `--verdict` emit a blocked verdict (exit 2),
  otherwise keep today's `error: …` on stderr + exit 2.
- Catch the same errors around `load_registry()` and each `adapter_for_kind()`
  inside `_run_verdict_mode`, emitting a blocked verdict.
- Add `--timeout-total SECONDS` (default `3600`, `0` disables) and enforce it in
  `_run_verdict_mode` with the supervisor's semantics: clamp each invocation's
  timeout to the remaining budget, and for invocations that never start,
  synthesize a timed-out report (`exit_code=124`, `timed_out=True`,
  `duration_s=0.0`) rather than running them.
- Tests for every branch.

**NOT in scope**:
- The `--run` (non-verdict) path's error handling — it already prints to stderr
  and its contract permits free-form output.
- The green cache / baseline: `_run_verdict_mode` returns at
  `select_tests.py:348`, before the cache write at line 520, so "no green cache
  on partial runs" (S9) already holds for verdict mode.
- Changing `guard.VERDICT_ARGV` — the new default applies without a caller change.
- `ValidationSupervisor` — its deadline handling is already correct.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `scripts/sdd/select_tests.py` | MODIFY | Guard plan construction + registry/adapter lookups; add and enforce `--timeout-total` |
| `tests/sdd_scripts/test_select_tests.py` | MODIFY | Tests for blocked verdicts and the overall deadline |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# scripts/sdd/select_tests.py:152 — already imported inside _run_verdict_mode
from test_scope.runners.registry import load_registry  # verified: select_tests.py:156
```

### Existing Signatures to Use
```python
# scripts/sdd/select_tests.py:126 — the blocked-verdict builder to reuse verbatim
def _blocked_verdict(kernel: ModuleType, *, tier: str, note: str) -> object:
    return kernel.ValidationVerdict(
        schema=1, status="blocked", tier=tier, runners=(), failures=(), notes=(note,),
    )

# scripts/sdd/select_tests.py:119
def _write_verdict(verdict: object) -> None:

# scripts/sdd/select_tests.py:153
def _run_verdict_mode(*, args, kernel, plan, worktree, base_ref) -> int:

# scripts/sdd/select_tests.py:315 — the UNGUARDED call that raises first
    plan = kernel.plan_tests(
        worktree=worktree, changed_files=kernel.changed_files(worktree, base_ref),
        tier=args.tier, declared=declared, contract=contract,
    )

# scripts/sdd/select_tests.py:171 — the existing precedent for "blocked, exit 2"
        verdict = _blocked_verdict(kernel, tier=args.tier, note=f"cannot create validation log directory: {exc}")
        _write_verdict(verdict)
        return 2

# packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py:122
def load_registry(worktree: Path) -> RunnerRegistry:   # raises ValueError
# registry.py:31
    def adapter_for_kind(self, kind: str) -> RunnerAdapter:   # raises KeyError / ModuleNotFoundError

# registry.py:73 — the per-runner timeout used at select_tests.py:202
    def timeout_for(self, kind: str) -> int:

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py:986 — the
# semantics to mirror for an invocation that never starts
                if time.monotonic() >= deadline:
                    report = await self._parse_invocation_report(
                        ..., exit_code=124, duration_s=0.0, timed_out=True, stdout="",
                    )
```

### Does NOT Exist
- ~~`args.timeout_total`~~ — the flag does not exist yet; `--timeout` (line 61) is
  pytest-timeout per *test*, and `--timeout-baseline` (line 45) only bounds
  baseline classification. Neither is an overall cap.
- ~~a `blocked` branch in `_run_verdict_mode`~~ — the only blocked verdicts today
  are the log-dir failure (line 171) and the empty task-tier plan (line 342)
- ~~`adapter.parse_report` raising on a synthesized timeout~~ — it takes
  `timed_out: bool` and a missing `report_path` is a normal input

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "scripts/sdd/select_tests.py", "action": "MODIFY"},
    {"path": "tests/sdd_scripts/test_select_tests.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:scripts/sdd/select_tests.py#_run_verdict_mode",
    "sym:scripts/sdd/select_tests.py#_blocked_verdict",
    "sym:scripts/sdd/select_tests.py#_build_parser",
    "sym:scripts/sdd/select_tests.py#main",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py#load_registry",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/test_scope/runners/registry.py#RunnerRegistry.adapter_for_kind"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- **Never print anything but the verdict JSON under `--verdict`.** No stderr
  `error:` line, no traceback — the note travels inside the verdict's `notes`.
- Exit code for a blocked verdict is `2`, matching the existing log-dir and
  empty-plan precedents.
- Keep finished evidence on a partial run: reports already collected stay in
  `reports`, and `log_path` is still written before `build_verdict`.
- `0` must disable the cap (no deadline) so an operator can opt out.
- Compute the deadline **once**, at the top of `_run_verdict_mode`, from
  `time.monotonic()`.

### Pattern to Follow
```python
# the clamp, mirroring background.py:1013
timeout_s = invocation.timeout_s or registry.timeout_for(invocation.runner)
if deadline is not None:
    timeout_s = max(1, min(timeout_s, int(deadline - time.monotonic())))
```

---

## Implementation Blueprint

### Steps (in order)
1. Add `--timeout-total` to `_build_parser` — *why*: the cap needs an operator-visible knob with a real default.
2. Guard the `kernel.plan_tests(...)` call in `main()` — *why*: this is where malformed TOML actually raises.
3. Guard `load_registry()` and `adapter_for_kind()` in `_run_verdict_mode` — *why*: defence in depth; the declared-runner path can still reach an unloadable adapter.
4. Thread the overall deadline through the invocation loop — *why*: spec S9.
5. Add tests for each branch — *why*: AC gate.

### `scripts/sdd/select_tests.py` (MODIFY)
```python
# 1. occurrences: 1 (verified: grep -c '"--timeout-baseline"' scripts/sdd/select_tests.py)
# AFTER the `--timeout-baseline` argument (line 45), insert:
    parser.add_argument(
        "--timeout-total",
        type=int,
        default=3600,
        metavar="SECONDS",
        help="Overall wall-clock cap across every planned invocation (0 disables).",
    )

# 2. occurrences: 1 — REPLACE the bare `plan = kernel.plan_tests(...)` at line 315 with:
    try:
        plan = kernel.plan_tests(
            worktree=worktree,
            changed_files=kernel.changed_files(worktree, base_ref),
            tier=args.tier,
            declared=declared,
            contract=contract,
        )
    except (ValueError, KeyError, ModuleNotFoundError) as exc:
        if args.verdict:
            _write_verdict(_blocked_verdict(kernel, tier=args.tier, note=f"cannot plan validation: {exc}"))
            return 2
        print(f"error: {exc}", file=sys.stderr)  # noqa: T201 - CLI output
        return 2

# 3. occurrences: 1 — REPLACE `registry = load_registry(worktree)` (line 175) with:
    try:
        registry = load_registry(worktree)
    except (ValueError, OSError) as exc:
        _write_verdict(_blocked_verdict(kernel, tier=args.tier, note=f"cannot load the runner registry: {exc}"))
        return 2

# 4. occurrences: 1 — REPLACE `adapter = registry.adapter_for_kind(invocation.runner)` (line 181) with:
        try:
            adapter = registry.adapter_for_kind(invocation.runner)
        except (KeyError, ModuleNotFoundError) as exc:
            _write_verdict(_blocked_verdict(kernel, tier=args.tier, note=f"unusable runner: {exc}"))
            return 2

# 5. the overall deadline. AFTER `log_lines = [...]` (line 177), insert:
    deadline = None if not args.timeout_total else time.monotonic() + args.timeout_total

# and inside the loop, REPLACE `timeout_s = invocation.timeout_s or registry.timeout_for(invocation.runner)`
# (line 202) with a budget check that skips the launch when the cap is spent:
        timeout_s = invocation.timeout_s or registry.timeout_for(invocation.runner)
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            # FILL IN: build the never-started report via adapter.parse_report(
            #   report_path=report_path, exit_code=124, stdout="", stderr="",
            #   duration_s=0.0, timed_out=True, suite=report_mod.suite_name(run_invocation))
            # append it to `reports`, add a log line, and `continue` — do NOT launch.
            raise NotImplementedError
        if remaining is not None:
            timeout_s = max(1, min(timeout_s, int(remaining)))
```
**Why this shape**: every escape hatch funnels into the one existing
`_blocked_verdict` + `_write_verdict` + `return 2` idiom, so the "only the JSON on
stdout" contract holds on every path. The deadline mirrors
`background.py:986-1013` exactly, so the CLI and the supervisor agree on what a
partial run looks like.

### FILL IN checklist
- [ ] `_run_verdict_mode` — the never-started report block: build it from `adapter.parse_report(...)` with `exit_code=124, timed_out=True, duration_s=0.0`, append to `reports`, log `# skipped: overall deadline exceeded`, then `continue`. Bounded by spec S9 ("only unfinished invocations `timed_out`; finished evidence kept").

---

## Acceptance Criteria

- [ ] With a malformed `.parrot/test_runners.toml`, `--verdict` prints exactly one JSON object with `status == "blocked"`, a note naming the config, exit code 2, and **nothing** on stderr
- [ ] With a contract declaring an unknown runner kind, `--verdict` prints a single blocked verdict, exit 2
- [ ] Without `--verdict`, the same malformed TOML still produces `error: …` on stderr and exit 2 (unchanged behaviour)
- [ ] `--timeout-total 0` runs with no overall cap (today's behaviour)
- [ ] When the cap is exhausted mid-chain, the invocations that already ran keep their reports and evidence, and each unstarted invocation appears as a timed-out runner in the verdict
- [ ] Each invocation's own timeout is clamped to the remaining budget
- [ ] `ruff check scripts/sdd/select_tests.py` is clean
- [ ] All validation commands pass

---

## Validation Commands

- `pytest tests/sdd_scripts/test_select_tests.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_verdict.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_runners_registry.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_scope/test_guard.py -q`

---

## Test Specification

```python
# tests/sdd_scripts/test_select_tests.py — add alongside the existing verdict tests

def test_verdict_blocked_on_malformed_runner_config(fixture_monorepo, capsys):
    """Malformed .parrot/test_runners.toml yields one blocked verdict, not a traceback."""
    (fixture_monorepo / ".parrot").mkdir(exist_ok=True)
    (fixture_monorepo / ".parrot/test_runners.toml").write_text("this is not = = toml\n")

    rc = main(["--tier", "task", "--worktree", str(fixture_monorepo), "--verdict"])

    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err == ""
    payload = json.loads(captured.out.strip())   # exactly one object, nothing else
    assert payload["status"] == "blocked"
    assert "test_runners.toml" in " ".join(payload["notes"])


def test_non_verdict_mode_keeps_stderr_error_on_malformed_config(fixture_monorepo, capsys):
    """Without --verdict the old stderr contract is unchanged."""
    # FILL IN: same setup, call main() without --verdict, assert rc == 2 and "error:" in err


def test_verdict_blocked_on_unknown_runner_kind(fixture_monorepo, capsys):
    """A declared runner kind with no adapter blocks instead of raising KeyError."""
    # FILL IN: declare an unknown kind in the index contract; assert one blocked verdict, rc == 2


def test_timeout_total_zero_disables_the_overall_cap(fixture_monorepo, monkeypatch, capsys):
    """--timeout-total 0 leaves per-invocation timeouts untouched."""
    # FILL IN: capture the `timeout=` kwarg passed to subprocess.run; assert it equals
    # the registry default, not a clamped value


def test_exhausted_overall_deadline_marks_unstarted_invocations_timed_out(
    fixture_monorepo, monkeypatch, capsys
):
    """Finished evidence is kept; only unfinished invocations are timed_out (spec S9)."""
    # FILL IN: build a two-invocation plan; make the first consume the whole budget
    # (monkeypatch time.monotonic); assert the first runner's report survives in the
    # verdict and the second is reported timed out with exit 124, and that
    # subprocess.run was called exactly once
```

---

## Agent Instructions

Follow the standard SDD task loop (see `sdd/templates/task.md` §Agent Instructions).
Work in `.claude/worktrees/feat-FEAT-709-language-agnostic-validation-runners`.
TASK-4542 must be `done` first — it edits the same `--run` loop region.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
