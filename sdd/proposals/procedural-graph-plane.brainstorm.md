---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [sdd-tooling, procedural-graph, wikitoolkit, skills, hooks, agent-knowledge]
---

# Brainstorm: Procedural Graph Plane (`procedure`)

**Date**: 2026-11-13
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

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

## Constraints & Requirements

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

---

## Options Explored

### Option A: Frontmatter in place, pages in the main wiki plane

Every procedure file declares its own graph fields in frontmatter (`mode`, `intents`,
`applies_to`, `preconditions`, `requires`, `executor`, `next`, `on_failure`, `confirm`).
`wikitoolkit build` parses them and writes one page per procedure into the main wiki
(`category="procedure"`) plus typed rows in the existing `edges` table. Queries reuse
`neighbors(rel=...)` and `search_fts(category=...)`.

✅ **Pros:**
- Smallest amount of new machinery: the `edges` table already has an open `rel` column and a
  `provenance` column.
- A procedure and its graph data live in one file; nothing to keep in sync.
- Matches the owner's wording literally ("skills with typed edges").

❌ **Cons:**
- SDD commands have four or more copies each; every frontmatter change is a four-file edit, and
  the twin-drift tests would have to cover the new keys.
- The command frontmatter belongs to the host (Claude Code, agy, codex). Unknown keys there are
  not verified to be ignored by every host.
- The hook would need the 920 MB main wiki database to answer "what is next" unless a compiled
  index is added anyway.
- `wikitoolkit build` and its lint rules would have to learn a new page category inside the code
  graph.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `python-frontmatter` | parse the declarations | already used by `parrot.skills.parsers` |
| `sqlite3` (stdlib) | storage | the wiki backend |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/skills/parsers.py` — `parse_skill_file`
- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py` — `edges` table, `add_edges`, `neighbors`

---

### Option B: One procedure model, two producers, a dedicated overlay plane and a compiled index

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
- Deviates from the literal "frontmatter" wording for the SDD case (flagged as an open question).

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

---

### Option C: `FlowDefinition` as the graph, read instead of executed

Declare every procedure as an `AgentsFlow` `FlowDefinition` (nodes, edges, predicates). A
"consultative reader" walks the definition against the current state and reports the reachable
next nodes without running anything. Mandatory procedures later execute the same definition.

✅ **Pros:**
- One format for advisory and mandatory: no translation step when a procedure is promoted to an
  executed flow.
- Predicates, OR-joins and skip-propagation already exist and are tested.

❌ **Cons:**
- `FlowDefinition` describes agent nodes inside one run, not standalone procedures with intents,
  entity types and cross-procedure edges; the fields this feature needs are not there.
- It pulls the `parrot.bots` stack into wikitoolkit and into the hook path, which a ledger issue
  already reports as a problem for CLI start-up cost.
- Authoring a flow definition for a five-line advisory skill is heavy.
- The SDD workflow steps are host commands, not agents.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | reuses `parrot.bots.flows` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/bots/flows/flow/definition.py` — `FlowDefinition`

---

### Option D: No authored graph — mine the transitions from history

Infer the procedure graph from what agents actually did: per-spec index timestamps, ledger
events, commit messages and session transcripts give observed transitions and their frequency.
The graph is whatever the history shows.

✅ **Pros:**
- No authoring and no drift: the graph is always what really happens.
- Surfaces the real deviations, which are the cases the owner wants to "settle".

❌ **Cons:**
- It describes behavior, not the rule: a frequent wrong path becomes an edge.
- It cannot mark a step as mandatory, and cannot state a precondition nobody has violated yet.
- Needs durable per-step logs that most seats do not have.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| none new | — | stdlib JSONL parsing |

🔗 **Existing Code to Reuse:**
- `sdd/tasks/index/*.json`, `sdd/ledger/events.jsonl` — observed state changes

---

## Recommendation

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

---

## Feature Description

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
- **Before a guarded command** (a Bash command that a procedure node declares as its entry, for
  example `parrot sdd task close`, `gh pr create`, `git push`), an advisory when a precondition
  does not hold ("`depends_on` TASK-5583 is not done"). The command still runs as written.
- **On prompt submit**, when the prompt names an SDD command or an intent a node declares, the
  applicable procedure and its unmet preconditions. Advisory only.
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
task-start briefing gains a procedure block. The prompt-submit injection needs one more event on
that shared entry (see Open Questions). Every injection is `additionalContext`, bounded and
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

## Capabilities

### New Capabilities
- `procedure-spec-model`: one model for a procedure node, its preconditions and typed edges.
- `procedure-producers`: skill-frontmatter producer and manifest producer.
- `procedure-plane`: overlay plane plus compiled index, built idempotently from the producers.
- `procedure-resolver`: deterministic "applicable procedures and valid next steps" over named probes.
- `procedure-lint`: broken edges, `requires` cycles, unknown probes, missing executors, manifest coverage.
- `sdd-procedure-graph`: the SDD workflow manifest and the SDD probe set.
- `procedure-advisory-injection`: procedure block at task start, pre-command advisory, prompt-submit advisory.

### Modified Capabilities
- `agent-skill-system`: optional graph fields in skill frontmatter and `SkillDefinition`.
- `sdd-experience-memory` (FEAT-887): shared hook entry calls the resolver; briefing gains a procedure block; `learned_from` edges.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot.knowledge.wiki` (new `procedure` subpackage) | extends | overlay plane, service, tools; lazy exports like `schema` |
| `parrot.knowledge.lint.packs` | extends | new rule pack added to `default_rules` |
| `parrot.skills.models` / `parsers` | modifies | optional fields only; skills without them are unchanged |
| `parrot.sdd` (CLI noun, probes, manifest) | extends | `parrot sdd procedure <verb>`; release smoke scenario required |
| wikitoolkit MCP server | extends | one read-only tool |
| FEAT-887 hook runtime and briefing | depends on | not implemented yet (spec approved, no tasks); ordering matters |
| `.claude/commands/sdd-*.md` and twins | none | untouched under Option B |
| Sandbox policy | none | plane is read-only at runtime |

---

## Code Context

Verified at `f3d1b420b6` by reading the files. Imports were checked as module paths, not executed.

### User-Provided Code

```yaml
# Source: discussion (illustrative frontmatter agreed with the owner; not existing code)
mode: mandatory            # or advisory
intents: [refund_request]
applies_to: [Order, Customer]
preconditions: ["order.status == 'delivered'"]
requires: [fact:refund_policy, state:order_api.get_order]
executor: {kind: flow, ref: refund_flow}
next: [notify_customer]
on_failure: escalate:billing-expert
```

### Verified Codebase References

#### Classes & Signatures
```python
# packages/ai-parrot/src/parrot/skills/models.py:68
class SkillDefinition(BaseModel):
    name: str                                   # :75
    description: str                            # :76
    triggers: list[str]                         # :77
    source: SkillSource = SkillSource.AUTHORED  # :78  (AUTHORED | LEARNED, :53)
    priority: int = 90                          # :79
    version: str = "1.0"                        # :80
    category: str | None = None                 # :81
    template_body: str                          # :82
    token_count: int                            # :83
    file_path: Path                             # :84
    assets_dir: Path | None                     # :85
    global_only: bool                           # :89
    suggestions: list[SkillSuggestion]          # :93
    MAX_TOKENS: ClassVar[int] = 1000            # :98

# packages/ai-parrot/src/parrot/skills/parsers.py:69
def parse_skill_file(file_path: Path) -> SkillDefinition: ...   # raises ValueError when 'triggers' key is absent (:94)

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py:870
class BaseWikiStore(ABC):
    async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int: ...  # :907
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...                                         # :917
    async def add_edges(self, edges: list[tuple]) -> int: ...                                                     # :920
    async def search_fts(self, query: str, category: Optional[str] = None, limit: int = 10) -> list[dict[str, Any]]: ...  # :949
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]: ...  # :955

# packages/ai-parrot/src/parrot/knowledge/wiki/schema/store.py:48
class SchemaStore(SQLiteWikiStore): ...        # overlay plane; file is plane_dir / "schema.db" (schema/service.py:67)

# packages/ai-parrot/src/parrot/knowledge/wiki/claude_code/hook.py
def _prefilter_rejects(payload: dict[str, Any]) -> bool: ...     # :166; rejects any event other than PreToolUse (:182)
def build_nudge(payload, root=None, config=None, now=None) -> Optional[dict[str, Any]]: ...  # :193
def run_pre_tool_use_hook(stdin=None, stdout=None) -> int: ...   # :250; always returns 0

# packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py:12
def default_rules(options: "LintOptions") -> list["LintRule"]: ...
# packages/ai-parrot/src/parrot/knowledge/lint/rule.py:22
class LintRule(Protocol): ...

# packages/ai-parrot/src/parrot/auth/confirmation.py:378
class ConfirmationGuard:
    async def confirm(...): ...        # :417
    async def _ask_approval(...): ...  # :594

# packages/ai-parrot/src/parrot/sdd/scripts/check_task_state.py:98
def find_violations(*, index_dir: Path, active_dir: Path, completed_dir: Path) -> list[TaskStateViolation]: ...
```

#### Verified Imports
```python
from parrot.skills.models import SkillDefinition, SkillSource          # skills/models.py:68, :53
from parrot.skills.parsers import parse_skill_file                     # skills/parsers.py:69
from parrot.knowledge.wiki.store import BaseWikiStore, SQLiteWikiStore # wiki/store.py:870, :1265
from parrot.knowledge.wiki.schema.store import SchemaStore             # wiki/schema/store.py:48
from parrot.knowledge.lint.packs import default_rules                  # lint/packs/__init__.py:12
from parrot.bots.flows.flow.definition import FlowDefinition           # flows/flow/definition.py:377
from parrot.bots.mixins.intent_router import IntentRouterMixin         # mixins/intent_router.py:130
from parrot.core.exceptions import HumanInteractionInterrupt           # core/exceptions.py:12
from parrot.auth.confirmation import ConfirmationGuard                 # auth/confirmation.py:378
from parrot_tools.wiki.tools import create_wiki_tools                  # ai-parrot-tools/.../wiki/tools.py:608
```

#### Key Attributes & Constants
- `edges` table → `(src, dst, rel DEFAULT 'references', provenance DEFAULT 'extracted')`, primary key `(src, dst, rel)` (`wiki/store.py:147`)
- Edge tuples are `(src, dst, rel, provenance)`; asserted edges use provenance `"asserted"` (`wiki/operations.py:406`)
- `wikitoolkit link` → `def link(` (`wiki/cli.py:5130`); `wikitoolkit lint` → `@wiki.command("lint")` (`wiki/cli.py:2352`); `claude-hook` (`wiki/cli.py:6718`)
- `SkillFileToolkit.save_learned_skill` (`skills/tools.py:552`, class at `:381`)
- `TaskScopedBrief` (`flows/dev_loop/models/base.py:478`), `DevelopmentOutput` (`:527`) — where FEAT-887 adds `experience_briefing`
- `native_sandbox_settings` (`sdd/scripts/native_claude_sandbox.py:410`), `_install_dangerous_guard` (`sdd/installer.py:399`) — FEAT-887's hook wiring sites
- Experts rules: `parse_rules` (`experts/rules.py:18`), `resolve_chain` (`:63`)
- SDD command sources: `.claude/commands/sdd-start.md`, `.agent/workflows/sdd-start.md`, `packages/ai-parrot/src/parrot/sdd/_assets/claude/commands/sdd-start.md`, `packages/ai-parrot/src/parrot/sdd/_assets/agent/workflows/sdd-start.md`; frontmatter keys are `model` and `description`

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.wiki.procedure`~~ / ~~`procedures`~~ — no such package; no file under `knowledge/wiki/` mentions procedures
- ~~`parrot.knowledge.wiki.experience`~~ — planned by FEAT-887, not implemented
- ~~`parrot/sdd/scripts/experience_hook.py`~~ and ~~`parrot sdd experience …`~~ — planned by FEAT-887, not implemented; FEAT-887 has no task index yet
- ~~`SkillDefinition.applies_to` / `.preconditions` / `.executor` / `.on_failure` / `.mode` / `.intents`~~ — none of these fields exist
- ~~`UserPromptSubmit` handling~~ — no Python file under `packages/ai-parrot/src/parrot` references it; FEAT-887 does not register it either
- ~~`WikiPageCategory.PROCEDURE`~~ — the enum has no such member (`wiki/models.py:27`)
- ~~`parrot sdd procedure`~~ — no such CLI noun
- ~~A "consultative" reader for `FlowDefinition`~~ — flows are only executed

---

## Parallelism Assessment

- **Internal parallelism**: moderate. The model comes first. After it, the two producers, the
  lint pack and the SDD probe set are independent of each other; the plane and resolver depend on
  the model only; CLI, MCP tool and injection depend on the resolver.
- **Cross-feature independence**: conflicts with FEAT-887 on the shared hook entry, the
  task-start briefing (`TaskScopedBrief`, `sdd-start.md` and twins) and
  `native_claude_sandbox.py` / `installer.py` if a prompt-submit event is added. The injection
  tasks must start after FEAT-887's hook runtime and briefing are merged. `skills/models.py` and
  `parsers.py` are also touched by skill features; the change there is additive.
- **Recommended isolation**: `per-spec`.
- **Rationale**: the tasks share one small model and one resolver, and the injection tasks are
  serialized behind FEAT-887 anyway. Sub-worktrees for the producers, lint pack and probes are
  possible but buy little.

---

## Open Questions

- [x] Are procedures advisory, or are there mandatory stretches? — *Owner: Jesus Lara*: both; mandatory procedures point to a flow/crew and are dispatched by the pipeline; advisory ones are injected as guidance.
- [x] Does a mandatory dispatch confirm with the user? — *Owner: Jesus Lara*: yes, through the existing HITL infrastructure (suspend until the user answers) when the procedure has external effects.
- [x] Granularity of the confirmation? — *Owner: Jesus Lara*: confirming a procedure is implicit acceptance of all the tools it declares; no per-tool confirmation.
- [x] Where does the graph live? — *Owner: Jesus Lara*: a wikitoolkit plane for now; a central graph database is a follow-up (ArangoDB is being deprecated).
- [x] Pilot: SDD workflow or a product expert? — *Owner: Jesus Lara*: the SDD workflow; it is deterministic and measurable.
- [x] One feature with FEAT-887 or two? — *Owner: Jesus Lara*: two; this one depends on FEAT-887's hook pipeline.
- [x] When may an agent write facts? — *Owner: Jesus Lara*: never in the authoritative tier; own episodes yes, system-of-record API results as cache, inferences only as candidates.
- [ ] Option B declares the SDD graph in a manifest instead of command frontmatter (commands have four or more copies and host-owned frontmatter). Is that deviation from "skills with typed edges" accepted for the SDD case? — *Owner: Jesus Lara*
- [ ] Prompt-submit injection needs an event neither the wiki hook nor FEAT-887 registers. Add it to FEAT-887's shared entry (a change to an approved spec), add it in this feature on top of that entry, or drop it from the pilot and keep task-start plus pre-command? — *Owner: Jesus Lara*
- [ ] Preconditions as named probes (recommended: deterministic, lintable) or as expressions (`order.status == 'delivered'`, as in the illustrative frontmatter)? — *Owner: Jesus Lara*
- [ ] Which commands are guarded in v1 (candidates: `parrot sdd task close`, `parrot sdd ids reserve`, `parrot sdd worktree ensure`, `gh pr create`, `git push`)? — *Owner: Jesus Lara*
- [ ] How is the pilot measured: task-state violations and hand-rolled closes before and after, advisories fired versus followed, or both? — *Owner: Jesus Lara*
- [ ] Does the manifest ship in the package assets (so `parrot sdd install` gives every repo the SDD graph) or stay repo-local in the pilot? — *Owner: Jesus Lara*
- [ ] Hosts other than Claude Code (codex, agy, in-process seats): same parity rule as FEAT-887 in v1, or Claude Code first? — *Owner: Jesus Lara*
