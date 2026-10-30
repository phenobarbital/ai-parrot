# Native Claude sandbox for SDD sessions (FEAT-768)

The strict Claude Code sandbox is the enforcement boundary for `sdd-worker` and `sdd-coder`
sessions on the supported launch paths. The repository's PreToolUse hook
(`parrot/flows/dev_loop/worktree_environment.py --hook`) stays in the chain for the test-scope guard,
the RTK rewrite, the bounded shell and the file-tool checks, but it no longer wraps commands in its own
Bubblewrap: nested bwrap is not used, and the policy is compiled by
`parrot/flows/dev_loop/native_claude_sandbox.py` from the linked worktree the session runs in.

## What it protects — and what it does not

- Bash commands and their descendants: writes are limited to the task worktree, the common Git
  directory, the primary checkout's `.claude/worktrees/` and `.parrot/ledger/`, and the per-user
  scratchpad (`/tmp/claude-<uid>`). Everything else, including the primary checkout, `$HOME`, the
  shared `.venv` (and any symlink alias to it), RTK's data directory, Git `config`/`hooks`/
  `config.worktree`, is read-only. Network egress is denied unless a host is explicitly allowed.
- File tools (`Write`/`Edit`/`MultiEdit`/`NotebookEdit`) are checked by the retained hook against the
  same allow/deny lists and the policy/hook control files.
- **Trusted surfaces that run outside the sandbox**: hooks themselves, MCP servers, plugins and LSP
  servers. The sandbox does not confine them, and it offers **no secret confidentiality**: anything
  readable by the user is readable by the session. These are spec non-goals, not gaps to be fixed by
  configuration.

## Supported launch paths

| Path | How | Policy source |
|---|---|---|
| Interactive worker | `scripts/sdd/launch_worker.sh [--sandbox-allow-domain HOST]... [claude args]` from inside the feature worktree | compiled for `$PWD`, passed as `--settings` with `--agent sdd-worker --setting-sources project,local` |
| Dev-loop dispatcher (`ClaudeCodeDispatcher`, SDK-bundled CLI) | `ClaudeCodeDispatchProfile(subagent="sdd-worker" \| "sdd-coder", sandbox_allowed_domains=[...])` | compiled for the dispatch cwd; `PARROT_SDD_SANDBOX_BACKEND=claude-native` and a per-dispatch cache dir are set for the child |

A bare `claude --agent sdd-worker` is **not** a qualified native launch: it loads the `user` setting
source (competing hooks) and carries no compiled policy.

## Sandbox mode

The SDD flow runs in many consumer repositories whose developers cannot all harden their hosts at once
(FEAT-633). The native sandbox therefore has an explicit, auditable mode (spec §4 policy 10, AC13):

| Mode | Native sandbox can start | Cannot start |
|---|---|---|
| `required` (**default**) | strict settings | launcher exit 1 with the probe reason; dispatcher `DispatchExecutionError` |
| `preferred` | strict settings (identical to `required`) | **degraded** launch: hooks only, no `sandbox` block, no OS write boundary — declared, never silent |
| `off` | never compiles the `sandbox` block (ephemeral CI, disposable containers); hooks still apply | — |

Resolution order: `PARROT_SDD_SANDBOX_MODE` (empty or whitespace counts as unset) → `[tool.parrot.sdd]
sandbox = "required" | "preferred"` in the repository root `pyproject.toml` → `required`. **`off` can only be
set through the environment variable**: the worktree's `pyproject.toml` is writable by the sandboxed session
itself, so letting it select `off` would be a self-disable path; a repository may go as far as `preferred`,
which on a host where the sandbox starts is the same as `required`. Any other value, a non-string value,
`[tool.parrot.sdd] sandbox = "off"` or an unreadable/malformed `pyproject.toml` fails the launch (exit 2 /
`DispatchExecutionError`).

```toml
[tool.parrot.sdd]
sandbox = "preferred"   # a developer workstation during the transition; ai-parrot keeps the default "required"
```

Availability is decided before launch by a cheap probe — `bwrap` and `socat` on `PATH`, then
`bwrap --unshare-user --unshare-pid --ro-bind / / true` with a 10 s timeout — cached for 60 s per process so a
long-lived dispatcher does not block on it for every launch. The probe is a weaker proxy than Claude's own
runtime (no network namespace); a false positive still fails closed because the strict settings carry
`failIfUnavailable`. `off` never runs the probe.

What a degraded launch looks like:

- launcher stderr: `launch_worker: WARNING native sandbox unavailable (<reason>); mode=<mode> launches DEGRADED (hook only, no OS write boundary)`
- dispatcher log: `native sandbox DEGRADED for <subagent> (mode=<mode>): <reason>` (no free-form telemetry field
  exists on `DispatchLabels`; the log line is the record)
- child environment: `PARROT_SDD_SANDBOX_BACKEND=claude-native` and `PARROT_SDD_SANDBOX_DEGRADED=1`
  (a marker inherited from the parent is cleared on strict launches)
- every Bash call in the session is prefixed by the hook with `[sdd] degraded sandbox: no OS write boundary` on stderr

Degraded keeps the test-scope guard, the RTK rewrite, the bounded shell and the native file-tool checks; it
does **not** stop Bash from writing anywhere the user can. The default flips to a hardened posture only by an
announced release once the FEAT-633 installer provisions the host prerequisites.

### `launch_worker.sh` reference

- Defaults: `--model sonnet`, `--setting-sources project,local`; both can be overridden, but
  `--setting-sources` must not include `user`.
- `--sandbox-allow-domain HOST` (repeatable, or `=HOST`): exact DNS hostnames only.
- Rejected caller options (the launcher owns them): `--settings`, `--add-dir`, any `--agent` other
  than `sdd-worker`, a `--setting-sources` value containing `user`.
- Exit codes: **1** — a host prerequisite is missing (`claude`, `bwrap` or `socat` not on `PATH`);
  **2** — the caller's input violates the policy (rejected option, invalid domain, or the cwd is not a
  linked Git worktree: the primary checkout and non-repositories are refused). Any other status is
  the CLI's own.
- The hook that rides with the settings runs with `PARROT_SDD_SANDBOX_BACKEND=claude-native`; an
  unset value means the legacy Bubblewrap mode, and any other value makes the hook deny every call.

## Host prerequisites and qualified matrix

Linux with Bubblewrap and socat on `PATH`, and — on Ubuntu 24.04-family hosts with
`kernel.apparmor_restrict_unprivileged_userns=1` — an AppArmor profile for `/usr/bin/bwrap`
(`profile bwrap /usr/bin/bwrap flags=(unconfined) { userns, }`, the one documented by Claude Code).
Installing it is a root action performed by the operator outside this feature; the feature never
mutates system security settings. Without it the strict sandbox refuses to start and no workload runs.

Qualified configuration (copied from `sdd/state/FEAT-768/native-sandbox-qualification.md`; a CLI or SDK
version change requires re-qualification):

| Item | Value |
|---|---|
| OS | elementary OS 8.1 (Ubuntu 24.04 base) |
| `kernel.apparmor_restrict_unprivileged_userns` | 1 (unchanged; the profile is the remediation, not the sysctl) |
| AppArmor profile | `/etc/apparmor.d/bwrap`, loaded per `aa-status` |
| Bubblewrap / socat | 0.9.0 / 1.8.0.0 |
| `claude` on PATH (interactive launcher) | 2.1.314 |
| SDK-bundled CLI | 2.1.301 (claude-agent-sdk 0.2.168), 2.1.310 (0.2.174) |
| Result | 8/8 live scenarios PASS on both paths, strict settings (`allowAllUnixSockets=false`, `strictAllowlist=true`) |

## Network

- Default: no egress. The compiled settings always carry `network.strictAllowlist: true` — under
  `bypassPermissions` a bare `allowedDomains` list only prompts, and the prompt is auto-approved.
- Grants: `sandbox_allowed_domains` on the dispatch profile or `--sandbox-allow-domain` on the launcher.
  Exact hostnames, lower-cased and de-duplicated; URLs, wildcards, ports and IP literals are rejected.
  Redirect targets need their own entry.
- HTTPS Git and `gh` need `github.com` and `api.github.com`. Raw SSH is not supported in v1.
- Unknown destinations never trigger an unattended authorization prompt and are never auto-learned.

## Git inside a native session

1. The **host** sets the upstream before launch (`git push -u origin <branch>` from a normal shell,
   or the dispatcher's own setup): Git `config` is read-only inside the session, so `-u` fails there.
2. The session commits normally and pushes with `git push origin <branch>` — never `-u`.
3. `config`, `config.worktree`, hooks and lock files stay read-only by design; worktree administration
   under the primary checkout's `.claude/worktrees/` remains possible (needed by `/sdd-done`).
4. A native `sdd-coder` seat prefixes every Bash command with `cd <its sub-worktree> && …`: `cd` does
   not persist between tool calls, and the hook uses that exact prefix to pick the task cwd for the
   scope guard and `PYTHONPATH`.

## Failure handling and rollback

- `sandbox required but unavailable` / `failIfUnavailable`: the host is not qualified (missing
  prerequisite, denied namespaces). Fix the host; **never restart the session unprotected**, never set
  `allowUnsandboxedCommands`, never add `excludedCommands`, never request `dangerouslyDisableSandbox`.
- Hook denials (`Native sandbox policy forbids …`, `A leading cd must have the exact form …`) are the
  policy working; rewrite the command or path, do not widen the policy.
- Project/local `.claude/settings*.json` cannot loosen the compiled policy (qualified: settings-widening
  scenario); a user-level source is excluded on purpose.
- Rollback is a code/deployment revert of the feature (the launcher and dispatcher wiring), or setting
  the mode back to `required`; there is no silent runtime fallback that turns protection off.
