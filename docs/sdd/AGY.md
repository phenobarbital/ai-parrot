# SDD in Google Antigravity CLI (AGY)

How the SDD skills and agents run under `agy`. Codex uses `docs/sdd/CODEX.md`; Claude Code needs neither.

## Antigravity Adaptation Contract

The shared `.agents/skills/sdd-*` skills and `.agents/agents/*` assets are written with Claude-style primitives.
Under `agy` apply the mappings below; everything else in a skill is unchanged.

### 1. Tool and model mapping

| Claude / skill wording | Antigravity equivalent |
|---|---|
| `Bash` | `run_command` |
| `Read` | `view_file` |
| `Write` / `Edit` | `write_file` / `edit_file` |
| `Agent(...)` | `invoke_subagent(TypeName, Role, Prompt, Model, Workspace)` |
| `TaskStop` | `manage_subagents(Action="kill")` (`list` and `kill_all` also exist) |

- `subagent_type: "fork"` maps to `TypeName="self"` only. Do not substitute `research`: it is a different agent
  type with a different tool set and would not inherit the current context.
- `Model` accepts only `inherit`, `flash_lite`, `flash` or `pro`; any other value is rejected by the binary.
  Map `haiku` to `flash` and every other value (`sonnet`, `opus`, a full model id) to `inherit`. Never pick `pro` or
  `flash_lite` automatically; an operator chooses those explicitly.

### 2. Worktree commands across fresh shells

Every `run_command` starts a fresh bash session: `cd`, exported variables and venv activation do not persist
between calls. A skill step that does `cd "$WT"` in one call and runs bare commands in the next would act on the
main checkout. Therefore:

- use an absolute path in every call, or assign and use the worktree in the same call (`WT=<abs> && cd "$WT" && ...`);
- pass the same absolute path as `Workspace` to `invoke_subagent`;
- never rely on a previous call's `cd`, variables or activation.

<!-- agy-fresh-shell-example -->
```bash
WT=/abs/path/to/worktree && cd "$WT" && git rev-parse --show-toplevel
```

<!-- agy-fresh-shell-example -->
```bash
git -C /abs/path/to/worktree status --short
```

### 3. Background work is reactive

There are no monitors. After starting background work, check its status on the next turn (read its output or call
`manage_subagents(Action="list")`) instead of waiting for a notification.

### 4. Approval semantics

The hook answers verified on agy 1.4.12 and 1.5.3:

| Hook answer | Default mode, headless (`agy -p`) | `--dangerously-skip-permissions` |
|---|---|---|
| `allow` (with or without overrides) | ignored; runs only if a `permissions.allow` rule matches, otherwise soft-denied | runs |
| `ask` | neutral; rules decide | runs |
| `force_ask` | prompts (soft-denied headless) even when a rule matches | **runs** |
| `deny` | blocked: `tool call denied by pre-tool hook: <reason>`; the agent continues | blocked the same way |

- `overwrite` rewrites the executed `CommandLine` with both `allow` and `ask`, and permission rules are evaluated
  against the **rewritten** command: a rewrite to a command no rule covers is soft-denied.
- Under `--dangerously-skip-permissions` only `deny` stops a call.
- The unattended worker sets `PARROT_SDD_AGY_UNATTENDED=1`: every `force_ask` becomes `deny` (reason prefixed
  `unattended:`) and commands are wrapped in Bubblewrap.
- Unattended, a `run_command` whose `Cwd` resolves outside the checkout is denied (attended, it answers `ask`).
- A workspace the hook cannot resolve to a checkout root has no worktree guard to apply, so every `run_command`
  is denied: the hook fails closed outside a Git checkout.
- `PARROT_ALLOW_DANGEROUS=1` is the operator escape hatch: attended, it makes the hook answer `ask` for everything.
  It is ignored when `PARROT_SDD_AGY_UNATTENDED=1`, so a value inherited from the launching shell never disarms
  an unattended worker. The launcher never sets it.
- Interactive sessions use the managed allow-rules the installer merges into the agy settings, plus operator
  approval; the hook only denies or asks.
- **Only `parrot sdd launch worker <FEAT-ID> --host google` is a supported unattended mode.** A hand-started
  `agy --dangerously-skip-permissions` lets `force_ask` calls through.
- `--mode auto` is account-gated: on accounts without it, `agy` prints a notice and silently continues in the
  default mode. SDD never passes it by default.

### 5. Installation

Install the official build:

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

It installs `~/.local/bin/agy` without sudo, verifies a checksum and self-updates. Settings live at
`~/.gemini/antigravity-cli/settings.json`.

The community `antigravity-cli` snap is unsupported: under its confinement there is no project Python
interpreter, no `bwrap`, no `ssh`, and `~/.gitconfig` is invisible. Every Google launch refuses an `agy` that
resolves to the snap and prints the command above.

### 6. Re-verification

The facts above were verified on agy 1.4.12 and 1.5.3. After an update that touches hooks or permissions, re-run
the hook probes: register a logging `PreToolUse` hook that answers `deny` for one chosen command, run that command
headless in both default mode and `--dangerously-skip-permissions`, and confirm the call is blocked and the
payload shape (`toolCall`, `workspacePaths`) is unchanged.
