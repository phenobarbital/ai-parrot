# AI-Parrot Development Guide for Claude

## Project

Async-first Python framework for AI Agents and Chatbots.
See @.agent/CONTEXT.md for full architectural context.

**Main Branch**: `main`

## Development Environment

### Package Management & Virtual Environment

**CRITICAL RULES:**
1. **Package Manager**: Use **`uv`** exclusively for package management
   ```bash
   uv pip install <package>
   uv pip list
   uv add <package>
   ```

2. **Virtual Environment**: ALWAYS activate before Python operations
   ```bash
   source .venv/bin/activate
   ```
   **NEVER** run `uv`, `python`, or `pip` commands without activating first.

3. **Dependencies**: Manage all dependencies via `pyproject.toml`

### Repository layout — this is a uv workspace

The repo root is the `ai-parrot-workspace` declarator
(`[tool.uv.workspace] members = ["packages/*"]`). **There is no `parrot/`
directory at the repo root.** The core package source root is:

```
packages/ai-parrot/src/parrot/
```

Sibling distributions under `packages/`:

| Directory | Distribution | Contributes |
|---|---|---|
| `ai-parrot/` | `ai-parrot` | the whole `parrot.*` namespace (core) |
| `ai-parrot-advisors/` | `ai-parrot-advisors` | `parrot.advisors` |
| `ai-parrot-embeddings/` | `ai-parrot-embeddings` | backends under `parrot.embeddings` / `.stores` / `.rerankers` |
| `ai-parrot-integrations/` | `ai-parrot-integrations` | `parrot.human`, `parrot.integrations`, `parrot.voice` |
| `ai-parrot-server/` | `ai-parrot-server` | `parrot.a2a`, `parrot.handlers`, `parrot.manager`, `parrot.mcp`, `parrot.server`, … |
| `ai-parrot-visualizations/` | `ai-parrot-visualizations` | `parrot.outputs` assets |
| `ai-parrot-tools/` | `ai-parrot-tools` | top-level **`parrot_tools`** |
| `ai-parrot-loaders/` | `ai-parrot-loaders` | top-level `parrot_loaders` |
| `ai-parrot-pipelines/` | `ai-parrot-pipelines` | top-level `parrot_pipelines` |

Namespace satellites use PEP 420: their `src/parrot/` has **no**
`__init__.py`, only the subpackage they exclusively own does.


## Tool-Centric Architecture

AI-Parrot's agents interact with the world through tools. When creating tools:

1. **Location**: Concrete external API/service wrappers live in the
   **ai-parrot-tools** distribution (`packages/ai-parrot-tools/src/parrot_tools/`).
   Only the base machinery — `AbstractTool`, `AbstractToolkit`, the `@tool`
   decorator, `ToolManager`, `working_memory/` — stays in core
   `parrot/tools/`. A `sys.meta_path` finder in `parrot/tools/__init__.py`
   redirects `parrot.tools.<x>` → `parrot_tools.<x>` → `plugins.tools.<x>`
   for any name that is not a core submodule, so legacy import paths keep
   working; prefer the explicit `parrot_tools.<x>` in new code.
2. **Decorator Pattern**: Use `@tool` for simple functions
   ```python
   from parrot.tools import tool

   @tool
   def get_weather(location: str) -> str:
       """Get the current weather for a location."""
       return f"Weather in {location}: Sunny, 25°C"
   ```

3. **Toolkit Pattern**: Use `AbstractToolkit` for complex tool collections
4. **Documentation**: Every tool MUST have clear docstrings explaining purpose, parameters, and return values

## Async-First Development

AI-Parrot is built on async/await patterns

## Integration Patterns

AI-Parrot supports multiple integration methods:

### 1. A2A (Agent-to-Agent)
Native protocol for agent discovery and communication

### 2. MCP (Model Context Protocol)
Expose agents as MCP servers or consume external MCP servers

### 3. OpenAPI Integration
Consume any OpenAPI spec as a dynamic toolkit using `OpenAPIToolkit`

## Non-Negotiable Rules

### Environment
- Package manager: `uv` exclusively (`uv add`, `uv pip install`)
- ALWAYS activate venv before any command: `source .venv/bin/activate`
- NEVER run python/uv/pip without activating first

### Code Standards
- All functions and classes: Google-style docstrings + strict type hints
- Pydantic models for all data structures
- async/await throughout — no blocking I/O in async contexts
- Logger (`self.logger`) instead of print statements

### Workflow: Think → Act → Reflect
1. For complex tasks: create plan in `artifacts/plan_[task_id].md` first
2. Implement incrementally
3. Run `pytest` after ANY logic change — no exceptions
4. Save evidence to `artifacts/logs/`

### Security
- Never commit API keys — use environment variables
- Never run `rm -rf` or system-level deletions
- No form submissions or logins without user approval

### Adversarial Second Opinion

Use an external CLI agent as an independent perspective for adversarial
code reviews, design opinions, brainstorming, research cross-checks, and
implementation sanity checks. The reviewer is **`codex` (OpenAI)**.

> **`agy` (Google Gemini / Antigravity) MUST NOT be used as a reviewer.**
> It was removed as an option on 2026-09-01 after it returned a fabricated
> review: invented a 188-test pytest run with test names that do not exist
> in the branch under review, then terminated with `Error: timeout waiting
> for response`. A reviewer that hallucinates passing evidence is worse
> than no reviewer, because its output reads like corroboration. Do not
> re-add it, and do not fall back to it when `codex` is unavailable — when
> there is no external reviewer, say so and rely on a Claude subagent.
>
> This bans `agy` **as a reviewer only**. It is unrelated to the
> `google_coding` dev-loop backend, which drives the same `agy` binary as a
> *coding* agent (`dispatchers/google_coding.py`) and is untouched.

Rules:
- Never feed the reviewer your reasoning, justification, or preferred
  conclusion. Give it only the diff, the requirement, and the question.
  Supplying your conclusions produces ratification, not review.
- Treat reviewer output as advisory. For every substantive finding,
  explicitly mark it as `CONFIRM` (adopt), `REJECT` (with reason), or
  `ESCALATE`.
- Never silently concede to the reviewer and never silently drop a finding.
- Run each reviewer call as a full background agent session. Typical runtime
  is 30 seconds to 2 minutes; do not call it per edit or from hooks.
- For parallel perspective, use one Claude subagent and one background
  reviewer session with the same neutral brief, then synthesize agreements
  and disagreements.
- **Verify the reviewer's evidence before believing it.** If it claims a
  test run, a file, or a symbol, spot-check that the thing exists. Treat an
  unverifiable claim as no finding at all, and say the review was
  unusable rather than reporting it as a pass.

**Detection:**
```bash
if command -v codex &>/dev/null; then REVIEWER="codex"
else echo "No external reviewer CLI found"; fi
```

#### codex commands
```bash
# Reviews
codex exec review --uncommitted
codex exec review --base dev
codex exec review --commit <sha>

# Opinions, brainstorming, and cross-checks
codex exec --sandbox read-only -o <scratch-file> "<neutral brief>"

# Follow-up in the same Codex session
codex exec resume --last "<question>"

# Image generation / mockups / wireframes (codex-only)
codex exec --sandbox workspace-write -o <out.txt> \
  "Generate an image: <description>. Save as <name>.png"
```

#### Design research at spec time (FEAT-545)

The same codex seat gives an **independent design opinion** in `/sdd-spec`
§3b, over the *accepted* brainstorm/proposal only — never over the spec
draft. Model: `${SDD_DESIGN_RESEARCH_MODEL:-gpt-5.6-luna}` with
`-c model_reasoning_effort=high` and `--ignore-user-config` (the operator's
`~/.codex/config.toml` must not swap the model silently). The pass is
**optional and never blocking**: no `codex`, failed probe, timeout or invalid
output ⇒ spec §9 reads `Status: skipped (<reason>)` and the command continues
(`sdd-planner` runs it unattended). Every suggestion is triaged
`CONFIRM` / `REJECT` / `ESCALATE` in spec **§9 Design Research Cross-Check**;
the transcript is committed under `sdd/state/<FEAT-ID>/design_research/`.
The `agy` ban above applies to this seat too.

## Key References
- Architecture & patterns: @.agent/CONTEXT.md
- SDD workflow: @docs/sdd/WORKFLOW.md
- Skills: @.agent/skills/
- Workflows: @.agent/workflows/

# SDD Workflow & Worktree Policy

---

## Git Configuration

The Git Parrot Flow (FEAT-187) uses three long-lived branches:

- **`main`** — tagged releases only. Hotfixes land here via PR;
  no feature work ever bases on `main`.
- **`staging`** — release candidate branch. Cut from `dev` when the
  team decides to freeze a release. Receives `main → staging` syncs
  automatically (via `.github/workflows/sync-down.yml`); the
  `dev → staging` direction is a manual cut at freeze time.
- **`dev`** — integration branch for all feature work. Default base
  for `type: feature` flows.

**Flow types** (FEAT-145, refined by FEAT-187):
- `feature` — base is `dev` (default) or `staging` (during a release
  freeze). NEVER `main`.
- `hotfix` — base is `main` (mandatory).

**Sync-down automation** (FEAT-187): `.github/workflows/sync-down.yml`
listens for pushes to `main` and tries to fast-forward `staging` and
`dev`. When fast-forward is not possible, it opens a sync PR against
the lagging branch. `/sdd-done --sync-down` is the manual fallback for
the same operation.

**`/sdd-done` NEVER pushes to or opens a PR against `main`** —
hotfix PRs are user-initiated. After the user merges the hotfix into
`main`, the Action propagates the change to `staging` and `dev`. If
the Action fails (or the user is offline), run
`/sdd-done <FEAT-ID> --sync-down` to do the same locally.

**Recommended branch protection**: `main` (and `staging` once in use)
should require PRs, passing CI, and signed commits. Not configured
declaratively in this repo — set via GitHub repo settings.

## Worktrees

Everything about worktrees — location (`.claude/worktrees/`), naming,
creation via `python -m scripts.sdd.ensure_worktree` (always from
`origin/<base_branch>`, never `HEAD`, never `claude --worktree`), working
inside one, finishing and cleanup — lives in **one** rule:
`.claude/rules/worktree-management.md` (twin: `.agent/skills/worktree-management/`).
Worktrees are created by whoever implements (`/sdd-start`, `sdd-worker`, the
dev-loop orchestrators); `/sdd-task` creates none (FEAT-552).

## SDD Auto-Commit Rule

> **CRITICAL**: Every SDD command that creates or modifies files MUST commit
> them on the appropriate branch before finishing. Uncommitted files are
> invisible to worktrees and other sessions.

| Command | What it commits | Where (FEAT-145) |
|---------|-----------------|------------------|
| `/sdd-brainstorm` | `sdd/proposals/<n>.brainstorm.md` (with frontmatter) | `base_branch` |
| `/sdd-proposal`   | `sdd/proposals/<n>.proposal.md` (with frontmatter)  | `base_branch` |
| `/sdd-spec`       | `sdd/specs/<n>.spec.md` (with frontmatter) + a `reserve_ids.py` FEAT-ID reservation commit to `sdd/tasks/.id_ledger.json` (FEAT-387) | `base_branch` |
| `/sdd-task`       | `sdd/tasks/index/<feature>.json` + `sdd/tasks/active/TASK-*` + a `reserve_ids.py` TASK-ID reservation commit to `sdd/tasks/.id_ledger.json` (FEAT-387) — and NO worktree (FEAT-552: it is created by the implementing lane) | `base_branch` |
| `/sdd-start`      | Per-spec index status update + implementation code  | worktree (feature branch) |
| `/sdd-done`       | Verification stamp on per-spec index (committed on feature branch); merges feature → `base_branch` | worktree (feature branch), merged to `base_branch` by Step 9 |

Commit message convention:
```
sdd: <action> for <feature-name>
```

**Note (FEAT-466)**: the `/sdd-spec` and `/sdd-task` reservation commits in
the table above do **not** occur for `type: hotfix`. A bugfix is not a
feature and reserves no `FEAT-<NNN>`/`TASK-<NNN>` id — `/sdd-spec` skips
`reserve_ids.py --kind feature` and `/sdd-task` is normally skipped
entirely (the single-agent dev-loop path handles a hotfix directly from the
spec). The hotfix's identity is its Jira issue key instead; see
`sdd/specs/dev-loop-run-fidelity.spec.md` §3 Module 2.

**Note (FEAT-145)**: `/sdd-start` no longer needs to `cd` back to the main
repo to update SDD state — per-spec indexes mean each feature owns its own
index file, so the worktree's commit covers code AND state in one stroke.
The merge in `/sdd-done` brings them to `base_branch` atomically.

**Note (FEAT-387)**: `sdd/tasks/.id_ledger.json` is a git-tracked
compare-and-swap counter for `TASK-<NNN>`/`FEAT-<NNN>` numbers, allocated
via `scripts/sdd/reserve_ids.py` (not scanned-and-incremented by hand). Its
reservation commit is independent — pushed to `base_branch` immediately by
`reserve_ids.py` itself, BEFORE the calling command's own task/spec files
are written, never bundled into the same commit. `scripts/sdd/
check_id_collisions.py` is an independent, read-only backstop wired into
CI that catches any `TASK-<NNN>` collision that still slips through. See
`sdd/WORKFLOW.md` ("TASK/FEAT ID Allocation") for full details.

## Typical Workflow

```bash
git checkout dev && git pull origin dev
/sdd-spec <feature> -- ...                 # spec, committed to dev
/sdd-task sdd/specs/<feature>.spec.md      # tasks, committed to dev
/sdd-start TASK-<NNN>                      # creates the worktree, implements the task
cd .claude/worktrees/feat-FEAT-<NNN>-<slug>
/sdd-start TASK-<NNN+1> …                  # or: claude --agent sdd-worker
/sdd-done FEAT-<NNN>                       # verify, push, merge → dev, clean up
```

## Autonomous Agent (`sdd-worker`)

The `sdd-worker` agent (`.claude/agents/sdd-worker.md`) implements all tasks for
a feature sequentially. Launch it **inside** a manually-created worktree:

```bash
cd .claude/worktrees/<feature-worktree>
claude --agent sdd-worker --model sonnet --verbose
```

Key properties: uses Sonnet, implements EXACTLY what tasks
specify (no redesigns), commits after each task.

For background execution:
```bash
cd .claude/worktrees/feat-014
tmux new -s feat-014 \
  "claude --agent sdd-worker --model sonnet --verbose"
# Ctrl+B, D to detach — tmux attach -t feat-014 to reconnect
```

## Task Index Schema (FEAT-145 — per-spec)

Each feature has its own per-spec index at `sdd/tasks/index/<feature-slug>.json`.
The header carries flow metadata cached from the spec frontmatter; the
`tasks[]` array is local to that feature only.

```json
{
  "feature": "<feature-slug>",
  "feature_id": "FEAT-<NNN>",
  "spec": "sdd/specs/<feature-slug>.spec.md",
  "type": "feature",
  "base_branch": "dev",
  "created_at": "<ISO-8601>",
  "completed_at": null,
  "tasks": [
    {
      "id": "TASK-<NNN>",
      "feature_id": "FEAT-<NNN>",
      "feature": "<feature-slug>",
      "status": "pending",
      "depends_on": [],
      "...": "..."
    }
  ]
}
```

Both `feature_id` and `feature` must be present on every task entry.
Commands resolve features by matching either field (exact, numeric suffix,
or substring) against the per-spec index headers.

**Migration history**: the legacy `sdd/tasks/.index.json` monolith was
split per-spec by `scripts/sdd/migrate_index.py`. The monolith is preserved
as a historical artifact and ignored by all FEAT-145 commands. Tasks the
migration could not attribute to a feature live in
`sdd/tasks/index/_orphans.json` and are surfaced (but not assigned) by
`/sdd-status` / `/sdd-next`.

Authoritative reference: `sdd/specs/sdd-flow-types-and-per-spec-index.spec.md`
(FEAT-145).

> **Heads-up**: `.gitignore` has a global `templates/` rule (line 245).
> The three `sdd/templates/*.md` files were already tracked before the
> rule landed, so they remain editable. If you ever need to add a NEW
> template file, you must `git add -f` it and consider tightening the
> ignore pattern.

<!-- parrot:wiki:begin -->
## Codebase Knowledge Graph (LLM Wiki)

This repository maintains a machine-first knowledge graph of the
codebase (pages + typed edges over a local SQLite plane, built by
`wikitoolkit build`). For ANY question about the codebase — where
something lives, how modules relate, what a subsystem does — you MUST
run a scoped wiki query FIRST, before Grep/Glob/Read or any shell
search (`grep`/`rg`/`find`/`cat` via Bash):

- `wikitoolkit query "<question>"` — token-budgeted, ranked page
  stubs for a scoped question. ALWAYS start here.
- `wikitoolkit page <id>` — read one page in full (file summaries,
  API outlines, content). Use the ids returned by `query`.
- `wikitoolkit related <id>` — follow typed edges (`contains`,
  `references`) to neighbouring files/modules.
- `wikitoolkit status` — plane statistics and staleness.
- `wikitoolkit build` — refresh the graph after large changes
  (a git post-commit hook may already keep it fresh).

These same operations are also exposed as native MCP tools —
`wiki_query`, `wiki_page`, `wiki_related`, `wiki_remember`, `wiki_note`,
`wiki_status` — via the `wikitoolkit` MCP stdio server registered in
this repo's `.mcp.json` (FEAT-403). If they appear in your tool list,
prefer calling them directly; they have equal standing with Grep/Read
at tool-selection time instead of competing via a Bash-invoked CLI.

**Symbol lookup and blast radius (FEAT-498).** For a specific
function/class/method — not a general question — prefer the structural
tools over `wiki_query`: `wikitoolkit symbols lookup <name>`
(`wiki_symbol_lookup` MCP tool) finds it by name/qualname directly;
`wikitoolkit symbols outline <file>` (`wiki_code_outline`) lists a
file's symbols before you read the whole thing; `wikitoolkit symbols
blast <symbol>` (`wiki_blast_radius`) shows every symbol that
transitively calls/extends/implements it — run this BEFORE editing a
widely-used function or class to see what you might break.

**Query discipline** (avoids the two most common ways the wiki
"fails" — which are usually caller error, not missing coverage):

1. **Query for the *thing*, not for your *hypothesis* about it.** The
   ranking is lexical — extra concept words steer it toward those
   concepts. To locate a class or feature, name the symbol/module/
   subsystem you want (`"attestation model service"`), not your theory
   about where it might live.
2. **Follow the thread before falling back.** If a result scores low
   or names a parent module, resolve it with `wikitoolkit page <id>`
   or `wikitoolkit related <id>` — one hop usually lands the real
   page. Do NOT jump to grep just because the first `query` didn't
   rank the exact page first.

Only fall back to Grep/Glob/Read (or shell search) once a clean query
*and* a page/related follow-up have genuinely come up empty — and say
so before you do. Consider `wikitoolkit build` if results look stale.

**Saving knowledge (persistent memory).** The wiki is also your
durable memory — what you save here survives this session and is
found by future `wikitoolkit query` calls ("the agent forgets, the
graph does not"). When you learn a durable fact, make a decision, or
extract a lesson worth keeping, SAVE it:

- `wikitoolkit remember "<fact>" --category [note|decision|lesson|concept]
  [--title "<short title>"] [--link <page_id> --rel <relation>]` —
  file new knowledge (idempotent: same title+category updates the
  existing memory). Link it to the pages it is about.
- `wikitoolkit note <page_id> "<text>"` — append an attributed,
  dated note to an existing page.
- `wikitoolkit link <src_id> <dst_id> --rel <relation>` — connect
  two pages with a typed, asserted edge.
- `wikitoolkit memories` — list saved memories;
  `wikitoolkit audit` — the attributed write log.

Save selectively: durable decisions, gotchas, and cross-file
relationships — not session chatter. Every write is attributed and
auditable.

The `/parrotwiki` command wraps these (e.g. `/parrotwiki query how
does ingest work`, `/parrotwiki remember <fact>`, `/parrotwiki --wiki`
to export a human-readable markdown wiki).
<!-- parrot:wiki:end -->
