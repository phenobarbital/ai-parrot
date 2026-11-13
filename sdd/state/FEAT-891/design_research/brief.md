<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
An agent needs three kinds of knowledge: what is true (knowledge), what matters now (context) and
what to do next (procedure). AI-Parrot answers the first well (Ontology, GraphIndex, PageIndex,
the wikitoolkit code graph) and the second partly (`GraphContextBuilder`, `UnifiedMemoryManager`,
the Experts `KnowledgeResolver`). The third is scattered and not queryable:

- **Skills** are text. An agent can load one, but cannot ask "which procedures apply to this
  state, and which step is valid next?".
- **Flows and crews** (`AgentsFlow`, `AgentCrew`) are executable code. They run, but nothing
  links them to the intent that should trigger them.
- **Governance rules** (Experts, `ALWAYS tool:x before tool:y`) are constraints with no link to
  the procedures they govern.
- **The SDD workflow** itself (`spec → task → start → codereview → done`) lives in prose
  (`WORKFLOW.md`, command files). Agents re-derive the valid next step from prose every session,
  and skip obligatory steps (reserve ids with the script, close a task with the script) when the
  prose is not in front of them.

Who is affected: SDD agents first (wrong step order, hand-rolled moves instead of the mandated
script), and later product agents, where some user intents need a fixed multi-step procedure that
an LLM does not get right at the first attempt.

What we want: procedures as nodes of one graph with typed edges, derived from files, with a
deterministic query — "given this state, which procedure applies and what is the valid next
step" — and an advisory injection of the answer where the agent is about to act. The SDD workflow
is the first graph, because its live state (per-spec index, ledger, git) is deterministic and
measurable.

### Constraints and goals
Decisions already taken by the owner during discovery (not to be re-litigated by `/sdd-spec`):

- **Approach is a unified pre-ask pipeline.** The procedure is resolved **before** facts and
  context, because its `requires` declares which facts and which live state are needed. Context
  selection then stops being similarity-driven.
- **Three procedure forms in one graph**: *constraint* (governance rules), *advisory* (the skill
  body is injected as guidance, the model decides) and *mandatory* (the node points to a flow or
  crew and the pipeline dispatches it).
- **Mandatory dispatch with external effects confirms through the existing HITL infrastructure**
  (`ConfirmationGuard`, `SUSPEND` / `HumanInteractionInterrupt`). Confirming a procedure is
  implicit acceptance of every tool the procedure declares; there is no per-tool confirmation
  inside a confirmed procedure.
- **Substrate is a wikitoolkit plane derived from files**, behind the wiki store contract. A
  central graph database is a follow-up (ArangoDB is being deprecated in ai-parrot).
- **Pilot is the SDD workflow.** In the pilot, mandatory procedures are **announced, not
  dispatched**.
- **Separate feature from FEAT-887 (`sdd-experience-memory`), depending on its hook pipeline**:
  no hooks of its own, one shared entry point, and confirmed pitfalls linked to a procedure with
  a `learned_from` edge.
- **Agents never write into the tier they read as authoritative.** Own episodes: yes. Results of
  a system-of-record API: as a cache with provenance and expiry. Inferences: only as candidates
  (`origin: inferred`, unreviewed) until promoted. For this feature: a learned procedure is never
  served as mandatory.
- **The SDD graph is declared in a manifest**, not in command frontmatter (accepted deviation
  from "skills with typed edges" for the SDD case; skill frontmatter stays the producer for
  parrot skills).
- **Preconditions are named, deterministic probes**, validated by lint. No free-form expressions.
- **Prompt-submit injection is out of the pilot.** The pilot injects at task start and before a
  guarded command only.
- **Five guarded commands in v1**: `parrot sdd task close`, `parrot sdd worktree ensure`,
  `gh pr create`, `git push`, and `mv` / `git mv` on `sdd/tasks/active/`.
- **The pilot is measured by task-state violations only**, before and after.
- **The manifest ships in the package assets** and is installed by `parrot sdd install`; a
  repo-local manifest may overlay it.
- **Host parity is inherited from FEAT-887**; this feature builds no host adapters.

Hard constraints from the codebase:

- A hook runs on every tool call: a miss must cost a few milliseconds (stdlib-only prefilter, no
  pydantic import, no SQLite open) — the FEAT-595 pattern in the wiki hook.
- A hook must emit `additionalContext` only. An `updatedInput` hook must be idempotent and can
  displace the sandbox wrapper.
- The wiki hook runtime accepts only `PreToolUse` today (`hook.py:182`). FEAT-887 registers
  `PreToolUse`, `PostToolUse` and `PostToolUseFailure` with matcher `Bash`; **no prompt-submit
  event exists in either**.
- SDD procedures are **command files, not parrot skills**: `.claude/commands/sdd-*.md` carries
  the host's own frontmatter (`model`, `description`), and each command has at least four source
  copies (`.claude/commands/`, `.agent/workflows/`, and both under
  `packages/ai-parrot/src/parrot/sdd/_assets/`).
- The plane is read at runtime from sandboxed worktrees: it must resolve through the shared root
  and need no write access.
- New `parrot sdd` helpers need a release smoke scenario, and CLI nouns follow
  `parrot sdd <noun> <verb>`.

### Recommended option / probable scope
A single `ProcedureSpec` model describes a node and its outgoing edges. Two producers feed it:

- **Skill frontmatter** for parrot skills (extends `SkillDefinition` with the optional graph
  fields) — the path product agents will use.
- **A manifest file** for procedures whose files the feature must not touch: one git-tracked
  YAML per graph (first: the SDD workflow), where each entry names the command, its graph fields
  and its edges. The command files and their twins stay unchanged.

Both are folded into a small overlay plane (`procedure.db`, the `schema.db` precedent: a
`SQLiteWikiStore` subclass in its own file under the wiki storage directory), and into a
**compiled JSON index** that the hook and the CLI read without opening SQLite. A deterministic
resolver takes a state (a mapping of named facts) and returns the applicable procedures and the
valid next steps. State comes from **named probes** (for SDD: task status, `depends_on` all
done, worktree clean, branch pushed, PR open), never from free-form expressions.

Surfaces: a CLI noun (`parrot sdd procedure next|show|list|check`), one MCP tool on the
wikitoolkit server, a lint pack (broken edge targets, `requires` cycles, unknown probes, missing
executor for a mandatory node), and advisory injection through FEAT-887's shared hook entry.

✅ **Pros:**
- Twins and host frontmatter are untouched; the SDD graph is one reviewable file.
- The same model serves product agents later through skill frontmatter, with no second design.
- The hook fast path is a small JSON read, in line with FEAT-595 and FEAT-887.
- The plane is read-only at runtime, so no sandbox change is needed.
- The plane sits behind the wiki store contract: moving to a central graph backend later is a
  backend swap.

❌ **Cons:**
- A manifest can drift from the command files it describes; a lint rule must check that every
  referenced command exists and that every `sdd-*` command is either in the manifest or listed
  as excluded.
- More new code than A: model, two producers, resolver, index, probes, CLI noun, lint pack.
- One more database file under the wiki storage directory.
- Deviates from the literal "frontmatter" wording for the SDD case (accepted by the owner).

📊 **Effort:** Medium–High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` v2 | `ProcedureSpec`, edge and probe models | core dependency; kept out of the hook fast path |
| `PyYAML` | manifest parsing | already a dependency |
| `python-frontmatter` | skill producer | already used by `parrot.skills.parsers` |
| `sqlite3` (stdlib) | overlay plane | same backend as the wiki |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/schema/` — overlay-plane precedent (`SchemaStore`, service, tools, toolkit)
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — `BaseWikiStore`, `edges`, `neighbors`
- `packages/ai-parrot/src/parrot/knowledge/lint/` — `LintRule` protocol and `default_rules`
- `packages/ai-parrot/src/parrot/skills/models.py`, `parsers.py` — `SkillDefinition`, `parse_skill_file`
- `packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py` — state checks to wrap as probes
- `packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py` — stdlib prefilter pattern
- FEAT-887 (planned) — `parrot sdd experience hook` entry point and the task-start briefing


**Option B** is recommended because:

- The pilot's procedures are command files with four or more copies and host-owned frontmatter.
  Option A turns every graph change into a multi-file edit plus twin-drift risk; a manifest makes
  the SDD graph one reviewable file. Skill frontmatter remains the producer for parrot skills, so
  the owner's "skills with typed edges" decision holds for product agents.
- The hook constraint (milliseconds, no SQLite) forces a compiled index in any option; B designs
  for it from the start.
- A dedicated overlay plane keeps procedure pages out of the code graph and its lint rules, and
  follows a precedent that already exists (`schema.db`).
- Option C's strength — one format for advisory and mandatory — is kept cheaply: a mandatory node
  carries `executor: {kind: flow, ref: ...}`, so the flow stays the executor without being the
  graph format.
- Option D is not discarded: observed transitions are the measurement for the pilot (how often a
  precondition was violated before and after), and later the source of candidate edges.

What is traded off: a manifest that can drift from the commands it describes (covered by lint),
and more new code than A.


### User-Facing Behavior

For the maintainer:

- The SDD workflow is described once, in a manifest: each command is a node with its mode,
  preconditions, required state and edges (`next`, `requires`, `alternative_to`, `on_failure`).
- `parrot sdd procedure list|show <id>` prints the graph; `parrot sdd procedure next` prints,
  for the current checkout or a given feature/task, the applicable procedures and the valid next
  steps, each with the preconditions that hold and those that do not.
- `parrot sdd procedure check` (and the lint pack inside `wikitoolkit lint`) reports broken edge
  targets, `requires` cycles, unknown probes, mandatory nodes with no executor, and `sdd-*`
  commands that are neither in the manifest nor excluded.

For an agent:

- **At task start**, next to the FEAT-887 pitfalls block, a short "Procedure" block: where the
  task is in the workflow, the next valid step and the mandatory steps ahead (for example: close
  the task with `parrot sdd task close`, never a hand-rolled move).
- **Before a guarded command** (a Bash command that a procedure node declares as its entry; the
  v1 set is the five listed under Constraints), an advisory when a precondition does not hold ("`depends_on` TASK-5583 is not done"). The command still runs as written.
- A mandatory node is announced as mandatory. Nothing is dispatched in the pilot.

### Internal Behavior

**Model.** A `ProcedureSpec` holds: id, title, kind (`skill` | `command` | `flow` | `crew` |
`rule`), mode (`advisory` | `mandatory` | `constraint`), intents, `applies_to` (entity types),
preconditions (named probes with expected values), `requires` (facts, state probes, other
procedures, tools), executor reference, confirm flag, source (`authored` | `learned`), and
outgoing edges. Edge relations: `applies_to`, `requires`, `next`, `alternative_to`,
`escalates_to`, `on_failure`, `learned_from`.

**Producers.** The skill producer reads the optional graph fields from skill frontmatter; a skill
without them is not a procedure node and behaves exactly as today. The manifest producer reads a
YAML file per graph. Both yield `ProcedureSpec` records; ids are namespaced by producer.

**Plane.** A build step folds the records into the overlay plane (pages with the spec as
attributes and a readable body, edges with `provenance` set to the producer) and writes the
compiled index: procedures by id, by guarded command, by intent keyword, with their
preconditions and edges. The build is idempotent and keyed by content hash.

**State and probes.** A probe is a named, deterministic function from a scope (repository,
feature, task) to a value. The SDD probe set wraps what already exists: task status and
`depends_on` from the per-spec index, task-state violations, worktree status, branch pushed, PR
open. A precondition whose probe is unknown or fails to run is reported as *unknown*, never as
satisfied.

**Resolver.** Given a scope, it evaluates probes lazily (only those the candidate procedures
name), keeps the procedures whose preconditions hold or are the nearest unmet, orders them by the
`next` edges from the last completed step, and returns a bounded list. No LLM call.

**Injection.** No new hook registration. The shared FEAT-887 entry point calls the resolver on
its pre-tool path when the leading executable is in the index's guarded-command set, and the
task-start briefing gains a procedure block. Every injection is `additionalContext`, bounded and
templated.

**Link to FEAT-887.** A confirmed pitfall whose scope matches a procedure's guarded command gets
a `learned_from` edge from the procedure to the lesson. The procedure block lists at most a few
linked pitfalls. The edge is declared by this feature and resolved only when the FEAT-887 plane
is present.

**Mandatory and confirm in the pilot.** `mode: mandatory`, `executor` and `confirm` are parsed,
stored, linted and shown. They change the wording of the advisory and nothing else.

### Edge Cases & Error Handling

- **Stale plane**: the index records the content hash of its sources; when a source changed, the
  CLI says so and the hook stays silent instead of advising from a stale graph.
- **No procedure matches**: nothing is injected.
- **Several match**: ordered by priority, capped; the cap is part of the template.
- **Loops**: `next` cycles are legal (`codereview → start` after findings). Lint flags cycles
  only in `requires`.
- **Unknown or failing probe**: precondition reported as unknown; the advisory says it could not
  be checked.
- **Learned procedures**: stored with `source: learned`, shown only as candidates, never
  announced as mandatory and never given a `confirm` grant.
- **Worktrees and sandbox**: the plane and index are read through the shared root; no write is
  needed at runtime, so no sandbox path is added.
- **Hook failure**: always exit 0 with no output; a procedure advisory can never block a tool
  call.
- **Injection safety**: authored procedures come from git-tracked files and are trusted like
  command files; text from `learned_from` lessons follows FEAT-887's rules (bounded, templated,
  redacted).

### Out of scope — follow-ups to record

- Prompt-submit injection (needs an event that neither the wiki hook nor FEAT-887 registers).
- Mandatory dispatch with HITL confirmation in product agents (procedure-level grant covering
  the declared tools).
- In-process delegation between agents without A2A: a `delegate` outcome of the pipeline through
  `AgentRegistry`, passing the resolved envelope; a router is an agent whose pipeline ends at the
  decision. Open points: the `spawn_sub_agent` deny rule of Experts, conversation-turn
  ownership, permission propagation, a depth limit.
- The pre-ask pipeline inside `IntentRouterMixin`.
- Knowledge and context layers for product agents (Ontology, GraphIndex, PageIndex,
  `UnifiedMemoryManager` / `ContextAssembler`, the Experts `KnowledgeResolver`).
- Central graph backend replacing the SQLite overlay.
- Promotion path learned skill → candidate procedure → authored procedure → flow.

---

### Verified code anchors (paths only — open them yourself)
.agent/workflows/sdd-start.md
.claude/commands/sdd-start.md
packages/ai-parrot/src/parrot/auth/confirmation.py
packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py
packages/ai-parrot/src/parrot/knowledge/lint/rule.py
packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py
packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py
packages/ai-parrot/src/parrot/knowledge/wiki/store.py
packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md
packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md
packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py
packages/ai-parrot/src/parrot/skills/models.py
packages/ai-parrot/src/parrot/skills/parsers.py
sdd/installer.py
sdd/scripts/experience_hook.py
sdd/scripts/native_claude_sandbox.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
