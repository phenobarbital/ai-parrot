# FEAT-768 native sandbox — preflight probes (open-question resolution)

Date: 2026-10-29. Purpose: answer spec §8 open questions with evidence before tasking.
**This is NOT the M4 qualification report.** Every run below used
`network.allowAllUnixSockets: true`, because strict mode cannot start on this host until the
operator installs the AppArmor profile (see Q1). Strict re-runs remain an M4 gate.

## Host and executables

| Item | Value |
|---|---|
| OS | elementary OS 8.1 (Ubuntu 24.04 base) |
| `kernel.apparmor_restrict_unprivileged_userns` / `unprivileged_userns_clone` | 1 / 1 |
| Bubblewrap / socat | `/usr/bin/bwrap` 0.9.0 / `/usr/bin/socat` 1.8.0.0 |
| Interactive CLI (`claude` on PATH, `~/.local/bin/claude`) | 2.1.312 |
| Programmatic CLI (bundled in `claude-agent-sdk` 0.2.168, `_bundled/claude`) | 2.1.301 |
| AppArmor profiles present | `bwrap-userns-restrict-patched` only (none for Claude's seccomp helper) |

Strict mode on this host fails closed with `apply-seccomp: write /proc/self/setgroups ... Permission
denied` (recorded in `sdd/state/6756c929a450/native-sandbox-research.md`, Q0). That is the
restricted-host failure evidence AC10 asks for.

## Harness

Each run: `claude -p <probe> --model haiku --max-turns 12 --setting-sources <src> --settings <json>
--permission-mode bypassPermissions --output-format stream-json --verbose`, 180 s timeout, cwd a fresh
`git init` project in the session scratchpad. Base CLI settings: `sandbox.enabled`,
`failIfUnavailable: true`, `allowUnsandboxedCommands: false`, `excludedCommands: []`,
`allowAllUnixSockets: true`. Canary directory `~/.nsbx-canary-768` (removed afterwards, still empty at
the end of every run). Competing hook: a `PreToolUse` command hook that logged the payload
(`cwd`, `tool_name`, `agent_id`, `agent_type`, command) and rewrote every Bash command to
`echo REWRITTEN_MARK; <command>`. 7 sessions, about USD 0.03 total.

## Q2 — native Agent child inheritance (runs A on 2.1.312, A2 on bundled 2.1.301)

| Observation | 2.1.312 | 2.1.301 |
|---|---|---|
| Child Bash went through the competing rewrite (`REWRITTEN_MARK` in result) | yes | yes |
| Child write to canary outside allowances | read-only | read-only |
| Child write to a `filesystem.allowWrite` dir (via `cd <dir> && touch`) | writable | writable |
| Nested `bwrap` in child | ENOSPC, failed | not run |
| Parent write to canary | read-only | not run |
| `PreToolUse` fires for child tool calls, with `agent_id` / `agent_type` set | yes | yes |
| Hook payload `cwd` for child calls | parent session cwd | parent session cwd |
| Child shell start directory (`pwd`) | parent session cwd | parent session cwd |
| `cd` persists to the child's next Bash call | no (`pwd` back at session cwd) | not run |

Conclusion: the sandbox and the retained hook both reach native children. The child has no task cwd
of its own: neither the payload nor the shell knows about the coder's sub-worktree.

## Q3 — can project/local settings widen the CLI-injected policy? (2.1.312, `--setting-sources project,local`)

| Run | Project/local setting | CLI settings | Result |
|---|---|---|---|
| BC | project `filesystem.allowWrite: [canary/bdir]`, `excludedCommands: ["mkdir *","mkdir:*"]` | explicit empty arrays | write blocked; `mkdir` stayed sandboxed (read-only) |
| D | local `enabled: false`, `allowUnsandboxedCommands: true`, `failIfUnavailable: false` | strict | still sandboxed |
| E | project `network.allowedDomains: [example.com]` | `allowedDomains: [example.org]` | `example.org` 200; `example.com` blocked (curl 35) |
| CTL | project: same `allowWrite` + `excludedCommands` + `allowedDomains` | strict flags, **no** path/exclusion/domain keys | all three blocked |
| CTL2 | as CTL plus a project `PreToolUse` hook | as CTL | hook fired (project file loaded); write still blocked |

Conclusion: on 2.1.312, with a CLI `sandbox` object present, project/local `sandbox` keys did not widen
paths, exclusions or domains, nor disable the sandbox, even when the CLI omitted the keys. The
mechanism (project sandbox keys ignored vs. the CLI `sandbox` object replacing them) was not isolated.
The bundled 2.1.301 CLI was not tested for Q3.

## 2026-10-30 — AppArmor profile installed; first strict-mode runs

Operator action (root, outside the repo): the upstream recipe from
<https://code.claude.com/docs/en/sandboxing> was installed as `/etc/apparmor.d/bwrap`
(`profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, include if exists <local/bwrap> }`,
`abi <abi/4.0>`) and loaded at 01:20 (`apparmor="STATUS" operation="profile_load" name="bwrap"` in the
kernel log). `apparmor.service` is enabled, so the profile persists across reboots. The earlier
`bwrap-userns-restrict-patched` / `unpriv_bwrap` profiles were removed. Sysctls unchanged
(`apparmor_restrict_unprivileged_userns = 1`). Inside the sandbox, `/proc/self/attr/apparmor/current`
reads `bwrap (unconfined)` on both executables, and bwrap no longer transitions to `unprivileged_userns`
(which is what denied the seccomp helper's `setgroups` write in Q0).

Harness as above but **strict**: `failIfUnavailable: true`, `allowUnsandboxedCommands: false`,
`excludedCommands: []`, **no** `allowAllUnixSockets`; `--permission-mode bypassPermissions`,
`--setting-sources local`, haiku, fresh `git init` cwd in the scratchpad. 9 sessions, about USD 0.03.
Canary dirs (`~/.nsbx-canary-768-*`) were empty afterwards and removed.

| Check | PATH `claude` 2.1.312 | bundled 2.1.301 (`claude_agent_sdk/_bundled/claude`) |
|---|---|---|
| Sandbox starts in strict mode | yes | yes |
| `touch` canary under `$HOME` outside allowances | read-only | read-only |
| `connect()` to `/run/dbus/system_bus_socket` (AF_UNIX) | `EPERM` — seccomp filter active | `EPERM` — seccomp filter active |
| `unshare -U true` inside the sandbox | `EPERM` (nested userns blocked) | **succeeds** — nested userns NOT blocked |
| `network.allowedDomains: ["example.org"]` alone, unlisted hosts | google / httpbin `CONNECT 200` | not run |
| … plus `network.strictAllowlist: true` | unlisted → `CONNECT 403` "host is not on the allow list" | same |
| `strictAllowlist: true` + `allowedDomains: []` | every host denied | not run |
| `deniedDomains: ["*"]` + `allowedDomains: ["example.org"]` | **everything** denied, example.org included | not run |

Findings:

1. **The AppArmor prerequisite is met** on this host for both executables (policy 9). The restricted-host
   failure (Q0) is reproducible only by removing the profile again.
2. **`allowedDomains` is not a deny list.** Hosts outside it *prompt*, and `bypassPermissions` (the
   dispatcher's mode) auto-approves the prompt — so without `strictAllowlist` the sandbox proxy lets
   every host through. The compiler (TASK-4885) must emit `network.strictAllowlist: true`; the
   docs scope it "User or managed", but it was honored when passed via `--settings` on both CLIs.
   `deniedDomains: ["*"]` is not a substitute: it overrides the allowlist.
3. **Correction to Q3 Run E above.** "example.com blocked (curl 35)" was a false positive: example.com
   resets the TLS handshake from this host *outside* the sandbox too (curl rc 35, `Connection reset by
   peer`), while example.org and www.google.com answer 200. Run E therefore showed nothing about the
   allowlist; the project-vs-CLI precedence question for `allowedDomains` is **re-opened** and must be
   re-tested with `strictAllowlist` and a reachable control host. Use www.google.com / httpbin.org as
   controls, never example.com.
4. **Nested user namespaces are only blocked from 2.1.305** (`allowNestedUserNamespaces` exists from
   that version). The bundled 2.1.301 lets a sandboxed command `unshare -U`, so AC claims about
   "nested bwrap fails" hold for the interactive path only until `claude-agent-sdk` bundles ≥ 2.1.305.
   TASK-4891 must record this per executable.
