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
- [The kind picker](#the-kind-picker)
- [The interactive wizard](#the-interactive-wizard)
- [Feature-mode intake](#feature-mode-intake)
- [Dev-agent pool & judge panel](#dev-agent-pool--judge-panel)
- [Slash commands](#slash-commands)
- [Approval gates](#approval-gates)
- [Brief file format](#brief-file-format)
  - [WorkBrief (YAML)](#workbrief-yaml)
  - [FeatureBrief (YAML)](#featurebrief-yaml)
  - [RevisionBrief (YAML)](#revisionbrief-yaml)
- [Revision mode](#revision-mode)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

---

## What is it?

`parrot devloop` is an interactive terminal console that embeds the
dev-loop flow (research → development → QA → synthesis) in a single
process. Instead of orchestrating via HTTP or a message bus, it runs the
flow locally, rendering live progress via Rich and prompting you for
approval-gate decisions inline.

The CLI is homologated with the web console (FEAT-388): a
[kind picker](#the-kind-picker) routes bug/enhancement reports to the
familiar `WorkBrief` wizard and new-feature requests to
[free-text intake](#feature-mode-intake) (no Jira ticket, no log
sources), both backed by the same
[backend catalog](#dev-agent-pool--judge-panel) and
[backend-aware preflight](#backend-aware-dev-agent-check) the web
console uses.

No new runtime dependencies — `rich`, `click`, and `prompt_toolkit` are
already core deps of AI-Parrot.

---

## Prerequisites

The preflight check runs automatically when you start the console.
The **development-agent check is backend-aware** (homologated with the
web console, FEAT-388 G6): it checks whichever backend
`DEV_LOOP_DEVELOPMENT_AGENT` actually resolves to — a missing `claude`
binary never blocks preflight unless `claude-code` is the *selected*
backend (default).

| Check | Requirement | How to fix |
| --- | --- | --- |
| **Redis** | `REDIS_URL` env var set and reachable | `export REDIS_URL=redis://localhost:6379` |
| **Dev-agent backend** | See table below — depends on `DEV_LOOP_DEVELOPMENT_AGENT` | Install/authenticate the resolved backend, or unset the env var for the `claude-code` default |
| **Jira credentials** | `JIRA_URL` + `JIRA_TOKEN` env vars | Set from your Jira instance |
| **Worktree base** | `.claude/worktrees/` directory exists | `mkdir -p .claude/worktrees` |
| **Intake-LLM credentials** (soft) | Credentials for `DEV_LOOP_INTAKE_LLM`'s provider | Optional — only needed for feature-mode free-text intake; never blocks `--brief` runs |

### Backend-aware dev-agent check

`DEV_LOOP_DEVELOPMENT_AGENT` (fallback `claude-code`) selects which
backend `parrot devloop` dispatches development work to — the same env
var the web console (`examples/dev_loop/server.py`) honors:

| `DEV_LOOP_DEVELOPMENT_AGENT` | Transport | What preflight checks |
| --- | --- | --- |
| `claude-code` (default) | CLI | `claude` binary on `$PATH` — fails if missing |
| `codex` | CLI | `codex` binary on `$PATH` — fails if missing |
| `gemini` | CLI | `gemini` binary on `$PATH` — fails if missing |
| `google_coding` | CLI | `agy` binary on `$PATH` — fails if missing |
| `nvidia` | API | Soft check (always passes) — hints at `NVIDIA_API_KEY` if unset |
| `grok`, `zai`, `moonshot` | API | Soft check (always passes) — hints at the backend's credentials |
| *(anything else)* | — | **Fails** with a hint listing every valid backend id |

Only the **selected** backend's requirement is checked — switching
`DEV_LOOP_DEVELOPMENT_AGENT` away from `claude-code` means the `claude`
binary is never checked at all. API-transport backends are soft/
informational only (`BackendInfo` has no structured credential-env
field to verify against); CLI-transport backends genuinely gate
preflight on their binary being present.

---

## Quick start

```bash
# Interactive mode — kind picker, then WorkBrief wizard or feature intake
parrot devloop

# Non-interactive — load brief from file, skip wizard
parrot devloop run --brief brief.yaml --yes

# Feature-mode, non-interactive: free text -> draft -> dispatch
parrot devloop run --text "Add a dark-mode toggle" --yes

# Feature-mode with an explicit dev-agent pool
parrot devloop run --text "Add a dark-mode toggle" --yes \
  --dev-agent codex:gpt-5.5:2 --dev-agent google_coding

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
| `--brief FILE` | — | Path to a YAML/JSON `WorkBrief` or `FeatureBrief` file. `kind: feature` routes to feature-mode; anything else (or no `kind`) loads as `WorkBrief`. |
| `--yes` | off | Skip confirmation prompts (requires `--brief`), **or** with `--text`, skip the intake accept/edit/redo/cancel confirm loop (FEAT-388 G5). |
| `--dev-agent BACKEND[:MODEL[:COUNT]]` | — | *(FEAT-388 G2, repeatable)* Add a dev-agent pool row, e.g. `--dev-agent codex:gpt-5.5:2`. Merges into the built brief; a `--brief` file's own `dev_agents` (if already set) wins over this. Unknown backend fails fast, listing every valid catalog id. |
| `--text "<request>"` | — | *(FEAT-388 G4)* Non-interactive free-text feature intake — skips the kind picker entirely and goes straight to the intake draft/confirm loop (or, combined with `--yes`, dispatches the first draft with no prompts at all). |

**Without `--brief` or `--text`:** opens the interactive console — a
[kind picker](#the-kind-picker) routes you to either the WorkBrief
wizard or [feature-mode intake](#feature-mode-intake).

**With `--brief` only:** pre-seeds the wizard from the file; you can
review and edit fields before dispatching.

**With `--brief` and `--yes`:** non-interactive dispatch. The brief file
must validate against `WorkBrief`/`FeatureBrief`; the console aborts on
validation errors.

**With `--text`:** non-interactive feature intake — see
[Feature-mode intake](#feature-mode-intake).

**With `--dev-agent`:** overrides the default single-agent dispatch with
an explicit pool, for either brief kind — see
[Dev-agent pool & judge panel](#dev-agent-pool--judge-panel).

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

## The kind picker

*(FEAT-388 Module 3)* When no `--brief` file and no `--text` are given,
the interactive path first asks:

```
What kind of work is this?
  1. bug
  2. enhancement
  3. feature
  Choice [1]:
```

- **`bug` / `enhancement`** → the existing `WorkBrief` wizard, byte-
  identical field-by-field (the picker only pre-fills `kind` — every
  other prompt, field, and order is unchanged), plus an optional
  [dev-agent pool step](#dev-agent-pool--judge-panel) at the end.
- **`feature`** → [feature-mode intake](#feature-mode-intake) — never
  asks for a Jira ticket or log sources.

Pressing Enter (or hitting EOF) defaults to `bug`, matching the
pre-FEAT-388 `WorkBrief.kind` default exactly.

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

## Feature-mode intake

*(FEAT-388 Module 2/3, goals G3–G5)* Instead of the log-driven `WorkBrief`
wizard (Jira ticket, log sources, acceptance criteria), feature-mode
intake turns a free-text request into a structured draft, review it, and
dispatches a document-driven `FeatureBrief` — the same contract
`PlannerNode` (FEAT-378) already consumes.

Reach it via the [kind picker](#the-kind-picker)'s `feature` choice, the
`/feature` slash command, or non-interactively with `--text`:

```bash
parrot devloop run --text "Add a dark-mode toggle that persists across sessions"
```

**Flow:**

1. **Describe** the feature (multiline free text; interactively, an
   empty line finishes input).
2. A configurable light LLM (`DEV_LOOP_INTAKE_LLM`, default
   `anthropic:claude-haiku-4-5`) drafts a structured `FeatureDraft`:
   title, slug, problem statement, requirements, acceptance criteria,
   affected areas, out-of-scope items, open questions.
3. The draft is shown in a review panel, then you choose:

   | Action | Effect |
   | --- | --- |
   | `accept` | Confirm the draft and continue |
   | `edit <field>` | Directly overwrite one field (list fields prompt one item per line) |
   | `redo <guidance>` | Re-draft via the LLM, folding in your guidance |
   | `cancel` | Abort — nothing is written or dispatched |

   Intake **never** auto-dispatches without an explicit `accept` — the
   only way to skip this loop is `--text` combined with `--yes`.
4. The confirmed draft is rendered as a brainstorm markdown document
   under `sdd/proposals/<slug>.brainstorm.md` (FEAT-145 frontmatter).
   Re-running the same request never overwrites an existing file — a
   slug collision appends `-2`, `-3`, ….
5. Optional [dev-agent pool and judge-panel steps](#dev-agent-pool--judge-panel).
6. The resulting `FeatureBrief(document_kind="brainstorm", ...)` is
   dispatched exactly like a `--brief kind: feature` file.

**LLM errors** (a bad/missing API key, a malformed structured response)
surface as `Brief error: ...` — never a raw traceback (one retry is
attempted internally before surfacing an error).

---

## Dev-agent pool & judge panel

*(FEAT-388 Module 3, goal G2)* Both the WorkBrief wizard (bug/enhancement)
and feature-mode intake offer an optional dev-agent pool step — rows of
`backend` / `model` / `count`, sourced from the same catalog the web
console uses:

```
Configure a custom dev-agent pool? [y/N]: y
Add a dev-agent row? [Y/n]: y
  1. claude-code (default model: claude-sonnet-4-6)
  2. codex (default model: gpt-5.5)
  3. gemini (default model: auto)
  4. google_coding (default model: auto)
  5. nvidia (default model: moonshotai/kimi-k2-instruct-0905)
  6. grok (default model: grok-build-0.1)
  7. zai (default model: glm-5.2)
  8. moonshot (default model: kimi-k3)
  Backend: 2
  Model [gpt-5.5]:
  Count [1]: 2
Add a dev-agent row? [y/N]: n
```

Skipping the step (default) dispatches the single-agent path, unchanged.

Feature-mode intake also offers a **judge-panel** step, restricted to
backends with a review profile (`claude-code`, `codex`, `gemini`,
`google_coding`) — skipping it falls back to the default 3-judge panel
(`default_judge_panel()` / `DEV_LOOP_JUDGE_PANEL`).

**Non-interactively**, use the repeatable `--dev-agent` flag instead of
either step:

```bash
parrot devloop run --text "..." --yes \
  --dev-agent codex:gpt-5.5:2 --dev-agent google_coding
```

`--dev-agent backend[:model[:count]]` parses on `:` (max 2 splits — model
ids never contain `:`); an unrecognized backend fails fast, listing every
valid catalog id; a non-positive/invalid `count` is rejected. When
`--dev-agent` is given, the interactive pool step (and, with `--brief`,
a file that didn't already set `dev_agents`) is skipped/merged
accordingly — a `--brief` file's own `dev_agents` always wins.

---

## Slash commands

Once inside the console, these slash commands are available at the
prompt:

| Command | Description |
| --- | --- |
| `/new` | Start a new run (opens the kind picker + wizard again) |
| `/feature [text]` | *(FEAT-388)* Start a new feature-mode run via free-text intake. With `text`, skips straight to the draft (no re-prompt); without it, prompts for the description. |
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

### FeatureBrief (YAML)

```yaml
kind: feature
document_path: sdd/proposals/add-dark-mode.brainstorm.md
document_kind: brainstorm
jira_issue_key: OPS-1234  # optional — feature-mode never creates a Jira issue
dev_agents:
  - agent: codex
    model: gpt-5.5
    count: 2
  - agent: google_coding
judge_panel:
  judges:
    - agent: claude-code
      model: claude-sonnet-4-6
    - agent: codex
      model: gpt-5.5
    - agent: gemini
  decision: majority
```

`document_path` must already exist and be readable — validated eagerly
at brief construction, before any dispatch. `document_kind` is one of
`brainstorm` / `proposal` / `spec`; `dev_agents` and `judge_panel` are
both optional (omit for the default single-agent path / 3-judge panel).

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

## Configuration reference

*(FEAT-388)* Config keys new/relevant to the CLI's homologated surface —
all resolved via `parrot.conf.config.get(key, fallback=...)`, so they
work as environment variables or `parrot.conf` settings:

| Key | Default | Description |
| --- | --- | --- |
| `DEV_LOOP_DEVELOPMENT_AGENT` | `claude-code` | Default dispatch backend for the single-agent path (same key the web console honors) — see the [backend-aware preflight table](#backend-aware-dev-agent-check). |
| `DEV_LOOP_INTAKE_LLM` | `anthropic:claude-haiku-4-5` | `provider:model` spec for the feature-mode free-text intake LLM. |
| `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES` | `3` | Concurrency cap for the default dispatcher (applies to whichever backend `DEV_LOOP_DEVELOPMENT_AGENT` resolves to). |
| `FLOW_STREAM_TTL_SECONDS` | `604800` | Redis stream TTL for the default dispatcher. |
| `DEV_LOOP_CODEX_MODEL`, `DEV_LOOP_GEMINI_MODEL`, `DEV_LOOP_GOOGLE_CODING_MODEL`, `DEV_LOOP_NVIDIA_CODE_MODEL`, `DEV_LOOP_GROK_MODEL`, `DEV_LOOP_ZAI_MODEL`, `DEV_LOOP_MOONSHOT_MODEL` | per-backend | Per-backend default model override, resolved by `agent_builder.build_dispatcher` when `DEV_LOOP_DEVELOPMENT_AGENT` (or a `--dev-agent`/pool-step row) selects that backend and no explicit model is given. |

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Preflight failed` | Check the prerequisites table above; fix the failing checks. |
| `dev-agent-backend` check fails | `DEV_LOOP_DEVELOPMENT_AGENT` is set to an id the catalog doesn't recognize — the hint lists every valid backend id. |
| Gate prompt doesn't appear | Ensure the run is attached (`/attach <run-id>`); gates only prompt on the active run. |
| `SystemExit` on startup | A preflight check failed hard; check terminal output for details. |
| Brief file rejected | Validate your YAML against the `WorkBrief` / `FeatureBrief` / `RevisionBrief` schema; check field names and types. |
| `--dev-agent` rejected | Check the backend id against the hint's catalog list; `count` must be a positive integer. |
| Feature intake fails/loops | Check `DEV_LOOP_INTAKE_LLM`'s provider credentials (see the intake-LLM soft preflight hint); `redo <guidance>` to steer a bad draft instead of `cancel`+retry. |
| Rich display garbled | Ensure your terminal supports 256 colors; try `TERM=xterm-256color`. |

---

*Part of AI-Parrot (FEAT-374, homologated with the web console in
FEAT-388). Source: `parrot/cli/devloop/` — wizard in `wizard.py`,
bootstrap in `bootstrap.py`, renderer in `renderer.py`, console engine in
`console.py`, free-text intake in `intake.py`. Shared backend catalog in
`parrot/flows/dev_loop/catalog.py`.*
