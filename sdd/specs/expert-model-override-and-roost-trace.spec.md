---
type: feature
base_branch: dev
projects: [ai-parrot]
tags: [domain-experts, roost, experts-registry, model-config, tracing, audit]
---

# Feature Specification: Expert model overrides and trace-carrying Roost queries

**Feature ID**: FEAT-790
**Date**: 2026-11-02
**Author**: Jesus Lara (with Codex)
**Status**: draft
**Target version**: 1.3.0 (planned, inherited from FEAT-778)

Source: `sdd/proposals/expert-model-override-and-roost-trace.proposal.md`; extends FEAT-778.

## 1. Motivation & Business Requirements

### Problem Statement

The finance committee requires an exact provider/model per expert and a run identifier in every
Roost audit entry. ExpertRegistry always selects the tier default despite the policy helper already
accepting overrides. RoostEndpoint.query cannot accept the caller's trace identifier. These gaps
block the downstream roster readiness check and native trace propagation.

### Goals

- Add keyword-only `model_overrides`, keyed by expert manifest name, without changing tier defaults.
- Fail closed on malformed overrides and overrides without an admitted bundle, with public report evidence.
- Expose the actual configured model through `effective_model(name)` without exposing mutable registry state.
- Add keyword-only `trace_id` to query and retain it across LocalEnvelope exchanges and terminal audit records.
- Preserve the downstream signature probes for exactly `model_overrides` and `trace_id`.

### Non-Goals (explicitly out of scope)

- Changes to tier policy, tool/spawn denials, knowledge sources, or finance-specific code.
- Squawk wire changes or claims of satellite parity without satellite-installed qualification.
- Trace keywords on cfp/request/inform/subscribe; these optional extensions are deferred.
- Provider availability probes, live LLM calls, dynamic model reconfiguration, or a new dependency.

## Governing Decisions

<!-- decision-audit: input_digest=sha256:2c59d5ffe1cc2a74f6ec74c0676eb5fc3b485378a4a25d4f342d4bb206c346b3 evaluation_digest=sha256:f8147966ce10b70e0d4677dc19f6f30bf4b706eca3f8f31861839544d48f3b79 rules_version=0 status=invalid -->

## 2. Architectural Design

### Overview

**Registry.** Copy the supplied mappings at construction so later caller mutations cannot change a
load. Resolve keys against `manifest.name` only, after bundle shadowing. Tags such as `expert:slug`
are not aliases. Validate override entries during `load()` before building the affected expert:
the entry must be a mapping with exactly the required `provider` and `model` keys plus optional
`temperature` and `max_tokens`. Provider and model must be non-empty, non-whitespace strings;
numeric values use the existing ModelConfig validation. Reject unknown keys explicitly because
ModelConfig otherwise ignores extras. A non-mapping outer argument raises ValueError at construction;
malformed individual entries remain reportable at load time.

Keep the existing partial-load contract: a bad override skips that expert and never falls back to
its tier default; unrelated experts still load. Append entries to the existing `skipped` list with
`name`, `path` (bundle root when known, otherwise the expected workspace bundle path), and a stable
`reason` prefix: `invalid-model-override`, `unknown-model-override`, or `unadmitted-model-override`.
Include diagnostic detail after a colon. Discovery/admission reports remain intact; overrides for
discovered but unadmitted bundles get an additional explicit override diagnostic. Process each
override once per load invocation. A missing or empty override map leaves existing reports unchanged.
Preserve existing duplicate-name exceptions and registration policy behavior.

For valid overrides, `_build` calls
`model_config_for(bundle.manifest.tier, overrides=self._model_overrides.get(bundle.manifest.name))`.
The same resolved ModelConfig goes into the existing resolver call and ExpertAgent constructor.
`effective_model(name)` returns a deep copy of the loaded agent's ModelConfig and raises KeyError
before load or for unknown/skipped names; callers cannot mutate live state through this accessor.
No additional knowledge-resolution pass is necessary: both `_build` and `ExpertAgent.configure`
already pass the configured model name into the resolver.

**Query.** Validate a non-None trace id before creating state, a waiter, an envelope, or sending:
it must be a non-empty str with no Unicode whitespace or control/format characters (Unicode
categories Cc and Cf). Reject invalid values with ValueError; do not strip, normalize, or require
W3C hex length. `t1` is valid. Construct TraceContext with the exact supplied trace_id and a fresh
16-hex span_id, then pass `trace=` to new_envelope. None preserves the absence of a trace; do not
implicitly inherit an ambient trace. Keep grants, authority, hop accounting and result validation.
This is an application audit identifier; arbitrary ids are not promised to be valid W3C traceparent headers.

**Terminal coverage.** Ordinary replies already reuse their envelope. Add `envelope: Any = None`
to ConversationState and initialize it from the opener. ProtocolEngine-generated timeout, budget,
hop-limit and cancellation messages must carry this envelope. Keep cancellation's existing REJECT
performative and CANCELLED failure payload. In `_route_emitted`, locally addressed generated
messages must be audited before resolving their waiter; remotely addressed messages continue
through `_send_reply` and must not be double-recorded.

Add an endpoint-private async `_finish_query_failure(conversation_id, *, code, detail)` helper
for local timeout/task-cancellation paths. If state is still open, close it with TIMED_OUT or
CANCELLED, then record one local FAILURE message addressed to the initiator, with the retained
envelope and failure payload. This is a local audit event, not a remote cancellation protocol.
Do not route the engine's cancellation REJECT from this helper. If another terminal path already
won, do not add another locally synthesized terminal entry. Leave request's existing synchronous
`_close_timed_out` helper unchanged. Query catches asyncio.CancelledError, completes this cleanup,
and re-raises cancellation; timeout still raises RoostFailure(TIMEOUT). Always remove the pending
waiter. Endpoint.cancel remains a typed RoostFailure(CANCELLED) path and must be idempotent when
state is already terminal. Audit errors stay fail-closed; never report a successful audit after a
storage failure. Tests must distinguish failure code on the emitted message from ledger fields:
RoostAuditEntry does not contain a failure-code field.

The no-trace path preserves results and exception types, but intentionally gains missing local
terminal audit records. Successful untraced query exchanges remain unchanged.

### Component Diagram

```text
model_overrides -> ExpertRegistry -> model_config_for -> ModelConfig
                                    |                    |
                                    v                    v
                            KnowledgeResolver       ExpertAgent

query(trace_id) -> TraceContext -> LocalEnvelope -> opener/reply -> audit ledger
                                      |
                                      v
                              ConversationState -> generated failure -> audit ledger
```

### Integration Points

| Existing component | Integration | Notes |
|---|---|---|
| ExpertRegistry / model_config_for | Pass per-name overrides | Tier policy stays unchanged |
| KnowledgeResolver / ExpertAgent | Reuse configured model flow | No provider-specific budgeting API |
| new_envelope / RoostMessage.reply | Supply trace and retain envelope | No wire schema change |
| ProtocolEngine / RoostAuditLedger | Retain envelope and record local terminal events | Pure engine, async endpoint I/O |
| Finance signature probes | Preserve exact keyword names | Downstream verification after merge |

### Data Models

Reuse ModelConfig, TraceContext, FailureInfo and RoostAuditEntry. The only added model field is
ConversationState.envelope (default None for backwards compatibility). Reports retain their current
top-level shape; invalid overrides add structured entries under `skipped`. No new public exception.

### New Public Interfaces

`ExpertRegistry(..., model_overrides=...)`, `ExpertRegistry.effective_model(name)` and
`RoostEndpoint.query(..., trace_id=...)`; full signatures appear below.

## 3. Module Breakdown

### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not |
|---|---|---|---|
| M1 Registry overrides | yes | Slug-only mapping, partial-load diagnostics, copy-on-read ModelConfig | — |
| M2 Protocol envelope retention | yes | Add state envelope; preserve emitted message performatives | — |
| M3 Query and local audit | yes | Exact trace validation, local terminal helper and exception contracts | — |
| M4 Documentation | yes | Examples, partial-load semantics, LocalEnvelope qualification boundary | — |

### M1: Registry overrides and readiness

- **Paths**: `packages/ai-parrot/src/parrot/experts/registry.py`;
  create `packages/ai-parrot/tests/experts/test_model_overrides.py`.
- **Depends on**: existing policy, resolver and agent. No module dependency.
- **Interface Skeleton** (modified/new methods; no implementation bodies):

```python
# verified: packages/ai-parrot/src/parrot/experts/registry.py:24
class ExpertRegistry:
    def __init__(self, *, agent_registry: Any, agents_dir: Path | None = None,
                 workspace: Path | None = None, bundled_dir: Path | None = BUNDLED_EXPERTS_DIR,
                 wiki_toolkit: Any = None, bookstore: Any = None, decisions: Any = None,
                 seed_knowledge: bool = True,
                 model_overrides: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        """Copy host overrides; reject a non-mapping outer argument with ValueError."""

    async def load(self) -> int:  # verified: packages/ai-parrot/src/parrot/experts/registry.py:189
        """Load valid experts, reporting invalid, unknown and unadmitted override entries."""

    async def _build(self, bundle: ExpertBundle) -> ExpertAgent:
        """Build using the validated per-name override, including knowledge budgeting."""
        # verified: packages/ai-parrot/src/parrot/experts/registry.py:160

    def effective_model(self, name: str) -> ModelConfig:
        """Return an isolated copy of the loaded config; raise KeyError if not loaded."""
```

### M2: Protocol-generated message envelope retention

- **Path**: `packages/ai-parrot/src/parrot/roost/protocols.py`.
- **Depends on**: existing RoostMessage; no module dependency.
- **Interface Skeleton**:

```python
# verified: packages/ai-parrot/src/parrot/roost/protocols.py:54
class ConversationState(BaseModel):
    """Existing conversation fields plus the opener's envelope for terminal messages."""
    envelope: Any = None  # new; existing fields remain unchanged

# verified: packages/ai-parrot/src/parrot/roost/protocols.py:217
class ProtocolEngine:
    def open(self, opener: RoostMessage, *, budget: Optional[ConversationBudget] = None) -> ConversationState:
        """Retain opener envelope along with existing state and budget initialization."""
        # verified: packages/ai-parrot/src/parrot/roost/protocols.py:235

    def close(self, conversation_id: str, terminal: TerminalState, *, reason: str = "") -> Transition:
        """Preserve the state envelope on cancellation output."""
        # verified: packages/ai-parrot/src/parrot/roost/protocols.py:343

    def _close_with_failure(self, state: ConversationState, code: FailureCode, detail: str,
                            source: Optional[RoostMessage] = None) -> Transition:
        """Retain the original envelope on generated failures, including timer expiration."""
        # verified: packages/ai-parrot/src/parrot/roost/protocols.py:374
```

### M3: Query tracing and terminal audit coverage

- **Paths**: `packages/ai-parrot/src/parrot/roost/endpoint.py`;
  create `packages/ai-parrot/tests/roost/test_query_trace.py` (also owns M2 tests).
- **Depends on**: M2; M1 is independent.
- **Interface Skeleton**:

```python
# verified: packages/ai-parrot/src/parrot/roost/endpoint.py:51
class RoostEndpoint:
    async def query(self, question: Any, *, receiver: AgentAddress,
                    timeout: Optional[float] = None, expected_schema: Optional[dict] = None,
                    hops: int = 0, trace_id: str | None = None) -> Any:
        """Query with optional audit trace; reject invalid trace ids before side effects."""
        # verified: packages/ai-parrot/src/parrot/roost/endpoint.py:539

    async def _finish_query_failure(self, conversation_id: str, *, code: FailureCode, detail: str) -> None:
        """Close an open query and audit one local TIMEOUT or CANCELLED failure."""

    async def _route_emitted(self, emitted: RoostMessage) -> None:
        """Audit locally routed engine output, or send remotely using the existing path."""
        # verified: packages/ai-parrot/src/parrot/roost/endpoint.py:158

    async def cancel(self, conversation_id: str, *, reason: str = "") -> None:
        """Cancel an open conversation once; preserve its typed failure and trace."""
        # verified: packages/ai-parrot/src/parrot/roost/endpoint.py:699
```

### M4: Documentation

- **Paths**: `docs/experts/domain-experts.md`, `docs/roost/README.md`.
- **Depends on**: M1 and M3.
- **Interface Skeleton**: documentation-only; no Python callable. Add sections
  `### Per-expert model overrides` and `## Query trace identifiers` respectively. Show direct
  ExpertRegistry construction, report inspection, effective_model, and query(trace_id="run-123").
  Explain that bootstrap helpers do not gain an override parameter in this feature, errors skip
  affected experts, None leaves tracing absent, and satellite parity is unqualified.

### Worktree Strategy

**Isolation**: per-spec. One feature worktree after task decomposition; no implementation in dev.
Module graph: 4 modules, 3 dependency edges (M2 → M3, M1 → M4, M3 → M4).
M1 and M2 may run independently. M3 exclusively owns endpoint.py and test_query_trace.py;
protocol retention tests belong to M3 to avoid concurrent edits to that new test file.

## 4. Test Specification

### Unit Tests

| Proposed test | Module | Required assertions |
|---|---|---|
| test_defaults_match_tier_policy | M1 | None and empty mappings preserve all three tier configs and normal reports |
| test_override_is_per_expert | M1 | Named expert gets provider/model and optional numeric overrides; sibling keeps defaults |
| test_invalid_override_is_reported | M1 | Missing keys, unknown keys, invalid value types and empty strings skip target without fallback |
| test_unknown_and_unadmitted_override | M1 | Missing slug, tag key, invalid bundle and failed admission have explicit diagnostics |
| test_model_config_is_applied | M1 | Real ExpertAgent config and runtime model setup match; resolver receives overridden model |
| test_effective_model_is_isolated | M1 | Caller mapping/result mutations cannot change live config; unavailable names raise KeyError |
| test_shadowed_bundle_override | M1 | Override applies once to winning bundle; duplicate-name rejection preserved |
| test_invalid_trace_has_no_side_effects | M3 | Empty, non-string, whitespace, Cc and Cf rejected; send/state/pending untouched |
| test_engine_terminal_retains_envelope | M2/M3 | Expire, hop/token budget and cancel retain opener envelope with/without trace |
| test_trace_span_identity | M3 | Exact id, fresh span per query, no ambient inheritance and no W3C-only restriction |

### Integration Tests

| Proposed test | Required assertions |
|---|---|
| test_query_trace_exchange | Two in-process endpoints: query and reply entries on both ledgers, both roles, all t1; verify signatures |
| test_query_without_trace | Same successful exchange has None on every entry and unchanged result |
| test_query_local_timeout_trace | Disable sweeper; local timeout raises TIMEOUT, closes state, removes waiter and audits traced failure |
| test_query_sweep_timeout_trace | Advance injected clock; local and remote generated timeout paths retain trace and resolve waiter |
| test_query_cancellation_trace | Explicit endpoint.cancel yields CANCELLED; task.cancel re-raises CancelledError; terminal audit retains trace |
| test_terminal_races | Controlled timeout/sweep/cancel/late reply ordering does not duplicate locally synthesized terminal entries |
| test_query_trace_isolation | Concurrent queries have separate traces; grant, authority, hops and schema checks remain effective |
| test_audit_storage_failure | Recording failure cannot become successful completion; pending state cleaned up |

### Validation Contract

tests:
- packages/ai-parrot/tests/experts/test_model_overrides.py
- packages/ai-parrot/tests/experts/test_registry.py
- packages/ai-parrot/tests/experts/test_policy.py
- packages/ai-parrot/tests/experts/test_agent_activation.py
- packages/ai-parrot/tests/experts/test_resolver.py
- packages/ai-parrot/tests/roost/test_query_trace.py
- packages/ai-parrot/tests/roost/test_endpoint.py
- packages/ai-parrot/tests/roost/test_protocols.py
- packages/ai-parrot/tests/roost/test_audit.py
- packages/ai-parrot/tests/roost/test_squawk_bridge.py
markers: none

Also run the existing `packages/ai-parrot/tests/experts/` and `packages/ai-parrot/tests/roost/`
suites before feature completion. New files above are planned operands, not claims of present tests.
No live LLM/provider tests; save logs in artifacts/logs/.

### Test Data / Fixtures

Use temporary valid bundles following experts/conftest.py:20, an in-memory wiki and stub guardrail
loader as in test_registry.py:32. Construct real ExpertAgents without executing provider calls.
For Roost use in-process endpoints patterned after test_endpoint.py:24, fake wake responses,
controlled clocks/events and LocalEnvelope forced through a monkeypatched satellite probe. Do not
depend on whichever optional satellite happens to be installed. Capture terminal messages to assert
their FailureInfo, and use ledger.entries()/verify() for audit evidence. No wall-clock polling races.

## 5. Acceptance Criteria

- [ ] Exact keyword names are visible to introspection: model_overrides and trace_id.
- [ ] Default registry configuration remains identical for every tier; siblings and policy denials are unchanged.
- [ ] Invalid, unknown and unadmitted overrides appear in report()['skipped']; no invalid expert falls back silently.
- [ ] Effective config equals the one supplied to the real agent and resolver; accessor mutation is isolated.
- [ ] Every LocalEnvelope query/reply audit entry on both endpoints retains the supplied id; absent id stays None.
- [ ] Local/swept timeouts, protocol failures and both cancellation paths retain trace and clean up waiters.
- [ ] Invalid ids raise ValueError before any state or send side effect; grants and authority remain fail-closed.
- [ ] Validation contract and existing experts/Roost suites pass; documentation covers both new APIs and limits.
- [ ] After merge, finance confirms c8_supported=True and native dispatch in its qualified LocalEnvelope setup,
      and records the merged ai-parrot revision. This is a downstream release handoff, not evidence produced here.
- [ ] Governing-decision audit is rerun successfully after the repository approval manifest is repaired, before approval.

## 6. Codebase Contract

Verified against `8e0c12322b66f410ddfa6fba8c353a6e73121368` on 2026-11-02.
Paths below are repository-relative unless explicitly marked installed dependency.

### Verified Imports

```python
from parrot.experts.registry import ExpertRegistry  # packages/ai-parrot/src/parrot/experts/registry.py:24
from parrot.experts.policy import model_config_for  # packages/ai-parrot/src/parrot/experts/policy.py:19
from parrot.models.basic import ModelConfig  # packages/ai-parrot/src/parrot/models/basic.py:40
from parrot.core.events.lifecycle import TraceContext  # packages/ai-parrot/src/parrot/core/events/lifecycle/__init__.py:18
from parrot.roost.messages import AgentAddress, FailureInfo, RoostMessage  # packages/ai-parrot/src/parrot/roost/messages.py:42,50,58
from parrot.roost.protocols import ConversationState, TerminalState  # packages/ai-parrot/src/parrot/roost/protocols.py:54,25
```

### Existing Class Signatures and Integration Points

| Contract | Verified at |
|---|---|
| model_config_for(tier: ExpertTier, *, overrides: Mapping[str, Any] \| None = None) -> ModelConfig | packages/ai-parrot/src/parrot/experts/policy.py:19 |
| ModelConfig: provider: str, model: str, temperature: float = 0.1, max_tokens: int = 8192 | packages/ai-parrot/src/parrot/models/basic.py:40 |
| Registry report() -> dict[str, Any], names() -> list[str], get(name: str, *, tenant: str \| None = None) -> ExpertAgent | packages/ai-parrot/src/parrot/experts/registry.py:53,57,61 |
| _discover returns overlaid bundles; _admit reports rejected wiki admission; load registers only built agents | packages/ai-parrot/src/parrot/experts/registry.py:85,101,189 |
| _build resolves with model=model_config.model and passes model_config to ExpertAgent | packages/ai-parrot/src/parrot/experts/registry.py:173 |
| ExpertAgent sets llm to provider:model, passes temperature/max_tokens, stores model_config | packages/ai-parrot/src/parrot/experts/agent.py:51 |
| ExpertAgent.configure resolves again with self.model_config.model | packages/ai-parrot/src/parrot/experts/agent.py:70 |
| KnowledgeResolver.resolve(expert, stage, workspace, *, model: str \| None, budget_tokens: int \| None = None) -> KnowledgeContext | packages/ai-parrot/src/parrot/experts/knowledge/resolver.py:43 |
| new_envelope(*, correlation_id: str, caller: str, trace: Optional[TraceContext] = None, budget_ms: Optional[int] = None, token_budget: Optional[int] = None, idempotency_key: Optional[str] = None) -> Any | packages/ai-parrot/src/parrot/roost/squawk_bridge.py:83 |
| LocalEnvelope.trace: Optional[TraceContext] = None; reply reuses self.envelope; trace_id() reads nested trace only | packages/ai-parrot/src/parrot/roost/messages.py:35,121,132 |
| Engine expire() -> list[Transition]; close(...)->Transition; state(...)->Optional[ConversationState] | packages/ai-parrot/src/parrot/roost/protocols.py:297,343,339 |
| RoostAuditLedger.record(msg, *, direction, self_name) -> RoostAuditEntry takes trace from msg.trace_id() | packages/ai-parrot/src/parrot/roost/audit.py:116,147 |
| Ledger.verify(entry) -> bool (async); entries(*, conversation_id=None, trace_id=None) -> list[RoostAuditEntry] | packages/ai-parrot/src/parrot/roost/audit.py:162,173 |
| TraceContext requires trace_id and span_id; new_root() supplies a fresh span | installed dependency .venv/lib/python3.12/site-packages/navigator_eventbus/lifecycle/trace.py:15,38,45 |

### Does NOT Exist (Anti-Hallucination)

- ExpertRegistry.model_overrides constructor parameter and effective_model method do not yet exist.
- query(trace_id=...) does not yet exist; _finish_query_failure is a new private helper.
- ConversationState does not currently retain the envelope; engine-generated failures omit it.
- Local _route_emitted currently resolves without auditing; query's local timeout currently only closes state.
- RoostAuditEntry has no failure-code field; capture the message to inspect its FailureInfo.
- `packages/ai-parrot-squawk/src/parrot/squawk/schema/messages.py` is absent in this checkout.
  Do not claim installed-satellite parity from the stub bridge tests.
- Root-level `tests/experts` and `tests/roost` in the proposal are shorthand; actual tests are under packages/ai-parrot/tests.

### Edit Sites (Blueprint Anchors)

Occurrence counts below use literal `grep -F -c` against the verified base. Recheck at task generation.
CREATE rows name future files only. Exact existing signatures are in the module skeletons above.

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| packages/ai-parrot/src/parrot/experts/registry.py | MODIFY | `class ExpertRegistry:` | packages/ai-parrot/src/parrot/experts/registry.py:24 | 1 |
| packages/ai-parrot/src/parrot/roost/protocols.py | MODIFY | `class ConversationState(BaseModel):` | packages/ai-parrot/src/parrot/roost/protocols.py:54 | 1 |
| packages/ai-parrot/src/parrot/roost/endpoint.py | MODIFY | `    async def query(` | packages/ai-parrot/src/parrot/roost/endpoint.py:539 | 1 |
| docs/experts/domain-experts.md | MODIFY | `### Tier to model projection` | docs/experts/domain-experts.md:89 | 1 |
| docs/roost/README.md | MODIFY | `## Quick start` | docs/roost/README.md:30 | 1 |
| packages/ai-parrot/tests/experts/test_model_overrides.py | CREATE | — | — | — |
| packages/ai-parrot/tests/roost/test_query_trace.py | CREATE | — | — | — |

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Keep I/O async and the protocol engine pure. Existing self.logger and Pydantic patterns apply.
- Keep shared clients/base.py, tier policy and bootstrap wiring outside the change.
- Use standard-library Mapping, secrets and unicodedata; no new third-party imports.
- Defensive copying belongs at registry input and readiness output boundaries.
- No changes to Squawk import isolation or wire serialization. TraceContext remains the existing imported type.
- Keep the proposal's registry no-override regression distinct from the intentional Roost terminal-audit repair.

### Known Risks / Gotchas

- ModelConfig ignores unknown fields: explicit key validation is essential. Provider names/models are
  configuration strings, not a guarantee of credentials or provider availability.
- asyncio.CancelledError is not an ordinary Exception; cleanup must explicitly handle it and preserve cancellation.
- An engine timeout may race the local wait timeout. Claim terminal state before awaiting audit storage;
  the losing path must not synthesize another terminal event. Existing genuine received messages remain auditable.
- Satellite bridge writes a flat trace_id while Roost reads a nested trace. This spec qualifies LocalEnvelope
  only; neither a mocked CallMessage nor signature introspection proves satellite trace parity.
- Retaining envelopes in state retains their contents for the engine's existing state lifetime. Do not retain
  whole query payloads or introduce a second unbounded per-conversation map.
- The governing lookup is blocked by duplicate approval batch `seed-architecture-rules-v1` in
  sdd/decisions/approvals.jsonl. Do not infer absence of governing decisions or mark this spec approved.

### External Dependencies

| Package | Existing requirement | Use |
|---|---|---|
| pydantic | >=2.12.5,<3 (packages/ai-parrot/pyproject.toml:54) | Existing models/copy/validation |
| navigator-eventbus | >=0.4.0 (packages/ai-parrot/pyproject.toml:193) | TraceContext via core re-export |

No added or upgraded dependencies.

## Decisions

```yaml
schema_version: 1
document_id: expert-model-override-and-roost-trace
entries:
  - id: explicit-expert-models
    statement: Per-expert overrides use manifest names and must never silently fall back after validation fails.
    relation: requires
    about: [bots, config]
    targets: ["file:packages/ai-parrot/src/parrot/experts/registry.py"]
    contradicts: []
    supersedes: []
    rationale: Exact model selection is a host readiness contract; partial loading must expose rejected seats.
    rejected_alternatives: ["Tag aliases", "Silent tier fallback for invalid overrides"]
  - id: query-audit-trace
    statement: LocalEnvelope query traces must survive normal replies and generated terminal audit events.
    relation: requires
    about: [bots]
    targets:
      - "file:packages/ai-parrot/src/parrot/roost/endpoint.py"
      - "file:packages/ai-parrot/src/parrot/roost/protocols.py"
    contradicts: []
    supersedes: []
    rationale: Auditable run attribution must include local timeouts and cancellations as well as successful replies.
    rejected_alternatives: ["Only add a query keyword", "Claim satellite parity from stub tests"]
```

## Consequences

<!-- decision-audit: input_digest=sha256:2c59d5ffe1cc2a74f6ec74c0676eb5fc3b485378a4a25d4f342d4bb206c346b3 evaluation_digest=sha256:f8147966ce10b70e0d4677dc19f6f30bf4b706eca3f8f31861839544d48f3b79 rules_version=0 status=invalid -->

Audit status: `invalid` (exit 2)

Findings:
- none

Diagnostics:
- `APPROVAL_MANIFEST_INVALID`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/expert-model-override-and-roost-trace.spec.md; message: /home/jesuslara/proyectos/ai-parrot/sdd/decisions/approvals.jsonl: duplicate spec/seed approval batch_id(s): seed-architecture-rules-v1

Coverage:
- Subsystems: not recorded
- Unmapped tags: not recorded
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
    "subsystems": [],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": []
  },
  "diagnostics": [
    {
      "code": "APPROVAL_MANIFEST_INVALID",
      "decision_id": null,
      "message": "/home/jesuslara/proyectos/ai-parrot/sdd/decisions/approvals.jsonl: duplicate spec/seed approval batch_id(s): seed-architecture-rules-v1",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/expert-model-override-and-roost-trace.spec.md"
    }
  ],
  "evaluation_digest": "sha256:f8147966ce10b70e0d4677dc19f6f30bf4b706eca3f8f31861839544d48f3b79",
  "exit_code": 2,
  "findings": [],
  "input_digest": "sha256:2c59d5ffe1cc2a74f6ec74c0676eb5fc3b485378a4a25d4f342d4bb206c346b3",
  "snapshot": null,
  "status": "invalid"
}
```

## 8. Open Questions

The proposal supplied four unchecked questions and no previously resolved questions.

- [x] Should overrides accept manifest.name only or tags? — Resolved in this draft from the proposed
  slug contract and registry lookup: manifest.name only, tags remain discovery metadata.
- [x] Re-run knowledge budgeting on provider change? — Existing _build and configure calls use the
  resolved model; preserve that flow and verify it, without an extra pass or provider-only API.
- [x] Squawk CallMessage end-to-end trace? — Scope resolution permitted by the proposal: qualify
  LocalEnvelope only and document the flat/nested mismatch. Satellite qualification remains deferred.
- [ ] Release/tag and finance runtime-source-manifest revision — Owner: release maintainer; record
  the merged revision and downstream readiness results after implementation. Target 1.3.0 is provisional.
- [ ] Repair duplicate decision approval batch and rerun governing/consequence audits — Owner:
  SDD maintainer; prerequisite for spec approval, outside this feature's modification scope.

## 9. Design Research Cross-Check

Status: skipped (the supplied exploration is status draft, not accepted; the optional independent
design-research precondition is not met). No independent review is claimed.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: 0 confirmed · 0 rejected · 0 escalated.

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-02 | Jesus Lara (with Codex) | Initial draft with verified contracts and terminal audit repair |
