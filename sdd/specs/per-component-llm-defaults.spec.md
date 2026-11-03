---
type: feature
base_branch: dev
projects: [ai-parrot, ai-parrot-server]
tags: [llm-config, credentials, agentcrew, experts, configuration]
---

# Feature Specification: Per-Component LLM Defaults

**Feature ID**: FEAT-796
**Date**: 2026-11-03
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor

---

## 1. Motivation & Business Requirements

### Problem Statement

Default LLM selection is scattered and hardcoded. Today:

- `conf.py:248` defines `DEFAULT_LLM_MODEL_NAME` (env `LLM_MODEL_NAME`, fallback
  `gemini-2.5-pro`) but **nothing in any `packages/*/src` reads it** — it is a dead knob.
- `conf.py:456` defines a *second* global, `DEFAULT_LLM_MODEL` (env `LLM_MODEL`, fallback
  `gemini-flash-latest`), which IS live (`bots/chatbot.py:355`, `loaders/abstract.py:315`,
  `parrot_pipelines/planogram/backend.py:23`).
- The agent HTTP handler (`ai-parrot-server handlers/agents/abstract.py:179-180`) hardcodes
  `_use_llm = 'google'` / `_use_model = 'gemini-2.5-pro'`.
- `AgentCrew` hardcodes `gemini-2.5-pro` twice: the `run_sequential(model=...)` default
  (`crew.py:1755`) and the lazy synthesis client (`crew.py:2154/2156`, `GoogleGenAIClient`).
- `experts/policy.py:11-13` hardcodes provider **and** model for all three tiers.

Operators cannot move one component to another model/provider, nor bill it to a separate
API key, without editing code. Only `AgentCrew` has a separate key today (`CREW_AI_KEY`,
FEAT-575), and its name does not say which provider it is for.

### Goals

- G1. Each component reads its own `<COMPONENT>_LLM` env var in `provider:model` form
  (e.g. `CREW_LLM=google:gemini-2.5-pro`), cascading to one new optional global
  `DEFAULT_LLM` (`provider:model`), then to the component's **current hardcoded value**.
- G2. Each component resolves its API key by the same cascade, per resolved provider:
  `<COMPONENT>_<PROVIDER>_API_KEY` (e.g. `CREW_GOOGLE_API_KEY`) → component-family key
  (e.g. `EXPERT_GOOGLE_API_KEY` for the expert tiers) → legacy alias (crew: `CREW_AI_KEY`)
  → `None` (the client then uses its provider-wide key, e.g. `GOOGLE_API_KEY`, as today).
- G3. Components covered: `AGENT` (agent HTTP handler), `CREW` (AgentCrew default/synthesis
  client), `EXPERT_JUDGMENT` / `EXPERT_BALANCED` / `EXPERT_TEMPLATED` (expert tiers).
- G4. Delete the dead `DEFAULT_LLM_MODEL_NAME` / `LLM_MODEL_NAME` knob.
- G5. Zero behavior change when none of the new variables is set.

### Non-Goals (explicitly out of scope)

- `BOT_LLM` for `AbstractBot`: `bots/abstract.py:968` is a **docstring example**, and
  `_parse_model_config` has no literal model fallback (`model=cfg.pop("model", None)`), so
  there is nothing to replace.
- Changing or replacing `DEFAULT_LLM_MODEL` / `LLM_MODEL` (live, model-only, used by
  chatbot/loaders/planogram). `DEFAULT_LLM` is a separate, opt-in, provider-qualified knob.
- Per-component usage/cost attribution (`UsageRecord` has no component field). Separate keys
  already give per-key billing; tagging records is a follow-up.
- The UI model selector (a list of choices, not a default).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:7092b6fd51b88520297acd2c15f87d485d72ba6b6982df4e5168d786965f0273 evaluation_digest=sha256:f156f3111dd0a33e88d53f88ed53db9639b21b6f6c59e78ed744527e91a7d010 rules_version=1 status=pass -->

No eligible decisions govern subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, server, skills, tools

## 2. Architectural Design

### Overview

A new core module `parrot/llm_defaults.py` owns resolution. It is pure (reads
`parrot.conf` / `navconfig.config`, no client imports) so `conf.py` import order is not
affected.

```
resolve_component_llm("CREW", builtin="google:gemini-2.5-pro")
  1. config.get("CREW_LLM")            → "provider:model" (or bare "model" ⇒ builtin provider)
  2. conf.DEFAULT_LLM                  → "provider:model", only if explicitly set
  3. builtin                           → today's hardcoded value
→ ComponentLLM(provider="google", model="gemini-2.5-pro", source="builtin")

resolve_component_api_key(("EXPERT_JUDGMENT", "EXPERT"), provider="google",
                          legacy=())
  for name in components: config.get(f"{name}_{PROVIDER}_API_KEY")
  then each legacy var (crew: "CREW_AI_KEY")
  → str | None   (None ⇒ client falls back to its own provider key)
```

`PROVIDER` token: any key in `GOOGLE_PROVIDER_KEYS` (`google`, `gemini-live`,
`google-compat`) maps to `GOOGLE`; otherwise `provider.upper().replace("-", "_")`
(`openai` → `OPENAI`, `anthropic` → `ANTHROPIC`). An API key is applied only when the
caller did not already pass an explicit credential (reuse `has_explicit_google_credential`
semantics for Google; `api_key` kwarg for others).

Malformed `<COMPONENT>_LLM` (empty provider, provider not in `SUPPORTED_CLIENTS`) raises
`ValueError` naming the variable — fail loudly at first resolution, never silently fall
back. Key values are never logged.

### Component Diagram

```
env / navconfig ──→ parrot/llm_defaults.py ──┬──→ handlers/agents/abstract.py  (AGENT)
                                              ├──→ bots/flows/crew/crew.py       (CREW)
                                              │      └─ crew/credentials.py (CREW_AI_KEY legacy)
                                              └──→ experts/policy.py + agent.py (EXPERT_*)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.conf` | modifies | add `DEFAULT_LLM`; delete `DEFAULT_LLM_MODEL_NAME` |
| `AgentHandler` (server) | modifies | `_use_llm`/`_use_model` default from `AGENT_LLM`; pass `AGENT_<P>_API_KEY` |
| `AgentCrew.run_sequential` / lazy `_llm` | modifies | model + key from `CREW_LLM` / `CREW_GOOGLE_API_KEY` |
| `crew/credentials.get_crew_google_api_key` | modifies | cascade `CREW_GOOGLE_API_KEY` → `CREW_AI_KEY` |
| `experts.policy.DEFAULT_TIER_POLICY` | modifies | built from `EXPERT_<TIER>_LLM` at call time |
| `ExpertAgent.__init__` | modifies | inject `EXPERT_<TIER>_<P>_API_KEY` → `EXPERT_<P>_API_KEY` |

### Data Models

```python
class ComponentLLM(BaseModel):
    provider: str
    model: str
    source: Literal["component", "global", "builtin"]
```

### New Public Interfaces

See §3 Module 1 skeleton.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: llm_defaults resolver | yes | skeleton below; ValueError on malformed; GOOGLE family mapping | — |
| M2: conf cleanup | yes | add `DEFAULT_LLM = config.get("DEFAULT_LLM", fallback=None)`; delete line 248 | — |
| M3: AgentCrew wiring | yes | builtin `google:gemini-2.5-pro`; legacy `CREW_AI_KEY` | — |
| M4: Expert tiers wiring | yes | builtins = today's dict; temperature unchanged | — |
| M5: Agent handler wiring | yes | builtin `google:gemini-2.5-pro`; class attrs stay overridable | — |
| M6: docs | yes | env table in `docs/configuration/llm-defaults.md` | — |

### Module 1: Resolver

- **Path**: `packages/ai-parrot/src/parrot/llm_defaults.py` (new)
- **Responsibility**: resolve `(provider, model)` and API key per component.
- **Depends on**: `parrot.conf`
- **Interface Skeleton**:
  ```python
  # parrot/llm_defaults.py (new)
  class ComponentLLM(BaseModel):
      """Resolved provider/model for a component plus where it came from."""

  def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM:
      """Resolve ``<COMPONENT>_LLM`` → ``DEFAULT_LLM`` → ``builtin`` (all ``provider:model``).

      A bare model in an env var inherits the builtin's provider.
      Raises ValueError naming the variable when the value is malformed or the provider
      is not a ``SUPPORTED_CLIENTS`` key.
      """

  def provider_key_token(provider: str) -> str:
      """``google``/``gemini-live``/``google-compat`` → ``GOOGLE``; else upper snake case."""

  def resolve_component_api_key(
      components: Sequence[str], provider: str, *, legacy: Sequence[str] = ()
  ) -> str | None:
      """First set of ``<C>_<TOKEN>_API_KEY`` for C in components, then ``legacy`` vars.

      Returns None when nothing is set (client keeps its provider-wide default).
      Never logs the value.
      """
  ```

### Module 2: conf cleanup

- **Path**: `packages/ai-parrot/src/parrot/conf.py`
- **Responsibility**: add optional `DEFAULT_LLM`; remove dead `DEFAULT_LLM_MODEL_NAME`.
- **Interface Skeleton**:
  ```python
  # modifies parrot/conf.py:247-248
  DEFAULT_LLM: str | None = config.get("DEFAULT_LLM", fallback=None)  # provider:model, opt-in
  ```

### Module 3: AgentCrew wiring

- **Path**: `bots/flows/crew/crew.py`, `bots/flows/crew/credentials.py`
- **Responsibility**: `run_sequential(model: Optional[str] = None)` → resolved `CREW_LLM`
  model when None; lazy `_llm` (crew.py:2149-2156) builds the client for the resolved
  provider via `SUPPORTED_CLIENTS` (not hardcoded `GoogleGenAIClient`), key =
  `self._google_api_key` (explicit, wins) else `resolve_component_api_key(("CREW",), p,
  legacy=("CREW_AI_KEY",))`. `get_crew_google_api_key()` reads `CREW_GOOGLE_API_KEY` first,
  then `CREW_AI_KEY`; warn-once message names both.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # modifies crew.py:1755
  model: Optional[str] = None,
  # modifies credentials.py get_crew_google_api_key (verified: credentials.py:~51-67)
  def get_crew_google_api_key() -> Optional[str]:
      """CREW_GOOGLE_API_KEY → CREW_AI_KEY (legacy) → None."""
  ```

### Module 4: Expert tiers

- **Path**: `experts/policy.py`, `experts/agent.py`
- **Responsibility**: `_BUILTIN_TIER_POLICY` keeps today's dict; new
  `tier_policy(tier) -> dict` overlays `resolve_component_llm(f"EXPERT_{tier.name}",
  builtin=...)`; `model_config_for` uses it. `DEFAULT_TIER_POLICY` stays exported, equal to
  the builtin dict (back-compat for importers). `ExpertAgent.__init__` passes
  `api_key=resolve_component_api_key((f"EXPERT_{tier}", "EXPERT"), provider)` in the
  client kwargs when not None and not already in `kwargs`.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # modifies experts/policy.py:19
  def tier_policy(tier: ExpertTier) -> dict[str, Any]:
      """Builtin tier dict with provider/model overridden by EXPERT_<TIER>_LLM / DEFAULT_LLM."""
  def model_config_for(tier: ExpertTier, *, overrides: Mapping[str, Any] | None = None) -> ModelConfig:
      """Unchanged signature; base is tier_policy(tier). Registry overrides still win."""
  ```

### Module 5: Agent HTTP handler

- **Path**: `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py`
- **Responsibility**: class attrs `_use_llm` / `_use_model` default to `None`; at
  `_create_agent` (`:795-800`) resolve `AGENT_LLM` when the subclass left them `None`, and
  pass `api_key` from `resolve_component_api_key(("AGENT",), provider)` when set.
  Subclasses that set `_use_llm`/`_use_model` keep winning.
- **Depends on**: M1

### Module 6: Docs

- **Path**: `docs/configuration/llm-defaults.md` (new) + note in `docs/crew_handler.md`.
- **Responsibility**: env var table, cascade order, `CREW_AI_KEY` legacy status.

---

## 4. Test Specification

### Unit Tests

| Test | Module | Description |
|---|---|---|
| `test_resolve_builtin_when_unset` | M1 | no env → builtin, `source="builtin"` |
| `test_component_var_wins_over_global` | M1 | `CREW_LLM` beats `DEFAULT_LLM` |
| `test_bare_model_inherits_builtin_provider` | M1 | `CREW_LLM=gemini-2.5-flash` → google |
| `test_malformed_raises_named_var` | M1 | `CREW_LLM=nope:x` → ValueError mentioning `CREW_LLM` |
| `test_provider_token_google_family` | M1 | gemini-live / google-compat → GOOGLE |
| `test_api_key_cascade_order` | M1 | `<C>_GOOGLE_API_KEY` → family → legacy → None |
| `test_crew_google_key_precedence` | M3 | `CREW_GOOGLE_API_KEY` beats `CREW_AI_KEY` |
| `test_crew_lazy_llm_uses_crew_llm` | M3 | lazy client gets resolved model/provider + key |
| `test_crew_sequential_default_model` | M3 | `model=None` → resolved model |
| `test_tier_policy_env_override` | M4 | `EXPERT_BALANCED_LLM=openai:gpt-x` |
| `test_default_tier_policy_unchanged` | M4 | exported dict equals today's literal |
| `test_expert_agent_api_key_injected` | M4 | `EXPERT_GOOGLE_API_KEY` reaches client kwargs |
| `test_handler_agent_llm_env` | M5 | `AGENT_LLM` used when subclass sets nothing |
| `test_handler_subclass_override_wins` | M5 | subclass `_use_model` beats env |
| `test_default_llm_model_name_removed` | M2 | `parrot.conf` has no `DEFAULT_LLM_MODEL_NAME` |

### Integration Tests

| Test | Description |
|---|---|
| existing crew Google-key suite | must stay green with `CREW_AI_KEY` only (legacy path) |

### Validation Contract

tests:
- packages/ai-parrot/tests/unit/test_llm_defaults.py
- packages/ai-parrot/tests/bots/flows/crew/test_crew_credentials.py
- packages/ai-parrot/tests/bots/flows/crew/test_crew_key_documented.py
- packages/ai-parrot/tests/experts/test_integration.py
- packages/ai-parrot-server/tests/handlers/test_crew_handler_google_key.py
- packages/ai-parrot-server/tests/manager/test_crew_google_key.py
- packages/ai-parrot/tests/test_conf.py
markers: none

### Test Data / Fixtures

```python
@pytest.fixture
def llm_env(monkeypatch):
    """Patch navconfig.config.get to read from a dict; clears all *_LLM / *_API_KEY."""
```

---

## 5. Acceptance Criteria

- [ ] AC1: With no new env vars set, the agent handler, AgentCrew and every expert tier use
      exactly today's provider/model/key (asserted by tests).
- [ ] AC2: `<COMPONENT>_LLM` (provider:model) overrides each of AGENT, CREW,
      EXPERT_JUDGMENT, EXPERT_BALANCED, EXPERT_TEMPLATED; `DEFAULT_LLM` applies when the
      component var is unset.
- [ ] AC3: When the resolved provider is Google, `<COMPONENT>_GOOGLE_API_KEY` is the default
      key for that component (e.g. `CREW_GOOGLE_API_KEY` for AgentCrew); explicit caller
      credentials still win; unset ⇒ `GOOGLE_API_KEY` as today.
- [ ] AC4: Same key rule for any provider (`<COMPONENT>_<PROVIDER>_API_KEY`).
- [ ] AC5: `CREW_AI_KEY` keeps working as a legacy fallback after `CREW_GOOGLE_API_KEY`.
- [ ] AC6: A malformed `<COMPONENT>_LLM` raises `ValueError` naming the variable.
- [ ] AC7: `DEFAULT_LLM_MODEL_NAME` is removed; no API key is ever logged.
- [ ] AC8: `crew.py` no longer contains the literal `"gemini-2.5-pro"` outside the M3 builtin
      constant; same for the handler and `experts/policy.py` builtins.
- [ ] AC9: Validation Contract tests pass; `ruff check` clean; docs page added.

---

## 6. Codebase Contract

### Verified Imports

```python
from navconfig import config  # verified: parrot/conf.py:6
from parrot import conf  # used as module object in crew/credentials.py:17
from parrot.clients.factory import SUPPORTED_CLIENTS  # verified: crew.py:60 (relative)
from parrot.bots.abstract import _resolve_supported_client  # verified: crew.py:58 (relative)
from parrot.bots.flows.crew.credentials import GOOGLE_PROVIDER_KEYS, has_explicit_google_credential  # verified: crew.py:61
from parrot.models.basic import ModelConfig  # verified: experts/policy.py:8
from parrot.experts.models import ExpertTier  # verified: experts/policy.py:7
```

### Existing Class Signatures

```python
# parrot/conf.py
DEFAULT_LLM_MODEL_NAME = config.get("LLM_MODEL_NAME", fallback="gemini-2.5-pro")  # line 248 — unused
GOOGLE_API_KEY = config.get("GOOGLE_API_KEY")  # line 389
CREW_AI_KEY = config.get("CREW_AI_KEY")  # line 392 (FEAT-575)
DEFAULT_LLM_MODEL = config.get("LLM_MODEL", fallback="gemini-flash-latest")  # line 456 — live

# parrot/bots/flows/crew/credentials.py
GOOGLE_PROVIDER_KEYS: frozenset[str] = frozenset({"google", "gemini-live", "google-compat"})
def has_explicit_google_credential(kwargs: Mapping[str, Any]) -> bool: ...
def get_crew_google_api_key() -> Optional[str]: ...  # reads getattr(conf, "CREW_AI_KEY")

# parrot/bots/flows/crew/crew.py
class AgentCrew:
    def __init__(..., llm: Optional[Union[str, AbstractClient]] = None, ..., google_api_key: Optional[str] = None, ...)  # line 158/182
    self._google_api_key = google_api_key  # line 234
    async def run_sequential(..., model: Optional[str] = "gemini-2.5-pro", **kwargs) -> FlowResult  # line 1755
    # lazy synthesis client, lines 2149-2156

# parrot/experts/policy.py
DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]]  # line 10
def model_config_for(tier, *, overrides=None) -> ModelConfig  # line 19

# parrot/experts/agent.py
super().__init__(..., llm=f"{model_config.provider}:{model_config.model}", ..., **kwargs)  # line 51-59

# parrot/models/basic.py
class ModelConfig(BaseModel):  # line 38 — provider, model, temperature, max_tokens (no api_key)

# ai-parrot-server/src/parrot/handlers/agents/abstract.py
_use_llm: str = 'google'  # line 179
_use_model: str = 'gemini-2.5-pro'  # line 180
agent = self._agent_class(name=..., tools=..., llm=self._use_llm, model=self._use_model)  # line 795-800

# parrot/bots/abstract.py
def _parse_llm_string(self, llm: str) -> Tuple[str, Optional[str]]  # line 847
def _parse_model_config(...)  # line 961 — "gemini-2.5-pro" at 968 is docstring only
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `resolve_component_llm` | crew lazy `_llm` | call | `crew.py:2149` |
| `resolve_component_api_key` | `get_crew_google_api_key` | call | `credentials.py:~59` |
| `tier_policy` | `model_config_for` | call | `experts/policy.py:21` |
| `resolve_component_api_key` | `ExpertAgent.__init__` | kwargs | `experts/agent.py:51` |
| `resolve_component_llm` | `_create_agent` | call | `handlers/agents/abstract.py:795` |

### Does NOT Exist (Anti-Hallucination)

- ~~`parrot.llm_defaults`~~ — created by M1
- ~~`conf.DEFAULT_LLM`~~, ~~`CREW_GOOGLE_API_KEY`~~, ~~`AGENT_LLM`~~, ~~`EXPERT_*_LLM`~~ — new
- ~~`ModelConfig.api_key`~~ — no such field; do not add one (key goes via client kwargs)
- ~~`UsageRecord.component`~~ — no such field (out of scope)
- ~~any real usage of `DEFAULT_LLM_MODEL_NAME`~~ — zero readers in `packages/*/src`

### Edit Sites (Blueprint Anchors)

Verified against: `0b38ff68bd`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/llm_defaults.py` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/conf.py` | MODIFY | `DEFAULT_LLM_MODEL_NAME = config.get("LLM_MODEL_NAME", fallback="gemini-2.5-pro")` | `conf.py:248` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | `        model: Optional[str] = "gemini-2.5-pro",` | `crew.py:1755` | 1 |
| `packages/ai-parrot/src/parrot/bots/flows/crew/crew.py` | MODIFY | `if self._google_api_key:` + next line `self._llm = GoogleGenAIClient(model="gemini-2.5-pro", ...` | `crew.py:2153-2156` | 2 (`if self._google_api_key:` also at 4407 — use context) |
| `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py` | MODIFY | `    key = getattr(conf, "CREW_AI_KEY", None)` | `credentials.py` | 1 |
| `packages/ai-parrot/src/parrot/experts/policy.py` | MODIFY | `DEFAULT_TIER_POLICY: Final[dict[ExpertTier, dict[str, Any]]] = {` | `policy.py:10` | 1 |
| `packages/ai-parrot/src/parrot/experts/agent.py` | MODIFY | `            llm=f"{model_config.provider}:{model_config.model}",` | `agent.py:54` | 1 |
| `packages/ai-parrot-server/src/parrot/handlers/agents/abstract.py` | MODIFY | `    _use_model: str = 'gemini-2.5-pro'` | `abstract.py:180` | 1 |
| `packages/ai-parrot/tests/unit/test_llm_defaults.py` | CREATE | — | — | — |
| `docs/configuration/llm-defaults.md` | CREATE | — | — | — |

---

## 7. Implementation Notes & Constraints

### Patterns to Follow

- Read env through `navconfig.config.get` (same as `conf.py`), read conf values through the
  module object (`getattr(conf, ...)`) so monkeypatching works — the FEAT-575 pattern.
- Resolve lazily (at call/construct time), never at import, so tests and runtime env changes apply.
- Follow `GITHUB_REVIEW_GOOGLE_API_KEY` (`conf.py:833`) naming precedent: `<SCOPE>_GOOGLE_API_KEY`.

### Known Risks / Gotchas

- `conf.py` import cycle (comment at `conf.py:~452`): `llm_defaults.py` must not be imported
  by `conf.py`, and must import `SUPPORTED_CLIENTS` lazily inside the validating function.
- Crew lazy client: switching from hardcoded `GoogleGenAIClient` to `SUPPORTED_CLIENTS`
  lookup must keep `max_tokens=8192`; if the provider satellite is absent, raise a clear error.
- `DEFAULT_LLM` deliberately differs from `LLM_MODEL` — do not make it fall back to
  `LLM_MODEL`, or every deployment that set `LLM_MODEL` for chatbots would silently move
  crew/experts to that model (breaks G5).
- Removing `DEFAULT_LLM_MODEL_NAME` breaks any external `from parrot.conf import
  DEFAULT_LLM_MODEL_NAME` — hard cut accepted (no internal readers).
- Expert registry overrides (`registry.py:75-102`) must still win over env.

### External Dependencies

None.

---

## Consequences

<!-- decision-audit: input_digest=sha256:7092b6fd51b88520297acd2c15f87d485d72ba6b6982df4e5168d786965f0273 evaluation_digest=sha256:f156f3111dd0a33e88d53f88ed53db9639b21b6f6c59e78ed744527e91a7d010 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- `SPEC_BLOCK_MISSING`; path: /home/jesuslara/proyectos/ai-parrot/sdd/specs/per-component-llm-defaults.spec.md; message: no fenced yaml block under '## Decisions'

Coverage:
- Subsystems: auth, bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, server, skills, tools
- Unmapped tags: agentcrew, configuration, credentials, experts, llm-config
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
      "auth",
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "server",
      "skills",
      "tools"
    ],
    "targets_resolved": 0,
    "targets_total": 0,
    "unmapped_tags": [
      "agentcrew",
      "configuration",
      "credentials",
      "experts",
      "llm-config"
    ]
  },
  "diagnostics": [
    {
      "code": "SPEC_BLOCK_MISSING",
      "decision_id": null,
      "message": "no fenced yaml block under '## Decisions'",
      "path": "/home/jesuslara/proyectos/ai-parrot/sdd/specs/per-component-llm-defaults.spec.md"
    }
  ],
  "evaluation_digest": "sha256:f156f3111dd0a33e88d53f88ed53db9639b21b6f6c59e78ed744527e91a7d010",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:7092b6fd51b88520297acd2c15f87d485d72ba6b6982df4e5168d786965f0273",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:b11fe8e33d80455017c18de7c66615b790b28eae29c88d3cc6defc398db393fb",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [ ] Should `CREW_AI_KEY` be deprecated (warning when used) or kept silently as an alias? Spec keeps it silently. — *Owner: Jesus*
- [ ] One `EXPERT_GOOGLE_API_KEY` for all tiers plus optional per-tier keys (spec), or per-tier only? — *Owner: Jesus*
- [ ] Is `LLM_MODEL_NAME` set in any deployment `env/` file that should be migrated to `DEFAULT_LLM`? — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Worktree Strategy

- Isolation: one feature worktree `feat-FEAT-796-per-component-llm-defaults`; tasks get sub-worktrees.
- Module graph: M3, M4, M5 → M1 (import `resolve_component_llm` / `resolve_component_api_key`);
  M2 independent; M6 after M3–M5 (documents final names). M3, M4, M5 run concurrently.
- Shared files: none across modules (crew.py + credentials.py both in M3).
- Exclusive resources: none.
- Cross-feature dependencies: none.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-03 | Jesus Lara | Initial draft |
