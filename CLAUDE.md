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
implementation sanity checks. **Prefer `agy` (Google Gemini)** when
available; fall back to `codex` (OpenAI) otherwise.

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

**Detection — pick the first available:**
```bash
if command -v agy &>/dev/null; then REVIEWER="agy"
elif command -v codex &>/dev/null; then REVIEWER="codex"
else echo "No external reviewer CLI found"; fi
```

#### agy commands (preferred)
```bash
# Reviews
agy --sandbox --print "Review the uncommitted changes (run git diff). \
  Focus on correctness, security, async patterns, and project conventions. \
  Output findings with file:line references."
agy --sandbox --print "Review changes between current branch and dev \
  (run git diff dev...HEAD). List findings with file:line references."
agy --sandbox --print "Review commit <sha> (run git show <sha>). \
  List findings with file:line references."

# Opinions, brainstorming, and cross-checks
agy --sandbox --print "<neutral brief>" > <scratch-file>

# Follow-up in the same agy session
agy --continue --print "<question>"
```

#### codex commands (fallback)
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

- **Worktrees branch from `base_branch`** (which `/sdd-task` and `sdd-worker` ensure HEAD is on before creating the worktree). Hotfix worktrees branch from `main`; feature worktrees branch from `dev` or `staging` (during a release freeze).

## Worktree Creation

> **CRITICAL**: Do NOT use `claude --worktree`. It branches from the repo's default
> branch (`main`), which does not contain SDD artifacts.
>
> Always create worktrees manually from the current branch:

```bash
# Standard pattern: create worktree from current branch
git worktree add -b <branch-name> .claude/worktrees/<worktree-name> HEAD
```

> **Carve-out (FEAT-466): "from the current branch … `HEAD`" is shorthand,
> not the rule.** The actual rule is **worktrees branch from `base_branch`**
> (§ Git Configuration above). `HEAD` only works as shorthand when `HEAD`
> already *is* the intended base — true for `/sdd-task` and `sdd-worker`,
> which always `git checkout "$BASE_BRANCH"` immediately beforehand. It is
> **not** true for a hotfix: `sdd-research.md` branches
> `hotfix-<JIRA-KEY>-<slug>` explicitly from `origin/main`, regardless of
> what branch happens to be checked out in the main repo at the time (a
> hotfix must never inherit unreleased `dev` commits — this is the FEAT-466
> root cause, PR #1250). When base and `HEAD` might differ, name the ref
> explicitly:
> ```bash
> # Feature — from the base branch (dev, or staging during a freeze)
> git worktree add -b feat-<id>-<slug> .claude/worktrees/feat-<id>-<slug> origin/dev
> # Hotfix — ALWAYS from origin/main, never from HEAD/dev
> git worktree add -b hotfix-<JIRA-KEY>-<slug> .claude/worktrees/hotfix-<JIRA-KEY>-<slug> origin/main
> ```

### Quick reference

```bash
# From dev (most common)
git checkout dev
git worktree add -b feat-014-videoreel-visual-changes \
  .claude/worktrees/feat-014-videoreel-visual-changes HEAD

# From another feature branch (sub-features)
git checkout feat/ontology-rag
git worktree add -b feat-014-sub-task \
  .claude/worktrees/feat-014-sub-task HEAD

# Then launch Claude inside the worktree
cd .claude/worktrees/feat-014-videoreel-visual-changes
claude   # interactive, manual /sdd-start
# or
claude --agent sdd-worker --model sonnet --verbose
```

### Cleanup

```bash
# After PR merge
git worktree remove .claude/worktrees/<name>
# or prune all dead worktrees
git worktree prune
```

### .gitignore

```gitignore
.claude/worktrees/
```

## SDD Auto-Commit Rule

> **CRITICAL**: Every SDD command that creates or modifies files MUST commit
> them on the appropriate branch before finishing. Uncommitted files are
> invisible to worktrees and other sessions.

| Command | What it commits | Where (FEAT-145) |
|---------|-----------------|------------------|
| `/sdd-brainstorm` | `sdd/proposals/<n>.brainstorm.md` (with frontmatter) | `base_branch` |
| `/sdd-proposal`   | `sdd/proposals/<n>.proposal.md` (with frontmatter)  | `base_branch` |
| `/sdd-spec`       | `sdd/specs/<n>.spec.md` (with frontmatter) + a `reserve_ids.py` FEAT-ID reservation commit to `sdd/tasks/.id_ledger.json` (FEAT-387) | `base_branch` |
| `/sdd-task`       | `sdd/tasks/index/<feature>.json` + `sdd/tasks/active/TASK-*` + a `reserve_ids.py` TASK-ID reservation commit to `sdd/tasks/.id_ledger.json` (FEAT-387) | `base_branch` |
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

## Isolation Model

Worktrees isolate **features** from each other. Tasks within a feature run
sequentially in the same worktree via `/sdd-start TASK-<NNN>`.

```
Terminal 1 (in .claude/worktrees/feat-007):     Terminal 2 (in .claude/worktrees/feat-008):
  /sdd-start TASK-001 → commit                   /sdd-start TASK-010 → commit
  /sdd-start TASK-002 → commit (sees 001)         /sdd-start TASK-011 → commit
  /sdd-start TASK-003 → commit (sees 001+2)       /sdd-start TASK-012 → commit
  push, PR against dev                            push, PR against dev
```

## Typical Workflow

```bash
# 1. Ensure you're on dev with latest
git checkout dev && git pull origin dev

# 2. Create and approve a spec (committed to dev automatically)
/sdd-spec videoreel-visual-changes -- ...
/sdd-task sdd/specs/videoreel-visual-changes.spec.md

# 3. Create worktree from dev
git worktree add -b feat-014-videoreel-visual-changes \
  .claude/worktrees/feat-014 HEAD

# 4. Enter worktree and work
cd .claude/worktrees/feat-014

# Manual (task-by-task):
claude
/sdd-start TASK-069
/sdd-start TASK-070
/sdd-done FEAT-014

# Or autonomous:
claude --agent sdd-worker --dangerously-skip-permissions --model sonnet --verbose
/sdd-done FEAT-014

# 5. Push and PR
git push origin feat-014-videoreel-visual-changes
# Create PR against dev

# 6. Cleanup after merge
cd ~/proyectos/...   # back to main repo
git worktree remove .claude/worktrees/feat-014
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

### When NOT to Use Worktrees

- **Hotfixes on `main`**: Work directly on `main` or a short-lived `hotfix/*` branch.
- **Documentation-only changes**: No code conflicts possible, work on `dev` directly.
- **Single-task features**: If a spec has only one task, a worktree adds overhead
  with no benefit. Work directly on a feature branch.
- **Exploratory brainstorming**: `/sdd-brainstorm` doesn't produce code — no worktree needed.
- **Quick bug fixes**: If the fix is a single commit, skip the worktree ceremony.

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

Ids may come back qualified as `<namespace>::<id>` (e.g.
`asyncdb::file:pool.py`) when federated namespaces are configured
(FEAT-450) — local pages stay unprefixed. Pass a qualified id verbatim
to `page` / `related`; narrow a read with `--ns <name>|all|local`, and
see `wikitoolkit ns list` for what is registered. One such namespace is
`issues` — the Jira ticket corpus (FEAT-454); see
`docs/runbooks/jira-issues-namespace.md` for setup, the daily sweep, and
how to query it.

These same operations are also exposed as native MCP tools —
`wiki_query`, `wiki_page`, `wiki_related`, `wiki_remember`, `wiki_note`,
`wiki_status` — via the `wikitoolkit` MCP stdio server registered in
this repo's `.mcp.json` (FEAT-403). If they appear in your tool list,
prefer calling them directly; they have equal standing with Grep/Read
at tool-selection time instead of competing via a Bash-invoked CLI.

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
