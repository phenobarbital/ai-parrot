---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-tools]
tags: [sdd-tooling, procedural-graph, wikitoolkit, skills, hooks, agent-knowledge]
docs:
  policy: required
  pages:
    - wiki/sdd-tooling/sdd/procedure-graph.md
  api_modules:
    - parrot.knowledge.wiki.procedure
---

# Feature Specification: Procedural Graph Plane (`procedure`)

**Feature ID**: FEAT-891
**Date**: 2026-11-13
**Author**: Jesus Lara
**Status**: approved
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

An agent needs three kinds of knowledge: what is true (knowledge), what matters now (context) and
what to do next (procedure). AI-Parrot answers the first well and the second partly. The third is
scattered and not queryable:

- **Skills** are text. An agent can load one, but cannot ask "which procedures apply to this
  state, and which step is valid next?".
- **Flows and crews** are executable code, with nothing linking them to the intent that should
  trigger them.
- **Governance rules** (Experts) are constraints with no link to the procedures they govern.
- **The SDD workflow** (`spec → task → start → codereview → done`) lives in prose. Agents
  re-derive the valid next step from prose every session, and skip obligatory steps (close a task
  with the script, open a feature PR against the right base) when the prose is not in front of
  them.

Affected: SDD agents first; later product agents, where some intents need a fixed multi-step
procedure an LLM does not get right at the first attempt.

### Goals

- G1. One model for a procedure node — mode, typed requirements, preconditions, completion
  condition, typed edges — independent of how the procedure is implemented.
- G2. Two producers of that model: a git-tracked manifest (first: the SDD workflow) and optional
  graph fields in skill frontmatter. A skill without the fields behaves exactly as today.
- G3. A derived plane: a wikitoolkit store (`procedure.db`) plus a compiled JSON index, built
  idempotently from the producers and published atomically.
- G4. A deterministic resolver: given a scope, return the applicable procedures, the valid next
  steps and, for each, which preconditions hold, fail or could not be checked. No LLM call.
- G5. Preconditions are **named probes** with a declared cost class; no free-form expressions.
- G6. Surfaces: `parrot sdd procedure build|list|show|next|check|brief`, one MCP tool, a lint
  pack.
- G7. The SDD workflow is the first graph, shipped in the package assets, installed by
  `parrot sdd install`, with a repo-local overlay.
- G8. Guard integration on **existing** pre-tool guards, with no new hook registration: a
  mandatory node whose guarded command violates the procedure is **denied**, naming the correct
  command; every other guarded command gets an advisory.
- G9. A procedure block at task start, next to the FEAT-887 pitfalls block.
- G10. The pilot is measured by task-state violations (`check_task_state`), before and after.

### Non-Goals (explicitly out of scope)

- Dispatching a mandatory procedure (running its flow or crew). `executor` and `confirm` are
  parsed, validated and shown; they authorize nothing in v1.
- Prompt-submit injection — no host event is registered for it.
- A new hook registration on any host. Codex and agy get no guard integration in v1 (their
  pre-tool hooks are different programs); they receive the task-start block only.
- Measuring "advisories fired versus followed" (needs an event log).
- A cached local signal for "a PR already exists for this branch". `pr.open` stays `remote`
  and CLI-only in v1; the cached signal was judged worthwhile (Jesus Lara, 2026-11-13) and is
  a follow-up.
- Declaring the SDD graph in command frontmatter — rejected in brainstorm (Option A): each
  command has four or more copies and host-owned frontmatter.
- `FlowDefinition` as the graph format (Option C) and a graph mined from history (Option D).
- In-process agent delegation, the pre-ask pipeline inside `IntentRouterMixin`, knowledge and
  context layers for product agents, and a central graph backend — follow-ups.
- Automatic registration of the plane as a wiki namespace; the operator runs
  `wikitoolkit ns add` (documented in §10).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:b4708de574a95ebd3fb33e7e78e7cf2020e0866939f14ce463527960fe1abe57 evaluation_digest=sha256:7ed8e053931de2ce64d1b3a253924b62ae32aadb7e16c97d84170faa49eee5f9 rules_version=1 status=pass -->

## 2. Architectural Design

### Overview

**One model, two producers.** `ProcedureSpec` describes a node. The manifest producer reads
`sdd/procedures/*.yaml`; the skill producer reads optional graph fields from skill frontmatter.
Ids are namespaced by producer (`sdd:<name>`, `skill:<name>`).

**Three forms in one graph.** `mode` is `advisory` (guidance, the agent decides), `mandatory`
(the procedure must be used; violating commands are denied by the guard) or `constraint`
(reserved for governance rules; parsed and stored, not produced in v1).

**Typed requirements** (design research S4). A node does not have one mixed `requires` list. It
has `requires_procedures` (ids — the only field that forms the `requires` graph), `requires_facts`
(free identifiers, informational in v1), `requires_tools` (tool names, informational in v1) and
`preconditions` (probe checks).

**Position is derived, not recorded** (S8). There is no log of completed steps. Each node
declares `done_when`, a list of probe checks. A node is *done* when all of them hold. The valid
next steps are the nodes that are not done and whose `requires_procedures` are all done. With no
history at all the answer is still deterministic.

**Probes.** A probe is a named, deterministic function `(scope, args) -> True | False | None`
(`None` = unknown). Each has a cost class: `local` (reads files in the checkout or the
environment, no subprocess, no network) or `remote` (may run `gh` or `git` with a timeout).
An unknown result never satisfies a precondition and never causes a denial.

| Probe | Cost | True when |
|---|---|---|
| `spec.exists` | local | `sdd/specs/<feature>.spec.md` exists |
| `index.exists` | local | `sdd/tasks/index/<feature>.json` exists |
| `task.status` | local | the task's index `status` equals `expect` |
| `task.depends_done` | local | every id in the task's `depends_on` is `done` |
| `feature.tasks_done` | local | every task of the feature is `done` or `done-with-issues` |
| `flow.base_allowed` | local | the command's `--base` is not `hotfix_base` while the current branch is a `feat-*` / `fix-*` branch; unknown when `--base` is absent |
| `env.not_worker_sandbox` | local | neither launcher marker variable is set |
| `branch.pushed` | remote | the branch has an upstream and is not ahead of it |
| `pr.open` | remote | `gh pr list --head <branch>` returns a PR |

**Guards.** A node may declare guards — shell commands that relate to it:

- `entry`: the command *is* the procedure's entry (`parrot sdd task close`). The node's local
  preconditions are evaluated against the scope read from the command line.
- `bypass`: the command *replaces* the procedure by hand (`mv` / `git mv` of a file under
  `sdd/tasks/active/`). It is a violation by itself; the node names the command to use instead.

Guard decision, in the hook:

| Node mode | Guard kind | Local preconditions | Result |
|---|---|---|---|
| mandatory | bypass | — | **deny**, reason names `use_instead` |
| mandatory | entry | at least one definitely false | **deny**, reason lists the unmet preconditions |
| mandatory | entry | none false (true or unknown) | advise only when something is unknown |
| advisory | entry / bypass | any false or unknown | advise |
| any | any | all true | nothing |

Only a denial reaches the model before the command runs. Advisory text
(`additionalContext`) reaches it after the command has run (FEAT-887 adversarial review F12;
not re-verified here), so an advisory is worded as a correction, not a warning.
`PARROT_ALLOW_PROCEDURE=1` turns every denial into an advisory; `PARROT_ALLOW_DANGEROUS=1` and
`procedure.enforce: false` in `sdd/config.json` do the same.

**v1 guarded commands** (owner decision):

| Command | Node | Mode | Guard | Checked |
|---|---|---|---|---|
| `mv` / `git mv` of `sdd/tasks/active/*` | `sdd:task-close` | mandatory | bypass | — (use `parrot sdd task close`) |
| `gh pr create` | `sdd:pr-create` | mandatory | entry | `flow.base_allowed` (deny); `pr.open` is remote → CLI only |
| `parrot sdd task close` | `sdd:task-close` | mandatory | entry | `task.status == in-progress`, `task.depends_done` |
| `parrot sdd worktree ensure` | `sdd:worktree-ensure` | advisory | entry | `spec.exists`, `index.exists` |
| `git push` | `sdd:push` | advisory | entry | `env.not_worker_sandbox` |

**Plane and index.** `parrot sdd procedure build` folds the specs into
`<shared-root>/.parrot/procedure/`:

- `procedure.db` — a plain wiki store (`create_wiki_store`), one page per node
  (`category="procedure"`, spec fields in `page_attrs`, a readable body), one source slice per
  producer file (`replace_source_slice`), edges added with `provenance` = producer name.
- `procedures.json` — the compiled index the hook and the CLI fast path read. Written to a temp
  file in the same directory and published with `os.replace` (S3). It carries `schema_version`,
  a `generation` digest and the sha1 of every source file. A reader that finds a missing file,
  an unknown schema version or a source whose sha1 differs treats the plane as **stale**: the
  hook does nothing; the CLI rebuilds when the directory is writable, else says so.

`<shared-root>` is the primary checkout, so every worktree reads the same plane. Nothing is
written at hook time, so no sandbox path is added. Builds run from `parrot sdd install`, from
any `parrot sdd procedure` verb that finds the plane stale, and by hand.

**Sources.** `sdd/procedures/sdd-workflow.yaml` is a packaged asset installed by
`parrot sdd install`. Any other `sdd/procedures/*.yaml` is a repo overlay: it may add nodes and
list `exclude:` ids. Sources are read from the primary checkout.

**Guard integration (no new hook).** A stdlib-only module, `procedure_advice`, is called from the
two pre-tool guards that already run for Bash in Claude Code:

- `dangerous_actions.main` — interactive sessions and their subagents;
- `worktree_environment.hook_response` — launched workers.

A denial from either existing guard wins; the procedure check runs only when the guard allows.
Codex (`parrot_tools.tool_optimizations.hooks`) and agy (`agy_permissions`) are not touched.

**Task-start block.** `parrot sdd procedure brief --task-file <task.md>` prints a short block:
where the task is, the next valid step, and the mandatory rules ahead. It is delivered through
FEAT-887's briefing path (§3 M11) and is the only part of this feature that depends on FEAT-887.

**`learned_from`.** The edge relation is reserved and accepted by the model and the validator.
No producer emits it in v1; linking confirmed pitfalls needs the FEAT-887 plane and is a
follow-up.

**Design research.** Ten suggestions from the codex seat, all folded in (§9).

### Component Diagram

```
 sdd/procedures/*.yaml ──┐                        ┌──→ procedure.db   (wiki store, MCP tool, wikitoolkit query)
 skill frontmatter ──────┼─→ producers ─→ specs ──┤
                         │        │               └──→ procedures.json (atomic publish)
                         │        └─→ validate ──→ `procedure check`, lint pack        │
                         │                                                             │ read-only
 dangerous_actions.main ─────────────┐                                                 ▼
 worktree_environment.hook_response ─┴─→ procedure_advice (stdlib) ─→ local probes ─→ deny | advise | nothing

 parrot sdd procedure next|brief ─→ resolver ─→ probes (local + remote) ─→ Resolution
 FEAT-887 briefing path ──────────→ procedure brief
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `SkillDefinition` / `parse_skill_file` | extends | optional `procedure` field; parser copies and validates it (S5) |
| `create_wiki_store`, `replace_source_slice`, `add_edges`, `upsert_attrs` | uses | no store subclass (S6) |
| `find_shared_root` | uses | plane location; the hook re-states it in stdlib |
| `parrot.knowledge.lint` (`LintRule`, `default_rules`) | extends | new pack `procedure` |
| `parrot sdd` CLI `VERBS` | extends | noun `procedure` |
| `SddConfig` | extends | optional `procedure` section (`extra="forbid"` today) |
| `dangerous_actions.main` | modifies | procedure check after an `allow` / `warn` verdict |
| `worktree_environment.hook_response` | modifies | procedure check for Bash when not denied |
| `native_claude_sandbox._control_files` | modifies | protect `procedure_advice.py` |
| SDD asset manifest, `pyproject.toml` package data, `install_sdd_integration` | extends | one asset, one install step (S10) |
| wiki MCP server (framework and SDK transports) | extends | tool `wiki_procedure_next` |
| FEAT-887 briefing path | depends on | M11 only; not merged |

### Data Models

```python
ProcedureMode = Literal["advisory", "mandatory", "constraint"]
ProcedureKind = Literal["command", "skill", "flow", "crew", "rule"]
ProcedureSource = Literal["authored", "learned"]
EdgeRel = Literal["requires", "next", "alternative_to", "escalates_to", "on_failure", "learned_from", "applies_to"]
ProbeCost = Literal["local", "remote"]
GuardKind = Literal["entry", "bypass"]

class ProbeCheck(BaseModel):
    probe: str                              # registered probe name
    expect: bool | str = True               # compared with the probe's value
    args: dict[str, str] = {}

class ScopeArg(BaseModel):                  # where a guard reads a scope value from the command line
    argv: int | None = None                 # positional index after argv_prefix
    flag: str | None = None                 # e.g. "--base"; exactly one of argv / flag

class GuardSpec(BaseModel):
    kind: GuardKind
    executable: str                         # basename, e.g. "parrot", "gh", "mv", "git"
    argv_prefix: list[str] = []             # e.g. ["sdd", "task", "close"]; for git mv: ["mv"]
    path_globs: list[str] = []              # bypass: any argument must match one (repo-relative, fnmatch)
    scope: dict[str, ScopeArg] = {}         # keys: "task", "feature", "base"

class ExecutorRef(BaseModel):
    kind: Literal["flow", "crew", "command"]
    ref: str

class ProcedureSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str                                 # "<producer>:<name>", kebab-case name
    title: str
    kind: ProcedureKind
    mode: ProcedureMode = "advisory"
    source: ProcedureSource = "authored"
    command: str = ""                       # human-readable invocation, e.g. "parrot sdd task close <TASK> <slug> verified"
    intents: list[str] = []
    applies_to: list[str] = []              # entity type names
    scope_kind: Literal["repo", "feature", "task"] = "feature"
    preconditions: list[ProbeCheck] = []
    done_when: list[ProbeCheck] = []
    requires_procedures: list[str] = []
    requires_facts: list[str] = []
    requires_tools: list[str] = []
    next: list[str] = []
    alternative_to: list[str] = []
    escalates_to: list[str] = []
    on_failure: list[str] = []
    learned_from: list[str] = []
    guards: list[GuardSpec] = []
    use_instead: str = ""                   # required when any guard is "bypass"
    executor: ExecutorRef | None = None     # inert in v1
    confirm: bool = False                   # inert in v1
    advice: str = ""                        # <= 300 chars, shown in advisories and the briefing
    body: str = ""                          # page body (skill body or manifest description)
    origin_path: str = ""                   # repo-relative source file

class ProcedureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    graph: str                              # producer prefix, e.g. "sdd"
    exclude: list[str] = []                 # overlay only: ids removed from the merged graph
    procedures: list[ProcedureSpec] = []    # ids written without the prefix; the producer adds it

class ProbeResult(BaseModel):
    check: ProbeCheck
    value: bool | None                      # None = unknown
    cost: ProbeCost
    detail: str = ""

class ResolvedProcedure(BaseModel):
    spec: ProcedureSpec
    done: bool | None
    ready: bool                             # every requires_procedures is done
    preconditions: list[ProbeResult]

class Resolution(BaseModel):
    scope: dict[str, str]                   # "feature", "task", "branch"
    stale: bool
    next: list[ResolvedProcedure]           # not done and ready, ordered
    mandatory: list[ProcedureSpec]          # mandatory nodes not yet done

class ProcedureSettings(BaseModel):         # sdd/config.json "procedure"
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    enforce: bool = True                    # False: never deny, advise instead
    brief_max_lines: int = 8
    remote_probe_timeout_seconds: int = 5
```

Compiled index (`procedures.json`, `schema_version` 1):

```json
{
  "schema_version": 1,
  "generation": "<sha1 of the canonical JSON without this key>",
  "sources": [{"path": "sdd/procedures/sdd-workflow.yaml", "sha1": "<hex>"}],
  "guards": [
    {"procedure": "sdd:task-close", "kind": "entry", "executable": "parrot",
     "argv_prefix": ["sdd", "task", "close"], "path_globs": [],
     "scope": {"task": {"argv": 0}, "feature": {"argv": 1}}}
  ],
  "procedures": {
    "sdd:task-close": {
      "title": "Close a task", "mode": "mandatory", "command": "parrot sdd task close <TASK> <slug> verified",
      "use_instead": "parrot sdd task close <TASK> <slug> verified", "advice": "...",
      "preconditions": [{"probe": "task.status", "expect": "in-progress", "args": {}, "cost": "local"}]
    }
  }
}
```

### New Public Interfaces

```
parrot sdd procedure build [--root <path>]             # fold sources into procedure.db + procedures.json
parrot sdd procedure list [--mode M] [--json]
parrot sdd procedure show <id> [--json]
parrot sdd procedure next [--feature <slug|FEAT-ID>] [--task TASK-<N>] [--no-remote] [--json]
parrot sdd procedure check [--json]                    # exit 1 on any error finding
parrot sdd procedure brief --task-file <task.md> [--max-lines N]
```

MCP tool `wiki_procedure_next(feature: str | None, task: str | None)` — the `next` resolution
with local probes only.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: Models | yes | models in §2 verbatim; lazy `__init__` like `wiki/schema/__init__.py` | — |
| M2: Producers and skill frontmatter | yes | signatures below; id prefixing; discovery contract | — |
| M3: Validation and lint pack | yes | finding codes below; `LintRule` shape | — |
| M4: Plane and compiled index | yes | index shape in §2; atomic publish; store calls named | — |
| M5: Hook-side advice | yes | stdlib-only rule; decision table in §2; signatures below | — |
| M6: Probes and resolver | yes | probe table in §2; resolver contract below | — |
| M7: CLI noun | yes | verb table in §2; `main(argv) -> int`; `VERBS` shape | — |
| M8: Guard integration | yes | exact call sites and response shapes below | — |
| M9: SDD manifest and asset lifecycle | yes | node table below; asset entry and install step fixed | — |
| M10: MCP tool | yes | mirror the schema-plane tool in both transports | — |
| M11: Task-start block | no | — | attaches to FEAT-887 code that is not merged; anchors cannot be verified yet |
| M12: Documentation and release smoke | yes | page path and scenario key fixed | — |

### Module 1: Models
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/{__init__,models}.py`
- **Responsibility**: the Pydantic models of §2 and the package's lazy exports (every public
  name of M1–M6 declared once here, so later modules do not edit `__init__.py`).
- **Depends on**: nothing in this spec.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/procedure/models.py  (new)
  # ProbeCheck, ScopeArg, GuardSpec, ExecutorRef, ProcedureSpec, ProcedureManifest, ProbeResult,
  # ResolvedProcedure, Resolution and the Literal aliases — exactly as in §2 Data Models.
  INDEX_SCHEMA_VERSION = 1
  PLANE_DIR = Path(".parrot") / "procedure"
  INDEX_FILE = "procedures.json"
  EDGE_FIELDS: dict[str, str]   # ProcedureSpec field name → EdgeRel ("requires_procedures" → "requires", "next" → "next", …)

  class ProcedureSpec(BaseModel):
      def edges(self) -> list[tuple[str, str, str]]:
          """Return (src, dst, rel) for every id listed in an edge field; applies_to targets are 'type:<Name>'."""

  # knowledge/wiki/procedure/__init__.py  (new) — PEP 562 lazy exports, pattern verified: wiki/schema/__init__.py:8
  ```

### Module 2: Producers and skill frontmatter
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/producers.py`;
  `packages/ai-parrot/src/parrot/skills/models.py`, `parsers.py`
- **Responsibility**: turn manifests and skills into `ProcedureSpec` records.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/procedure/producers.py  (new)
  MANIFEST_DIR = Path("sdd") / "procedures"

  def load_manifest(path: Path, *, root: Path) -> ProcedureManifest:
      """Parse one YAML manifest; raise ValueError naming the file on a schema error."""

  def manifest_specs(root: Path) -> tuple[list[ProcedureSpec], list[Path]]:
      """Merge every sdd/procedures/*.yaml under root (sorted by name); return (specs, source files).

      Ids get the manifest's graph prefix; every `exclude` id is removed after the merge; a
      duplicate id across files raises ValueError naming both files.
      """

  def skill_spec(skill: SkillDefinition, *, root: Path | None = None) -> ProcedureSpec | None:
      """Return the skill's node (id 'skill:<name>', kind 'skill', body = template_body), or None
      when skill.procedure is None. source 'learned' forces mode 'advisory' and confirm False."""

  def skill_specs(directories: Sequence[Path], *, root: Path | None = None) -> tuple[list[ProcedureSpec], list[Path]]:
      """skill_spec over discover_skills_in_dir (verified: skills/parsers.py:181) for each directory."""

  # skills/models.py  (modifies SkillDefinition, verified: :68)
  #   procedure: dict[str, Any] | None = Field(default=None, description="Optional graph fields (FEAT-891).")

  # skills/parsers.py  (modifies parse_skill_file, verified: :69)
  #   reads metadata.get("procedure"); None when absent; a non-mapping value raises
  #   ValueError(f"Skill file 'procedure' must be a mapping: {file_path}") — same contract as 'suggestions' (:130).
  ```
  The skill model keeps the raw mapping; `skill_spec` validates it into `ProcedureSpec`. This
  keeps `parrot.skills` free of an import of `parrot.knowledge.wiki`.

### Module 3: Validation and lint pack
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/validate.py`;
  `packages/ai-parrot/src/parrot/knowledge/lint/packs/procedure.py`, `packs/__init__.py`
- **Responsibility**: deterministic graph checks, reusable by the CLI and by `wikitoolkit lint`.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/procedure/validate.py  (new, pure)
  class GraphFinding(BaseModel):
      code: str            # see table
      severity: Literal["error", "warning"]
      subjects: list[str]
      message: str

  def validate_graph(specs: Sequence[ProcedureSpec], *, known_probes: Mapping[str, ProbeCost],
                     known_commands: Sequence[str] = ()) -> list[GraphFinding]:
      """Return every finding, sorted by (code, subjects)."""

  # knowledge/lint/packs/procedure.py  (new)
  class ProcedureGraphRule:
      """LintRule (verified: lint/rule.py:22). rule_id 'procedure-graph', pack 'procedure', default_severity 'error'.

      check(): no-op ([]) when ctx.root is None or <root>/sdd/procedures has no manifest; else one
      Finding per GraphFinding (fingerprint via make_fingerprint, verified: lint/rule.py:15). fix(): None.
      """
  PROCEDURE_RULES: tuple[type, ...] = (ProcedureGraphRule,)
  ```
  | Code | Severity | Condition |
  |---|---|---|
  | `broken-edge` | error | an edge target id that is not a node (`applies_to` and `learned_from` exempt) |
  | `requires-cycle` | error | a cycle in `requires_procedures` |
  | `unknown-probe` | error | a `ProbeCheck.probe` not in `known_probes` |
  | `remote-probe-in-guard` | warning | a guarded node whose only preconditions are `remote` |
  | `mandatory-without-enforcement` | error | `mode: mandatory` with no guard and no executor |
  | `bypass-without-alternative` | error | a `bypass` guard on a node with empty `use_instead` |
  | `learned-mandatory` | error | `source: learned` with `mode: mandatory` or `confirm: true` |
  | `uncovered-command` | warning | a name in `known_commands` that no node's `command` mentions |
  | `advice-too-long` | error | `advice` over 300 characters |

  `next` cycles are legal and not reported.

### Module 4: Plane and compiled index
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/{index,plane}.py`
- **Responsibility**: build and publish `procedures.json`; fold specs into `procedure.db`.
- **Depends on**: M1.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/procedure/index.py  (new)
  def compile_index(specs: Sequence[ProcedureSpec], sources: Sequence[Path], *, root: Path,
                    probe_costs: Mapping[str, ProbeCost]) -> dict[str, Any]:
      """Return the §2 index document; 'generation' is the sha1 of its canonical JSON."""

  def publish_index(plane_dir: Path, document: Mapping[str, Any]) -> Path:
      """Write procedures.json via a temp file in plane_dir + os.replace; return the path."""

  def read_index(plane_dir: Path) -> dict[str, Any] | None:
      """Return the document, or None when absent, unreadable or of another schema version."""

  def is_stale(document: Mapping[str, Any] | None, *, root: Path) -> bool:
      """True when document is None, a listed source is missing or its sha1 differs, or a manifest
      under sdd/procedures is not listed."""

  # knowledge/wiki/procedure/plane.py  (new)
  class ProcedurePlane:
      """procedure.db + procedures.json under <shared-root>/.parrot/procedure."""
      def __init__(self, plane_dir: Path) -> None: ...
      @classmethod
      def for_root(cls, start: Path | None = None) -> "ProcedurePlane | None":
          """Plane of the shared root (find_shared_root, verified: wiki/project.py:1563); None outside a repository."""
      async def build(self, specs: Sequence[ProcedureSpec], sources: Sequence[Path], *, root: Path,
                      probe_costs: Mapping[str, ProbeCost]) -> dict[str, int]:
          """Rebuild the store, then publish the index last. Returns {'pages', 'edges', 'sources'}.

          One replace_source_slice per source file (verified: wiki/store.py:923) with pages of
          category 'procedure' and origin 'ingest'; attrs via upsert_attrs (verified: :907); edges via
          add_edges 4-tuples (src, dst, rel, provenance) (verified: :920; tuple shape wiki/operations.py:406).
          Source slices of files that no longer exist are removed.
          """
      async def specs(self) -> list[ProcedureSpec]:
          """Read every node back from the store (read-only handle)."""
  ```
  The store is opened with `create_wiki_store(storage_dir=plane_dir, wiki_name="procedure")`
  (verified: `wiki/store.py:3288`). The index is published only after the store commit, so a
  crash leaves the previous index, which then reads as stale.

### Module 5: Hook-side advice
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py`
- **Responsibility**: everything a guard needs, with **stdlib imports only** and no `parrot`
  import at module level, so it loads both as `parrot.sdd.scripts.procedure_advice` and as a
  script sibling (S2).
- **Depends on**: nothing in this spec (the index shape is fixed in §2; a contract test ties it
  to M4).
- **Interface Skeleton**:
  ```python
  # sdd/scripts/procedure_advice.py  (new — stdlib only; no main())
  INDEX_SCHEMA_VERSION = 1
  ESCAPE_ENV = "PARROT_ALLOW_PROCEDURE"
  LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")   # same values as worktree_environment.py:624

  @dataclass(frozen=True)
  class Advice:
      decision: Literal["none", "advise", "deny"]
      text: str = ""

  def shared_root(cwd: Path) -> Path | None:
      """Primary checkout for cwd, without a subprocess: walk up to '.git'; when it is a file,
      follow 'gitdir:' and its 'commondir' file to the main .git and return its parent."""

  def load_index(root: Path) -> dict[str, Any] | None:
      """<root>/.parrot/procedure/procedures.json when it parses, has INDEX_SCHEMA_VERSION and is
      at most 262144 bytes; else None. Never raises."""

  def leading_command(command: str) -> tuple[str, list[str]]:
      """(executable basename, argv after it) of the first real command segment; skips env
      assignments, 'cd … &&' and the wrappers rtk, sudo, timeout, 'uv run'. ('', []) when unknown."""

  def match_guards(index: Mapping[str, Any], command: str) -> list[dict[str, Any]]:
      """Index guard entries whose executable and argv_prefix match and, when path_globs is set,
      whose arguments include a matching repo-relative path."""

  LOCAL_PROBES: dict[str, Callable[[Path, Mapping[str, str], Mapping[str, str]], bool | None]]
      # name → probe(checkout, scope, args); the 'local' rows of the §2 probe table. Never raises: an
      # exception is reported as None.

  def evaluate_command(command: str, cwd: Path, *, env: Mapping[str, str] | None = None) -> Advice:
      """The §2 guard decision table for one Bash command.

      Returns Advice('none') when the command matches no guard, the plane is absent or stale
      (a listed source's sha1 differs), 'procedure.enabled' is false, or anything fails. A deny
      is downgraded to 'advise' when ESCAPE_ENV or PARROT_ALLOW_DANGEROUS is '1' or
      'procedure.enforce' is false (sdd/config.json read with json, no pydantic).
      Text is built from fixed templates, at most 600 characters.
      """
  ```
  Templates: deny — `Procedure <id> is mandatory: <reason>. Use: <command>. (Deliberate
  exception: ask the user to re-run with PARROT_ALLOW_PROCEDURE=1.)`; advise —
  `Procedure <id>: <unmet or unknown preconditions>. <advice>`.

### Module 6: Probes and resolver
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/resolver.py`;
  `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py`
- **Responsibility**: the full probe registry and the `next` resolution.
- **Depends on**: M1, M5.
- **Interface Skeleton**:
  ```python
  # knowledge/wiki/procedure/resolver.py  (new — no import of parrot.sdd)
  class ProbeRunner(Protocol):
      def cost(self, probe: str) -> ProbeCost | None: ...
      def run(self, check: ProbeCheck, scope: Mapping[str, str]) -> bool | None: ...

  def resolve(specs: Sequence[ProcedureSpec], scope: Mapping[str, str], runner: ProbeRunner, *,
              allow_remote: bool = True, stale: bool = False) -> Resolution:
      """Evaluate done_when lazily, keep nodes that are not done and whose requires_procedures are
      all done, order them by (mode mandatory first, id), and attach their precondition results.
      A probe of cost 'remote' is reported as unknown when allow_remote is False."""

  # sdd/scripts/procedure_probes.py  (new — no main())
  PROBE_COSTS: dict[str, ProbeCost]       # every row of the §2 probe table

  class SddProbeRunner:
      """ProbeRunner over a checkout: LOCAL_PROBES from procedure_advice plus the remote probes."""
      def __init__(self, checkout: Path, *, timeout: int = 5) -> None: ...

  def scope_for(checkout: Path, *, feature: str | None = None, task: str | None = None) -> dict[str, str]:
      """Fill 'feature', 'task' and 'branch': explicit arguments first, then the current branch
      name ('feat-<FEAT-ID>-<slug>'), matching per-spec index headers by feature or feature_id."""
  ```
  Remote probes run `git` / `gh` with `subprocess.run(..., timeout=timeout)` and return `None`
  on any failure.

### Module 7: CLI noun
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/procedure.py`;
  `packages/ai-parrot/src/parrot/sdd/cli.py`; `packages/ai-parrot/src/parrot/sdd/config.py`
- **Responsibility**: the six verbs of §2; the `procedure` config section.
- **Depends on**: M2, M3, M4, M6.
- **Interface Skeleton**:
  ```python
  # sdd/scripts/procedure.py  (new)
  def main(argv: Sequence[str] | None = None) -> int:
      """Dispatch build | list | show | next | check | brief. Exit 0; 1 for 'check' with an error
      finding or 'show' of an unknown id; 2 on usage errors."""

  async def build(root: Path) -> dict[str, int]:
      """manifest_specs(primary checkout) → validate (errors abort, exit 1) → ProcedurePlane.build."""

  def render_brief(resolution: Resolution, *, max_lines: int) -> str:
      """Markdown block: one line of position, the next valid step(s), then 'Mandatory:' rules
      (command + use_instead). '' when there is nothing to say."""

  # sdd/cli.py  (modifies VERBS, verified: :247)
  #   "procedure": {v: ("procedure", (v,), f"Procedure graph: {v}") for v in ("build", "list", "show", "next", "check", "brief")},

  # sdd/config.py  (modifies SddConfig, verified: :25)
  #   procedure: ProcedureSettings | None = None       # ProcedureSettings defined in this file (model in §2)
  ```
  `next`, `list`, `show` and `brief` rebuild first when the plane is stale and its directory is
  writable; otherwise they print one `stale` line on stderr and continue with the stale data
  (`brief` prints nothing).

### Module 8: Guard integration
- **Path**: `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py`,
  `worktree_environment.py`, `native_claude_sandbox.py`
- **Responsibility**: call `evaluate_command` from the two existing guards.
- **Depends on**: M5.
- **Interface Skeleton**:
  ```python
  # sdd/scripts/dangerous_actions.py  (modifies main, verified: :436; _render, verified: :422)
  def _procedure_advice(payload: dict[str, Any]) -> Any | None:
      """Advice for a Bash payload, or None for other tools or on any failure (lazy, guarded import
      of parrot.sdd.scripts.procedure_advice)."""
  # main(): after `verdict = evaluate(payload, root=root)`:
  #   verdict 'deny'            → unchanged (procedure check not run)
  #   advice 'deny'             → {"hookSpecificOutput": {"hookEventName": "PreToolUse",
  #                                "permissionDecision": "deny", "permissionDecisionReason": advice.text}}
  #   advice 'advise'           → _render(verdict) plus {"hookSpecificOutput": {"hookEventName": "PreToolUse",
  #                                "additionalContext": advice.text}}
  #   advice 'none' / None      → _render(verdict), byte-identical to today

  # sdd/scripts/worktree_environment.py  (modifies hook_response, verified: :1026)
  def _load_procedure_advice() -> Any:
      """Sibling module, package or script mode — same pattern as _load_native_sandbox (verified: :603)."""
  # hook_response(): for tool 'Bash', when output has no 'permissionDecision':
  #   advice 'deny'   → output.update(permissionDecision="deny", permissionDecisionReason=advice.text); drop 'updatedInput'
  #   advice 'advise' → output["additionalContext"] = advice.text
  # The procedure check is evaluated on the ORIGINAL command, before wrapping. Any exception from it is swallowed.

  # sdd/scripts/native_claude_sandbox.py  (modifies _control_files, verified: :209)
  #   names = ("native_claude_sandbox.py", "worktree_environment.py", "procedure_advice.py")
  ```

### Module 9: SDD manifest and asset lifecycle
- **Path**: `packages/ai-parrot/src/parrot/sdd/_assets/sdd/procedures/sdd-workflow.yaml`,
  `sdd/procedures/sdd-workflow.yaml` (installed twin), `_assets/manifest.json`,
  `packages/ai-parrot/pyproject.toml`, `packages/ai-parrot/src/parrot/sdd/installer.py`
- **Responsibility**: the first graph, shipped and installed like the other SDD assets (S10).
- **Depends on**: M2, M3, M7.
- **Interface Skeleton**:
  ```python
  # sdd/installer.py  (modifies install_sdd_integration, verified: :1515)
  def _install_procedure_index_step(root: Path, receipt: dict[str, Any]) -> list[str]:
      """Run procedure.build(root) after the assets are deployed; return a one-line action.
      Never fails the install: an error becomes the action text 'procedure index: skipped (<reason>)'."""
  ```
  Asset entry: `{"source": "sdd/procedures/sdd-workflow.yaml", "target":
  "sdd/procedures/sdd-workflow.yaml", "hosts": ["claude", "codex", "google"]}`; package data
  pattern `"_assets/sdd/procedures/*.yaml"`.

  Manifest nodes (`graph: sdd`):

  | Id | Mode | Scope | `requires_procedures` | `done_when` | Guards |
  |---|---|---|---|---|---|
  | `spec` | advisory | feature | — | `spec.exists` | — |
  | `task` | advisory | feature | `spec` | `index.exists` | — |
  | `worktree-ensure` | advisory | feature | `task` | — | entry `parrot sdd worktree ensure` |
  | `start` | advisory | task | `task` | `task.status == in-progress` | — |
  | `task-close` | mandatory | task | `start` | `task.status == done` | entry `parrot sdd task close`; bypass `mv`, `git mv` on `sdd/tasks/active/*` |
  | `codereview` | advisory | task | `task-close` | — | — |
  | `push` | advisory | feature | — | `branch.pushed` | entry `git push` |
  | `pr-create` | mandatory | feature | — | `pr.open` | entry `gh pr create` |
  | `done` | advisory | feature | `task-close` | — | — |

  `next` edges: `spec → task → start → task-close → codereview → done`, and
  `codereview → start`. `done` carries `preconditions: [feature.tasks_done]`.
  `known_commands` for `uncovered-command` is the list of `sdd-*` command files under
  `_assets/claude/commands/`; commands outside the workflow are listed in the manifest's
  top-level `uncovered_ok:` (added to `ProcedureManifest` as `uncovered_ok: list[str] = []`).

### Module 10: MCP tool
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/wiki/procedure.py`;
  `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py`, `transport.py`
- **Responsibility**: `wiki_procedure_next` on both transports.
- **Depends on**: M4, M6.
- **Interface Skeleton**:
  ```python
  # parrot_tools/wiki/procedure.py  (new)
  class ProcedureNextInput(BaseModel):
      feature: str | None = None
      task: str | None = None

  async def op_procedure_next(params: ProcedureNextInput, *, root: Path | None) -> str:
      """Rendered Resolution (local probes only); a one-line message when no plane exists."""

  def create_procedure_tools(store: BaseWikiStore, root: Optional[Path], config: WikiProjectConfig) -> list[AbstractTool]:
      """[WikiProcedureNextTool] when <shared-root>/.parrot/procedure/procedures.json exists, else []."""
  ```
  Wiring mirrors the schema plane: one line in `build_framework_tools` after the schema tools
  (verified: `mcp_server.py:387`), and a `_Spec` entry plus a dispatch branch in `transport.py`
  (verified: `:216`, `:391`).

### Module 11: Task-start block
- **Path**: FEAT-887's briefing path — `flows/dev_loop/sdd_coder/engine.py`
  (`_experience_briefing_for`), `.claude/commands/sdd-start.md` and its twins
- **Responsibility**: append `procedure brief` output to the briefing every seat receives.
- **Depends on**: M6, M7, and **FEAT-887 merged**.
- **Interface Skeleton**:
  ```python
  # flows/dev_loop/sdd_coder/engine.py  (modifies — anchor unverified: FEAT-887 not merged)
  async def _procedure_briefing_for(self, ctx: _FeatureCtx, task: PlannedTask) -> str:
      """render_brief(resolve(...)) for the task with local probes only; '' on any error or when
      'procedure.enabled' is false. The result is joined to the experience briefing with a blank line."""
  ```
  `sdd-start.md` gains one step next to FEAT-887's `parrot sdd experience brief`:
  `parrot sdd procedure brief --task-file <task.md>`. If FEAT-887 has not landed when this
  module's task starts, the task stops and reports; it does not create a second briefing channel.

### Module 12: Documentation and release smoke
- **Path**: `wiki/sdd-tooling/sdd/procedure-graph.md`; `wiki/_index.yaml`;
  `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py`
- **Responsibility**: the operator page (model, manifest format, probes, guard behavior and the
  escape variables, skill frontmatter fields, `wikitoolkit ns add procedure --store
  .parrot/procedure`), and a `SCENARIOS["procedure"]` entry. The page carries a **Pilot
  activation** section: the host-operator step that switches a repository's interactive guard
  entry from the legacy shell script to the packaged Python guard
  (`parrot sdd install --portable`), to be run in ai-parrot after merge. `.claude/settings.json`
  is untracked, so this is an operator step and never a task edit.
- **Depends on**: M7, M8, M9.
- **Interface Skeleton**: none (documentation and a test table entry).

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_spec_edges` | M1 | `ProcedureSpec.edges()` maps every edge field to its relation |
| `test_models_forbid_extra` | M1 | unknown keys are rejected in `ProcedureSpec` and `ProcedureManifest` |
| `test_manifest_merge_prefix_exclude` | M2 | ids prefixed; overlay `exclude` removes a node; duplicate id raises |
| `test_skill_without_procedure_unchanged` | M2 | a skill with no `procedure` key parses as today; `skill_spec` returns `None` |
| `test_skill_procedure_not_mapping_raises` | M2 | `procedure: "x"` raises `ValueError` naming the file |
| `test_learned_skill_never_mandatory` | M2 | a learned skill's node is advisory with `confirm` false |
| `test_validate_codes` | M3 | one case per finding code; `next` cycle produces none |
| `test_lint_rule_noop_without_manifest` | M3 | `ProcedureGraphRule.check` returns `[]` when no manifest exists |
| `test_index_atomic_and_generation` | M4 | publish goes through a temp file; `generation` is stable for equal input |
| `test_is_stale_on_source_change` | M4 | editing a manifest or adding one makes the index stale |
| `test_plane_build_idempotent` | M4 | two builds give the same pages and edges; a removed source drops its slice |
| `test_advice_stdlib_only` | M5 | importing `procedure_advice` in a subprocess loads no `pydantic`, `yaml` or `sqlite3` |
| `test_index_contract` | M4+M5 | `load_index` accepts what `publish_index` writes; both schema versions are equal |
| `test_guard_decision_table` | M5 | every row of the §2 decision table, including unknown → no deny |
| `test_escape_downgrades_deny` | M5 | each of the three switches turns a deny into an advisory |
| `test_stale_index_is_silent` | M5 | a source sha1 mismatch yields `Advice("none")` |
| `test_leading_command_wrappers` | M5 | `cd x && rtk git mv …`, env assignments, `uv run` |
| `test_resolver_next_without_history` | M6 | `spec` done, `task` not → `task` is next; mandatory nodes listed |
| `test_resolver_remote_unknown_when_disallowed` | M6 | `allow_remote=False` reports remote probes as unknown |
| `test_cli_verbs` | M7 | `build`, `list`, `show`, `next --json`, `check` exit codes; `procedure` mounted in `VERBS` |
| `test_sdd_config_procedure_section` | M7 | `procedure` accepted by `SddConfig`; absent keeps defaults |
| `test_dangerous_guard_unchanged_without_plane` | M8 | output byte-identical to today when no index exists |
| `test_dangerous_guard_denies_bypass` | M8 | `git mv sdd/tasks/active/TASK-1-x.md …` is denied and names the script |
| `test_dangerous_guard_existing_deny_wins` | M8 | a destructive command is denied by the original rule; no procedure text |
| `test_worktree_guard_deny_and_advise` | M8 | deny drops `updatedInput`; advise keeps the wrapper and adds `additionalContext` |
| `test_control_files_include_advice` | M8 | `procedure_advice.py` is in `_control_files` |
| `test_sdd_manifest_valid` | M9 | the packaged manifest has no error finding; every `sdd-*` command is covered or listed |
| `test_manifest_twin_in_sync` | M9 | `sdd/procedures/sdd-workflow.yaml` equals the packaged asset |
| `test_install_builds_index` | M9 | `install_sdd_integration` leaves a fresh `procedures.json`; a build error does not fail the install |
| `test_mcp_tool_both_transports` | M10 | `wiki_procedure_next` is listed and answers on the framework and SDK transports |

### Integration Tests

| Test | Description |
|---|---|
| `test_pilot_flow_end_to_end` | temp repo with a spec, an index and one task: `build` → `next` reports `start`; hand `git mv` of the task file is denied by both guards; `parrot sdd task close` on a `pending` task is denied; on an `in-progress` task with dependencies done nothing is emitted |
| `test_wheel_only_procedure` | the `procedure` scenario in the wheel-only foreign-repo smoke: install, `procedure check`, `procedure next` |

### Validation Contract

tests:
- packages/ai-parrot/tests/knowledge/wiki/procedure/test_models.py
- packages/ai-parrot/tests/knowledge/wiki/procedure/test_producers.py
- packages/ai-parrot/tests/knowledge/wiki/procedure/test_validate.py
- packages/ai-parrot/tests/knowledge/wiki/procedure/test_index_plane.py
- packages/ai-parrot/tests/knowledge/wiki/procedure/test_resolver.py
- packages/ai-parrot/tests/knowledge/wiki/procedure/test_mcp_tool.py
- packages/ai-parrot/tests/sdd/test_procedure_advice.py
- packages/ai-parrot/tests/sdd/test_procedure_cli.py
- packages/ai-parrot/tests/sdd/test_procedure_guards.py
- packages/ai-parrot/tests/sdd/test_procedure_assets.py
- packages/ai-parrot/tests/sdd/test_dangerous_actions.py
- packages/ai-parrot/tests/sdd/test_sdd_cli.py
- packages/ai-parrot/tests/unit/test_skill_definition.py
- tests/sdd_scripts/test_check_asset_sync.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def procedure_repo(tmp_path):
    """A git repository with sdd/config.json, sdd/procedures/sdd-workflow.yaml (the packaged asset),
    one spec, one per-spec index with two tasks (TASK-1 in-progress, TASK-2 pending, depends_on TASK-1)
    and the matching files under sdd/tasks/active/. Returns the root."""

@pytest.fixture
def built_plane(procedure_repo):
    """procedure_repo after `parrot sdd procedure build`."""
```

---

## 5. Acceptance Criteria

- [ ] Every test file in the §4 Validation Contract passes.
- [ ] A skill file with no `procedure` key produces the same `SkillDefinition` as before, apart
      from the new field being `None`.
- [ ] `parrot sdd procedure check` exits 0 on the packaged manifest and 1 on a manifest with a
      broken edge, a `requires` cycle or an unknown probe.
- [ ] `parrot sdd procedure next` gives the same answer on two runs with unchanged state, and
      makes no LLM call.
- [ ] No precondition is a free-form expression: every `ProbeCheck.probe` is a registered name.
- [ ] `procedure_advice` imports only the standard library at module level (subprocess test).
- [ ] With no plane, a stale plane, `procedure.enabled: false`, or any internal error, both
      guards produce exactly the output they produce today.
- [ ] `mv` / `git mv` of a file under `sdd/tasks/active/` is denied by both guards with a reason
      naming `parrot sdd task close`.
- [ ] `gh pr create --base main` on a `feat-*` branch is denied; without `--base` it is not denied.
- [ ] `parrot sdd task close` for a task that is not `in-progress`, or whose dependencies are not
      done, is denied; a precondition that cannot be checked never causes a denial.
- [ ] `PARROT_ALLOW_PROCEDURE=1`, `PARROT_ALLOW_DANGEROUS=1` and `procedure.enforce: false` each
      turn a denial into an advisory.
- [ ] A denial issued by an existing guard rule is unchanged and carries no procedure text.
- [ ] No hook registration is added on any host; `.codex/hooks.json`, `.agents/hooks.json` and
      the settings entries written by the installer are unchanged.
- [ ] `procedures.json` is published with a temp file and `os.replace`, and is written after the
      store commit.
- [ ] `executor` and `confirm` change no behavior: no flow is run and no tool is authorized.
- [ ] `sdd/procedures/sdd-workflow.yaml` equals the packaged asset; `parrot sdd install` deploys
      it and builds the index; a build failure does not fail the install.
- [ ] `wiki_procedure_next` is available on both MCP transports and returns `[]`-equivalent
      behavior (no tool) when no plane exists.
- [ ] The task-start block is delivered through FEAT-887's briefing path only (M11); no second
      briefing channel exists.
- [ ] `SCENARIOS` in the wheel-only smoke has a `procedure` entry.
- [ ] `wiki/sdd-tooling/sdd/procedure-graph.md` exists (`parrot sdd techwiki check`).
- [ ] Baseline for the pilot is recorded in the documentation page: the count of
      `parrot sdd task state` violations at merge time.
- [ ] The documentation page has a "Pilot activation" section naming the operator step that
      switches the interactive guard entry to the packaged Python guard
      (`parrot sdd install --portable`).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified by reading the main checkout at `b95685da81` (code identical to `origin/dev`
> `7ba5fd1cd9` for every file listed). Imports were checked as module paths, not executed.

### Verified Imports
```python
from parrot.skills.models import SkillDefinition, SkillSource          # skills/models.py:68, :53
from parrot.skills.parsers import parse_skill_file, discover_skills_in_dir  # skills/parsers.py:69, :181
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord, create_wiki_store  # wiki/store.py:870, :606, :3288
from parrot.knowledge.wiki.project import find_shared_root, WikiProjectConfig  # wiki/project.py:1563, :589
from parrot.knowledge.lint.rule import LintRule, make_fingerprint      # lint/rule.py:22, :15
from parrot.knowledge.lint.models import Finding, FixResult, Severity  # lint/models.py:14, :26
from parrot.knowledge.lint.context import LintContext                  # lint/context.py:13
from parrot.sdd.config import SddConfig, load_sdd_config               # sdd/config.py:25, :278
from parrot.sdd.scripts.check_task_state import find_violations        # sdd/scripts/check_task_state.py:98
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/skills/models.py
class SkillDefinition(BaseModel):                       # :68
    name: str; description: str; triggers: list[str]    # :75–:77
    source: SkillSource = SkillSource.AUTHORED          # :78
    template_body: str; token_count: int; file_path: Path   # :82–:84
    suggestions: list[SkillSuggestion] = Field(...)     # :93

# packages/ai-parrot/src/parrot/skills/parsers.py
def parse_skill_file(file_path: Path) -> SkillDefinition: ...                       # :69
def discover_skills_in_dir(directory: Path, logger=_LOGGER, exclude_names=()) -> List[SkillDefinition]: ...  # :181

# packages/ai-parrot/src/parrot/knowledge/wiki/store.py
class BaseWikiStore(ABC):                                                            # :870
    async def upsert_attrs(self, concept_id: str, attrs: Mapping[str, str], *, replace: bool = True) -> int: ...  # :907
    async def upsert_pages(self, pages: list[WikiPageRecord]) -> int: ...            # :917
    async def add_edges(self, edges: list[tuple]) -> int: ...                        # :920
    async def replace_source_slice(self, source_id: str, pages: list[WikiPageRecord],
                                   edges: Optional[list[tuple[str, str, str]]] = None) -> dict[str, Any]: ...  # :923
    async def neighbors(self, concept_id: str, rel: Optional[str] = None, direction: str = "both") -> list[dict[str, Any]]: ...  # :955
def create_wiki_store(storage_dir: str | Path, wiki_name: str = "", backend: str = "sqlite", **kwargs: Any) -> BaseWikiStore: ...  # :3288
# edges table: (src, dst, rel DEFAULT 'references', provenance DEFAULT 'extracted'), PK (src, dst, rel)   # :147

# packages/ai-parrot/src/parrot/knowledge/lint/context.py
class LintContext:                                                                   # :13
    def __init__(self, store: BaseWikiStore, *, root: Path | None = None, config: Any | None = None,
                 options: LintOptions | None = None) -> None: ...
    # attributes: store, root, config, options, extras

# packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py   (stdlib only; no parrot import at module level)
@dataclass(frozen=True)
class Verdict: decision: Literal["allow", "deny", "warn"]; reason: str = ""          # :36
def find_root(cwd: str | Path | None) -> Path | None: ...                            # :58
def evaluate(payload: dict[str, Any], *, root: Path | None) -> Verdict: ...          # :403
def _render(verdict: Verdict) -> dict[str, Any]: ...                                 # :422
def main(argv: Sequence[str] | None = None) -> None: ...                             # :436

# packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py
def _load_native_sandbox() -> Any: ...                                               # :603
LAUNCHER_MARKERS = ("PARROT_SDD_SANDBOX_ROOTS", "PARROT_SDD_CACHE_DIR")              # :624
def hook_response(payload: dict[str, Any], *, backend: str = "bubblewrap") -> dict[str, Any]: ...  # :1026
#   builds output = {"hookEventName": "PreToolUse"}; may set output["updatedInput"]; on error
#   output.update(permissionDecision="deny", permissionDecisionReason=str(exc)); returns {"hookSpecificOutput": output}

# packages/ai-parrot/src/parrot/sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]]                        # :247  noun → verb → (module, prefix, help)
def mounted_modules() -> set[str]: ...                                               # :344
def _mount(noun, verb, module, prefix, help_) -> None: ...                           # :349  calls parrot.sdd.scripts.<module>.main([*prefix, *args])

# packages/ai-parrot/src/parrot/sdd/config.py
class SddConfig(BaseModel):                                                          # :25
    model_config = ConfigDict(extra="forbid")                                        # :28
    hotfix_base: str = "main"                                                        # :32
    techwiki: TechwikiConfig | None = None                                           # :43

# packages/ai-parrot/src/parrot/sdd/installer.py
def _install_dangerous_guard(root: Path, receipt: dict[str, Any], *, portable: bool | None) -> list[str]: ...  # :399
def _install_ledger_hooks_step(root: Path, receipt: dict[str, Any]) -> list[str]: ...  # :1282
def install_sdd_integration(...): ...                                                # :1515; steps appended to `actions` at :1609–:1619

# packages/ai-parrot-tools/src/parrot_tools/wiki/schema.py
def create_schema_tools(store: BaseWikiStore, root: Optional[Path], config: WikiProjectConfig,
                        service: Optional[SchemaPlaneService] = None) -> list[AbstractTool]: ...  # :111
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `ProcedurePlane.build` | `BaseWikiStore.replace_source_slice` / `add_edges` / `upsert_attrs` | method calls | `wiki/store.py:923`, `:920`, `:907` |
| `ProcedurePlane.for_root` | `find_shared_root` | function call | `wiki/project.py:1563` |
| `ProcedureGraphRule` | `default_rules` | added to the rules tuple | `lint/packs/__init__.py:21` |
| `procedure` noun | `VERBS` | dict entry | `sdd/cli.py:247` |
| `_procedure_advice` | `dangerous_actions.main` | call after `evaluate` | `dangerous_actions.py:446` |
| `_load_procedure_advice` | `hook_response` | call before the return | `worktree_environment.py:1075` |
| `create_procedure_tools` | `build_framework_tools` | appended to `tools` | `wiki/mcp_server.py:387` |
| `wiki_procedure_next` | SDK transport `_Spec` table and dispatch | new entry and branch | `wiki/transport.py:216`, `:391` |
| `_install_procedure_index_step` | `install_sdd_integration` | appended to `actions` | `sdd/installer.py:1611` |
| manifest asset | SDD asset manifest | new entry | `sdd/_assets/manifest.json:557` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.knowledge.wiki.procedure`~~, ~~`parrot.sdd.scripts.procedure`~~,
  ~~`procedure_advice`~~, ~~`procedure_probes`~~ — created by this feature
- ~~`sdd/procedures/`~~ — the directory does not exist yet
- ~~`SkillDefinition.procedure`~~, ~~`.applies_to`~~, ~~`.preconditions`~~, ~~`.mode`~~ — not fields today
- ~~`SddConfig.procedure`~~ — not a field; the model forbids extra keys
- ~~`WikiPageCategory.PROCEDURE`~~ — no such member; the store's `category` is an open string
- ~~`parrot.knowledge.wiki.experience`~~, ~~`parrot/sdd/scripts/experience_hook.py`~~,
  ~~`SddCoderEngine._experience_briefing_for`~~ — specified by FEAT-887, not merged
- ~~A pre-tool hook from FEAT-887~~ — FEAT-887 v1 registers none (its review F12)
- ~~`UserPromptSubmit` handling~~ — no Python file under `packages/ai-parrot/src/parrot` references it
- ~~The dangerous-actions guard in launched workers, codex or agy sessions~~ — workers run
  `worktree_environment --hook` (`native_claude_sandbox.py:436`); codex runs
  `parrot_tools.tool_optimizations.hooks` (`scripts/sdd/codex_hook.sh`); agy runs `agy_permissions`
- ~~`.claude/settings.json` in a worktree~~ — the file is not tracked
- ~~`replace_source_slice` carrying edge provenance~~ — its edges are 3-tuples; provenance needs `add_edges`
- ~~A worker-sandbox flag other than the launcher markers~~ — `_live_worker()` (`dangerous_actions.py:342`) scans processes and is not a sandbox test

### Edit Sites (Blueprint Anchors)

Verified against: `b95685da81`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/__init__.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/models.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/producers.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/validate.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/index.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/plane.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/resolver.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/procedure.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_advice.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure_probes.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/scripts/procedure.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/_assets/sdd/procedures/sdd-workflow.yaml` | CREATE | — | — | — |
| `sdd/procedures/sdd-workflow.yaml` | CREATE | — | — | — |
| `packages/ai-parrot-tools/src/parrot_tools/wiki/procedure.py` | CREATE | — | — | — |
| `wiki/sdd-tooling/sdd/procedure-graph.md` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/skills/models.py` | MODIFY | `    suggestions: list[SkillSuggestion] = Field(` | `models.py:93` | 1 |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | `    raw_suggestions = metadata.get("suggestions", None)` | `parsers.py:124` | 1 |
| `packages/ai-parrot/src/parrot/skills/parsers.py` | MODIFY | `        suggestions=suggestions,` | `parsers.py:144` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` | MODIFY | `    from parrot.knowledge.lint.packs.plane_fix import PLANE_FIX_RULES` | `__init__.py:18` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/lint/packs/__init__.py` | MODIFY | `        cls() for cls in (*PLANE_RULES, *PLANE_FIX_RULES, *EXPORT_RULES, *ADR_RULES, *MEMORY_RULES)` | `__init__.py:21` | 1 |
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `    "hooks": {` | `cli.py:327` | 1 |
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | `    techwiki: TechwikiConfig \| None = None` | `config.py:43` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/dangerous_actions.py` | MODIFY | `        result = _render(evaluate(payload, root=root))` | `dangerous_actions.py:446` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `    return {"hookSpecificOutput": output}` | `worktree_environment.py:1075` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/worktree_environment.py` | MODIFY | `def _load_native_sandbox() -> Any:` | `worktree_environment.py:603` | 1 |
| `packages/ai-parrot/src/parrot/sdd/scripts/native_claude_sandbox.py` | MODIFY | `    names = ("native_claude_sandbox.py", "worktree_environment.py")` | `native_claude_sandbox.py:218` | 1 |
| `packages/ai-parrot/src/parrot/sdd/_assets/manifest.json` | MODIFY | `"source": "sdd/WORKFLOW.md"` | `manifest.json:557` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `    "_assets/sdd/WORKFLOW.md",` | `pyproject.toml:1043` | 1 |
| `packages/ai-parrot/src/parrot/sdd/installer.py` | MODIFY | `            actions.extend(_install_ledger_hooks_step(root, receipt))` | `installer.py:1611` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/mcp_server.py` | MODIFY | `        tools = tools + create_schema_tools(read_store, root, config, context.schema_service)` | `mcp_server.py:387` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    "wiki_schema_lookup": _Spec(` | `transport.py:216` | 1 |
| `packages/ai-parrot/src/parrot/knowledge/wiki/transport.py` | MODIFY | `    elif name == "wiki_schema_lookup":` | `transport.py:391` | 1 |
| `packages/ai-parrot/tests/sdd/test_wheel_only_foreign_repo.py` | MODIFY | `SCENARIOS: dict[str, Scenario] = {` | `test_wheel_only_foreign_repo.py:363` | 1 |
| `wiki/_index.yaml` | MODIFY | (unverified — check before use) | — | — |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/engine.py` | MODIFY | (unverified — FEAT-887 not merged) | — | — |
| `.claude/commands/sdd-start.md` and twins | MODIFY | (unverified — FEAT-887 not merged) | — | — |

Rows marked unverified depend on code that is not merged (FEAT-887) or on a file whose anchor
was not located; `/sdd-task` must verify them before use.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- **Hook fast path**: `procedure_advice` follows `dangerous_actions.py` — stdlib only, no
  `parrot` import at module level, every exception swallowed, never a non-zero exit.
- **Fail open, deny narrowly**: a denial needs a mandatory node and a definite violation. Absent
  plane, stale index, unknown probe, disabled config or any exception means no denial.
- **One decision table**: the §2 guard table lives in `evaluate_command` only; the two guards
  render its result and add no logic of their own.
- **Advisory envelope**: `additionalContext` only; never `updatedInput`. In the worktree guard a
  denial removes the pending `updatedInput`.
- **Templates, not free text**: guard and briefing text come from fixed templates filled with
  node fields; `advice` is capped at 300 characters by the validator.
- **Overlay planes**: `procedure` is a separate store file, like `schema.db`
  (`wiki/schema/service.py:67`); nothing is written to the code wiki.
- **Script helpers**: `parrot.sdd.scripts.<module>.main(argv) -> int`, mounted through `VERBS`.
  A helper with a `main()` must be mounted or listed in `_UNMOUNTED`; `procedure_advice` and
  `procedure_probes` have no `main()`.
- **Asset twins**: after editing the packaged manifest, `scripts/sdd/check_asset_sync.py` must pass.

### Known Risks / Gotchas

- **Advisory text arrives after the command.** Taken from FEAT-887's adversarial review (F12),
  not re-probed here. If a host delivers it earlier, nothing breaks; the wording stays valid.
- **Coverage is narrower than "every seat".** Guards run in interactive Claude Code sessions
  (when the dangerous-actions guard is registered by `parrot sdd install`) and in launched
  Claude workers. Codex and agy seats get the task-start block only.
- **ai-parrot's own interactive sessions** register a legacy shell guard
  (`.claude/hooks/dangerous-actions-blocker.sh`), not the Python module; the guard integration
  is inactive there until the entry is the packaged one (`parrot sdd install --portable`).
  Decided (Jesus Lara, 2026-11-13): ai-parrot switches to the packaged guard after merge, as
  an operator step (the settings file is untracked). Rule parity between the shell script and
  the Python guard was not compared here; the operator checks it before switching.
- **False denials on `mv`.** The bypass guard matches only paths under `sdd/tasks/active/`.
  Closing through the script moves files in Python, not with `mv`, so it is not affected.
  Deliberate repairs use `PARROT_ALLOW_PROCEDURE=1`.
- **`gh pr create` without `--base`** is not denied (unknown), although `gh` then targets the
  default branch. The advisory says to pass `--base`.
- **Stale plane**: the hook hashes the listed source files only after a guard matched, so a miss
  costs one small JSON read. A stale plane silences the guard until the next build.
- **Worktrees**: sources and the plane are read from the primary checkout. A manifest edited on
  a feature branch takes effect only after it reaches the primary checkout.
- **Loops**: `next` cycles are legal; only `requires` cycles are errors.
- **`SddConfig` forbids extra keys**: the `procedure` section must be added to the model before
  any repository writes it.
- **FEAT-887 ordering**: M11 cannot start until FEAT-887's briefing path is merged. M1–M10 and
  M12 do not depend on it.
- **`confirm` is inert** (S9). A future dispatch feature must define the grant scope (declared
  tools only), expiry and behavior on edited arguments before enabling it.
- **Learned procedures** are never mandatory and never carry `confirm`; the validator enforces it.

### External Dependencies

| Package | Version | Reason |
|---|---|---|
| `pydantic` | existing | models (kept out of the hook path) |
| `PyYAML` | existing | manifest parsing |
| `python-frontmatter` | existing | skill producer, via `parrot.skills.parsers` |

No new dependency.

---

## Consequences

<!-- decision-audit: input_digest=sha256:b4708de574a95ebd3fb33e7e78e7cf2020e0866939f14ce463527960fe1abe57 evaluation_digest=sha256:7ed8e053931de2ce64d1b3a253924b62ae32aadb7e16c97d84170faa49eee5f9 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/procedural-graph-plane.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-pageindex, knowledge-wiki, memory, skills, tools
- Unmapped tags: agent-knowledge, hooks, procedural-graph, sdd-tooling, wikitoolkit
- Targets resolved: 0/0
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-pageindex",
      "knowledge-wiki",
      "memory",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "agent-knowledge",
      "hooks",
      "procedural-graph",
      "sdd-tooling",
      "wikitoolkit"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/procedural-graph-plane.spec.md"
    }
  ],
  "evaluation_digest": "sha256:7ed8e053931de2ce64d1b3a253924b62ae32aadb7e16c97d84170faa49eee5f9",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:b4708de574a95ebd3fb33e7e78e7cf2020e0866939f14ce463527960fe1abe57",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {
      "adr:doc:171b17ccd26bdbd2d71040746b22371a335d364d": "b22c79daae2a187f2091ea23449825e8769e2c07",
      "adr:doc:34394c36f5bf140678b8e17d43c3628e3d2c1440": "3fa15352d0e9ed972bd5de7ac1fd60e06906e60b",
      "adr:doc:666d8f740c695673063f76777db7b7b0e9d95a2e": "47f1bebe56724843f6c0981f67bbba72917b4b0b",
      "adr:doc:87781d348dff80cbfb25c253989a8940badd08d1": "49458f64f4bb614a9ff42750b53d9caa806f81a0",
      "adr:doc:89e808b78adee5c727e047ac239817bfd29e5cfe": "9feeb90ec52cb53395d978a3b946323a7b9072ab",
      "adr:doc:96dabb33251cd210186d7ab5c456ded102a4b025": "b537050f62f77a85b651af8c2595f4dc7fd4cebe",
      "adr:doc:c3c29b415ba46e730ee37c6fc520914a1905d022": "0cd9cc9f082b9d988da023e3886d310f8eed8eae",
      "adr:doc:c6b0e17a26d4b1ae2be8569a33db9a3aeedc0fbd": "804496ec336c99570df5502580ff980a38f56bfc",
      "adr:doc:e7c5ae770b06db3b35cdd4cba93001a58bfa7bef": "394f4656c71618a256427d81350fdc32335fa791"
    },
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "65548b9a71329b13ab44f4904dff99814e1aac0da4bb2b58171a7201e3a9ba39"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] Advisory or mandatory procedures? — *Resolved in brainstorm*: both; mandatory procedures point to a flow/crew; advisory ones are injected as guidance.
- [x] Does a mandatory dispatch confirm with the user? — *Resolved in brainstorm*: yes, through the existing HITL infrastructure, when dispatch exists. Not in v1 (dispatch is a non-goal).
- [x] Granularity of the confirmation? — *Resolved in brainstorm*: confirming a procedure is implicit acceptance of all the tools it declares. Recorded for the dispatch follow-up; `confirm` is inert in v1.
- [x] Where does the graph live? — *Resolved in brainstorm*: a wikitoolkit plane; a central graph database is a follow-up.
- [x] Pilot? — *Resolved in brainstorm*: the SDD workflow.
- [x] One feature with FEAT-887 or two? — *Resolved in brainstorm*: two.
- [x] When may an agent write facts? — *Resolved in brainstorm*: never in the authoritative tier. Here: learned procedures are never mandatory.
- [x] Manifest instead of command frontmatter for the SDD graph? — *Resolved in brainstorm*: accepted.
- [x] Prompt-submit injection? — *Resolved in brainstorm*: out of the pilot.
- [x] Named probes or expressions? — *Resolved in brainstorm*: named probes with deterministic validation.
- [x] Guarded commands in v1? — *Resolved in brainstorm*: the five in §2. `parrot sdd ids reserve` excluded.
- [x] How is the pilot measured? — *Resolved in brainstorm*: task-state violations only.
- [x] Does the manifest ship in the package? — *Resolved in brainstorm*: yes, installed by `parrot sdd install`, with a repo-local overlay.
- [x] Host parity? — *Resolved in brainstorm*: inherit, build no host adapters. *Refined 2026-11-13 (Jesus Lara)*: see the next two items.
- [x] FEAT-887 dropped its pre-tool hook; where does the pre-command check attach? — *Jesus Lara, 2026-11-13*: the existing SDD guards (`dangerous_actions`, `worktree_environment`); no new hook.
- [x] Advisory text reaches the model after the command; what does the guard do on a violated mandatory node? — *Jesus Lara, 2026-11-13*: deny mandatory violations only, naming the correct command, with an escape variable; everything else is advisory. This supersedes "mandatory is only announced in the pilot" for guarded commands; dispatch stays out.
- [x] Should ai-parrot's own `.claude/settings.json` switch from the legacy shell guard to the packaged Python guard so the pilot covers interactive sessions here? — *Jesus Lara, 2026-11-13*: yes. Operator step after merge (the file is untracked), documented in the "Pilot activation" section (M12, §5, §7).
- [x] `pr.open` is remote and therefore not enforced by the guard; is "a PR already exists for this branch" worth a cached local signal later? — *Jesus Lara, 2026-11-13*: yes, it is worth it; recorded as a follow-up in Non-Goals, not in v1.

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` · Status: completed
> · Transcript: `sdd/state/FEAT-891/design_research/`

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Define the FEAT-887 integration contract before implementation (architecture) | CONFIRM | FEAT-887 has no pre-tool path; the dependency is reduced to one module with unverified anchors | §2 Overview, M8, M11 |
| S2 | Keep procedure hook evaluation on a dedicated stdlib fast path (risk) | CONFIRM | required by the hook budget | M5, §5 |
| S3 | Specify an atomic compiled-index publication protocol (architecture) | CONFIRM | readers must see one complete snapshot | §2 Plane and index, M4 |
| S4 | Separate procedure requirements into typed fields (api) | CONFIRM | makes cycle detection and validation unambiguous | §2 Data Models, M3 |
| S5 | Make the skill producer preserve graph metadata explicitly (api) | CONFIRM | the parser copies fields by hand | M2 |
| S6 | Reuse the existing source-slice and provenance mechanisms (architecture) | CONFIRM | no store subclass is needed | M4 |
| S7 | Constrain hook probes to bounded local evidence (risk) | CONFIRM | probe cost classes; remote probes are CLI-only | §2 Probes, M5, M6 |
| S8 | Define how the resolver knows the last completed procedure (architecture) | CONFIRM | position is derived from `done_when` probes, not recorded | §2 Overview, M6 |
| S9 | Treat mandatory confirmation as future metadata, not current authorization (api) | CONFIRM | `confirm` and `executor` are inert in v1 | §1 Non-Goals, §7 |
| S10 | Integrate the manifest into the existing packaged-asset lifecycle (testing) | CONFIRM | asset entry, package data, twin test, wheel-only smoke | M9, M12 |

Summary: **10** confirmed · **0** rejected · **0** escalated. Every `affected_paths` entry was
checked for containment and existence.

---

## 10. Documentation

- **Policy**: `required`
- **Pages**:
  - `wiki/sdd-tooling/sdd/procedure-graph.md` — create: the model, the manifest format and
    overlay, the probe table, guard behavior and the three escape switches, skill frontmatter
    fields, the CLI verbs, the namespace registration command, and the pilot baseline.
- **API modules**:
  - `parrot.knowledge.wiki.procedure`

---

## Worktree Strategy

- **Isolation**: one feature worktree; the `sdd-coder` engine gives each task its own
  sub-worktree inside it.
- **Module dependency graph**:
  - M2 → M1 (imports `ProcedureSpec`, `ProcedureManifest`).
  - M3 → M1 (validates `ProcedureSpec`).
  - M4 → M1 (compiles and stores `ProcedureSpec`).
  - M5 → none (stdlib; the index shape is fixed in §2).
  - M6 → M1, M5 (`Resolution` models; reuses `LOCAL_PROBES`).
  - M7 → M2, M3, M4, M6 (the verbs call all four).
  - M8 → M5 (`evaluate_command`).
  - M9 → M2, M3, M7 (the manifest must load and validate; the install step calls `build`).
  - M10 → M4, M6.
  - M11 → M6, M7, and FEAT-887.
  - M12 → M7, M8, M9.
  M2, M3, M4 and M5 have no edge between them and run concurrently after M1 (M5 from the start).
- **Shared files**: `packages/ai-parrot/src/parrot/knowledge/wiki/procedure/__init__.py` is
  written once by M1 with every export, so no later module edits it. `test_index_contract`
  belongs to M4's task and needs M5 merged first.
- **Exclusive resources**: packaged asset twins (M9; `scripts/sdd/check_asset_sync.py` after the
  task); `.claude/commands/sdd-start.md` and twins (M11).
- **Cross-feature dependencies**:
  - FEAT-887 `sdd-experience-memory` (approved, not implemented) must be merged before M11.
    FEAT-887 also edits `native_claude_sandbox.py` (`_control_files`, `native_sandbox_settings`)
    and `sdd/installer.py`; rebase M8 and M9 on it if it lands first.
  - Any in-flight SDD-tooling fix touching `dangerous_actions.py` or `worktree_environment.py`.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-13 | Jesus Lara | Initial draft from `sdd/proposals/procedural-graph-plane.brainstorm.md`; guard attachment and deny-on-mandatory decided after FEAT-887 rev 0.4 dropped its pre-tool hook |
| 0.2 | 2026-11-13 | Jesus Lara | Approved. Both open questions resolved: ai-parrot switches to the packaged guard as an operator step after merge; a cached `pr.open` signal is a follow-up |
