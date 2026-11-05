---
title: "Native Claude sandbox for SDD sessions (FEAT 768)"
---

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

## Tmux feature completion notifications

New `parrot sdd launch worker FEAT-ID --tmux` sessions automatically enable
best-effort host desktop notifications. The feature worker records completion
only after its tasks, child settlement, review/deferred findings and successful
feature-branch push. A host Stop hook consumes that explicit receipt; ordinary
pauses and task-scoped workers do not announce completion. This is worker
completion, not merge approval or successful `/sdd-done` closeout.

Claude Code and its pane remain open. Delivery needs `notify-send` and a usable
desktop session on the same host; SSH/headless hosts may show nothing. Nothing
is installed. Missing services and delivery failures never fail the worker.
One launch permits at most one attempt, including failed delivery; reattach does
not install new hooks or resend. Updating an existing installation's managed
worker asset is required to obtain the receipt instruction; launch a new session.

The launch captures only PATH, HOME, DISPLAY, WAYLAND_DISPLAY,
DBUS_SESSION_BUS_ADDRESS and XDG_RUNTIME_DIR from the operator environment.
Host delivery runs outside the worker's Bash sandbox; sandbox permissions and
socket grants stay unchanged. A changed HEAD invalidates a recorded receipt.

## Supported launch paths

| Path | How | Policy source |
|---|---|---|
| Interactive worker | `parrot sdd launch worker <FEAT-ID\|slug> [--tmux] [--detach] [--sandbox MODE] [--sandbox-allow-domain HOST]... [--no-upstream] [-- claude args]` | Resolves the feature, runs `ensure_worktree`, prepares the upstream (refusing a diverged branch unless `--no-upstream`), then launches `run <FEAT-ID>`. `--tmux` uses session `sdd-<feat-id>-<slug>` (lower-cased, e.g. `sdd-feat-2-simple-agent`, so FEAT ids that restart in every repository never collide on the shared tmux server; a live pre-fix `sdd-<FEAT-ID>` session started inside this checkout is still reattached or refused); its `-e` options preserve the prepared `PARROT_SDD_*`, `PATH`, and virtual-environment variables in the tmux server. |
| Deprecated interactive alias | `scripts/sdd/launch_worker.sh [--sandbox-allow-domain HOST]... [claude args]` from inside the feature worktree | Prints a deprecation warning, then compiles policy for `$PWD` and passes it as `--settings` with `--agent sdd-worker --setting-sources project,local`. It remains for brief worktrees and direct current-worktree launches. |
| Dev-loop dispatcher (`ClaudeCodeDispatcher`, SDK-bundled CLI) | `ClaudeCodeDispatchProfile(subagent="sdd-worker" \| "sdd-coder", sandbox_allowed_domains=[...])` | compiled for the dispatch cwd; `PARROT_SDD_SANDBOX_BACKEND=claude-native` and a per-dispatch cache dir are set for the child |

A bare `claude --agent sdd-worker` is **not** a qualified native launch: it loads the `user` setting
source (competing hooks) and carries no compiled policy. Always start workers (features **and** briefs) with
`parrot sdd launch worker <FEAT-ID|KEY>`.

### Hook backends (`PARROT_SDD_SANDBOX_BACKEND`)

| Value | Behavior |
|---|---|
| unset (`auto`, default) | One wrapper that decides **when the command runs**: inside Claude Code's native sandbox it runs the command directly (`env` + bounded shell); outside it, through the legacy `bwrap` boundary. Exactly one branch runs and nothing runs unsandboxed. |
| `claude-native` (set by the launcher) | Never wraps in `bwrap`. The hook cannot see the sandbox, so it **trusts the launcher's backend variable** only beside the launcher markers it always exports with it (`PARROT_SDD_SANDBOX_ROOTS` and `PARROT_SDD_CACHE_DIR`; the dev-loop dispatcher sets both too). A hand-exported `claude-native` without them is downgraded to `auto`, so it runs natively inside the native sandbox and under Bubblewrap outside it, never unsandboxed. With the markers there is no runtime check: the variable is coordination metadata, the enforcement boundary is the native settings. The launcher exports the session-fixed variables (`UV_NO_SYNC`, `PYTHONDONTWRITEBYTECODE`, `PYTHONPATH` for the session worktree, `XDG_CACHE_HOME`, `UV_CACHE_DIR`), so a plain command passes through **unchanged**; the hook rewrites only when the guard/RTK changed the command, the environment differs (a sub-worktree task cwd gets its own `PYTHONPATH`), the launch is degraded (banner), or the call carries an explicit `timeout`/`run_in_background` (the in-sandbox `timeout` backstop is kept only there; a plain call is bounded by the host). A hand-written `bwrap …` command is denied (`native sandbox is active; resend the command without the bwrap wrapper`). |
| `bubblewrap` (explicit opt-in) | The legacy wrapper, always. |

The hook process runs outside the sandbox and cannot see it, so the wrapped command checks for itself:
`SANDBOX_RUNTIME=1` and, on Linux, a `/proc/self/uid_map` that is a single line not starting with `0 0`.
macOS (Seatbelt) has no `uid_map` and relies on `SANDBOX_RUNTIME` alone; that platform is not certified.
A nested `bwrap` inside the native sandbox can never work: the policy sets `allowNestedUserNamespaces: false`,
so `bwrap` fails with `No permissions to create new namespace`.

**Auto mode.** Claude Code's auto mode reviews a Bash call before hooks run. When the hook rewrites it, the
review is refused once and the agent must resend the rewritten text **verbatim**; the hook recognises its own
output and passes it through unchanged, so the resend is approved. Each rewritten call therefore costs one extra turn.

## Sandbox mode

The SDD flow runs in many consumer repositories whose developers cannot all harden their hosts at once
(FEAT-633). The native sandbox therefore has an explicit, auditable mode (spec §4 policy 10, AC13):

| Mode | Native sandbox can start | Cannot start |
|---|---|---|
| `required` (**default**) | strict settings | launcher exit 1 with the probe reason; dispatcher `DispatchExecutionError` |
| `preferred` | strict settings (identical to `required`) | **degraded** launch: hooks only, no `sandbox` block, no OS write boundary — declared, never silent |
| `off` | never compiles the `sandbox` block (ephemeral CI, disposable containers); hooks still apply | — |
| `legacy` | Linux Bubblewrap hook boundary; native sandbox disabled, filesystem isolation only and no network isolation | fails closed without working `bwrap` or off Linux |

Resolution order: `PARROT_SDD_SANDBOX_MODE` (empty or whitespace counts as unset) → `[tool.parrot.sdd]
sandbox = "required" | "preferred"` in the repository root `pyproject.toml` → `required`. **`off` and `legacy`
can only be set through `PARROT_SDD_SANDBOX_MODE` or `--sandbox`**: the worktree's `pyproject.toml` is writable by
the sandboxed session itself, so letting it select either would be a self-disable path; a repository may go as far as `preferred`,
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
`failIfUnavailable`. `off` never runs the probe; `legacy` probes Bubblewrap before launch.

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
- Rejected caller options (the launcher owns them): `--settings`, `--add-dir`, `--dangerously-skip-permissions`,
  `--plugin-dir`, `--mcp-config`, `--agents`, any `--agent` other than `sdd-worker`, a `--setting-sources`
  value containing `user`.
- Exit codes: **1** — a host prerequisite is missing (`claude`, `bwrap` or `socat` not on `PATH`);
  **2** — the caller's input violates the policy (rejected option, invalid domain, or the cwd is not a
  linked Git worktree: the primary checkout and non-repositories are refused). Any other status is
  the CLI's own.
- The hook that rides with the settings runs under the launching interpreter (`sys.executable`) with
  `PARROT_SDD_SANDBOX_BACKEND=claude-native` and `PARROT_SDD_SANDBOX_ROOTS=<worktree>:<common git dir>:<primary>`.
  The roots are frozen at launch so a session cannot steer the hook by rewriting its own `.git` marker; a
  cwd outside the frozen root (a pool sub-worktree) derives its own roots. An unset backend means the legacy
  Bubblewrap mode — unless the launcher's other markers (`PARROT_SDD_CACHE_DIR`, `…_ROOTS`, `…_DEGRADED`) are
  present, in which case the hook denies every call instead of silently falling back; any other backend value
  denies too.

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

## Platforms

- **Linux / WSL2:** qualified only with the documented Bubblewrap, socat, and AppArmor prerequisites. `required`
  fails closed when the native sandbox probe fails; `legacy` requires a working Linux Bubblewrap boundary.
- **macOS:** the Seatbelt backend is implemented but **not certified**. A strict launch emits
  `launch_worker: NOTICE macOS Seatbelt backend is implemented but not certified (see wiki/sdd-tooling/dev_loop/claude-native-sandbox.md)`.
- **Native Windows:** no Claude Code sandbox is available. `required` refuses with `native Windows has no Claude Code sandbox; run the worker inside WSL2, or set PARROT_SDD_SANDBOX_MODE=preferred for a degraded (hook-only) launch`; `preferred` degrades to the declared hook-only mode, and `--tmux` refuses because it is unavailable on native Windows.
- **Legacy mode without Bubblewrap:** it refuses with `launch_worker: native sandbox unavailable (legacy mode needs a
  working Bubblewrap: missing prerequisite(s): bwrap); mode=legacy refuses to start`.

## Network

- Default: no egress. The compiled settings always carry `network.strictAllowlist: true` — under
  `bypassPermissions` a bare `allowedDomains` list only prompts, and the prompt is auto-approved.
- Grants: `sandbox_allowed_domains` on the dispatch profile or `--sandbox-allow-domain` on the launcher.
  Exact hostnames, lower-cased and de-duplicated; URLs, wildcards, ports and IP literals are rejected.
  Redirect targets need their own entry.
- Launcher defaults live in `[tool.parrot.sdd]` of the **primary checkout's** `pyproject.toml`:
  `sandbox_allowed_domains = ["api.github.com"]` and `gh_token = true`. They are read from the primary
  checkout only, never the worktree, because the sandboxed session can write its own worktree
  `pyproject.toml`. Config domains are unioned (order-stable, de-duplicated) with `--sandbox-allow-domain`.
  Malformed config (non-list, invalid host, non-bool `gh_token`) refuses to launch with exit 2.
- Policy: GitHub is reachable **only through `gh`** via `api.github.com`. `github.com`, git-over-HTTPS and
  SSH stay blocked, so the session cannot `git push`. Raw SSH is not supported in v1.
- `GH_TOKEN`: `gh`'s keyring is a D-Bus Unix socket, which the sandbox blocks (`allowAllUnixSockets: false`),
  so with `gh_token = true` the launcher runs `gh auth token` **on the host** and puts the result in the
  worker's environment (never in argv, never printed). A token already in `GH_TOKEN` wins. If it cannot be
  obtained the launcher prints `launch_worker: WARNING gh_token is enabled but no token could be obtained
  (<reason>); launching without GH_TOKEN` and continues. `--no-gh-token` skips resolution.
- **Token scope warning:** the agent can read `GH_TOKEN` and it carries `gh`'s full scopes — every repository
  the logged-in account can reach. To grant less, log `gh` in with a narrower token or pass `--no-gh-token`.
- Unknown destinations never trigger an unattended authorization prompt and are never auto-learned.
- tiktoken: the session exports `TIKTOKEN_CACHE_DIR=<scratch root>/parrot-sdd-cache/shared-<uid>/tiktoken`
  (tiktoken's default `$TMPDIR/data-gym-cache` is private and empty in the sandbox, so every token count
  tried `openaipublic.blob.core.windows.net` and was denied). The launcher seeds it on the host — copying the
  host's cached encodings, else downloading `cl100k_base` with a 15 s timeout — so no domain grant is needed.
  Best effort: a cold cache only means callers use their fallback token estimate.

## Git inside a native session

1. The **host** sets the upstream before launch (`git push -u origin <branch>` from a normal shell,
   or the dispatcher's own setup): Git `config` is read-only inside the session, so `-u` fails there.
2. The session commits normally but **never pushes** (no route to `github.com`). Push, PR and cleanup
   happen through `/sdd-done`, which must be **run on the host** — a normal shell or Claude session, not
   the sandboxed sdd-worker. Running `/sdd-done` from inside the worker (pre-FEAT-633 practice) no longer works.
3. `config`, `config.worktree`, hooks and lock files stay read-only by design; worktree administration
   under the primary checkout's `.claude/worktrees/` remains possible.
4. A native `sdd-coder` seat prefixes every Bash command with `cd <its sub-worktree> && …`: `cd` does
   not persist between tool calls, and the hook uses that exact prefix to pick the task cwd for the
   scope guard and `PYTHONPATH`. Known limitation: only that exact form is recognised — `cd X; …`,
   `cd\tX && …` and `pushd` fall through to the session cwd (any other leading `cd` form is denied). This
   affects the test-scope guard only; the OS boundary does not depend on cwd.
5. Sibling linked worktrees' administration directories under `.git/worktrees/*` are read-only: the
   common Git directory stays writable so this worktree can commit, but another worktree's
   `config.worktree`/`hooks` are not this session's business.

## Failure handling and rollback

- `sandbox required but unavailable` / `failIfUnavailable`: the host is not qualified (missing
  prerequisite, denied namespaces). Fix the host; **never restart the session unprotected**, never set
  `allowUnsandboxedCommands`, never add `excludedCommands`, never request `dangerouslyDisableSandbox`.
- Hook denials (`Native sandbox policy forbids …`, `A leading cd must have the exact form …`) are the
  policy working; rewrite the command or path, do not widen the policy.
- Project/local `.claude/settings*.json` cannot loosen the compiled policy (qualified: settings-widening
  scenario); a user-level source is excluded on purpose.
- Probe gotcha: reproducing a denial by hand needs the launcher's environment
  (`PARROT_SDD_SANDBOX_BACKEND=claude-native`). Without it the hook wraps the command in its own nested
  Bubblewrap, which fails with `No permissions to create new namespace` — a harness artefact, not a policy bug.
- Roll back deliberately: `required` → `legacy` when the native sandbox misbehaves but Bubblewrap works →
  `preferred` when no OS boundary is available (the degraded state is declared) → code/deployment revert.
  There is no silent runtime fallback that turns protection off.
