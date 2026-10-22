> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-633/design_research/`
> Every row is a suggestion the reviewer made; the disposition is the spec author's
> call (CONFIRM = folded into the spec, REJECT = reason recorded, ESCALATE = §8 question).

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Launcher import boundary genuinely stdlib-only; decide re-exec before importing targets; fast path survives re-exec (architecture) | CONFIRM | `parrot`/`bookstore` import heavy modules at load; resolution must precede import | §3 M1 |
| S2 | Extract PARROT_HOME into dependency-free module; callers delegate (architecture) | CONFIRM | matches M1/M3 consolidation design exactly | §3 M1/M3 |
| S3 | Specify venv resolution as subprocess-tested state machine incl. symlinks, Windows names, `--project`, no-candidate (testing) | CONFIRM | unit tests alone can't prove the exec boundary | §4 Integration |
| S4 | Centralize only low-level binary resolution; Google `PurePosixPath` breaks on Windows (architecture) | CONFIRM | matches M5 via `launcher.script_path`; PurePosixPath gotcha was unknown | §3 M5, §7 |
| S5 | Portable = complete per-host ownership/cwd contract (`cwd`, `--config`, bookstore), test both transitions (api) | CONFIRM | bare command alone leaves absolute state behind | §3 M5, §4, §5 |
| S6 | PEP 508 field separate from import probes; post_install as versioned handler registry (api) | CONFIRM (scoped) | separation already designed; handler registry NOT adopted — templates load from `importlib.resources` only (toolkit_seed.py:49), so argv never comes from user-writable input; constraint recorded instead | §3 M4, §7 |
| S7 | Migration safety = storage-layer protocol: cross-process Windows-safe lock; per-instance asyncio lock and POSIX-only fcntl insufficient (risk) | CONFIRM | real gap found in the brainstorm's "single-writer lock" | §3 M7, §4, §7 |
| S8 | SDD packaging as verified build artifact: MANIFEST.in, wheel-content CI check (architecture) | CONFIRM | MANIFEST.in is Cython-only today; byte-equality alone doesn't prove wheel contents | §3 M6, §6 Edit Sites |
| S9 | Audit installed commands for shell/jq/non-Windows assumptions; installer reports unavailable tooling (risk) | CONFIRM | folded into spike S5 scope + M6 install-time report | §3 M0/M6 |
| S10 | Global bootstrap branches BEFORE the system-Python guard; interrupted-run safety (risk) | CONFIRM | both scripts hard-require Python today — a clean machine never reaches `--global` otherwise | §3 M2, §5 |
| S11 | Gate wheel matrix on clean-install + console-script smoke tests; resolve cp314 vs `<3.14` (testing) | CONFIRM | build success ≠ installable; contradiction already flagged in §7 | §3 M8, §5 |

Summary: **11** confirmed (1 scoped) · **0** rejected · **0** escalated.
