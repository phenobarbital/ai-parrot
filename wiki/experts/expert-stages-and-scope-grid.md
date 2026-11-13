---
title: "Expert Stages and the Scope Grid"
summary: "How a scope grid declares ordered expert stages (subagent, mob, inline, pipeline), compiles to an AgentsFlow, pauses at gates and is driven by `parrot experts`."
---

# Expert Stages and the Scope Grid

## Purpose

A **scope grid** (`ScopeGrid`) is a declarative, ordered list of expert **stages**
(`ExpertStageConfig`). `compile_scope` turns it into a plain `FlowDefinition` of
`expert_stage` nodes that `AgentsFlow` executes, so a multi-expert workflow with
human approval points needs no new orchestrator.

## Stage modes

| Mode | What runs |
|---|---|
| `subagent` | exactly one expert, inside `activate_expert` (so spans carry `expert.*` attributes) |
| `mob` | every listed expert concurrently; a failed expert is skipped unless `strict`, and all failing raises `ExpertStageError`. The compiler appends a `<stage>-synthesis` node (stock `SynthesisNode`, needs `ctx.synthesis_client`) |
| `inline` | one `conductor` agent receives each expert's rules and knowledge layers under `expert_rules:<slug>` / `expert_knowledge:<slug>` (`build_inline_conductor`); two experts declaring the same `ALWAYS`/`NEVER` rule raise `InlineCompositionError` |
| `pipeline` | compiled into a chain of `<stage>-<n>` subagent nodes, one per expert; the stage gate sits on the last one |

A stage with a `gate` (`GateSpec`) opens it through the [generic gate host](../flows/generic-gate-host.md)
and returns `metadata["status"] == "awaiting_gate"`; the outgoing edge only fires once the gate is approved.

## Where scopes live

`load_scopes(agents_dir)` reads the bundled `parrot/experts/bundled/scopes/*.yaml` and overlays
`<agents_dir>/experts/scopes/*.yaml`; a workspace scope with the same name wins.

```yaml
scope: security-patch
description: Triage a CVE, await approval, then prepare a remediation plan.
stages:
  - stage: intake
    experts: [cve-analyst]
    mode: subagent
    gate:
      kind: approval
      title: Approve CVE remediation planning
  - stage: plan
    experts: [cve-remediation]
    mode: subagent
```

`match: {projects: [...], tags: [...]}` is optional and is what [SDD expert consult](../sdd-tooling/sdd/expert-consult.md)
uses to pick scopes for a document.

## Compiling

```python
from parrot.experts.grid.compiler import compile_scope
from parrot.experts.grid.loader import load_scopes

grid = load_scopes(agents_dir)["security-patch"]
definition = compile_scope(grid, registry=expert_registry)  # FlowDefinition
```

`compile_scope` raises `ScopeGridError` with one of `UNKNOWN_EXPERT`, `CAPABILITY_MISMATCH`,
`UNKNOWN_GATE_KIND`, `CYCLE` or `INVALID` (`ScopeGridErrorCode`). The nodes read `expert_registry`
(required), `gate_host` (when a stage has a gate), `run_id` and `tenant` from `FlowContext.shared_data`.

## Running: `parrot experts`

| Command | Effect |
|---|---|
| `parrot experts scopes` | list the scopes |
| `parrot experts run --scope S --input TEXT\|@FILE [--tenant T]` | run; prints `run <id> paused` with the gate id when a gate is hit |
| `parrot experts gates` | list pending gates |
| `parrot experts approve\|reject GATE_ID [--comment C]` | resolve a gate |
| `parrot experts resume --run-id ID` | continue once every gate of the run is approved |

Group options: `--agents-dir`, `--gate-db` (SQLite gate store, default `<parrot home>/gates.sqlite`) and
`--checkpoint-store`. `--checkpoint-store sqlite` checkpoints run state in a lease-capable SQLite store
(`LeaseDurableCheckpointStore`) so no Redis is needed; the default follows `FLOW_CHECKPOINT_STORE`.
Only `run_id`, `tenant`, `scope` and `pending_gates` are written to checkpoints; the live registry and gate host never are.

## Related behaviour

- **Episodes**: each expert run records an episode (`record_episode`); an expert manifest that declares a source of
  kind `episodes` retrieves its own recent ones through `EpisodeSource`.
- **Seat hints**: `RosterConfig.expert_tier_seats` maps expert tiers to a complexity class
  (`judgment`→complex, `balanced`→standard, `templated`→cheap) and `eligible_seats_for_tier` applies it.

## Gotchas

- Every gate kind used by a grid must be registered (`register_gate_kind`); the CLI registers `approval`.
- `resume` refuses to continue while any gate of the run is pending, rejected, expired or missing.
- Approvals from the CLI are recorded as `cli:<OS user>`, not as a Navigator identity.
