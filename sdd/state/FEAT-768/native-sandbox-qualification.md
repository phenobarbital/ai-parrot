# FEAT-768 native sandbox — live qualification (INTERIM, NOT QUALIFIED)

Date: 2026-10-30. Run by the sdd-worker orchestrator. **Overall verdict: NOT QUALIFIED. The `path` run is
invalid as a host qualification, and the `bundled` run was not performed.**

## Host
| Item | Value |
|---|---|
| `kernel.apparmor_restrict_unprivileged_userns` | 1 (unchanged from preflight) |
| bwrap / socat | bubblewrap 0.9.0 / socat 1.8.0.0 |
| `claude` on PATH | 2.1.312 |
| Claude seccomp-helper AppArmor profile | operator reports it is installed; the profile was not independently confirmed by this run |

## Execution context (why this is not a valid qualification)
The harness was run from the worker's own Bash tool, which is already wrapped in an outer Bubblewrap
(`--unshare-pid`, read-only root, private `/tmp`). The CLI's own sandbox was therefore nested. The operator
must rerun from an unsandboxed shell.

## Command
`PARROT_TEST_REAL_LLM=1 PARROT_NATIVE_QUAL_CLI=path PYTHONPATH=packages/ai-parrot/src pytest -q -rs packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py`
Result: 4 failed, 1 passed, 2 skipped, 1 xfailed (58.7 s). Sanitized records: `artifacts/logs/feat-768/*.json`.

## Per-scenario
| Scenario | Verdict | Evidence |
|---|---|---|
| filesystem-matrix | FAIL | `canaries_unchanged` false for primary, home, venv, venv_alias, rtk (all contain `BAD`); settings sha256 `f73fea36…bbcbee1a` |
| file-tool-bypass | FAIL | canary changed |
| settings-widening | FAIL | canary changed |
| retry-failure | FAIL | canary changed |
| rewrite/child boundary, git-controls | NOT RUN (skipped: "strict native sandbox did not start a workload") | — |
| egress | see `egress.json`; not independently reviewed |

A scenario that skipped or failed is not a pass (AC10). Ledger: `issue:94a4fa450148` (vulnerability, major).

## Open
1. Decide whether this is a real enforcement gap or a nesting artifact — rerun both executables (`path`, `bundled`)
   from an unsandboxed operator shell.
2. Confirm the AppArmor profile name and that strict start succeeds.
3. TASK-4891 stays pending; TASK-4892 stays blocked. The feature must not merge on this evidence.
