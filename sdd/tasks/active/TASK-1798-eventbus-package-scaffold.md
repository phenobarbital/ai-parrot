# TASK-1798: Package scaffold, CI y TOPICS.md para navigator-eventbus

**Feature**: FEAT-312 — EventBus Core Extraction → `navigator-eventbus`
**Spec**: `sdd/specs/eventbus-core-extraction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Fase 1 del plan de extracción (brainstorm `navigator-eventbus-extraction`).
El repo destino `/home/jesuslara/proyectos/navigator-eventbus` está vacío
(README + LICENSE). Este task crea el esqueleto del paquete sobre el que
TODOS los demás tasks de FEAT-312 depositan código. Implementa el Module 1
del spec.

> **IMPORTANTE — repo de trabajo**: este task se implementa en
> `/home/jesuslara/proyectos/navigator-eventbus`, en la rama
> `feat-FEAT-312-eventbus-core-extraction` (creada desde su `main`).
> En ai-parrot SOLO se actualiza el estado SDD (index) en `dev`.

## Scope

- Crear `pyproject.toml` (src-layout, `uv`-managed): name `navigator-eventbus`,
  import package `navigator_eventbus`, version `0.1.0`, `requires-python >=3.11`,
  license MIT, autor Jesus Lara.
- Dependencias directas: `navconfig[default]>=2.2.2`, `asyncdb>=2.11`, `aiohttp>=3.9`.
  Extras: `[redis]` (redis>=5), `[grpc]` (grpcio>=1.74, grpcio-tools>=1.74),
  `[notify]` (async-notify>=1.5.2), `[scheduler]` (apscheduler),
  `[watchdog]` (watchdog), `[mqtt]` (gmqtt), `[all]` (todos).
- Crear `src/navigator_eventbus/__init__.py` (placeholder con `__version__ = "0.1.0"`;
  los re-exports reales los añaden TASK-1799/1800).
- Crear árbol de subpaquetes vacíos con `__init__.py`: `backends/`, `subscribers/`,
  `ingress/`, `ingress/proto/`, `hooks/`, `hooks/brokers/`.
- Crear `tests/` con `conftest.py` mínimo y un test smoke
  (`test_package_imports`: `import navigator_eventbus; assert __version__`).
- CI GitHub Actions `.github/workflows/ci.yml`: pytest + ruff + mypy sobre
  Python 3.11/3.12, replicando la matriz de ai-parrot
  (`/home/jesuslara/proyectos/ai-parrot/.github/workflows/ci.yml` como referencia).
- Config de ruff y mypy en `pyproject.toml` (copiar secciones equivalentes de ai-parrot).
- Crear `TOPICS.md` en la raíz: registro de namespaces de topics con ownership:
  `bus.*` (meta-topics del core: `bus.subscriber_error`, `bus.backpressure`,
  `bus.shutdown_incomplete`, `bus.dlq`, `bus.dlq_error`), `hooks.<type>.<event>`
  (ingress de hooks), y reserva documentada de `lifecycle.*` (fase 2),
  `agent.*` (ai-parrot), `task.*`/`flow.*` (flowtask), `auth.*` (navigator-auth).
  Incluir la convención de registro para apps nuevas.
- Actualizar `README.md`: descripción, install (`uv pip install -e .`), extras.
- Borrar la rama remota `copilot/complete-event-bus-implementation`
  (`git push origin --delete copilot/complete-event-bus-implementation`).
- El commit inicial del scaffold debe referenciar el SHA de origen de ai-parrot
  (`dev`) desde el que se copiará el código (anotarlo en el mensaje de commit).

**NOT in scope**: mudar código del bus (TASK-1799+); publicar a PyPI;
configurar release workflow (post-fase-4).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `pyproject.toml` (repo navigator-eventbus) | CREATE | metadata, deps, extras, ruff/mypy config |
| `src/navigator_eventbus/__init__.py` | CREATE | `__version__` placeholder |
| `src/navigator_eventbus/{backends,subscribers,ingress,ingress/proto,hooks,hooks/brokers}/__init__.py` | CREATE | subpaquetes vacíos |
| `tests/conftest.py`, `tests/test_package.py` | CREATE | smoke test |
| `.github/workflows/ci.yml` | CREATE | pytest+ruff+mypy matrix |
| `TOPICS.md` | CREATE | registro de namespaces |
| `README.md` | MODIFY | descripción + install |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# En el venv del ecosistema (verificado 2026-07-17 en ai-parrot/.venv):
import navconfig    # 2.2.3
import asyncdb      # 2.15.9
import notify       # async-notify 1.5.7
from datamodel.parsers.json import JSONContent  # orjson-backed
```

### Existing Signatures to Use
```
# Referencia de CI: /home/jesuslara/proyectos/ai-parrot/.github/workflows/ci.yml
# Referencia de pyproject: /home/jesuslara/proyectos/ai-parrot/packages/ai-parrot/pyproject.toml
#   (build-system setuptools — el paquete nuevo NO necesita Cython)
# Estado del repo destino (verificado 2026-07-17): main limpio, solo README.md
#   + LICENSE; rama remota copilot/complete-event-bus-implementation existe y se borra.
# Meta-topics a documentar en TOPICS.md (origen verificado):
#   bus.subscriber_error, bus.backpressure, bus.shutdown_incomplete  (bus/core.py:44-46)
#   bus.dlq, bus.dlq_error                                           (bus/dlq.py:173,227)
#   convención hooks.<type>.<event>                                  (hooks/manager.py:127,138)
```

### Does NOT Exist
- ~~`navigator.eventbus` namespace~~ — import plano `navigator_eventbus`
  (`navigator/__init__.py` es paquete regular, PEP 420 inviable).
- ~~Cython en el paquete nuevo~~ — build puro Python (setuptools o hatchling).
- ~~Workflow `release.yml` en esta fase~~ — la publicación PyPI es post-fase-4.
- ~~Contenido útil en la rama copilot~~ — se borra sin revisar; FEAT-310 es canónico.

---

## Implementation Notes

### Key Constraints
- src-layout obligatorio: `src/navigator_eventbus/` (decisión de brainstorm).
- Python >=3.11; async-first; `uv` para todo manejo de paquetes.
- El CI no depende de ai-parrot ni de servicios externos (los tests redis se
  marcan y skipean sin servidor).

### References in Codebase
- `/home/jesuslara/proyectos/ai-parrot/.github/workflows/ci.yml` — matriz a replicar
- `sdd/specs/eventbus-core-extraction.spec.md` §2 Component Diagram — árbol destino

---

## Acceptance Criteria

- [ ] `uv pip install -e .` funciona en un venv limpio del repo destino
- [ ] `python -c "import navigator_eventbus; print(navigator_eventbus.__version__)"` → `0.1.0`
- [ ] `pytest tests/ -v` verde (smoke)
- [ ] `ruff check src/` y `mypy src/` corren sin errores
- [ ] CI verde en el primer push de la rama
- [ ] `TOPICS.md` presente con los meta-topics del core y las reservas de namespace
- [ ] Rama `copilot/complete-event-bus-implementation` eliminada de origin

---

## Test Specification

```python
# tests/test_package.py
import navigator_eventbus


def test_package_imports():
    assert navigator_eventbus.__version__ == "0.1.0"
```

---

## Agent Instructions

1. **Read the spec** at `sdd/specs/eventbus-core-extraction.spec.md` (repo ai-parrot).
2. Trabaja en `/home/jesuslara/proyectos/navigator-eventbus`, rama
   `feat-FEAT-312-eventbus-core-extraction` desde `main`.
3. Verify the Codebase Contract before writing code.
4. Update status in `sdd/tasks/index/eventbus-core-extraction.json` (repo ai-parrot, `dev`).
5. Commit en el repo destino: `feat: package scaffold (FEAT-312 TASK-1798) — source ai-parrot@<SHA>`.
6. Move this file to `sdd/tasks/completed/` y rellena la Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
