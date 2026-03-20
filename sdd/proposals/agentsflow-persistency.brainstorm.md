# Brainstorm: AgentsFlow Persistency

**Date**: 2026-02-22
**Author**: Claude
**Status**: exploration
**Recommended Option**: Option A

---

## Problem Statement

AgentsFlow (`parrot/bots/flow/fsm.py`) provides sophisticated DAG-based agent pipelines with FSM-controlled lifecycle management, conditional transitions, and pre/post hooks. However, flows are **defined exclusively in Python code**, which creates significant limitations:

1. **No persistence** — Flows cannot be saved, versioned, or transferred between services
2. **Developer-only** — Non-technical stakeholders cannot view or modify workflow definitions
3. **No visual editing** — Incompatible with visual builders (e.g., SvelteFlow, ReactFlow)
4. **No runtime composition** — Flows must be compiled at startup, cannot be loaded dynamically
5. **Lambda predicates are not serializable** — Conditional transitions use Python lambdas that cannot be persisted

**Who is affected:**
- **Developers** — Need to redeploy to modify workflows
- **Product teams** — Cannot visualize or understand agent flows
- **Ops teams** — Cannot inspect or debug flow definitions at runtime

## Constraints & Requirements

- **Parity with existing API** — Must support all current `AgentsFlow` features (transitions, conditions, hooks)
- **Async-first** — All I/O operations must be async (aioredis, aiofiles)
- **Type safety** — Pydantic models for validation
- **UI compatibility** — Schema must map to visual flow builders (nodes + edges)
- **Security** — No arbitrary code execution from persisted definitions
- **Backward compatibility** — Python-defined flows must continue working

---

## Options Explored

### Option A: CEL-Based Predicate Serialization

Use Google's Common Expression Language (CEL) for serializing conditional predicates. CEL is a safe, typed expression language used in Firebase, Kubernetes, and Open Policy Agent.

**Approach:**
- JSON schema with nodes + edges structure
- Predicates as CEL expression strings (e.g., `result.final_decision == "pizza"`)
- `FlowLoader` materializes JSON → runnable `AgentsFlow`
- Redis + file persistence mirroring `AgentCrew` patterns

**Example predicate:**
```json
{
  "from": "decision_node",
  "to": "pizza_agent",
  "condition": "on_condition",
  "predicate": "result.final_decision == \"pizza\""
}
```

✅ **Pros:**
- Industry-standard expression language (Google-backed)
- Safe sandbox — no arbitrary code execution
- Typed expressions with good error messages
- Familiar to ops teams (Kubernetes, Firebase)
- Small dependency (`cel-python` ~50KB)

❌ **Cons:**
- New dependency required (`cel-python`)
- Learning curve for developers unfamiliar with CEL
- Cannot express all Python logic (intentional security feature)
- CEL syntax differs from Python (e.g., `in` operator works differently)

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `cel-python` | CEL expression evaluation | v0.4+, pure Python, no external deps |
| `pydantic` | Schema validation | Already in project |
| `aioredis` | Redis persistence | Already in project |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flow/fsm.py` — `AgentsFlow`, `FlowNode`, `FlowTransition`
- `parrot/bots/flow/node.py` — `Node` base class with action hooks
- `parrot/bots/orchestration/crew.py` — Redis persistence patterns

---

### Option B: JSONPath + Simple Expressions

Use JSONPath for data extraction combined with a minimal expression grammar for comparisons. No external dependencies — built-in Python evaluation with restricted syntax.

**Approach:**
- JSONPath (via `jsonpath-ng`) for extracting values from results
- Simple comparison grammar: `$.result.decision == "pizza"`
- Custom parser validates expressions against allowlist

**Example predicate:**
```json
{
  "predicate": {
    "path": "$.result.final_decision",
    "operator": "eq",
    "value": "pizza"
  }
}
```

✅ **Pros:**
- Familiar JSONPath syntax
- Very restrictive — only comparisons, no logic
- `jsonpath-ng` is lightweight and well-maintained
- Easier to audit and secure

❌ **Cons:**
- Limited expressiveness — no `and/or`, no `in` operator
- Cannot handle complex conditions like `confidence > 0.8 && category in ["A", "B"]`
- Would need custom DSL for anything beyond simple comparisons
- Less portable than CEL (custom format)

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `jsonpath-ng` | Path extraction from JSON | Already in common use |
| `pydantic` | Schema validation | Already in project |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flow/fsm.py` — Core flow infrastructure
- Pydantic patterns from existing codebase

---

### Option C: Python AST Whitelisting

Parse Python expressions but restrict to a whitelist of safe operations. Uses Python's `ast` module to validate expressions before `eval()`.

**Approach:**
- Accept Python syntax predicates
- Parse with `ast.parse()`, walk tree to validate against allowlist
- Only allow: comparisons, boolean ops, attribute access, literals, `in`
- Reject: function calls, imports, assignments, comprehensions

**Example predicate:**
```json
{
  "predicate": "result.final_decision == 'pizza' and result.confidence > 0.8"
}
```

✅ **Pros:**
- Native Python syntax — zero learning curve
- Rich expressiveness (full boolean logic)
- No external dependencies
- Developers can test predicates directly in Python REPL

❌ **Cons:**
- Security burden — AST whitelisting is error-prone
- `eval()` is inherently risky even with restrictions
- Easy to accidentally allow unsafe patterns
- Harder to audit than CEL/JSONPath
- Not portable to other languages/platforms

📊 **Effort:** Medium-High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `ast` (stdlib) | Expression parsing | Built-in |
| `pydantic` | Schema validation | Already in project |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flow/fsm.py` — Core flow infrastructure
- Could leverage `RestrictedPython` patterns if needed

---

### Option D: Declarative Condition Objects

No expression language at all. Use structured JSON objects that enumerate all possible condition types.

**Approach:**
- Finite set of condition types defined as Pydantic models
- Each condition type has specific fields
- Conditions can be composed with `all_of` / `any_of` wrappers

**Example predicate:**
```json
{
  "condition": {
    "type": "field_equals",
    "field": "result.final_decision",
    "value": "pizza"
  }
}
```

**Compound example:**
```json
{
  "condition": {
    "type": "all_of",
    "conditions": [
      {"type": "field_equals", "field": "result.final_decision", "value": "pizza"},
      {"type": "field_greater_than", "field": "result.confidence", "value": 0.8}
    ]
  }
}
```

✅ **Pros:**
- Zero security risk — no expression parsing
- Fully declarative and predictable
- Easy to validate with Pydantic
- Simple to map to UI components

❌ **Cons:**
- Verbose — simple conditions require nested objects
- Limited flexibility — new conditions require code changes
- Less intuitive than expression strings
- Harder to read and write by hand

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` | Schema validation | Already in project |

🔗 **Existing Code to Reuse:**
- `parrot/bots/flow/fsm.py` — Core flow infrastructure
- Pydantic discriminated unions for condition types

---

## Recommendation

**Option A (CEL-Based Predicate Serialization)** is recommended because:

1. **Security without sacrificing power** — CEL provides rich expression capabilities (boolean logic, comparisons, list operations) in a proven sandboxed environment. Unlike Python AST whitelisting, CEL was designed from the ground up to be safe.

2. **Industry adoption** — CEL is used by Google Cloud, Kubernetes (admission webhooks), Firebase Security Rules, and Open Policy Agent. This means documentation, tooling, and community knowledge are readily available.

3. **Perfect balance of expressiveness** — Unlike JSONPath (too limited) or declarative objects (too verbose), CEL supports the exact level of logic needed for flow conditions:
   - `result.final_decision == "pizza"` — simple equality
   - `result.confidence > 0.8 && result.final_decision in ["pizza", "calzone"]` — compound logic
   - `ctx.retries < 3` — context access

4. **Portable** — CEL implementations exist for Go, Java, C++, and Python. If AI-Parrot ever needs polyglot support or cross-service flow definitions, CEL is ready.

5. **Minimal dependency** — `cel-python` is a pure-Python library with no native extensions, making it easy to install across environments.

**Trade-off accepted:** Developers will need to learn CEL syntax, which differs slightly from Python. This is acceptable because:
- The learning curve is small (CEL is Python-like)
- The security benefit outweighs the convenience cost
- Flow definitions are likely authored by a small set of developers

---

## Feature Description

### User-Facing Behavior

**For developers:**
- Define flows in JSON files or programmatically build `FlowDefinition` objects
- Load flows from files: `FlowLoader.load_from_file("flows/my_flow.json")`
- Save/load flows to Redis: `await FlowLoader.save_to_redis(redis, definition)`
- Materialize to runnable: `flow = FlowLoader.to_agents_flow(definition, agent_registry)`
- Export to SvelteFlow format: `svelteflow_data = to_svelteflow(definition)`

**For visual editor users:**
- Import/export flows as JSON
- Node types map 1:1 to UI components (agent, decision, start, end)
- Edges visualize transitions with condition labels

### Internal Behavior

1. **Schema Parsing** — `FlowDefinition` Pydantic model validates JSON structure
2. **CEL Compilation** — Predicate strings are compiled to CEL programs at load time (fast evaluation at runtime)
3. **Agent Resolution** — `agent_ref` fields are resolved against `AgentRegistry` or provided `extra_agents`
4. **Action Materialization** — `pre_actions` / `post_actions` are looked up in `ACTION_REGISTRY` and instantiated
5. **Transition Wiring** — Edges become `FlowTransition` objects with appropriate conditions/predicates
6. **Flow Construction** — Returns a fully configured `AgentsFlow` instance

### Edge Cases & Error Handling

| Scenario | Behavior |
|---|---|
| Invalid CEL expression | Raise `ValueError` at load time with expression and parse error |
| Missing agent_ref | Raise `LookupError` with agent name and available options |
| Unknown node type | Raise `ValueError` listing valid types |
| Circular edge references | Detected by existing `AgentsFlow._would_create_cycle()` |
| Redis connection failure | Let `aioredis` exception propagate (caller handles retries) |
| Malformed JSON | Pydantic validation error with field location |

---

## Capabilities

### New Capabilities
- `agentsflow-json-schema`: Pydantic models for `FlowDefinition`, `NodeDefinition`, `EdgeDefinition`
- `agentsflow-cel-evaluator`: CEL predicate compilation and evaluation
- `agentsflow-persistence`: File and Redis I/O via `FlowLoader`
- `agentsflow-actions`: Action registry with built-in action types (log, notify, webhook, etc.)
- `agentsflow-svelteflow-adapter`: Bidirectional conversion for visual editors

### Modified Capabilities
- `agentsflow-core`: Add `EndNode` as first-class type; ensure compatibility with loaded flows

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/bots/flow/fsm.py` | extends | Add `EndNode` support; no breaking changes |
| `parrot/bots/flow/node.py` | depends on | Actions use `Node.add_pre_action()` / `add_post_action()` |
| `parrot/bots/orchestration/crew.py` | pattern reference | Mirrors Redis persistence model |
| `pyproject.toml` | modifies | Add `cel-python>=0.4` dependency |
| `parrot/agents/registry.py` | depends on | `FlowLoader` resolves agents via registry |

---

## Open Questions

- [ ] **EndNode as first-class type** — Should `EndNode` be explicit in `fsm.py` (like `StartNode`), or remain implicit (node with no outgoing edges)? *Owner: Core team*
- [ ] **Fan-in edge semantics** — Should edges support `to: ["A", "B"]` for fan-out only, or also explicit fan-in (all sources must complete)? *Owner: Core team*
- [ ] **Action extensibility** — Should `ACTION_REGISTRY` allow runtime registration of custom actions? *Owner: Core team*
- [ ] **Versioning/migration** — When JSON schema evolves, should `FlowLoader` auto-migrate v1→v2, or require explicit migration? *Owner: Core team*
