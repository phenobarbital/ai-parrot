# `parrot devloop` — Interactive Dev-Loop CLI Console

> Run the AI-Parrot dev-loop flow from your terminal: collect a
> work brief, dispatch the flow in-process, watch the run in real time
> with Rich, and resolve HITL approval gates interactively.

---

## Table of contents

- [What is it?](#what-is-it)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
  - [`parrot devloop`](#parrot-devloop)
  - [`parrot devloop run`](#parrot-devloop-run)
  - [`parrot devloop revise`](#parrot-devloop-revise)
- [The interactive wizard](#the-interactive-wizard)
- [Slash commands](#slash-commands)
- [Approval gates](#approval-gates)
- [Brief file format](#brief-file-format)
  - [WorkBrief (YAML)](#workbrief-yaml)
  - [RevisionBrief (YAML)](#revisionbrief-yaml)
- [Revision mode](#revision-mode)
- [Troubleshooting](#troubleshooting)

---

## What is it?

`parrot devloop` is an interactive terminal console that embeds the
dev-loop flow (research → development → QA → synthesis) in a single
process. Instead of orchestrating via HTTP or a message bus, it runs the
flow locally, rendering live progress via Rich and prompting you for
approval-gate decisions inline.

No new runtime dependencies — `rich`, `click`, and `prompt_toolkit` are
already core deps of AI-Parrot.

---

## Prerequisites

The preflight check runs automatically when you start the console.
All checks must pass before a run can be dispatched:

| Check | Requirement | How to fix |
| --- | --- | --- |
| **Redis** | `REDIS_URL` env var set and reachable | `export REDIS_URL=redis://localhost:6379` |
| **Claude CLI** | `claude` binary on `$PATH` | Install Claude Code CLI |
| **Jira credentials** | `JIRA_URL` + `JIRA_TOKEN` env vars | Set from your Jira instance |
| **Worktree base** | `.claude/worktrees/` directory exists | `mkdir -p .claude/worktrees` |

---

## Quick start

```bash
# Interactive mode — wizard collects a WorkBrief, then dispatches
parrot devloop

# Non-interactive — load brief from file, skip wizard
parrot devloop run --brief brief.yaml --yes

# Revision mode — run a revision pass on an existing branch
parrot devloop revise --brief revision.yaml
```

---

## Command reference

### `parrot devloop`

```
parrot devloop [SUBCOMMAND]
```

A click group with `invoke_without_command=True`. Running it bare (no
subcommand) is equivalent to `parrot devloop run` — it launches the
interactive console with the wizard.

### `parrot devloop run`

```
parrot devloop run [OPTIONS]
```

| Option | Default | Description |
| --- | --- | --- |
| `--brief FILE` | — | Path to a YAML/JSON `WorkBrief` file. Skips the wizard if combined with `--yes`. |
| `--yes` | off | Skip confirmation prompts (requires `--brief`). |

**Without `--brief`:** opens the interactive wizard to collect a
`WorkBrief` step by step.

**With `--brief` only:** pre-seeds the wizard from the file; you can
review and edit fields before dispatching.

**With `--brief` and `--yes`:** non-interactive dispatch. The brief file
must validate against `WorkBrief`; the console aborts on validation
errors.

### `parrot devloop revise`

```
parrot devloop revise [OPTIONS]
```

| Option | Default | Description |
| --- | --- | --- |
| `--brief FILE` | — | Path to a YAML/JSON `RevisionBrief` file. |

Enters revision mode: collects a `RevisionBrief` (or loads one from
file), then dispatches `run_revision()` on the dev-loop runner.

---

## The interactive wizard

When no `--brief` file is provided, the console opens a pydantic-driven
wizard that walks through every field of the `WorkBrief` model:

```
 WorkBrief
┌──────────────────────────────────────────────┐
│ kind [bug/enhancement/new_feature]: bug      │
│ summary: Fix login timeout on mobile         │
│ description: Users report ...                │
│ affected_component: auth                     │
│ acceptance_criteria:                         │
│   [1] ShellCriterion  [2] FlowtaskCriterion  │
│   Pick variant: 1                            │
│     command: pytest tests/auth/ -v           │
│   Add another? [y/N]: n                      │
│ ...                                          │
└──────────────────────────────────────────────┘
```

Features:
- **Literal fields** present numbered choices
- **Optional fields** can be skipped with Enter
- **List fields** prompt "Add another?" in a loop
- **Discriminated unions** offer a variant picker
- **Nested models** recurse into sub-wizards
- **File input**: type `@path/to/file` to load content from a file

---

## Slash commands

Once inside the console, these slash commands are available at the
prompt:

| Command | Description |
| --- | --- |
| `/new` | Start a new run (opens the wizard again) |
| `/runs` | List all runs in this session with their status |
| `/attach <run-id>` | Switch the live display to a different run |
| `/cancel` | Cancel the currently active run |
| `/revise` | Start a revision-mode run |
| `/help` | Show the command listing |
| `/quit` (or `/exit`) | Exit the console |

---

## Approval gates

When the flow opens an approval gate (e.g. plan approval, QA sign-off),
the console:

1. **Pauses** the Rich Live display
2. **Renders a gate panel** showing:
   - Gate kind and title
   - Instructions (if any)
   - Time-to-live (if the gate has an expiry)
3. **Prompts** for your decision: `[a]pprove / [r]eject`
4. **Collects** an optional comment
5. **Resolves** the gate and resumes the live display

If the gate was already resolved (by another session or expiry), the
console shows a conflict notice and continues.

---

## Brief file format

### WorkBrief (YAML)

```yaml
kind: bug
summary: Fix login timeout on mobile clients
description: |
  Users on iOS report intermittent 504 errors when logging in
  over cellular connections. The auth middleware times out after
  5 seconds but mobile round-trips average 3-4s.
affected_component: auth
log_sources:
  - /var/log/auth/gateway.log
  - sentry:project-auth-mobile
acceptance_criteria:
  - type: ShellCriterion
    command: pytest tests/auth/test_timeout.py -v
    expected_exit_code: 0
  - type: FlowtaskCriterion
    description: Mobile login succeeds within 10s on 3G simulation
escalation_assignee: oncall@example.com
reporter: jlara@trocglobal.com
existing_issue_key: OPS-1234
dev_agents: 2
dev_isolation: worktree
```

### RevisionBrief (YAML)

```yaml
repo_path: /home/user/projects/ai-parrot
branch: feat-374-devloop-cli-console
pr_number: 42
repository: org/ai-parrot
jira_issue_key: OPS-1234
feedback: |
  The gate timeout handling needs to account for network latency.
  Also add a test for the concurrent-resolution conflict path.
head_sha: abc123def
```

Both formats also accept JSON.

---

## Revision mode

Revision mode (`parrot devloop revise`) is for iterating on an existing
branch after code review feedback. Instead of creating a fresh work
brief, it collects a `RevisionBrief` pointing at the branch, PR, and
feedback text, then dispatches `run_revision()` which re-enters the
dev-loop at the development node with the revision context.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Preflight failed` | Check the prerequisites table above; fix the failing checks. |
| Gate prompt doesn't appear | Ensure the run is attached (`/attach <run-id>`); gates only prompt on the active run. |
| `SystemExit` on startup | A preflight check failed hard; check terminal output for details. |
| Brief file rejected | Validate your YAML against the `WorkBrief` / `RevisionBrief` schema; check field names and types. |
| Rich display garbled | Ensure your terminal supports 256 colors; try `TERM=xterm-256color`. |

---

*Part of AI-Parrot (FEAT-374). Source: `parrot/cli/devloop/` — wizard in
`wizard.py`, bootstrap in `bootstrap.py`, renderer in `renderer.py`,
console engine in `console.py`.*
