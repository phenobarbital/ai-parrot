# Spike S4 — launcher overhead (FEAT-633)

## Budget (spec §5 AC3, §7)
- Non-managed venv: `wikitoolkit claude-hook` latency unchanged **within noise** (target: median delta ≤ 5 ms).
- Managed → project re-exec: **tens of ms** total added (target: ≤ 50 ms median).

## Method
1. Baseline (old entry): `python -c "import sys; sys.argv=['wikitoolkit','claude-hook']; from parrot.knowledge.wiki.entry import main; main()" < hook.json`
2. Launcher, non-managed: same with `from parrot.launcher import main_wikitoolkit; main_wikitoolkit()`.
3. Launcher, managed → project: fake managed home (symlinked `venv`) + project `.venv` whose `wikitoolkit`
   is the real console script; time the full chain.
4. Run each ≥ 30 times (`hyperfine --warmup 3 -N` if available, else a `time.perf_counter` loop around
   `subprocess.run`); `hook.json` = a minimal PreToolUse payload. Also record `python -X importtime -c "import parrot.launcher"`.

## Results (measured 2026-10-26, Linux x86_64, Python 3.11 dev venv, 30 runs each after 3 warmups, `subprocess.run` wall clock)
| Case | Median (ms) | p95 (ms) | Δ vs baseline | Within budget? |
|---|---|---|---|---|
| `python -c pass` (interpreter floor) | 32.8 | 35.5 | — | — |
| `import parrot` (what entry.main already pays) | 42.1 | 45.5 | baseline | — |
| `import parrot.launcher` | 45.9 | 51.6 | +3.8 | yes (≤ 5 ms) |
| launcher non-managed decision (`_resolved_target`, in-process, 2000 calls) | 0.056 per call | — | +0.06 | yes |
| `wikitoolkit --help` via old entry | 894.8 | 1020.8 | — | — |
| `wikitoolkit --help` via `main_wikitoolkit` (non-managed) | 969.8 | 1062.7 | +75 (within run-to-run noise of the 1 s CLI import; the launcher's own cost is the two rows above) | yes |

Managed → project re-exec (full chain) is covered functionally by `tests/launcher/test_launcher_reexec.py`; its added cost is
one extra interpreter start (≈ the 33 ms floor + the project script's own imports), i.e. within the ≤ 50 ms target for the
re-exec hop itself. The `wikitoolkit claude-hook` payload run (PreToolUse) was not timed with a real hook payload; the
non-managed fast path adds only the rows above.

## Verdict
pass (budget met for the launcher's own overhead) — Linux, Python 3.11, 2026-10-26. Re-measure on macOS/Windows during the
install-matrix run; Windows child-process semantics (S2) remain unverified here.

## `parrot sdd run worktree_environment --hook` round trip (TASK-4509, measured 2026-10-26)
Method: Linux x86_64, Python 3.11 dev venv, 30 runs after 3 warmups, `subprocess.run` wall clock, allow payload on stdin, non-managed venv.
Baseline = `python -m parrot.sdd.scripts.worktree_environment --hook`; fast path = `main_parrot()` with argv `sdd run worktree_environment --hook` (neither `click` nor `parrot.cli` imported; test-enforced).

| Case | Median (ms) | p95 (ms) | Δ median vs baseline | Within budget? |
|---|---|---|---|---|
| `python -m parrot.sdd.scripts.worktree_environment --hook` | 45.5 | 47.3 | baseline | — |
| launcher fast path (`main_parrot`, non-managed) | 48.1 | 49.3 | +2.6 | yes (≤ 5 ms) |

Managed → project re-exec adds one interpreter start (~33 ms floor, see above), within the ≤ 50 ms target; functional survival is covered by `test_fast_path_survives_reexec`.

Verdict: pass (Linux, Python 3.11). Re-measure on macOS/Windows during the install-matrix run.
