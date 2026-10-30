# Domain Experts (FEAT-778)

Domain experts are declarative agent bundles with structured knowledge, governance rules, and a deterministic knowledge resolution order. The feature provides a reusable pattern for building specialized agents that share the same infrastructure as ordinary agents while enforcing consistent behavior across the REPL, HTTP server, and future stage conductors.

## When to use it

Use domain experts when you need a specialized agent that follows a fixed methodology, carries domain-specific knowledge, and operates under governance rules. The two shipped experts — `cve-analyst` and `cve-remediation` — demonstrate the pattern for security analysis and remediation planning.

## Bundle layout

An expert bundle is a directory containing:

```
<root>/
├── expert.yaml           # Manifest (required)
├── persona.md            # Documentation only (optional)
├── identity/             # Identity files (required)
│   ├── backstory.md
│   ├── capabilities.md
│   ├── goal.md
│   ├── rationale.md
│   └── role.md
├── knowledge/            # Tier-1 knowledge (optional)
│   └── *.md
├── rules/                # Governance rules (optional)
│   └── governance.md
└── adr/                  # ADR templates (optional)
    └── *.md
```

### Two roots and shadowing

Experts are discovered in two roots, scanned in this order:

1. **Bundled root** — `parrot/experts/bundled/<slug>/` (shipped in the wheel)
2. **Workspace root** — `AGENTS_DIR/experts/<slug>/` (user-supplied)

A workspace bundle shadows a bundled one of the same name unless the bundled manifest declares `global_only: true`. Within one root, duplicate names raise `DuplicateExpertError` at load time.

### Tenant overlay

Tenant-specific knowledge lives below `tenants/<tenant>/`:

```
AGENTS_DIR/experts/cve-analyst/
├── knowledge/                    # Tier-1 shared
│   └── cve-triage-method.md
└── tenants/
    └── acme/
        └── knowledge/            # Tier-2 tenant-specific
            └── acme-policy.md
```

The tenant tree shadows Tier-1 by name with the same `global_only` lock semantics as skills. The reserved tenant names are: `experts`, `knowledge`, `governance`, `skills`, `learned`, `tenants`, `prompts`, `queries`, `kb`, `documents`, `flows`, `_drafts`, `_shared`.

### Wiki seeding

When an expert's wiki namespace (`expert-<slug>`) is empty, `ExpertRegistry.load()` writes the bundle's Tier-1 `knowledge/*.md` files as wiki pages through `BaseWikiStore.upsert_pages()`. This is an LLM-free, sha256-keyed, idempotent operation. A bundle with no knowledge files and an empty namespace is rejected at load time.

## Manifest reference

The `expert.yaml` manifest defines the expert's behavior:

```yaml
name: cve-analyst              # kebab-case, 2-64 chars (required)
display_name: CVE Analyst      # Human-readable name (required)
description: Triage, workspace # One-line description (required)
tier: judgment                 # judgment | balanced | templated (default: balanced)
toolkits: [CVEToolkit, ...]    # Toolkit names (required)
capabilities: [validate, write, review]  # Capability flags (optional)
produces: [vulnerability-report, adr]    # Output types (optional)
global_only: false             # Prevent workspace shadowing (default: false)
knowledge:                     # Knowledge sources (required)
  - {source: wiki, mode: retrieval, scope: {topics: [cve]}}
  - {source: bundled, mode: inline}
  - {source: graphindex, mode: retrieval}
  - {source: adr, mode: inline, filter: {status: [accepted]}}
```

### Manifest invariants

The manifest validator enforces these rules:

- `name` must be kebab-case
- `knowledge` must contain a `source: wiki` entry
- `spawn_sub_agent` must not appear in `toolkits` or `tools_allow`
- `tier` must be a recognized tier name, not a model id

### Tier to model projection

Each tier maps to a `ModelConfig` at load time:

| Tier | Use case | Model characteristics |
|---|---|---|
| `judgment` | Analysis, triage, strategic advice | High-capability model |
| `balanced` | General-purpose expert tasks | Mid-capability model |
| `templated` | Recipe-based remediation, form-filling | Efficient model |

## Knowledge resolution

`KnowledgeResolver.resolve(expert, stage, workspace, model, counter)` returns a `KnowledgeContext` with a fixed layer order:

1. **Rules chain** — org → team → project → expert (stage added in phase 4)
2. **Tier-1 shared** — bundled knowledge shared across all experts
3. **Tier-1 expert** — the expert's own bundled knowledge
4. **Tier-2 shared** — workspace knowledge under `AGENTS_DIR/experts/`
5. **Tier-2 expert** — workspace knowledge under `AGENTS_DIR/experts/<slug>/`
6. **ADR** — accepted decisions from `DecisionService`
7. **Stage inputs** — empty until phase 4
8. **Retrieval handles** — wiki, bookstore, GraphIndex, KB

### Budget and trimming

The knowledge budget is derived from `build_default_budget(model)`. Trimming removes Tier-1 methodology before Tier-2, but never removes rules or identity. Every trimmed layer is listed in `KnowledgeContext.trimmed`.

### Knowledge modes

- **inline** — content is embedded directly in the prompt (persona, rules, ADR, bundled knowledge)
- **retrieval** — a handle points to an external source (wiki, bookstore, GraphIndex, KB)

## Governance rules

Rules live in `rules/governance.md` and the org/team/project governance chain under `AGENTS_DIR/governance/`. The grammar:

```markdown
## Mandated
ALWAYS tool:read_file on path:/etc/**
ALWAYS tool:lookup_cve before tool:download_cve

## Forbidden
NEVER tool:spawn_sub_agent
NEVER tool:delete_file on path:/production/**
```

### Rules chain order

Rules are additive and evaluated in this order: org → team → project → expert. A rule at a higher layer cannot be overridden by a lower layer. Rules are never trimmed.

### Optional rules

A bundle without `rules/governance.md` loads with a warning: "expert <name>: no rules/governance.md — org/team/project rules still apply."

## ADR consume and produce

### Consuming ADRs

The `adr` knowledge source calls `DecisionService.why()` or `DecisionService.for_symbol()` with a token budget, keeping only hits where `source_status == "accepted"` and `review_status != "rejected"`.

### Producing ADRs

An expert with the `write` capability can propose an ADR through the `expert_propose_adr` tool. The record is born with:

- `origin: "inferred"`
- `review_status: "unreviewed"`

Only a human review can accept it. The proposal calls `DecisionService.generate(target)` which returns candidate decision ids.

## Persona is documentation only

The `persona.md` file in a bundle is for human readers. It is not parsed, not rendered into prompts, and has no runtime effect. This follows the decision from FEAT-321 and U1.

## The ordinary-agent guarantee

An agent declared in `AGENTS_DIR/agents/*.yaml` with no expert or governance attributes is **unaffected** by this feature:

- No resolver, no rules layer, no deny rule
- Legacy knowledge base path (`AbstractBot.knowledge_bases`) works byte-for-byte
- No `expert` tag, no wiki namespace seeding

This guarantee is AC24 in the spec.

## The spawn_sub_agent exception

Every expert carries a PBAC deny rule on `tool:spawn_sub_agent` with `SPAWN_DENY_PRIORITY = 100`. This ensures no expert can delegate to a sub-agent, enforcing the "mandatory wiki and bookstore access, no delegation" requirement (G7).

The deny rule is registered through `agent_registry.register_db_bot_policies()` after the expert is instantiated.

## Runtime wiring

### Loading experts

The `load_experts()` function in `parrot.experts.bootstrap` discovers, seeds, and registers experts:

```python
from parrot.registry import agent_registry
from parrot.experts.bootstrap import load_experts

experts = await load_experts(agent_registry)
# Returns ExpertRegistry or None if disabled
```

The function:
1. Builds `ExpertRegistry` with bundled and workspace roots
2. Calls `registry.load()` which discovers bundles, seeds empty wiki namespaces, and registers agents
3. Logs the report: "experts: N loaded, M skipped, K seeded, shadowing=..."
4. Stores the registry on `agent_registry.experts`

### Where loading happens

- **REPL** — `StandaloneAgentLoader._ensure_discovered()` calls `load_experts()` after loading agent definitions
- **HTTP server** — `BotManager.load_bots()` calls `load_experts(enabled=self.enable_experts)` after loading agent definitions

Both hosts fail open: an expert loading error is logged and swallowed, never preventing host startup.

### Enabling and disabling

The `enabled` parameter defaults to `True`. Set it to `False` to skip expert loading entirely:

```python
experts = await load_experts(agent_registry, enabled=False)  # Returns None
```

The HTTP server has a `BotManager.enable_experts` flag (default `True`) mirroring `enable_registry_bots`.

## What phases 3-5 add later

This documentation covers phases 1-2. Future phases add:

- **Phase 3** — Stage binding: experts run as part of a defined stage (research, review, implement)
- **Phase 4** — Dispatch modes: inline, subagent, pipeline, mob execution
- **Phase 5** — Additional shipped experts: ContractsAgent, LegalLibrarianAgent

The resolver and registry are designed to support these extensions without breaking existing experts.