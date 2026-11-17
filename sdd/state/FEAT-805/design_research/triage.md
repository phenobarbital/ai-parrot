## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration doc** (never over
> this spec). Model: `gpt-5.6-luna` · Status: completed · Transcript:
> `sdd/state/FEAT-805/design_research/`
> All 26 cited paths passed the containment and existence checks.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Separate primary-checkout configuration from worktree configuration (risk) | CONFIRM | Each reader's checkout is now an explicit table and a tamper test covers launch policy and the setup command. Moving `sandbox.mode` to the primary is a behaviour change left to the owner. | §2 Overview, §4, §8 (mode root) |
| S2 | Version and strongly type the new config blocks (api) | CONFIRM | Typed nested models were already the design; runner `cwd` containment is now validated. The schema-version half is not adopted: every released parrot forbids unknown keys, a version key included, so it cannot help the skew it targets. | §3 M1, §7 |
| S3 | Represent host setup as argv rather than a shell string (risk) | CONFIRM | Same model as `NativeGroup.build`: argv, relative `cwd`, bounded timeout, no shell; `cwd` and `inputs` reject absolute and `..` paths. | §2 Data Models, §3 M1, M4 |
| S4 | Define setup state and failure semantics separately from native sync (architecture) | CONFIRM | Separate `SetupReport` and fingerprint; the step runs outside the native-sync `try`; tests added for command change, native-sync failure and the skip switches. | §3 M4, §4 |
| S5 | Unify normal and verdict test execution paths (testing) | CONFIRM | One helper computes argv and working directory for both modes, with pytest, vitest and cargo regressions. Process supervision, deadlines and report parsing stay per mode: merging them is a larger refactor of gate code than this feature needs. | §2 Overview, §3 M6, §4 |
| S6 | Make profiles feed the runner registry instead of a second execution model (alternative) | CONFIRM | Profiles never run tests; `STEPS` has no `test`; adapters stay the only test execution path. Profiles cover fix / format / lint / typecheck, which the registry does not model. | §2 Overview |
| S7 | Resolve profiles per configured root (architecture) | CONFIRM | Already the design (root, runner `cwd`, override roots); the unique file-to-profile rule is now stated and tested for two kinds at one root. | §2 Overview, §4 |
| S8 | Make the vitest package manager part of the adapter contract (api) | CONFIRM | Precedence changed to setting → `packageManager` → lockfile; an unsupported manager fails `validate_settings`. | §3 M5, M7, §4 |
| S9 | Extend the engine boundary beyond the Python-only lint implementation (architecture) | CONFIRM | The profile pass contract now states suffix selection, bounded commands, commit behaviour and that it reports no residuals. Verified: `check_banned_imports` (`fidelity.py:88-100`) returns nothing without `.py` files, so it does not gate foreign tasks; it stays Python-only. | §2 Overview, §3 M9 |
| S10 | Turn the wheel-only foreign-repository harness into the Node acceptance fixture (testing) | CONFIRM | The scenarios move into `test_wheel_only_foreign_repo.py`; no separate test file. | §3 M12, §4, §6 |
| S11 | Make contract probing consume profile capabilities (architecture) | ESCALATE | The probe is phase 3, outside this spec; recorded as option c) of the open question. | §8 (contract probe) |
| S12 | Expand asset parity checks to every changed host twin (testing) | CONFIRM | `scripts/sdd/check_asset_sync.py` is the gate; the task confirms it covers the eight twins and the parity suites join the Validation Contract. | §3 M10, §4, §5 |

Summary: **11** confirmed · **0** rejected · **1** escalated.

---

