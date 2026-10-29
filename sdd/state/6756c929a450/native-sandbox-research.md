# Native Claude Code sandbox as defense in depth — research (HOTFIX-6756c929a450-3)

Source: ledger `issue:6756c929a450`, fix option 3. Research only: no production change.

**Verdict: adopt-with-limits.** The native sandbox closes the hook race on its own: a command that
another `PreToolUse` hook rewrote still ran inside the sandbox. It cannot be *stacked* under our
Bubblewrap wrapper, though. It would have to **replace** the wrapper for Bash, and on this host it
only starts with a setting that weakens its socket filter. Follow-up: a ledger issue (see the end).

## Setup

- Date: 2026-10-29. `claude --version`: `2.1.312 (Claude Code)`. Host: Elementary OS 8.1 (Ubuntu 24.04
  base), `/usr/bin/bwrap`, `/usr/bin/socat` present.
- `kernel.apparmor_restrict_unprivileged_userns = 1`, `kernel.unprivileged_userns_clone = 1`.
- Every run: `claude -p "<probe>" --model haiku --setting-sources local --settings '<json>'
  --output-format stream-json --verbose < /dev/null` (harness: `run.sh` + `summarize.py` in the
  session scratchpad). Probes only `touch` an empty marker file. The three marker files Q4 created were
  removed afterwards.
- Docs consulted: <https://code.claude.com/docs/en/sandboxing> (settings keys, the retry rules,
  `allowNestedUserNamespaces`, the Ubuntu 24.04 AppArmor note).

Base sandbox settings used below (`BASE`):

```json
{"sandbox": {"enabled": true, "failIfUnavailable": true, "allowUnsandboxedCommands": false}}
```

## Q0 — Does the sandbox start on this host?

With `BASE` alone, **every** Bash call fails before the command runs:

```
apply-seccomp: write /proc/self/setgroups (nested userns is capability-restricted; caller must provide CAP_SYS_ADMIN): Permission denied
```

It fails closed: nothing runs, not even with `dangerouslyDisableSandbox` (see Q3).
The AppArmor userns restriction allows `bwrap` (a `bwrap-userns-restrict-patched` profile exists) but
not the seccomp helper. Adding `"network": {"allowAllUnixSockets": true}` makes the sandbox start, but
this turns off the Unix-socket blocking the seccomp filter provides. The other route the docs give is
an AppArmor profile change, which needs root on each host. **Not tried** (no root changes in this task).
All the runs below use `BASE` + `allowAllUnixSockets: true`.

## Q1 — Does a command rewritten by a `PreToolUse` `updatedInput` still run sandboxed?

**Yes.** A test hook (`rewrite_hook.py`, standing in for RTK's global hook) prefixed every Bash command
with `echo REWRITTEN;`. Probe: `touch /home/jesuslara/proyectos/ai-parrot/.probe_nsbx_q1b && echo WRITABLE || echo READONLY`
from a cwd outside the repo.

```
REWRITTEN
touch: no se puede efectuar `touch' sobre '/home/jesuslara/proyectos/ai-parrot/.probe_nsbx_q1b': Sistema de archivos de solo lectura
READONLY
```

`REWRITTEN` shows the hook's version ran, and it ran inside the sandbox (read-only, no file created).
The transcript's `tool_use.input` still shows the original command, so measuring the sandbox from the
transcript needs the tool *result*, not the input.

## Q2 — Does our bwrap wrapper work nested inside the native sandbox?

**No.** With `worktree_environment.py --hook` installed (same command as the agent files, absolute
path) and cwd = this worktree, probe `echo nested-ok`:

```
bwrap: Creating new namespace failed: nesting depth or /proc/sys/user/max_*_namespaces exceeded (ENOSPC)
```

Sandboxed commands may not create user namespaces. The docs' only fix is
`sandbox.allowNestedUserNamespaces: true`. The docs warn that this setting lets code from a sandboxed
command run outside the sandbox, a repository cannot turn it on, and they say to set it in
`~/.claude/settings.json`, which our sandboxed sessions no longer load. **So the two cannot be
stacked:** for Bash, a session uses either the native sandbox or our wrapper. Our hook's other parts
(test-scope guard, `rtk rewrite`, the file-tool write check) do not need the wrapper. They could stay as
a hook that rewrites the command but does not wrap it.

## Q3 — With `allowUnsandboxedCommands: false`, is there any unsandboxed retry path?

**None observed**, in the most permissive mode tested (`--permission-mode bypassPermissions`). The
model ran `touch …/.probe_nsbx_q3b`, got `Sistema de archivos de solo lectura`, and retried with
`"dangerouslyDisableSandbox": true`. The retry got the **same** read-only error, and no file was created.
The flag was ignored, as the docs say. Under Q0's broken setup the retry also failed with the same
seccomp error: it stayed sandboxed rather than falling back.

Not covered: `sandbox.excludedCommands` (any matching pattern runs fully outside) must stay empty.
Per the docs, command hooks, MCP servers, plugin monitors and LSP servers always run **outside** the
sandbox.

## Q4 — Can `filesystem.allowWrite` express worktree-management §4?

**Yes, for the paths tested.** Settings: `BASE` + `allowAllUnixSockets` +
`"filesystem": {"allowWrite": ["<main>/.git", "<main>/.claude/worktrees", "<main>/.parrot/ledger"]}`,
cwd = this worktree. One loop `touch`ed each path:

```
W  …/.claude/worktrees/fix-6756c929a450-sdd-sandbox-user-hook-isolation/.probe_q4
W  /home/jesuslara/proyectos/ai-parrot/.git/.probe_q4
W  /home/jesuslara/proyectos/ai-parrot/.parrot/ledger/.probe_q4
RO /home/jesuslara/proyectos/ai-parrot/.venv/.probe_q4
RO /home/jesuslara/proyectos/ai-parrot/.probe_q4
RO /home/jesuslara/.probe_q4
```

The cwd is writable by default. The listed paths were writable. The shared `.venv`, the rest of the
primary checkout, and `$HOME` were read-only. Not tested: the scratchpad root (`/tmp/claude-<uid>`),
and network isolation. The native sandbox cuts network access by default, so `git push`, `gh`,
`uv run` downloads and similar commands would need `network.allowedDomains`. One limit: granting
`<main>/.git` makes `.git/hooks/` and `.git/config` writable. That gives a way to run code outside the
sandbox the next time git runs unsandboxed. Our current wrapper has the same exposure. A real
config should deny-write `.git/hooks` and `.git/config` if git still works without them.

## Summary

| Question | Answer |
|---|---|
| Q0 starts on this host | Only with `network.allowAllUnixSockets: true` (or a root AppArmor change); otherwise fails closed |
| Q1 hook-rewritten command sandboxed | Yes |
| Q2 our bwrap nested inside | No (ENOSPC); stacking needs `allowNestedUserNamespaces`, which defeats the boundary |
| Q3 unsandboxed retry with `allowUnsandboxedCommands: false` | None observed, even in `bypassPermissions` |
| Q4 `allowWrite` expresses §4 | Yes for tested paths; `.git` grant needs hooks/config carve-outs; network untested |

## Recommendation

Adopt with limits, as a separate change: for sandboxed seats, pass native sandbox settings with
`--settings`, and turn the SDD hook into a hook that rewrites but does not wrap (guard + `rtk rewrite`
+ file-tool check) whenever the native sandbox is on. Prerequisites: decide how to handle the
seccomp / AppArmor host requirement, define the network allowlist, and add a test that a sandboxed
seat with a competing rewrite hook still cannot write the primary checkout. Until then, the user
setting-source exclusion (HOTFIX-6756c929a450-1/-2) is the guard.
