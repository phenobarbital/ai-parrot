---
type: Wiki Overview
title: 'Feature Specification: Kubernetes Toolkit (kubectl-like agent tools)'
id: doc:sdd-specs-feat-214-kubernetes-toolkit-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: El usuario prefiere, frente al despliegue remoto Tailscale de **aphelion**,
relates_to:
- concept: mod:parrot.tools.toolkit
  rel: mentions
- concept: mod:parrot_tools
  rel: mentions
- concept: mod:parrot_tools.kubernetes
  rel: mentions
- concept: mod:parrot_tools.kubernetes.toolkit
  rel: mentions
- concept: mod:parrot_tools.pulumi.config
  rel: mentions
- concept: mod:parrot_tools.pulumi.toolkit
  rel: mentions
- concept: mod:parrot_tools.security.base_executor
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Kubernetes Toolkit (kubectl-like agent tools)

**Feature ID**: FEAT-214
**Date**: 2026-05-31
**Author**: jesuslarag (via Claude)
**Status**: approved
**Target version**: 0.x

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

El usuario prefiere, frente al despliegue remoto Tailscale de **aphelion**,
apoyarse en **sandbox + Pulumi + Kubernetes**. Tras auditar el codebase
(`packages/ai-parrot-tools`, 80+ toolkits):

- **YA EXISTEN** y NO se reconstruyen: `SandboxTool` (gVisor, red `none`),
  `PulumiToolkit` (`parrot_tools/pulumi/toolkit.py` — `pulumi_plan/apply/destroy/
  status/list_stacks`), `DockerToolkit`, `ShellTool`, y una suite de seguridad
  cloud.
- El **único hueco real** confirmado es un **toolkit Kubernetes como capacidad de
  agente** (kubectl-like: listar pods, logs, aplicar manifiestos, escalar). Ojo:
  existe `K8sToolExecutor` (`tools/executors/k8s.py:40`) pero es un **backend de
  ejecución** que corre *otras* tools dentro de un `Job` — NO sirve para
  **operar** un clúster.

**La brecha**: no hay forma de que un agente gestione recursos Kubernetes. Este
spec añade un `KubernetesToolkit` siguiendo el patrón **ya probado** de
`PulumiToolkit` (`AbstractToolkit` + un executor + modelos Pydantic), con las
operaciones **mutadoras** marcadas `requires_grant` para engancharse a la
gobernanza de **FEAT-211** (grants acotados).

### Goals

- **G1**: `KubernetesToolkit(AbstractToolkit)` en
  `packages/ai-parrot-tools/src/parrot_tools/kubernetes/`, espejo de
  `PulumiToolkit`: cada método público async = un tool con prefijo `k8s_`.
- **G2**: Operaciones **read** (sin grant): `k8s_list_pods`, `k8s_get_logs`,
  `k8s_describe`, `k8s_get` (genérico por kind).
- **G3**: Operaciones **mutadoras** (con `requires_grant=True` en `routing_meta`,
  enganche a FEAT-211): `k8s_apply_manifest`, `k8s_scale_deployment`,
  `k8s_delete_resource`, `k8s_rollout_restart`.
- **G4**: Cliente async (`kubernetes_asyncio`, ya usado por `K8sToolExecutor`),
  con `KubernetesConfig` (kubeconfig path/in-cluster, namespace por defecto,
  timeout, contexto).
- **G5**: Resultados tipados (`K8sOperationResult`, espejo de
  `PulumiOperationResult`), nunca volcar objetos crudos enormes.
- **G6**: Registro lazy en `parrot_tools` (como `"pulumi": ...PulumiToolkit`).
- **G7**: Tests con cliente k8s **mockeado** (nunca operar un cluster real en CI).

### Non-Goals (explicitly out of scope)

- **Reimplementar sandbox / Pulumi / Docker**: ya existen; este spec NO los toca.
- **Reusar/extender `K8sToolExecutor`**: es un backend de ejecución, no un
  toolkit; queda intacto.
- **Implementar el enforcement de grants**: lo provee **FEAT-211**. Aquí solo se
  **marca** `requires_grant` en `routing_meta` (sin lógica de gating propia).
- **Helm / kustomize / GitOps (ArgoCD/Flux)**: fuera de alcance (posible futuro).
- **Multi-cluster federation / RBAC management del cluster**: fuera de alcance.
- **Despliegue remoto estilo Tailscale**: explícitamente descartado.

---

## 2. Architectural Design

### Overview

`KubernetesToolkit` replica el patrón de `PulumiToolkit`: hereda
`AbstractToolkit`, construye un `KubernetesExecutor` (envuelve
`kubernetes_asyncio`) desde una `KubernetesConfig`, y expone cada método async
público como tool (`get_tools()`). Las tools mutadoras pasan
`routing_meta={"requires_grant": True, "grant_scope": "k8s:write"}`; el
`GrantGuard` de FEAT-211 (en `ToolManager`) las gateará cuando esté wired — y si
no, se comportan como cualquier tool (este spec no añade gating propio).

### Component Diagram

```
Agent ──► ToolManager.execute_tool("k8s_apply_manifest", ...)
                  │  (FEAT-211 guard: requires_grant? → approval window)
                  ▼
        KubernetesToolkit.k8s_apply_manifest(...)
                  │
                  ▼
        KubernetesExecutor (kubernetes_asyncio client)
                  │
                  ▼
        K8sOperationResult(success, summary, items, raw_excerpt)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `AbstractToolkit` (`tools/toolkit.py:191`) | extends | `get_tools()` (:337) genera tools desde métodos públicos. |
| `PulumiToolkit` (`parrot_tools/pulumi/toolkit.py:23`) | mirrors | Patrón de referencia (toolkit + executor + config + result). |
| `BaseExecutor`/`BaseExecutorConfig` (`parrot_tools/security/base_executor.py:92,25`) | optional-reuse | Base async de executor (Docker-o-CLI, timeout); reusar si encaja. |
| `kubernetes_asyncio` (ya en `K8sToolExecutor`) | uses | Cliente async del cluster. |
| `routing_meta` (`tools/abstract.py:100,140`) | uses | Marca `requires_grant` en mutadoras (FEAT-211). |
| `parrot_tools/__init__.py` lazy registry (:61) | extends | Añade `"kubernetes": "...KubernetesToolkit"`. |
| `K8sToolExecutor` (`tools/executors/k8s.py:40`) | unrelated | Backend de ejecución; NO se toca ni se reusa. |

### Data Models

```python
# packages/ai-parrot-tools/src/parrot_tools/kubernetes/config.py
class KubernetesConfig(BaseModel):
    kubeconfig_path: Optional[str] = None     # None → in-cluster or default
    context: Optional[str] = None
    namespace: str = "default"
    in_cluster: bool = False
    timeout_seconds: int = Field(60, gt=0)

class K8sOperationResult(BaseModel):
    success: bool
    operation: str                            # "list_pods", "apply", ...
    summary: str
    items: list[dict] = Field(default_factory=list)   # bounded projection
    error: Optional[str] = None
```

### New Public Interfaces

```python
# packages/ai-parrot-tools/src/parrot_tools/kubernetes/toolkit.py
class KubernetesToolkit(AbstractToolkit):
    def __init__(self, config: Optional[KubernetesConfig] = None, **kwargs): ...

    # READ (no grant)
    async def k8s_list_pods(self, namespace: Optional[str] = None,
                            label_selector: Optional[str] = None) -> K8sOperationResult: ...
    async def k8s_get_logs(self, pod: str, namespace: Optional[str] = None,
                           container: Optional[str] = None, tail_lines: int = 200) -> K8sOperationResult: ...
    async def k8s_describe(self, kind: str, name: str,
                           namespace: Optional[str] = None) -> K8sOperationResult: ...
    async def k8s_get(self, kind: str, namespace: Optional[str] = None,
                      label_selector: Optional[str] = None) -> K8sOperationResult: ...

    # MUTATING (requires_grant via routing_meta — FEAT-211)
    async def k8s_apply_manifest(self, manifest_yaml: str,
                                 namespace: Optional[str] = None) -> K8sOperationResult: ...
    async def k8s_scale_deployment(self, name: str, replicas: int,
                                   namespace: Optional[str] = None) -> K8sOperationResult: ...
    async def k8s_delete_resource(self, kind: str, name: str,
                                  namespace: Optional[str] = None) -> K8sOperationResult: ...
    async def k8s_rollout_restart(self, name: str,
                                  namespace: Optional[str] = None) -> K8sOperationResult: ...
```

---

## 3. Module Breakdown

### Module 1: Config + result models
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/kubernetes/config.py`
- **Responsibility**: `KubernetesConfig`, `K8sOperationResult`.
- **Depends on**: nada nuevo.

### Module 2: KubernetesExecutor
- **Path**: `parrot_tools/kubernetes/executor.py`
- **Responsibility**: envuelve `kubernetes_asyncio` (carga kubeconfig/in-cluster;
  CoreV1Api/AppsV1Api), implementa las operaciones read y mutadoras, devuelve
  proyecciones acotadas. Espejo de `PulumiExecutor`.
- **Depends on**: Module 1.

### Module 3: KubernetesToolkit
- **Path**: `parrot_tools/kubernetes/toolkit.py`
- **Responsibility**: `AbstractToolkit` con los métodos `k8s_*`; mutadoras con
  `routing_meta={"requires_grant": True, "grant_scope": "k8s:write"}`.
- **Depends on**: Modules 1-2.

### Module 4: Lazy registration + exports
- **Path**: `parrot_tools/__init__.py` + `parrot_tools/kubernetes/__init__.py`
- **Responsibility**: añadir `"kubernetes": "parrot_tools.kubernetes.toolkit.KubernetesToolkit"`
  al registry lazy; exportar clases.
- **Depends on**: Module 3.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_config_defaults` | M1 | `namespace="default"`, timeout>0. |
| `test_result_model_bounded` | M1 | `K8sOperationResult` serializa items acotados. |
| `test_executor_list_pods_mocked` | M2 | `list_pods` con `kubernetes_asyncio` mockeado → items mapeados. |
| `test_executor_scale_mocked` | M2 | `scale_deployment` llama el patch correcto (mock); replicas aplicadas. |
| `test_toolkit_get_tools` | M3 | `get_tools()` expone los 8 tools con prefijo `k8s_`. |
| `test_mutating_tools_require_grant` | M3 | Las 4 mutadoras tienen `routing_meta["requires_grant"] is True`; las read NO. |

### Integration Tests
| Test | Description |
|---|---|
| `test_toolkit_registered_lazy` | El registry lazy de `parrot_tools` resuelve `"kubernetes"` → `KubernetesToolkit`. |
| `test_read_tools_no_grant_meta` | `k8s_list_pods`/`k8s_get_logs` no llevan `requires_grant`. |

### Test Data / Fixtures
```python
@pytest.fixture
def fake_k8s_client(monkeypatch):
    # Patch kubernetes_asyncio CoreV1Api/AppsV1Api with AsyncMock returning
    # canned pod/deployment objects. NEVER touch a real cluster.
    ...
```

---

## 5. Acceptance Criteria

> Esta feature está completa cuando TODO lo siguiente es cierto:

- [ ] `KubernetesToolkit(AbstractToolkit)` expone vía `get_tools()` las 8 tools
  `k8s_*` (4 read + 4 mutadoras).
- [ ] Las 4 mutadoras llevan `routing_meta["requires_grant"] is True`
  (`grant_scope="k8s:write"`); las read NO.
- [ ] `KubernetesExecutor` usa `kubernetes_asyncio` (kubeconfig o in-cluster) y
  devuelve `K8sOperationResult` con proyecciones **acotadas**.
- [ ] Registro lazy en `parrot_tools` resuelve `"kubernetes"`.
- [ ] NO se modifican `SandboxTool`/`PulumiToolkit`/`K8sToolExecutor`.
- [ ] Tests con cliente k8s **mockeado** (sin cluster real en CI).
- [ ] Tests: `pytest packages/ai-parrot-tools/tests/kubernetes/ -v` verde.
- [ ] Sin breaking changes en el resto de `parrot_tools`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
```python
from parrot.tools.toolkit import AbstractToolkit          # verified: tools/toolkit.py:191
# Pattern reference (mirror):
from parrot_tools.pulumi.toolkit import PulumiToolkit      # verified: parrot_tools/pulumi/toolkit.py:23
from parrot_tools.pulumi.config import PulumiConfig, PulumiOperationResult  # verified: pulumi/config.py:16,224
# Optional executor base:
from parrot_tools.security.base_executor import BaseExecutor, BaseExecutorConfig  # verified: security/base_executor.py:92,25
import kubernetes_asyncio                                  # verified usage: tools/executors/k8s.py:84
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                                # line 191
    def get_tools(self, ...) -> list:                      # line 337 (exposes public async methods as tools)
    async def get_tools_filtered(self, ...): ...           # line 427
    def get_tools_sync(self, ...): ...                     # line 447

# packages/ai-parrot-tools/src/parrot_tools/pulumi/toolkit.py  (MIRROR THIS)
class PulumiToolkit(AbstractToolkit):                      # line 23
    def __init__(self, config: Optional[PulumiConfig] = None, **kwargs):  # line 45
        super().__init__(**kwargs); self.config = config or PulumiConfig()
        self.executor = PulumiExecutor(self.config)        # line 54
    async def pulumi_plan(self, project_path, stack_name=None, config=None,
                          target=None, refresh=True) -> PulumiOperationResult:  # line 82
    async def pulumi_apply(...): ...                        # line 137
    async def pulumi_destroy(...): ...                      # line 199
    async def pulumi_status(...): ...                       # line 254
    async def pulumi_list_stacks(...): ...                  # line 299

# packages/ai-parrot-tools/src/parrot_tools/pulumi/config.py
class PulumiConfig(BaseExecutorConfig): ...                # line 16
class PulumiOperationResult(BaseModel): ...                # line 224
# packages/ai-parrot-tools/src/parrot_tools/pulumi/executor.py
class PulumiExecutor(BaseExecutor):                        # line 22 (use_docker option :344)

# packages/ai-parrot-tools/src/parrot_tools/security/base_executor.py
class BaseExecutorConfig(BaseModel): ...                   # line 25
class BaseExecutor(ABC):                                   # line 92
    def __init__(self, config: BaseExecutorConfig)         # line 106
    async def execute(self, ...): ...                      # line 312

# packages/ai-parrot/src/parrot/tools/executors/k8s.py  (DO NOT REUSE — different purpose)
class K8sToolExecutor(AbstractToolExecutor):               # line 40 (runs OTHER tools in a Job; lazy-imports kubernetes_asyncio :84)

# Lazy registry: packages/ai-parrot-tools/src/parrot_tools/__init__.py
#   "pulumi": "parrot_tools.pulumi.toolkit.PulumiToolkit"  # line 61 (add "kubernetes" alongside)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `KubernetesToolkit` | `AbstractToolkit.get_tools()` | inheritance | `tools/toolkit.py:191,337` |
| toolkit structure | `PulumiToolkit` pattern | mirror | `pulumi/toolkit.py:23-54` |
| `KubernetesExecutor` | `kubernetes_asyncio` | client | `executors/k8s.py:84` |
| mutating tools | `routing_meta["requires_grant"]` | metadata (FEAT-211) | `abstract.py:100,140` |
| lazy registration | `parrot_tools.__init__` registry | dict entry | `parrot_tools/__init__.py:61` |

### Does NOT Exist (Anti-Hallucination)
- ~~`KubernetesToolkit` / `parrot_tools.kubernetes`~~ — **NO existe** (confirmado). Lo crea esta feature.
- ~~reusar `K8sToolExecutor` como toolkit~~ — NO; es un *executor* que corre otras tools en un Job, propósito distinto. No tocarlo.
- ~~enforcement de grants en el toolkit~~ — NO; el gating lo hace FEAT-211 en `ToolManager`. El toolkit solo **marca** `requires_grant`.
- ~~reimplementar Pulumi/sandbox~~ — ya existen; este spec NO los toca.
- ~~`routing_meta["requires_grant"]` ya consumido~~ — es NUEVO (lo introduce FEAT-211); aquí solo se anota en las mutadoras.

### Patterns to Follow
- **Espejar `PulumiToolkit`** al milímetro: `__init__(config)` → `self.executor`;
  un método async público por operación; docstrings claras (se vuelven la
  descripción del tool para el LLM).
- Validación de inputs antes de llamar al cluster (como `_validate_project_path`).
- async/await; `kubernetes_asyncio` (NUNCA cliente sync); cerrar el client.
- Proyecciones **acotadas** en `K8sOperationResult.items` (no volcar objetos
  enormes al LLM).
- Marcar mutadoras con `routing_meta={"requires_grant": True, "grant_scope": "k8s:write"}`.
- `self.logger`.

### Known Risks / Gotchas
- **`kubernetes_asyncio` es dependencia opcional**: lazy-import como hace
  `K8sToolExecutor` (`k8s.py:81-84`); fallar con mensaje claro si no está
  instalado.
- **Carga de config**: in-cluster vs kubeconfig — soportar ambos
  (`config.load_incluster_config` / `config.load_kube_config`).
- **Cierre del client**: `kubernetes_asyncio` ApiClient debe cerrarse (async
  context o `close()`), o fuga de conexiones.
- **Output enorme**: `get_logs`/`get` pueden devolver megabytes; aplicar
  `tail_lines`/límites y truncar.
- **Seguridad**: las mutadoras son peligrosas; el valor de marcar
  `requires_grant` es que FEAT-211 exija aprobación. Documentar que sin FEAT-211
  wired NO hay gating (igual que cualquier tool hoy).

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `kubernetes_asyncio` | (ya usado por K8sToolExecutor) | Cliente async del cluster. Extra opcional del paquete. |
| `pyyaml` | (presente) | Parsear `manifest_yaml` en `k8s_apply_manifest`. |

---

## 8. Open Questions

> Resueltas por el usuario antes de redactar este spec (decisión de plan #7):

- [x] ¿Reusar `K8sToolExecutor` o crear toolkit nuevo? — *Resuelto*: **toolkit
  nuevo** espejando `PulumiToolkit`; `K8sToolExecutor` es un backend distinto.
  Reflejado en Non-Goals y §6.
- [x] ¿Gating de mutadoras? — *Resuelto*: marcar `requires_grant`; el enforcement
  lo aporta **FEAT-211**. Reflejado en G3 y Non-Goals.

> Pendientes (decidibles en implementación):

- [ ] ¿`KubernetesExecutor` hereda de `BaseExecutor` (security) o es standalone?
  — *Owner: implementador M2* (preferencia: standalone si `BaseExecutor` asume
  Docker/CLI; reusar solo si encaja limpio).
- [ ] Alcance de `k8s_get`/`k8s_describe`: ¿kinds fijos (pod/deploy/svc) o
  genérico vía dynamic client? — *Owner: implementador M2* (preferencia: empezar
  con kinds comunes + apply genérico).

---

## Worktree Strategy

- **Default isolation unit**: `per-spec` — M1→M4 secuenciales bajo
  `parrot_tools/kubernetes/`. Sin paralelismo útil.
- **Cross-feature dependencies**: **soft** sobre FEAT-211 (grants): las mutadoras
  marcan `requires_grant`, pero el toolkit funciona sin FEAT-211 (sin gating).
  Independiente y mergeable solo.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-05-31 | jesuslarag (via Claude) | Initial draft — KubernetesToolkit espejando PulumiToolkit; read sin grant, mutadoras con requires_grant (FEAT-211). Sandbox/Pulumi ya existen, no se tocan. |
