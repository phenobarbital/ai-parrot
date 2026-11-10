---
title: SDD on Google Antigravity (agy)
summary: How the SDD workflow, its hook guard and its sub-agents run under the agy CLI, attended and unattended.
---

# SDD on Google Antigravity (agy)

## Purpose

The SDD workflow runs fully on Google Antigravity CLI (`agy`) with both interactive and unattended modes. It uses the `parrot-sdd-permissions` hook for command validation, worktree environment protection, and file containment. The workflow supports all SDD operations including task decomposition, implementation, code review, and PR management through specialized sub-agents. See the Antigravity Adaptation Contract (`docs/sdd/AGY.md`) for detailed runtime adaptations.

## Public API

- `agy_verdict` — worktree-environment guard and file containment for one AGY event
- `evaluate` — the `parrot-sdd-permissions` hook decision (deny > force_ask > ask, unattended mapping)
- `launch_agy_worker` — the unattended worker launch
- `launch_session` — interactive brief/fix sessions
- `GoogleCodingDispatchProfile` — dispatcher seat profile

## Configuration & Parameters

- `parrot sdd install --host google` — installs the hook with matcher `run_command|write_file|edit_file`, allow-rules, and `--no-agy-permissions` to skip managed hook installation
- `parrot sdd launch worker|brief|fix --host google` — launches with Google Antigravity CLI; `PARROT_SDD_HOST=google` is the environment equivalent
- `PARROT_SDD_AGY_UNATTENDED=1` — enables unattended mode where `force_ask` becomes `deny` 
- `PARROT_SDD_SANDBOX_BACKEND=bubblewrap` — enables Bubblewrap sandboxing for unattended workers
- `GoogleCodingDispatchProfile` supports `mode` values `"accept-edits"`, `"auto"`, `"plan"` and `effort` values `"low"`, `"medium"`, `"high"`, `"xhigh"`, `"max"`

## Usage Examples

Install SDD for Google Antigravity:
```bash
parrot sdd install --host google
```

Official AGY installation (required, snap is unsupported):
```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

Launch unattended worker:
```bash
parrot sdd launch worker --host google FEAT-123
```

Launch interactive session:
```bash
parrot sdd launch brief --host google ISSUE-456
```

Expected refusals include:
- Community snap installations (unsupported)
- Commands that modify shared environments
- File operations outside the checkout boundary
- Unapproved risky commands in interactive mode

## Gotchas

- Hook `allow` approves nothing; permission rules in `~/.gemini/antigravity-cli/settings.json` control actual approvals
- `force_ask` runs under `--dangerously-skip-permissions` (hence the unattended mapping to `deny`)
- Only the launcher's worker (`parrot sdd launch worker --host google`) is a supported unattended mode
- `--mode auto` is account-gated and may silently fall back to default mode
- The community snap is refused (official install command required)
- Fresh shell per `run_command` means `cd` and environment variables don't persist across calls
- Self-updating `agy` — re-run probes after hook/permission changes

## Related

- [Antigravity notes](ANTIGRAVITY.md) — earlier agy integration notes
- Antigravity Adaptation Contract (`docs/sdd/AGY.md`) — runtime adaptations for Google Antigravity CLI
- [AGY Permission Hook](../../../.agents/hooks.json) — the managed permission hook configuration