# TASK-5103: Per-expert model overrides and readiness accessor

**Feature**: FEAT-790 — Expert model overrides and trace-carrying Roost queries
**Spec**: `sdd/specs/expert-model-override-and-roost-trace.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

## Context

Implement spec M1 and the expert documentation portion of M4. Hosts need exact provider/model
selection for each manifest name and a public readiness accessor. The existing tier policy already
accepts overrides, but the registry never supplies them. No dependency on the Roost deliverable.
The spec is owner-approved. Decision-audit advisory remains `SNAPSHOT_UNSTABLE`; this task does
not repair that separate inventory problem or certify the feature's final consequence gate.

## Scope

- Add keyword-only `model_overrides: Mapping[str, Mapping[str, Any]] | None = None` to ExpertRegistry.
- Copy input mappings, reject a non-mapping outer value with ValueError at construction, and retain
  malformed per-expert values for reporting during load. Later mutation by the caller cannot affect load.
- Key only by manifest.name after overlay resolution; never recognize discovery tags as aliases.
- Require provider/model non-blank strings; allow only provider, model, temperature and max_tokens.
  Explicitly reject unknown keys; defer numeric type validation to ModelConfig. Do not change tier defaults.
- During load, invalid overrides skip their target without fallback. Report unknown and unadmitted
  targets; preserve unrelated experts, admission diagnostics, duplicate errors, policy registration and tags.
- Use `skipped` report entries containing name, path and a reason prefix of `invalid-model-override`,
  `unknown-model-override` or `unadmitted-model-override`, with diagnostic detail after a colon. Use
  the bundle root when known, otherwise the expected workspace bundle path. Report each override
  once per invocation; no new report entries when the mapping is absent or empty.
- Pass the resolved config through existing agent and knowledge-budget wiring. Expose
  `effective_model(name) -> ModelConfig` as a deep copy of the loaded agent config; unknown,
  skipped and not-yet-loaded names raise KeyError.
- Document construction, report inspection, effective-model reads, defaults and failure semantics.

**NOT in scope**: bootstrap parameters, tier-policy edits, client/provider SDK changes, provider availability
probes, tool permissions, model switching, Roost, dependencies or the decision-audit inventory repair.

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/registry.py` | MODIFY | Input, load validation, model wiring and accessor |
| `packages/ai-parrot/tests/experts/test_model_overrides.py` | CREATE | Registry behavior and isolation regressions |
| `docs/experts/domain-experts.md` | MODIFY | Per-expert configuration and readiness examples |

## Codebase Contract (Anti-Hallucination)

Verified at `408bd66808a46803df16e165a44b727b53aa6c82`; recheck before implementation.

### Verified Imports

```python
from collections.abc import Mapping  # Python standard library
from pathlib import Path  # Python standard library
from typing import Any  # Python standard library
from copy import deepcopy  # Python standard library; input boundary only if needed
import pytest  # existing test dependency; tests/experts/test_registry.py:9
from parrot.experts.registry import ExpertRegistry  # packages/ai-parrot/src/parrot/experts/registry.py:24
from parrot.experts.policy import model_config_for  # packages/ai-parrot/src/parrot/experts/policy.py:19
from parrot.models.basic import ModelConfig  # packages/ai-parrot/src/parrot/models/basic.py:40
from parrot.experts.agent import ExpertAgent  # packages/ai-parrot/src/parrot/experts/agent.py:17
from parrot.experts.models import ExpertBundle  # packages/ai-parrot/src/parrot/experts/models.py:171
from parrot.experts.loader import BUNDLED_EXPERTS_DIR  # packages/ai-parrot/src/parrot/experts/loader.py:18
```

Registry, policy and agent paths abbreviated below are relative to `packages/ai-parrot/src/parrot/experts/`.

### Existing Signatures to Use

- `ExpertRegistry.__init__` at registry.py:27 is keyword-only; preserve agent_registry, agents_dir,
  workspace, bundled_dir, wiki_toolkit, bookstore, decisions and seed_knowledge defaults.
- `load(self) -> int` at registry.py:189 isolates build failures; `_discover(self) -> list[ExpertBundle]`
  at :85 applies overlays; `_admit(self, bundle: ExpertBundle) -> bool` at :101 checks knowledge admission.
- `_build(self, bundle: ExpertBundle) -> ExpertAgent` at :160 selects config at :173, passes
  model=model_config.model to KnowledgeResolver at :174 and config to ExpertAgent at :183.
- `model_config_for(tier: ExpertTier, *, overrides: Mapping[str, Any] | None = None) -> ModelConfig`
  in policy.py:19 merges tier values and overrides; it does not reject unknown keys.
- ModelConfig has provider/model strings and temperature=0.1, max_tokens=8192 at
  `packages/ai-parrot/src/parrot/models/basic.py:40`.
- ExpertAgent constructor at agent.py:22 passes provider:model, temperature and max_tokens to its
  base at :51 and stores model_config at :60. configure at :70 reuses its model for budgeting.
- `KnowledgeResolver.resolve(expert, stage, workspace, *, model: str | None, budget_tokens: int | None = None)`
  at `packages/ai-parrot/src/parrot/experts/knowledge/resolver.py:43` already budgets from the model.
- Existing test fixture patterns: `packages/ai-parrot/tests/experts/test_registry.py:17` FakeWiki,
  :32 guardrail stub, :39 registry factory, :50 bundle builder. Reuse their approach without editing
  those tests or the shared conftest. Verify extra imports before adding them.

### Does NOT Exist

- model_overrides constructor keyword, effective_model method and test_model_overrides.py are new.
- No public provider-aware knowledge rebudgeting API or bootstrap override parameter is required.

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/registry.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_model_overrides.py",
      "action": "CREATE"
    },
    {
      "path": "docs/experts/domain-experts.md",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/experts/registry.py#ExpertRegistry",
    "sym:packages/ai-parrot/src/parrot/experts/policy.py#model_config_for",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#ModelConfig",
    "sym:packages/ai-parrot/src/parrot/experts/agent.py#ExpertAgent",
    "sym:packages/ai-parrot/src/parrot/experts/knowledge/resolver.py#KnowledgeResolver.resolve",
    "sym:packages/ai-parrot/src/parrot/experts/models.py#ExpertBundle"
  ]
}
```

## Implementation Notes

Partial-load reporting is an intentional compatibility contract: an invalid named override must
never construct that expert with defaults, but must not prevent unrelated valid experts loading.
Keep the override copy private and do not mutate the tier-policy dictionary. Return model_copy(deep=True)
from readiness. Preserve the registry's no-override report behavior. Follow async I/O and self.logger
conventions; format touched Python with black, line length 120. No changes to shared conftest.

## Implementation Blueprint

### Steps (in order)

1. Add the constructor keyword and defensive input capture — protects later loads from caller mutation.
2. Validate entries and classify target/admission failures in load — prevents silent default fallback.
3. Wire overrides into _build and add effective_model — one config governs both readiness and runtime.
4. Add isolated tests and the documentation section — make the new host-facing contract executable.

### `packages/ai-parrot/src/parrot/experts/registry.py` (MODIFY)

Anchor: `class ExpertRegistry:` at :24; literal `grep -F -c` occurrence count: **1**.
Extend the existing class; preserve methods and constructor setup not shown in this focused skeleton.

```python
# Add to imports: Mapping, deepcopy if needed, and ModelConfig from Verified Imports.
class ExpertRegistry:
    def __init__(self, *, agent_registry: Any, agents_dir: Path | None = None,
                 workspace: Path | None = None, bundled_dir: Path | None = BUNDLED_EXPERTS_DIR,
                 wiki_toolkit: Any = None, bookstore: Any = None, decisions: Any = None,
                 seed_knowledge: bool = True,
                 model_overrides: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        """Capture host dependencies and a defensive copy of per-name model overrides."""
        # FILL IN: preserve setup; validate outer mapping and copy its values (AC1, AC4).
        raise NotImplementedError

    async def load(self) -> int:
        """Load valid experts and report rejected model overrides without default fallback."""
        # FILL IN: validation/admission/report ordering and existing registrations (AC2, AC3).
        raise NotImplementedError

    async def _build(self, bundle: ExpertBundle) -> ExpertAgent:
        """Build with the named expert's validated model configuration."""
        # FILL IN: change config selection; retain resolver and agent wiring (AC1, AC5).
        raise NotImplementedError

    def effective_model(self, name: str) -> ModelConfig:
        """Return a deep copy of the loaded model; raise KeyError if unavailable."""
        # FILL IN: derive from the loaded ExpertAgent, not from guessed defaults (AC4).
        raise NotImplementedError
```

Why: the signature preserves downstream introspection; all policy and knowledge behavior stays in
the existing collaborators. These are planning stubs, never acceptable completed implementation.

### `packages/ai-parrot/tests/experts/test_model_overrides.py` (CREATE)

```python
"""Per-expert override, readiness and default-policy regression tests for FEAT-790."""
from __future__ import annotations

from pathlib import Path
import pytest
from parrot.experts.registry import ExpertRegistry
from parrot.experts.policy import model_config_for

@pytest.mark.asyncio
async def test_defaults_match_tier_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """None and empty mappings preserve each tier and the existing report."""
    # FILL IN: real agents with isolated bundle/wiki fixtures, no provider calls (AC1).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_override_is_per_expert(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the named expert changes, including optional numeric overrides."""
    # FILL IN: two experts, runtime config, resolver model and sibling defaults (AC1, AC5).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_invalid_override_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed entries, unknown slugs and failed admission never fall back."""
    # FILL IN: parameterize all Scope failure classes and report prefixes (AC2, AC3).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_effective_model_is_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Input/output mutations are isolated and unavailable names raise KeyError."""
    # FILL IN: mutation and lookup checks before/after load (AC4).
    raise NotImplementedError

@pytest.mark.asyncio
async def test_shadowed_bundle_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The winning bundle receives one override; duplicate-name behavior is unchanged."""
    # FILL IN: workspace overlay plus existing duplicate-name failure (AC3).
    raise NotImplementedError
```

Add the test-local helpers following test_registry.py, including its guardrail stub; do not import
optional provider SDKs. Expand the above tests as necessary to cover every acceptance assertion.

### `docs/experts/domain-experts.md` (MODIFY)

Anchor: `### Tier to model projection` at :89; literal occurrence count: **1**.
Insert the following subsection after the existing tier table, before Knowledge resolution.

```markdown
### Per-expert model overrides

<!-- FILL IN: show direct ExpertRegistry construction with model_overrides keyed by manifest.name;
await load(), inspect report()['skipped'], and read effective_model(name). Explain immutable-copy
readiness, both required keys, optional numeric keys, all failure categories and unchanged defaults.
State that bootstrap helpers do not gain this parameter. Do not include credentials. -->
```

Why: the example belongs beside tier selection and must show that load count alone is insufficient readiness.

### FILL IN checklist

- [ ] Constructor copies and outer validation; per-entry load validation and deterministic diagnostics.
- [ ] _build wiring and effective_model copy semantics.
- [ ] All failure, overlay, isolation, numeric override and default regression cases.
- [ ] Complete documentation prose/examples; remove every planning stub from implementation files.

## Acceptance Criteria

- [ ] AC1: Introspection exposes model_overrides; None/empty preserve all tiers; only named expert changes.
- [ ] AC2: Malformed/unknown/unadmitted overrides are clearly reported once per load; no fallback for affected expert.
- [ ] AC3: Siblings, overlays, duplicate rejection, tags and deny policy remain correct.
- [ ] AC4: Input mutation and accessor mutation cannot affect runtime; missing/skipped/preload lookup raises KeyError.
- [ ] AC5: Actual agent configuration and resolver model equal the selected override; no extra knowledge pass.
- [ ] AC6: Focused tests pass, docs complete, black/ruff clean, no live provider calls or added dependencies.

## Validation Commands

- `pytest packages/ai-parrot/tests/experts/test_model_overrides.py -q`

## Test Specification

The blueprint covers spec §4 registry cases. Add parameterized tests for partial provider/model pairs,
unknown keys, invalid numeric types, blank strings, non-mapping entry values, tag keys, absent bundles,
failed admission, outer invalid mapping and optional temperature/max_tokens. Use real ExpertAgent
construction with guardrails stubbed; assert runtime fields rather than only mock constructor calls.
The spec-wide cached contract supplies registry/policy/agent/resolver regressions at later gates.

## Agent Instructions

1. Use `$sdd-start TASK-5103` to provision the feature worktree; never implement on dev.
2. Read the spec and reverify this contract. Modify only the three declared files; respect concurrent work.
3. Implement, complete all FILL IN items, run the Validation Commands and repository lint/format checks.
4. Commit the scoped implementation and finalize with `scripts.sdd.finalize_task` and real
   TaskCompletionEvidence for the implementation HEAD, per docs/sdd/CODEX.md. Do not manually move tasks.
5. Commit the generated completion state. Do not claim downstream finance rollout or the inventory audit is complete.

## Completion Note

Pending implementation; populated by the finalization workflow with actual evidence.
