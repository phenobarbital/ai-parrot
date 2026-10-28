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

## Re-measure after the project-venv trust gate (FEAT-633 R6, measured 2026-10-28)
Why: the trust gate (`launcher._project_venv_trusted`: an ownership `lstat` plus one `git ls-files` per
managed→project resolution) landed after the runs above, and the full managed→project chain had never been timed
with a real hook payload.

Method: `S4-bench.py` (this directory). Linux x86_64, Python 3.12.13, git 2.53.0, run inside the Claude Code Bubblewrap
sandbox; 30 runs after 3 warmups, `subprocess.run` wall clock. The payload is a real PreToolUse `Bash` call whose `cwd`
is the project, so `worktree_environment --hook` does its full work. "Managed" = `PARROT_HOME/venv` symlinked to the dev
venv. The project is a fresh git repo whose untracked `.venv/bin/<script>` re-enters the launcher, so the gate runs and
passes. Every case is first checked for the expected path (re-exec'd or not, exit code 0) before it is timed.

| Case | Median (ms) | p95 (ms) | Δ median | Within budget? |
|---|---|---|---|---|
| `python -c pass` (interpreter floor) | 24.0 | 25.1 | — | — |
| `claude-hook` via old entry (non-managed) | 41.6 | 42.5 | baseline | — |
| `claude-hook` via launcher, non-managed | 42.0 | 44.5 | +0.4 vs old entry | yes (≤ 5 ms) |
| `claude-hook` via launcher, managed, no project venv | 41.9 | 43.8 | +0.3 vs old entry | yes |
| `claude-hook` via launcher, managed → project re-exec | 78.2 | 80.6 | +36.2 vs launcher non-managed | yes (≤ 50 ms) |
| sdd hook baseline: `python -m …worktree_environment --hook` | 87.0 | 89.8 | baseline | — |
| sdd hook via launcher (`main_parrot`), non-managed | 86.7 | 89.4 | −0.3 | yes (≤ 5 ms) |
| sdd hook via launcher, managed → project re-exec | 121.9 | 129.8 | +35.2 vs launcher non-managed | yes (≤ 50 ms) |
| trust gate `_project_venv_trusted` (in-process, 200 calls) | 1.00 per call | — | — | — |
| `resolve_venv` managed→project incl. gate (in-process, 200 calls) | 1.33 per call | — | — | — |

Findings:
- The trust gate costs about 1 ms of the ~36 ms re-exec hop. The rest is one more interpreter start plus the project
  script's imports. Caching the verdict per (repo, HEAD) is not worth it: it would save under 3% of the hop.
- The sdd hook baseline is ~87 ms here against 45.5 ms in the section above. The launcher is not the cause: the same
  hook without a `cwd` answers in ~39 ms. The 45.5 ms run used a payload that took a short path.

Verdict: pass (Linux, Python 3.12, 2026-10-28). macOS and Windows numbers still come from the install-matrix run (R7).
