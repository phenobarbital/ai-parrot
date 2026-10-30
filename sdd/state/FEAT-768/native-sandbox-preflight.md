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
