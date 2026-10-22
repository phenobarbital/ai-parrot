# Spec-Driven Development in Google Gemini / Antigravity CLI

This guide explains how to run AI-Parrot's Spec-Driven Development (SDD) workflow
from Google Gemini via the Antigravity CLI (`agy`).

In Antigravity CLI, the SDD workflow is exposed through two complementary surfaces:
1. **Workflows / Slash Commands (`.agent/workflows/sdd-*.md`)**: Type `/<command>` directly in the Antigravity CLI TUI to launch guided workflows.
2. **Workspace Skills (`.agents/skills/sdd-*/SKILL.md`)**: Progressive-disclosure procedural guides that Gemini loads on demand when performing SDD operations.
3. **Custom Subagents (`.agents/agents/` / `.agent/agents/`)**: Autonomous specialized personas (e.g. `sdd-worker`) for unattended task execution.

## Quick Map

| Slash Command | Skill | Purpose |
|---|---|---|
| `/sdd-brainstorm` | `sdd-brainstorm` | Explore a feature idea, compare options, and write a brainstorm. |
| `/sdd-proposal` | `sdd-proposal` | Research a Jira issue, inline request, or notes file before writing a spec. |
| `/sdd-brief` | `sdd-brief` | Research a bug or alert and create a worktree with a brief and local HOTFIX tasks. |
| `/sdd-spec` | `sdd-spec` | Convert a brainstorm, proposal, or direct request into a formal spec. |
| `/sdd-task` | `sdd-task` | Decompose an approved spec into atomic task files and a per-spec index. |
| `/sdd-start` | `sdd-start` | Implement and close one task inside the feature worktree. |
| `/sdd-done` | `sdd-done` | Verify, push, open or describe the PR, and clean up the worktree. |
| `/sdd-codereview` | `sdd-codereview` | Review completed task code against acceptance criteria and quality standards. |
| `/sdd-explain` | `sdd-explain` | Code-grounded architectural map or deep implementation trace. |
| `/sdd-status` | `sdd-status` | Show task index status board across all per-spec indexes. |
| `/sdd-next` | `sdd-next` | Suggest next unblocked tasks to assign. |
| `/sdd-fromjira` | `sdd-fromjira` | Bootstrap an SDD brainstorm from a Jira ticket. |
| `/sdd-tojira` | `sdd-tojira` | Export an SDD specification to a Jira Story and subtasks. |
| `/sdd-insight` | `sdd-insight` | Analyze collaboration transcripts and repo-level SDD process adherence. |

## Antigravity Surfaces

AI-Parrot configures three surfaces for Antigravity CLI:

| Surface | Path | Role |
|---|---|---|
| Repo guidance & Rules | `AGENTS.md`, `.agent/rules/*.md` | Always-loaded project rules, safety protocols, and python standards. |
| Workflows (Slash Commands) | `.agent/workflows/sdd-*.md` | TUI slash commands invoked as `/sdd-*`. |
| Repo Skills | `.agents/skills/sdd-*/SKILL.md` | Modular procedural runbooks loaded via progressive disclosure. |
| Custom Agents | `.agents/agents/<name>/agent.md` | Specialized autonomous workers (e.g. `sdd-worker`, `sdd-planner`). |

## Start From A Single Bug Or Alert

Use `/sdd-brief` for a single issue or hotfix; it replaces `sdd-spec --type hotfix`.

```text
/sdd-brief NAV-9001
/sdd-brief cs:123 --research light --no-interview
/sdd-brief issue:<hex> --split
```

The flow fetches the source, verifies a root cause and a `path:line` anchor,
then provisions a worktree through `scripts.sdd.ensure_worktree`. Non-ledger
sources default to `main`; ledger sources always use `dev` and refuse an
explicit `--base-branch main`. It commits and pushes only the new brief branch,
never `main`. Tasks use local `HOTFIX-<KEY>-<N>` IDs without FEAT/TASK reservation.

Open the returned worktree for manual implementation or ask its `sdd-worker`
agent to implement `<KEY>`, then run `/sdd-done <KEY>`.

For agy, follow `.agent/workflows/sdd-brief.md`; the shared skill's Codex runtime adaptations do not apply to this host.

## End-to-End Flow

```text
/sdd-proposal or /sdd-brainstorm
        |
        v
/sdd-spec
        |
        v
Review spec and set status: approved
        |
        v
/sdd-task
        |
        v
cd .claude/worktrees/<feature-worktree>
        |
        v
/sdd-start TASK-NNN
        |
        v
Repeat until all tasks are done, or delegate to sdd-worker
        |
        v
/sdd-done FEAT-NNN
```

## Shared Repository Infrastructure

Antigravity CLI shares the exact same underlying SDD engine with Claude Code and Codex:
- **Per-Spec Indexes**: Task metadata lives in `sdd/tasks/index/<feature-slug>.json`.
- **Git Flow**: Long-lived branches `dev` (default feature base), `staging` (freeze stabilization), and `main` (hotfixes only). Features never base on `main`.
- **ID Ledger**: `FEAT-<NNN>` and `TASK-<NNN>` IDs are allocated via git-native compare-and-swap through `python -m scripts.sdd.reserve_ids` (FEAT-387).
- **Knowledge Graph**: Codebase orientation uses `wikitoolkit query` before broad greps or file scans.
- **Codebase Contract**: Specs and tasks require explicit, verified import paths and function signatures to prevent LLM hallucinations.
- **Worktree Isolation**: Worktrees live under `.claude/worktrees/` for cross-tool compatibility.
- **Task Closure**: Tasks are closed and verified using `scripts/sdd/close_task.sh TASK-NNN <feature-slug> verified`.

## Using Custom Subagents

In Antigravity CLI, you can invoke the autonomous `sdd-worker` subagent to implement tasks unattended:

```text
Use the sdd-worker subagent to implement FEAT-NNN.
```

The worker creates or reuses the feature worktree, implements each task in dependency order, verifies acceptance criteria, commits code and SDD state in the worktree, and runs an adversarial review before pushing.
