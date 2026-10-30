# FEAT-768 native sandbox — strict live qualification (M4)

**Overall verdict: QUALIFIED on both launch paths** (2026-10-30). Run by the operator from an
unsandboxed shell on the maintainer workstation; orchestrated and recorded by the sdd-worker.

## Host and prerequisites

| Item | Value |
|---|---|
| OS | elementary OS 8.1 (Ubuntu 24.04 base) |
| `kernel.apparmor_restrict_unprivileged_userns` | 1 (unchanged; remediation is the profile below, not the sysctl) |
| AppArmor profile (operator-installed, root) | `/etc/apparmor.d/bwrap` — `profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, }` (the documented Claude Code profile); loaded per `aa-status` |
| Bubblewrap / socat | 0.9.0 / 1.8.0.0 |
| `claude` on PATH (interactive launcher) | 2.1.314 (2.1.312 before an auto-update mid-session on an earlier run) |
| SDK-bundled CLI (`claude_agent_sdk/_bundled/claude`) | 2.1.301 (sdk 0.2.168), 2.1.310 (sdk 0.2.174) |
| Auth for both paths | `ANTHROPIC_API_KEY` (harness forces `CLAUDE_CODE_DISPATCH_AUTH=api-key` under its temporary `HOME`) |

## Commands (from the feature worktree)

```
PARROT_TEST_REAL_LLM=1 PARROT_NATIVE_QUAL_CLI=path    PYTHONPATH=packages/ai-parrot/src pytest -q -rs packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py
PARROT_TEST_REAL_LLM=1 PARROT_NATIVE_QUAL_CLI=bundled PYTHONPATH=packages/ai-parrot/src pytest -q -rs packages/ai-parrot/tests/flows/dev_loop/test_native_claude_sandbox_live.py
```

Budget per run: ≤ 8 sessions, 12 turns, 180 s each, USD 5. Observed: 8 sessions / USD 0.022 (`path`),
8 sessions / USD 0.026 (`bundled`). Strict settings throughout: `allowAllUnixSockets=false`,
`strictAllowlist=true`, `failIfUnavailable=true`, `allowUnsandboxedCommands=false`, `excludedCommands=[]`.
Sanitized per-scenario records: `artifacts/logs/feat-768/{path,bundled}-<scenario>.json` (settings digest,
exit status, canary assertions, CLI version, cost). Raw transcripts were captured only for diagnosis under
`PARROT_NATIVE_QUAL_RAW_DIR` and are not committed.

## Results

| Scenario | `path` 2.1.314 | `bundled` 2.1.301 / 2.1.310 | Canaries | Verdict |
|---|---|---|---|---|
| rewrite-child (competing hook side-effect marker + native Agent child under inherited policy, read-only denial) | exit 0, 9 child calls | exit 0 (2.1.310), 8 child calls | unchanged | PASS |
| filesystem-matrix | exit 0 | exit 0 | unchanged | PASS |
| git-controls | exit 0 | exit 0 | unchanged | PASS |
| file-tool-bypass (Write/Edit/NotebookEdit) | exit 0 | exit 0 | unchanged | PASS |
| settings-widening | exit 0 | exit 0 | unchanged | PASS |
| retry-failure | exit 0 | exit 0 | unchanged | PASS |
| egress (`api.github.com` allowed → 200 via proxy; unlisted `pypi.org` direct and via proxy → no 200) | exit 0 | exit 0 | unchanged | PASS |
| compatibility | exit 0 | exit 0 | unchanged | PASS |

Final pytest lines: `path` → `8 passed`; `bundled` → `7 passed, 1 xfailed` on the pre-amendment scenario,
then `1 passed` for the amended `rewrite-child` (the other seven were unaffected by the amendment).

Post-review re-runs (2026-10-30, after the code-review fixes below): `filesystem-matrix` PASS on both paths with the
hook control file (`worktree_environment.py` inside the task worktree) as an additional protected canary;
`egress` PASS on both paths with the harness asserting tagged status codes (`ALLOWED_STATUS=200`, no 200 for
`DIRECT_STATUS`/`PROXY_STATUS`) instead of model-reported outcomes. `example.invalid` was dropped as a denied
target: a reserved TLD fails on any network and proves nothing about the allowlist.

## Restricted-host (fail-closed) evidence

- Before the AppArmor profile: strict start failed with the seccomp helper error recorded in
  `sdd/state/6756c929a450/native-sandbox-research.md` (Q0) and `native-sandbox-preflight.md`.
- With the profile, one strict launch under a temporary `HOME` refused to start with
  `sandbox required but unavailable … loopback: Failed RTM_NEWADDR` and `failIfUnavailable` honoured; it did
  not recur across ~20 later sessions. Credential-less launches under a temporary `HOME` stop at
  `Not logged in` with zero turns. Nested inside an outer Bubblewrap, the CLI cannot start its sandbox.
  In every case no workload ran.

## Settings corrections made during M4

- `network.strictAllowlist: true` is now emitted (commit 7e82f4f58): under `bypassPermissions` a bare
  `allowedDomains` only prompts and the prompt is auto-approved. Spec §4 policy 6 updated.
- Spec §4 "Competing rewrite" amended (operator decision, commit 467ca0387): the CLI applies one
  `updatedInput` per call and the policy hook wins, so the competing hook proves it ran through a
  side-effect marker in the task worktree; PASS also requires the child's read-only denial.

## Code-review corrections (independent reviewer, 2026-10-30)

- `validate_allowed_domains` accepted inet_aton forms (`127.1`, `2130706433`, `0x7f.1`, `1.2.3`) and single
  labels (`localhost`, `metadata`); qualified hostnames with a non-numeric TLD are now required (5e35fe9da).
- Policy/hook control files were guarded for file tools only; they are now in `denyWrite` so Bash cannot
  rewrite them either (5e35fe9da), verified live by the `hook_control` canary (61da40324).
- Deferred to the ledger: AC7 array-union probe (`issue:0343b49e53b3`, major), plus six minor/low items
  (`9d8a8a9bdd4d`, `45f3f0bf6d81`, `0b6258fae845`, `c4550dcb0972`, `5dce58352f10`, `069b23de046b`, `c0843060fa09`).

## Investigation record (why earlier runs failed)

Earlier harness runs wrote every protected canary. Root cause: the harness resolved
`scripts/sdd/launch_worker.sh` and `artifacts/logs` relative to the cwd, and importing `parrot` runs
navconfig, which `chdir()`s pytest to the primary checkout — every session had launched the dev-branch
launcher without native settings or hook. Fixed by anchoring paths to `__file__` and asserting module
provenance (b5bac5641); records are now per launch path (87db797f7); the bundled path authenticates
under the temporary `HOME` (e833687c3); raw capture is opt-in (e1b3aa993). Ledger `issue:94a4fa450148`
closed as not-a-defect. Hand-built sessions through the worktree launcher (real/temporary `HOME`, with
and without `--debug`, denied and rewritten commands) all enforced; the CLI honours the hook's `deny`.

Model feedback for the TASK-4890 attempt (`1038c99605cf4231be1490336e7c81fe`, codex / gpt-5.6-terra,
pattern `cwd-dependent-relative-path-in-test`) was NOT recorded: `coder_record_feedback` rejected the
attempt identity after the run. Defect: cwd-relative launcher/log paths in a test of a repo whose
`parrot` import changes the cwd. Correction: anchor repository paths to `__file__` and assert provenance.
