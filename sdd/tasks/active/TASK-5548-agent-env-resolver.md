# TASK-5548: Per-agent env resolver + component-key helpers in `llm_defaults`

**Feature**: FEAT-882 — Per-Agent Env LLM Credentials + AgentsFlow Default Key
**Spec**: `sdd/specs/per-agent-env-llm-credentials.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1 (rev 0.2). Every other task of FEAT-882 builds on these pure functions:
TASK-5549 (`AbstractBot.configure` per-agent override) and TASK-5550 (AgentsFlow FLOW defaults).
FEAT-796 already resolves `<COMPONENT>_LLM` / `<COMPONENT>_<PROVIDER>_API_KEY`; this task adds the
per-agent variant (`<AGENT>_MODEL`, `<AGENT>_<PROVIDER>_API_KEY`), the `COMPONENTS` registry,
value-based detection of component-default keys (spec §2 "Component-default keys are not explicit"),
and the generic pre-`configure()` injector `apply_component_api_key`.

---

## Scope

- Add `"agent"` to `ComponentLLM.source`'s `Literal`.
- Add `COMPONENTS` and a private `_LEGACY_COMPONENT_KEYS = ("CREW_AI_KEY",)`.
- Add `agent_env_token`, `resolve_agent_llm`, `resolve_agent_api_key`, `is_component_default_key`,
  `apply_component_api_key`, plus the private helper `_raw_llm_provider`.
- Append unit tests to `packages/ai-parrot/tests/unit/test_llm_defaults.py`.

**NOT in scope**: wiring into `AbstractBot.configure` (TASK-5549), AgentsFlow (TASK-5550), docs
(TASK-5552). Do not touch `crew/credentials.py`, the Agent HTTP handler or `experts/agent.py` — the
value-based detection exists precisely so those injectors stay unchanged.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/llm_defaults.py` | MODIFY | new resolvers, `COMPONENTS`, injector |
| `packages/ai-parrot/tests/unit/test_llm_defaults.py` | MODIFY | append unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# already at the top of packages/ai-parrot/src/parrot/llm_defaults.py
from typing import Literal, Optional, Sequence   # verified: llm_defaults.py:9
from navconfig import config                      # verified: llm_defaults.py:11
from pydantic import BaseModel                    # verified: llm_defaults.py:12
from parrot import conf                           # verified: llm_defaults.py:14
# lazy (inside a function body, like provider_key_token does at llm_defaults.py:64):
from parrot.bots.flows.crew.credentials import has_explicit_google_credential  # verified: credentials.py:30
```
Add `Any` to the existing `typing` import line (`from typing import Any, Literal, Optional, Sequence`).

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/llm_defaults.py
class ComponentLLM(BaseModel):                                   # :17
    provider: str
    model: str
    source: Literal["component", "global", "builtin"]            # :22  <- add "agent"
def _split(value: str, *, var: str, default_provider: str) -> tuple[str, str]   # :25
    # bare "model" -> (default_provider, model); raises ValueError naming `var`
def resolve_component_llm(component: str, *, builtin: str) -> ComponentLLM       # :47
def provider_key_token(provider: str) -> str                                     # :62  google family -> "GOOGLE"
def resolve_component_api_key(components: Sequence[str], provider: str, *, legacy: Sequence[str] = ()) -> Optional[str]  # :71
    # first non-empty config.get(f"{C.upper()}_{token}_API_KEY") for C in components, then legacy names

# packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py
def has_explicit_google_credential(kwargs: Mapping[str, Any]) -> bool             # :30
    # True if any of api_key / credentials_file / credentials / vertexai is truthy (generic despite the name)
def apply_google_api_key(agent: Any, api_key: Optional[str]) -> bool              # :123  pattern to mirror

# packages/ai-parrot/src/parrot/bots/abstract.py (attributes an agent carries before configure())
self._llm_raw = llm                      # :483  str | client class | client instance | callable | None
self._llm_kwargs = kwargs.get("llm_kwargs", {})   # :547  SHARED by reference with AgentDefinition.config
_default_llm: str = "google"             # :235  class attribute
def is_configured(self) -> bool          # :1922 @property -> self._configured
```

### Does NOT Exist
- ~~`parrot.llm_defaults.resolve_agent_llm` / `resolve_agent_api_key` / `agent_env_token` / `COMPONENTS` / `is_component_default_key` / `apply_component_api_key`~~ — created by THIS task.
- ~~`AbstractBot.agent_id`~~ — no such attribute; the identity is `agent.name`.
- ~~`parrot.llm_defaults.logger`~~ — the module has no logger yet; add `logger = logging.getLogger(__name__)` with `import logging` (stdlib) if you log.
- ~~`ComponentLLM.source == "agent"`~~ — not valid until this task extends the Literal.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/llm_defaults.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/unit/test_llm_defaults.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/llm_defaults.py#ComponentLLM",
    "sym:packages/ai-parrot/src/parrot/llm_defaults.py#_split",
    "sym:packages/ai-parrot/src/parrot/llm_defaults.py#provider_key_token",
    "sym:packages/ai-parrot/src/parrot/llm_defaults.py#resolve_component_api_key",
    "sym:packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py#has_explicit_google_credential"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Read every variable through `config.get(...)` (navconfig), never `os.environ` — the unit-test
  `env` fixture patches `ld.config.get`, and that is what keeps the tests hermetic.
- Never log a key value. Log names (component, agent name, variable name) only.
- `apply_component_api_key` must REBIND `agent._llm_kwargs` to a new dict, never mutate it — the dict
  is shared with `AgentDefinition.config["llm_kwargs"]` and served by `GET /api/v1/crew`
  (see the `apply_google_api_key` docstring, credentials.py:123).
- `CREW_AI_KEY` is a Google-only legacy alias: include it in `is_component_default_key` only when the
  provider token is `GOOGLE`.

### References in Codebase
- `packages/ai-parrot/src/parrot/bots/flows/crew/credentials.py:123` — injector pattern to mirror.
- `packages/ai-parrot/tests/unit/test_llm_defaults.py:9` — `env` fixture to reuse.

---

## Implementation Blueprint

### Steps (in order)
1. Extend the `typing` import with `Any` and the `ComponentLLM.source` Literal with `"agent"` — *why*: `resolve_agent_llm` returns `source="agent"` and the injector takes `Any` agents.
2. Append the constants and functions below after `resolve_component_api_key` (end of file) — *why*: they reuse `_split`, `provider_key_token` and `resolve_component_api_key`, which must be defined first.
3. Append the tests from the Test Specification to `tests/unit/test_llm_defaults.py` and run them — *why*: every later task trusts these functions.

### `packages/ai-parrot/src/parrot/llm_defaults.py` (MODIFY — 1/3)
```python
# occurrences: 1 (verified: grep -c 'from typing import Literal, Optional, Sequence' llm_defaults.py)
# REPLACE `from typing import Literal, Optional, Sequence` (verified: llm_defaults.py:9) with:
from typing import Any, Literal, Optional, Sequence
```

### `packages/ai-parrot/src/parrot/llm_defaults.py` (MODIFY — 2/3)
```python
# occurrences: 1 (verified: grep -c 'source: Literal\["component", "global", "builtin"\]' llm_defaults.py)
# REPLACE line llm_defaults.py:22 with:
    source: Literal["component", "global", "builtin", "agent"]
```

### `packages/ai-parrot/src/parrot/llm_defaults.py` (MODIFY — 3/3)
```python
# occurrences: 1 (verified: grep -c 'def resolve_component_api_key(' llm_defaults.py)
# AFTER — append below the whole body of `def resolve_component_api_key(` (verified: llm_defaults.py:71-78), at end of file

#: Every component with a ``<COMPONENT>_<PROVIDER>_API_KEY`` default (FEAT-882 rev 0.2).
COMPONENTS: tuple[str, ...] = (
    "AGENT",
    "CREW",
    "FLOW",
    "EXPERT_JUDGMENT",
    "EXPERT_BALANCED",
    "EXPERT_TEMPLATED",
)

#: Legacy component-default variables (Google only).
_LEGACY_COMPONENT_KEYS: tuple[str, ...] = ("CREW_AI_KEY",)

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def agent_env_token(name: str) -> str:
    """Return ``name`` as an env-var token: upper case, non-alphanumeric runs -> ``_``, edges stripped.

    Args:
        name: The agent's ``name`` (``odoo-helpdesk`` -> ``ODOO_HELPDESK``).

    Returns:
        The token, or ``""`` when ``name`` is empty or has no alphanumeric character.
    """
    return _NON_ALNUM.sub("_", name or "").strip("_").upper()


def resolve_agent_llm(name: str, *, default_provider: str) -> Optional[ComponentLLM]:
    """Resolve ``<AGENT>_MODEL`` (``provider:model``; a bare model inherits ``default_provider``).

    Returns:
        ``ComponentLLM(source="agent")``, or ``None`` when the variable is unset/empty or the token is empty.

    Raises:
        ValueError: Naming the variable when the value is malformed or the provider is unsupported.
    """
    token = agent_env_token(name)
    if not token:
        return None
    var = f"{token}_MODEL"
    value = config.get(var)
    if not value:
        return None
    provider, model = _split(value, var=var, default_provider=default_provider)
    return ComponentLLM(provider=provider, model=model, source="agent")


def resolve_agent_api_key(name: str, provider: str) -> Optional[str]:
    """Return ``<AGENT>_<PROVIDER_TOKEN>_API_KEY`` or ``None``. Never logs the value."""
    token = agent_env_token(name)
    if not token:
        return None
    return resolve_component_api_key((token,), provider)


def is_component_default_key(api_key: Optional[str], provider: str) -> bool:
    """True when ``api_key`` equals a configured component default for ``provider``.

    Checks ``<C>_<TOKEN>_API_KEY`` for every C in ``COMPONENTS``, plus ``CREW_AI_KEY`` when the
    token is ``GOOGLE``. Falsy ``api_key`` -> ``False``. Never logs a value.
    """
    if not api_key:
        return False
    token = provider_key_token(provider)
    names = [f"{component}_{token}_API_KEY" for component in COMPONENTS]
    if token == "GOOGLE":
        names.extend(_LEGACY_COMPONENT_KEYS)
    return any(config.get(name) == api_key for name in names)
```

### `packages/ai-parrot/src/parrot/llm_defaults.py` (MODIFY — 3b/3, continues the same append)
```python
# AFTER — append below `def is_component_default_key(` written in block 3/3 (end of file)

def _raw_llm_provider(llm: Any, default_provider: Optional[str]) -> Optional[str]:
    """Provider of an agent's raw ``llm`` declaration, or ``None`` when it cannot be known.

    ``None`` -> ``default_provider``; ``"provider[:model]"`` -> ``provider``; a client class ->
    its ``client_name``; a client instance or any other callable -> ``None``.
    """
    # FILL IN: implement the four branches above — bounded by AC5 (instances/callables never get a key);
    #   lower-case the result; for a string use llm.split(":", 1)[0].strip()


def apply_component_api_key(agent: Any, component: str) -> bool:
    """Inject ``<COMPONENT>_<PROVIDER>_API_KEY`` into an UNCONFIGURED agent's ``llm_kwargs``.

    Rebinds ``agent._llm_kwargs`` to a new dict (never mutates the shared one). No-op when the agent is
    configured, lacks ``_llm_raw``/``_llm_kwargs``, its provider cannot be determined (client instance,
    callable), no key is configured, or ``llm_kwargs`` already carries api_key / credentials_file /
    credentials / vertexai.

    Returns:
        ``True`` when the key was injected.
    """
    from parrot.bots.flows.crew.credentials import has_explicit_google_credential  # noqa: PLC0415

    if getattr(agent, "is_configured", False):
        return False
    if not hasattr(agent, "_llm_raw") or not hasattr(agent, "_llm_kwargs"):
        return False
    provider = _raw_llm_provider(agent._llm_raw, getattr(agent, "_default_llm", "google"))
    if not provider:
        return False
    llm_kwargs = agent._llm_kwargs or {}
    if has_explicit_google_credential(llm_kwargs):
        return False
    api_key = resolve_component_api_key((component,), provider)
    if not api_key:
        return False
    agent._llm_kwargs = {**llm_kwargs, "api_key": api_key}
    logger.debug("Injected %s default API key into agent %r", component.upper(), getattr(agent, "name", None))
    return True
```
**Why this shape**: `resolve_agent_api_key` reuses `resolve_component_api_key((token,), …)` because the
variable shape `<X>_<TOKEN>_API_KEY` is identical — one resolver, one Google-family rule. Value-based
`is_component_default_key` is the spec rev 0.2 decision: it lets TASK-5549 tell a component default
(CREW/AGENT/EXPERT/FLOW, injected before `configure()`) from a caller's explicit key without editing the
three existing injectors. Add `import logging`, `import re` at the top (stdlib, after `from __future__`)
and `logger = logging.getLogger(__name__)` below the imports.

### FILL IN checklist
- [ ] `_raw_llm_provider` — four branches; bounded by AC5 (no key for instances/callables).
- [ ] stdlib `import logging`, `import re` + module `logger` — placement only.

---

## Acceptance Criteria

- [ ] `agent_env_token("odoo-helpdesk") == "ODOO_HELPDESK"`; `"My Agent" -> "MY_AGENT"`; `"a__b" -> "A_B"`; `"--" -> ""`.
- [ ] `resolve_agent_llm` returns `None` when unset, parses `provider:model`, bare model inherits `default_provider`, malformed raises `ValueError` naming `<AGENT>_MODEL` (spec AC7).
- [ ] `resolve_agent_api_key` maps `gemini-live` / `google-compat` to `<AGENT>_GOOGLE_API_KEY`.
- [ ] `is_component_default_key` is True for each `COMPONENTS` key and for `CREW_AI_KEY` (Google only), False for unrelated values and falsy input.
- [ ] `apply_component_api_key` injects into an unconfigured stub, rebinding (the original dict object is unchanged — spec AC8), and is a no-op for configured agents, explicit credentials (each of the four signals), client instances and unset keys.
- [ ] No key value appears in captured logs.
- [ ] `ruff check packages/ai-parrot/src/parrot/llm_defaults.py` clean.

---

## Validation Commands

- `pytest packages/ai-parrot/tests/unit/test_llm_defaults.py -q`

---

## Test Specification

```python
# append to packages/ai-parrot/tests/unit/test_llm_defaults.py (reuse the existing `env` fixture)
class _Agent:
    """Unconfigured AbstractBot stand-in exposing the attributes the injector reads."""

    _default_llm = "google"

    def __init__(self, name="feat882-agent", llm=None, llm_kwargs=None, configured=False):
        self.name = name
        self._llm_raw = llm
        self._llm_kwargs = llm_kwargs if llm_kwargs is not None else {}
        self.is_configured = configured


@pytest.mark.parametrize("name,token", [("odoo-helpdesk", "ODOO_HELPDESK"), ("My Agent", "MY_AGENT"), ("a__b", "A_B"), ("--", "")])
def test_agent_env_token_normalizes(name, token): ...
def test_resolve_agent_llm_unset_none(env): ...
def test_resolve_agent_llm_provider_model(env): ...          # also: bare model inherits default_provider
def test_resolve_agent_llm_malformed_names_var(env): ...     # match="FEAT882_AGENT_MODEL"
@pytest.mark.parametrize("provider", ["google", "gemini-live", "google-compat"])
def test_resolve_agent_api_key_google_family(env, provider): ...
def test_is_component_default_key(env): ...                  # every COMPONENTS key, CREW_AI_KEY google-only, falsy
def test_apply_component_api_key_flow(env): ...              # shared = {}; agent=_Agent(llm="google", llm_kwargs=shared); assert shared == {} afterwards
@pytest.mark.parametrize("signal", [{"api_key": "x"}, {"credentials_file": "f"}, {"credentials": object()}, {"vertexai": True}])
def test_apply_component_api_key_noop_explicit(env, signal): ...
def test_apply_component_api_key_noop_configured(env): ...
def test_apply_component_api_key_noop_client_instance(env): ...
def test_no_key_value_logged(env, caplog): ...
# FILL IN: test bodies — bounded by the Acceptance Criteria above; set variables through env["..."]
```

---

## Agent Instructions

1. Work in the feature worktree (`parrot sdd worktree ensure --slug per-agent-env-llm-credentials --feature-id FEAT-882`), never on `dev`.
2. Read the spec; verify the Codebase Contract; set this task `in-progress` in `sdd/tasks/index/per-agent-env-llm-credentials.json`.
3. Implement from the blueprint, complete every `# FILL IN:`, run the Validation Commands.
4. Commit only the listed files; close with `parrot sdd task close TASK-5548 per-agent-env-llm-credentials verified`; fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
