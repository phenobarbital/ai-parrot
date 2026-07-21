# TASK-1859: Builder de dispatchers reutilizable + parsing de env del pool

**Feature**: FEAT-323 — Dev-Loop Multiple Dev Agents (Parallel Development Node)
**Spec**: `sdd/specs/dev-loop-multiple-dev-agents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1857
**Assigned-to**: unassigned

---

## Context

Implementa el **Module 3** del spec. Hoy el mapeo backend→dispatcher vive
inline en `examples/dev_loop/server.py` (bloque `DEV_LOOP_DEVELOPMENT_AGENT`,
líneas 461-575) y solo puede producir UN dispatcher. Esta task lo extrae a
un builder reutilizable `DevAgentSpec → (dispatcher, profile)` y añade el
parsing de las env vars nuevas del pool.

---

## Scope

- Crear `parrot/flows/dev_loop/agent_builder.py` con:
  - `build_dispatcher(spec: DevAgentSpec, *, redis_url: str,
    max_concurrent: int, stream_ttl_seconds: int, **backend_kwargs)
    -> tuple[DevLoopCodeDispatcher, BaseModel]` — mapea cada
    `DevAgentBackend` a su dispatcher + profile con los MISMOS defaults de
    modelo que usa hoy el server (`spec.model == ""` ⇒ default del backend).
  - `parse_pool_env(getter) -> Optional[DevAgentPoolConfig]` — parsea
    `DEV_LOOP_DEV_AGENTS` (JSON list de DevAgentSpec) y
    `DEV_LOOP_DEV_ISOLATION`; JSON inválido ⇒ warning + `None` (nunca crash).
  - `resolve_pool_max(getter) -> int` — `DEV_LOOP_DEV_POOL_MAX`
    (default razonable, p. ej. 4).
- Refactorizar `examples/dev_loop/server.py` para que el bloque single-agent
  actual consuma `build_dispatcher` (MISMO comportamiento observable: mismos
  dispatchers, modelos default y logs equivalentes por backend).
- Unit tests: mapeo de los 7 backends, defaults de modelo, env parsing
  válido/inválido, cap.

**NOT in scope**: pool/asignación (TASK-1860), cambios al DevelopmentNode,
wiring de factories/flow (TASK-1863).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py` | CREATE | Builder + env parsing |
| `examples/dev_loop/server.py` | MODIFY | Consumir el builder (sin cambio de conducta) |
| `tests/flows/dev_loop/test_agent_builder.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Rutas relativas a `packages/ai-parrot/src/` salvo `examples/`.

### Verified Imports
```python
# Dispatchers — todos definidos en parrot/flows/dev_loop/dispatcher.py:
from parrot.flows.dev_loop.dispatcher import (
    ClaudeCodeDispatcher,      # line 150
    CodexCodeDispatcher,       # dispatch en line 896
    GeminiCodeDispatcher,
    LLMCodeDispatcher,         # backend "nvidia"/"llm"
    GrokCodeDispatcher,
    ZaiCodeDispatcher,
    MoonshotCodeDispatcher,
    DevLoopCodeDispatcher,     # Protocol, line 129
)
# Profiles — parrot/flows/dev_loop/models.py:
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,   # line 381
    CodexCodeDispatchProfile,
    GeminiCodeDispatchProfile,
    LLMCodeDispatchProfile,
    GrokCodeDispatchProfile,
    ZaiCodeDispatchProfile,
    # tras TASK-1857:
    DevAgentPoolConfig, DevAgentSpec,
)
```

### Existing Signatures to Use
```python
# parrot/flows/dev_loop/dispatcher.py
class ClaudeCodeDispatcher:                               # line 150
    def __init__(self, *, max_concurrent: int, redis_url: str,
                 stream_ttl_seconds: int) -> None: ...    # line 157

# Selección/config actual por backend — examples/dev_loop/server.py
# (ruta desde raíz del repo). COPIAR estos defaults exactos al builder:
#   line 461: development_agent = conf.config.get("DEV_LOOP_DEVELOPMENT_AGENT", fallback="claude-code")
#   line 472: DEV_LOOP_CODEX_MODEL     fallback "gpt-5.5"
#   line 487: DEV_LOOP_GEMINI_MODEL    fallback "auto"
#   line 494: DEV_LOOP_NVIDIA_CODE_MODEL (+ ENABLE_THINKING/CLEAR_THINKING, lines 508-512)
#   line 530: DEV_LOOP_GROK_MODEL      fallback "grok-build-0.1"
#   line 546: DEV_LOOP_ZAI_MODEL       fallback "glm-5.2" (+ thinking/effort, lines 548-551)
#   line 569: DEV_LOOP_MOONSHOT_MODEL  fallback "kimi-k3" (+ effort, line 571)
# LEER el bloque completo 454-575 del server ANTES de escribir el builder:
# cada dispatcher tiene kwargs de constructor distintos — copiarlos del server.
```

### Does NOT Exist
- ~~`parrot/flows/dev_loop/agent_builder.py`~~ — lo crea ESTA task
- ~~env `DEV_LOOP_DEV_AGENTS` / `DEV_LOOP_DEV_ISOLATION` / `DEV_LOOP_DEV_POOL_MAX`~~ — los introduce ESTA task
- ~~clase `DevLoopConfig`~~ — `config.py` solo tiene `parse_repo_specs()`
- ~~un registry/factory de dispatchers preexistente~~ — el único mapeo actual es el if/elif del server (461-575)
- ~~`MoonshotCodeDispatchProfile` verificado~~ — (unverified — check before use): confirmar el nombre exacto del profile de Moonshot en models.py antes de importarlo

---

## Implementation Notes

### Pattern to Follow
```python
# Espejo del if/elif del server, pero parametrizado por DevAgentSpec:
def build_dispatcher(spec, *, redis_url, max_concurrent, stream_ttl_seconds, config_getter):
    if spec.agent == "codex":
        model = spec.model or config_getter("DEV_LOOP_CODEX_MODEL", fallback="gpt-5.5")
        return CodexCodeDispatcher(...), CodexCodeDispatchProfile(model=model, ...)
    ...
```

### Key Constraints
- `config_getter` inyectable (firma compatible con `conf.config.get(key, fallback=...)`)
  para que los tests no dependan del entorno real.
- El refactor del server NO puede cambiar el comportamiento single-agent:
  mismos tipos de dispatcher, mismos modelos default, mismos logs de
  selección (o equivalentes).
- `parse_pool_env` tolera: env ausente (⇒ None), JSON malformado (⇒ warning
  + None), entradas con backend desconocido (⇒ ValidationError de Pydantic
  capturada ⇒ warning + None).
- Logging con `logging.getLogger(__name__)`.

### References in Codebase
- `examples/dev_loop/server.py:454-575` — fuente de verdad de kwargs por backend
- `parrot/flows/dev_loop/config.py::parse_repo_specs` — patrón de parsing de env tolerante a errores

---

## Acceptance Criteria

- [ ] `build_dispatcher` cubre los 7 backends con los defaults de modelo actuales
- [ ] `spec.model` no vacío tiene precedencia sobre el default del backend
- [ ] `parse_pool_env` con JSON válido ⇒ `DevAgentPoolConfig`; inválido/ausente ⇒ `None` + warning
- [ ] `resolve_pool_max` lee `DEV_LOOP_DEV_POOL_MAX` con default documentado
- [ ] `examples/dev_loop/server.py` usa el builder y el camino single-agent no cambia de conducta
- [ ] All tests pass: `pytest tests/flows/dev_loop/test_agent_builder.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/flows/dev_loop/agent_builder.py`
- [ ] `from parrot.flows.dev_loop.agent_builder import build_dispatcher, parse_pool_env` funciona

---

## Test Specification

```python
# tests/flows/dev_loop/test_agent_builder.py
import pytest
from parrot.flows.dev_loop.agent_builder import (
    build_dispatcher, parse_pool_env, resolve_pool_max,
)
from parrot.flows.dev_loop.models import DevAgentSpec


def fake_getter(env: dict):
    def _get(key, fallback=None):
        return env.get(key, fallback)
    return _get


class TestBuildDispatcher:
    @pytest.mark.parametrize("backend", [
        "claude-code", "codex", "gemini", "nvidia", "grok", "zai", "moonshot",
    ])
    def test_all_backends_build(self, backend):
        d, profile = build_dispatcher(
            DevAgentSpec(agent=backend),
            redis_url="redis://localhost:6379/0",
            max_concurrent=2, stream_ttl_seconds=3600,
            config_getter=fake_getter({}),
        )
        assert hasattr(d, "dispatch")

    def test_explicit_model_wins(self):
        _, profile = build_dispatcher(DevAgentSpec(agent="codex", model="gpt-9"), ...)
        assert profile.model == "gpt-9"


class TestEnvParsing:
    def test_valid_json(self):
        cfg = parse_pool_env(fake_getter({
            "DEV_LOOP_DEV_AGENTS": '[{"agent": "claude-code", "count": 2}]',
        }))
        assert cfg and cfg.agents[0].count == 2

    def test_invalid_json_returns_none(self):
        assert parse_pool_env(fake_getter({"DEV_LOOP_DEV_AGENTS": "{oops"})) is None

    def test_absent_returns_none(self):
        assert parse_pool_env(fake_getter({})) is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — TASK-1857 in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — LEER `examples/dev_loop/server.py:454-575` completo antes de escribir el builder
4. **Update status** in `sdd/tasks/index/dev-loop-multiple-dev-agents.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**:
