# TASK-1929: Run-bundle runner wiring — export bundle.json + report.md at run close

**Feature**: FEAT-378 — DevLoop Enhancement — Feature-Mode Topology
**Spec**: `sdd/specs/devloop-enhancement.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1928
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (v0.2 amendment), step 4. `DevLoopRunner._close_host`
(runner.py:718) is the single point where every run — initial and
revision, succeeded, failed or cancelled — still has BOTH the live
`SessionHost` (envelope log + terminal state) and the flow `ctx` (shared
results), immediately before `_discard_host` throws them away. The
terminal snapshot is already persisted there; this task adds the run
bundle and its markdown closing report beside it.

---

## Scope

- **Runner** (`runner.py`):
  - New private method `_persist_run_bundle(host, ctx)` mirroring
    `_persist_terminal_snapshot` (:345): build the bundle via
    `build_run_bundle(host.snapshot(), host.replay_since(0), shared)`
    and write BOTH artifacts under `conf.OUTPUT_DIR/dev_loop_runs/`:
    - `{run_id}.bundle.json` — `bundle.model_dump_json(indent=2)`
    - `{run_id}.report.md` — `render_markdown(bundle)`
    Entire body wrapped in the same swallow-and-log pattern — bundle
    export must NEVER break or delay run teardown.
  - Call it from `_close_host` (:718) right after
    `_persist_terminal_snapshot(host)` and before `_discard_host` —
    on BOTH call sites' shared path (initial :591 and revision :713 both
    funnel through `_close_host`; one insertion point only).
  - Extract `shared` from `ctx` the same way `_close_host`/nodes do
    (duck-typed; tolerate `ctx=None` → empty mapping).
- **Package exports** (`__init__.py`): export `RunBundle`,
  `build_run_bundle`, `render_markdown`.
- Tests: end-of-run export (both files written, valid JSON, non-empty
  markdown), export-failure swallowed (monkeypatched writer raising →
  run closes normally), cancelled/failed run still exports.

**NOT in scope**: HTTP/CLI download surface for the bundle (future),
retention/deletion of bundle files (they follow the same manual
lifecycle as the existing `.snapshot.json`), telemetry harvest
(TASK-1927), bundle content (TASK-1928).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/runner.py` | MODIFY | `_persist_run_bundle` + `_close_host` call |
| `packages/ai-parrot/src/parrot/flows/dev_loop/__init__.py` | MODIFY | Export the three public names |
| `packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py` | CREATE | Export/teardown tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Anchors (2026-07-27)
```python
# runner.py
def _persist_terminal_snapshot(self, host): ...  # :345 — pattern to mirror (OUTPUT_DIR/dev_loop_runs)
def _close_host(self, ...): ...                  # :718 — RunClosed :750 → snapshot :753 → ... → _discard_host :758
# _close_host callers: :591 (initial), :713 (revision)
class SessionHost:
    def snapshot(self) -> Snapshot: ...          # session_state.py:770
    def replay_since(self, seq) -> List[ActionEnvelope]: ...  # session_state.py:775 — seq 0 → full log
# conf.py
OUTPUT_DIR = Path(...)                           # conf.py:48
```

### Does NOT Exist
- ~~`run_bundle.py`~~ until TASK-1928 lands — hard dependency.
- ~~A conf flag for bundle export~~ — do NOT add one; export
  unconditionally, exactly like the terminal snapshot (spec §3 M8).
- ~~Async file I/O requirement~~ — `_persist_terminal_snapshot` writes
  synchronously at teardown; match it (tiny files, terminal path).

---

## Implementation Notes

- Re-grep `_close_host` line anchors at task start — runner.py is under
  active FEAT-377/FEAT-378 edits.
- Log at INFO with both artifact paths on success (mirroring the
  snapshot log line at :359) so operators can find the report.
- Keep `_persist_run_bundle` independent from
  `_persist_terminal_snapshot` — one failing must not skip the other.

---

## Acceptance Criteria

- [ ] Every terminated run (succeeded/failed/cancelled; initial and
      revision) leaves `{run_id}.bundle.json` + `{run_id}.report.md`
      under `conf.OUTPUT_DIR/dev_loop_runs/`
- [ ] A raising bundle export is swallowed: run closes, host discarded,
      snapshot still persisted (order-independence test)
- [ ] `from parrot.flows.dev_loop import RunBundle, build_run_bundle,
      render_markdown` works
- [ ] All tests pass: `pytest packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py -v` AND the existing runner suite stays green
- [ ] `ruff check` clean on modified files

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_run_bundle_export.py
def test_close_host_writes_bundle_and_report(tmp_path): ...
def test_failed_run_still_exports(tmp_path): ...
def test_bundle_export_failure_never_breaks_teardown(tmp_path): ...
def test_package_exports(): ...
```

---

## Agent Instructions

1. **Read the spec** (§3 Module 8, §6, §7 Patterns)
2. **Check dependencies** — TASK-1928 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — re-grep the line anchors
4. **Update status** in `sdd/tasks/index/devloop-enhancement.json` → `"in-progress"`
5. **Implement**, **verify criteria**, move file to `sdd/tasks/completed/`, update index → `"done"`, fill Completion Note

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-07-27
**Notes**: Re-grepped `runner.py`'s anchors before implementing — the
merged worktree now has THREE `_close_host` callers (initial :903,
feature :1000, revision :1146; the contract's "initial :591 / revision
:713" numbers had drifted after the FEAT-377 merge), confirming the
"one insertion point" design still holds since all three funnel through
the single `_close_host` method. Added `_persist_run_bundle(host, ctx)`
mirroring `_persist_terminal_snapshot`'s swallow-and-log pattern exactly,
called it right after `_persist_terminal_snapshot(host)` in `_close_host`
(independent try/except — a bundle-export failure can't skip or break
the snapshot persist, and vice versa). `ctx` is read defensively
(`FlowContext` / plain dict / `None` → `{}`), matching
`DevLoopNode.shared_state`'s duck-typing. Exported `RunBundle`,
`build_run_bundle`, `render_markdown` from the package `__init__.py`
(both the `from ... import` line and `__all__`, alphabetically placed).

Test-writing surfaced a real order-dependency bug unrelated to the
production code: `monkeypatch.setattr("parrot.flows.dev_loop.runner.
build_run_bundle", fn)` (the dotted-string form) silently failed to
stick — the patched attribute reverted to the original function — only
when `test_lazy_import.py`'s tests (which aggressively
`del sys.modules[...]` / reimport / restore every
`parrot.flows.dev_loop*` entry) ran earlier in the same session, even
though the restored module object's identity and `__dict__` were
verified (via a standalone repro script) to be byte-identical to the
pre-churn one. Root cause not fully isolated (likely an interaction in
pytest's dotted-path import resolution racing the sys.modules churn);
sidestepped by monkeypatching the already-imported module OBJECT
directly (`monkeypatch.setattr(_runner_module, "build_run_bundle", fn)`)
instead of the string path — confirmed via the same repro script and a
full-suite run that this form is robust regardless of ordering. Also
found (again) and fixed the TASK-1928 completion commit's SDD-state
step: the `mv` + selective `git add` pattern used for TASK-1927/1928
left `sdd/tasks/active/TASK-1928-*.md`'s deletion unstaged (same class
of bug documented in TASK-1927's completion note) — fixed with
`git rm` + a follow-up commit, and switched to `git mv` for this task's
own active→completed move to avoid a third occurrence.

Tests: 4 new tests in `test_run_bundle_export.py`, all passing,
reproducing every acceptance criterion (bundle+report written on
success, still written on a failed run, export-failure swallowed
without breaking teardown or skipping the terminal snapshot, package
exports importable). Full `packages/ai-parrot/tests/flows/dev_loop/`
suite: 830 passed, 7 skipped, 1 pre-existing order-dependent failure
(`test_lazy_import.py::test_models_module_is_pure` — pre-existing,
unrelated, documented in TASK-1927/1928's completion notes).
`ruff check` clean on all three modified/created files.

This closes out FEAT-378 — all 12 tasks (TASK-1918 through TASK-1929)
are now `"done"` in the per-spec index; `completed_at` set on both this
task and the feature header.

**Deviations from spec**: none
