---
title: Procedure Graph
summary: The procedure plane — what to do next in a workflow, as a deterministic, queryable graph.
---

# Procedure Graph

## Purpose

An agent needs three kinds of knowledge: what is true, what matters now, and what to do next. The procedure plane answers the third question by folding authored workflow manifests into a deterministic graph that operators, guards, the CLI, and MCP can query without an LLM or conversation history.

## Public API

- [`ProcedureSpec`](ref:parrot.knowledge.wiki.procedure.ProcedureSpec) — one typed procedure node.
- [`ProcedureManifest`](ref:parrot.knowledge.wiki.procedure.ProcedureManifest) — one producer graph and its nodes.
- [`ProcedurePlane`](ref:parrot.knowledge.wiki.procedure.ProcedurePlane) — the SQLite wiki store and compiled index under `.parrot/procedure/`.
- [`validate_graph`](ref:parrot.knowledge.wiki.procedure.validate_graph) — deterministic graph validation.
- [`resolve`](ref:parrot.knowledge.wiki.procedure.resolve) — deterministic next-step resolution against a probe runner.

## Configuration & Parameters

### Plane and manifests

`parrot sdd procedure build` reads every `sdd/procedures/*.yaml` file from the primary checkout. It writes the procedure wiki to `.parrot/procedure/wiki.db` and publishes the guard-friendly compiled index last at `.parrot/procedure/procedures.json`.

A manifest has four top-level fields:

```yaml
schema_version: 1
graph: sdd
exclude: [obsolete-step]
uncovered_ok: [sdd-status]
procedures:
  - id: task-close
    title: Close a task with the script
    kind: command
    mode: mandatory
    scope_kind: task
    command: parrot sdd task close <TASK> <slug> verified
    preconditions:
      - {probe: task.status, expect: in-progress}
    guards:
      - kind: entry
        executable: parrot
        argv_prefix: [sdd, task, close]
        scope: {task: {argv: 0}, feature: {argv: 1}}
```

`schema_version` is `1`; `graph` is the producer prefix; `procedures` contains the nodes; and `uncovered_ok` exempts packaged command names from coverage warnings. Each additional manifest is an overlay: files are loaded in filename order, unqualified node and edge IDs receive that file's `graph:` prefix, `exclude` removes matching IDs after all files are merged, and a duplicate ID is an error naming both files.

Every node accepts these fields:

| Field | Meaning |
|---|---|
| `id` | `<producer>:<kebab-name>` after prefixing. |
| `title` | Human-readable name. |
| `kind` | `command`, `skill`, `flow`, `crew`, or `rule`. |
| `mode` | `advisory` by default; also `mandatory` or `constraint`. |
| `source` | `authored` by default, or `learned`. |
| `command` | Human-readable invocation. |
| `intents` | Intent phrases associated with the node. |
| `applies_to` | Entity type names; these become `applies_to` edges to `type:<name>`. |
| `scope_kind` | `repo`, `feature` (default), or `task`. |
| `preconditions` | Probe checks that describe whether the step applies now. |
| `done_when` | Probe checks that determine tri-state completion. |
| `requires_procedures` | Procedures that must be complete before this node is ready. |
| `requires_facts` | Required fact names. |
| `requires_tools` | Required tool names. |
| `next` | Normal successor IDs. |
| `alternative_to` | Alternative procedure IDs. |
| `escalates_to` | Escalation target IDs. |
| `on_failure` | Failure-path IDs. |
| `learned_from` | Provenance procedure IDs. |
| `guards` | Command matches that protect entry to, or bypass of, the procedure. |
| `use_instead` | Required replacement command for a bypass guard. |
| `executor` | Optional `{kind, ref}` reference; inert in v1. |
| `confirm` | Confirmation marker; inert in v1. |
| `advice` | Guard/brief text, limited to 300 characters. |
| `body` | Page body, including a skill's body when produced from frontmatter. |
| `origin_path` | Repository-relative source path, assigned by the producer. |

A probe check contains `probe`, `expect` (default `true`), and string-valued `args`. A guard contains `kind` (`entry` or `bypass`), an executable basename, an optional `argv_prefix`, optional repository-relative `path_globs`, and optional scope extractors; each extractor uses exactly one positional `argv` index or `flag` expression such as `--base|-B`.

### Probes

The resolver may run both cost classes. Hooks only evaluate local preconditions, and the MCP tool uses local probes only.

| Probe | Cost | Signal |
|---|---|---|
| `spec.exists` | local | The scoped specification exists. |
| `index.exists` | local | A per-spec task index resolves for the scope. |
| `task.status` | local | The task status matches the pipe-separated expected value. |
| `task.depends_done` | local | Every dependency is `done`. |
| `feature.tasks_done` | local | Every feature task is closed. |
| `flow.base_allowed` | local | A feature/fix branch is not targeting the configured hotfix base. |
| `env.not_worker_sandbox` | local | No worker-sandbox launcher marker is present. |
| `branch.pushed` | remote | `git rev-list --count @{u}..HEAD` reports zero commits. |
| `pr.open` | remote | `gh pr list --head <branch>` reports an open pull request. |

`branch.pushed` and `pr.open` are available to CLI resolution and use `remote_probe_timeout_seconds`. They are never evaluated by the hook. In particular, `pr.open` is not enforcement; a cached local "PR already exists" signal is only a recorded follow-up, not a v1 feature.

### Repository settings

The optional `procedure` object in `sdd/config.json` uses these defaults:

```json
{
  "procedure": {
    "enabled": true,
    "enforce": true,
    "brief_max_lines": 8,
    "remote_probe_timeout_seconds": 5
  }
}
```

`enabled` disables procedure advice and task-start briefs when false. `enforce` controls whether a mandatory guard violation denies the command. `brief_max_lines` caps the rendered task-start block, and `remote_probe_timeout_seconds` bounds each remote CLI probe.

### Skill frontmatter

An authored skill becomes `skill:<name>` only when its frontmatter contains a `procedure:` mapping:

```yaml
---
name: review-release
description: Review release readiness
procedure:
  mode: advisory
  scope_kind: feature
  command: /review-release
  preconditions:
    - {probe: feature.tasks_done}
  advice: Review the completed feature before release.
---
```

The mapping accepts node fields. The producer fixes the ID, kind, body, source, and origin from the skill; learned skills are always advisory and cannot require confirmation.

### Escape switches

Three switches downgrade a procedure denial to advice:

- `PARROT_ALLOW_PROCEDURE=1` bypasses only the procedure denial for a deliberate exception.
- `PARROT_ALLOW_DANGEROUS=1` bypasses the entire dangerous-actions guard, including procedure denial.
- `"procedure": {"enforce": false}` in `sdd/config.json` makes mandatory violations advisory for the repository.

## Usage Examples

The following excerpts were produced from the shipped `sdd-workflow.yaml` manifest:

```console
$ parrot sdd procedure build --root .
procedure plane: 9 pages, 12 edges, 1 sources

$ parrot sdd procedure list
sdd:pr-create  mandatory  feature  Open the pull request against the flow base branch
sdd:task-close  mandatory  task  Close a task with the script

$ parrot sdd procedure show sdd:task-close
id: sdd:task-close
title: Close a task with the script
kind: command
mode: mandatory
command: parrot sdd task close <TASK> <slug> verified

$ parrot sdd procedure next --feature procedural-graph-plane --task TASK-5652 --no-remote
scope: branch=main, feature=procedural-graph-plane, task=TASK-5652
sdd:pr-create  mandatory  gh pr create --base <base_branch> --head <branch>  unmet: flow.base_allowed
sdd:push  advisory  git push -u origin <branch>  unmet: env.not_worker_sandbox

$ parrot sdd procedure check
# no findings; exit status 0

$ parrot sdd procedure brief --task-file sdd/tasks/active/TASK-5652-procedure-documentation.md
### Procedure
Position: feature `procedural-graph-plane`, task `TASK-5652`.
Next: Open the pull request against the flow base branch — `gh pr create --base <base_branch> --head <branch>` (unmet: flow.base_allowed)
```

Use `--json` with `list`, `show`, `next`, or `check` for structured output; use `--mode` to filter `list`, and use `--max-lines` to override the configured brief limit.

The `wiki_procedure_next` MCP tool accepts optional `feature` and `task` arguments and returns the applicable next steps, unmet local preconditions, and mandatory nodes. It never runs remote probes or an LLM. Register the plane as a regular wikitoolkit namespace when direct wiki queries are also useful:

```bash
wikitoolkit ns add procedure --store .parrot/procedure
```

The documentation acceptance report is non-blocking and only reports pages declared by the spec:

```bash
parrot sdd techwiki check --spec sdd/specs/procedural-graph-plane.spec.md --root .
```

## Gotchas

The guard decision table is deliberately small:

| Mode and matched guard | Local precondition result | Decision |
|---|---|---|
| mandatory + bypass | any | deny; use `use_instead` |
| mandatory + entry | false | deny |
| mandatory + entry | unknown | advise |
| advisory + entry/bypass | false, unknown, or bypass | advise |
| any other match | satisfied | no procedure decision |

An escape switch or `enforce: false` downgrades `deny` to `advise`. Advice is injected as model context after the command; it does not retroactively stop the command.

- Interactive Claude Code is covered after the packaged Python dangerous-actions guard is activated, and launched workers are covered by the worktree-environment guard. Codex and agy have no interactive procedure guard integration; their procedure surface is the task-start `### Procedure` block only.
- Guard checks fail open. A missing, invalid, oversized, or stale compiled index silences procedure advice until the next successful `parrot sdd procedure build`.
- The manifest sources and compiled plane are read from the primary checkout, even when a command runs in a linked feature worktree. Local probes still inspect the active checkout.
- `gh pr create` without `--base` (or `-B`) leaves the base unknown, so the mandatory entry guard advises but does not deny. The guard enforces `flow.base_allowed`; it does not enforce remote `pr.open`.
- Mandatory nodes are reported by resolution, but v1 does not dispatch them. `confirm` and `executor` are stored metadata with no runtime effect.

## Pilot activation

Before switching ai-parrot's interactive guard, run the parity test that compares the deny/allow rule table in `.claude/hooks/dangerous-actions-blocker.sh` with the packaged Python guard in `parrot.sdd.scripts.dangerous_actions`, and review any newly added shell rule for a Python counterpart:

```bash
PYTHONPATH=packages/ai-parrot/src pytest packages/ai-parrot/tests/sdd/test_dangerous_actions.py -q -k parity_with_bash_blocker
```

When parity is green, install the portable hooks from the repository root:

```bash
parrot sdd install --portable
```

This registers `parrot sdd hooks dangerous-actions --hook` in `.claude/settings.json`. That settings file is untracked, so every collaborator must run the installation locally; merging the feature does not change anyone's interactive hook by itself.

## Pilot baseline

On 2026-11-14, at feature implementation commit `01a1b1eaf719cf5c45abf2753d00d7ba1cdcb095`, `parrot sdd task state` printed:

```text
OK: no stalled active/ task files (0 baselined).
```

Run the same command after later procedure or closeout changes and compare both the listed violations and the parenthesized baseline count with this zero-violation snapshot.

## Related

- [Decision Audit](decision-audit.md) — another deterministic SDD plane used by workflow operators.
- [Closeout Hooks](closeout-hooks.md) — configurable checks run at feature closeout.
- [Test Selection and Validation Contract](test-selection-validation-contract.md) — how SDD scopes verification commands.

