# Brainstorming: FlowtaskManagerToolkit

> **Objetivo**: Diseñar una interfaz completa (`parrot/interfaces`) (que evolucionará a un `AbstractToolkit`) para gestionar tareas de Flowtask: listar, leer, editar (YAML/JSON en un repo Git), abrir Pull Requests, y ejecutar tareas vía API REST o local. Incluye modelos Pydantic completos para representar todos los artefactos de una tarea.

Flowtask local repository: `/home/jesuslara/proyectos/parallel/flowtask`

---

## 1. Contexto del Sistema

### Lo que ya existe en AI-Parrot

| Componente | Relevancia |
|---|---|
| `FlowtaskToolkit` | Ejecuta componentes, tareas locales, remotas y desde código. Ya maneja `TASK_DOMAIN`, `httpx`, `long_running`, retry con backoff. | 
| `GitToolkit` | Crea PRs en GitHub via REST API. Modelos `GitHubFileChange`, `CreatePullRequestInput`. Soporta `modify/add/delete`. |
| `AbstractToolkit` | Base para todos los toolkits. `get_tools()` auto-descubre métodos async públicos. `exclude_tools` para métodos internos. |
| `tool_schema` decorator | Asocia un `BaseModel` de Pydantic como `args_schema` a un método. |
| `ToolResult` | Output estándar: `status/result/error/metadata/timestamp`. |

### Lo que le falta al ecosistema Flowtask

1. **Introspección de tareas**: No hay forma de listar/leer definiciones de tareas desde el repo Git.
2. **Edición de tareas**: No hay flujo para modificar YAML/JSON de una tarea y proponer cambios via PR.
3. **Modelos de dominio**: Los modelos Pydantic actuales son solo para _inputs de tools_, no para representar la _estructura interna_ de una tarea Flowtask.
4. **Gestión del ciclo de vida**: Crear tarea nueva, validar, preview, ejecutar — todo como un flujo coherente.

---

## 2. Anatomía de una Tarea Flowtask

Basándome en el uso existente (`flowtask_code_execution`, ejemplos YAML), una tarea Flowtask tiene esta estructura:

```yaml
# Ejemplo completo de tarea Flowtask
name: employees_report
description: "Genera reporte de empleados"
program: nextstop
enabled: true
debug: false

# Variables de entorno / parámetros
params:
  start_date: "2024-01-01"
  end_date: "2024-12-31"

# Configuración de schedule (opcional)
schedule:
  cron: "0 8 * * 1"
  timezone: "America/New_York"

# Notificaciones (opcional)
notifications:
  on_success:
    - type: email
      to: ["team@company.com"]
  on_failure:
    - type: slack
      channel: "#alerts"

# Steps: el DAG de componentes
steps:
  - QueryDatabase:
      input: "SELECT * FROM employees WHERE active = true"
      connection: "postgres_main"
      output: employees_data

  - TransformData:
      input: $employees_data
      operations:
        - filter: "salary > 50000"
        - rename: {emp_name: name}
      output: filtered_data

  - ExportToExcel:
      input: $filtered_data
      filename: "employees_{{start_date}}.xlsx"
      sheet: "Employees"

  - SendEmail:
      to: ["manager@company.com"]
      subject: "Reporte Empleados {{start_date}}"
      attachments: ["employees_{{start_date}}.xlsx"]
```

### Estructura del repo Git de tareas

```
tasks-repo/
├── nextstop/
│   ├── employees_report.yaml
│   ├── sales_summary.yaml
│   └── inventory_check.json
├── epson/
│   ├── planogram_analysis.yaml
│   └── sales_report.yaml
└── shared/
    └── templates/
        └── base_report.yaml
```

---

## 3. Modelos Pydantic de Dominio

### 3.1 Modelos de Step/Component

```python
from pydantic import BaseModel, Field, model_validator
from typing import Any, Dict, List, Literal, Optional, Union
from enum import Enum

class StepOutputRef(str):
    """Referencia a output de un step anterior: $variable_name"""
    pass

class ComponentStep(BaseModel):
    """Un step individual en el DAG de la tarea."""
    component: str = Field(description="Nombre del componente Flowtask (ej: QueryDatabase)")
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Configuración del componente (input, output, atributos)"
    )
    # Campos extraídos del config para facilitar acceso
    input: Optional[Union[str, List[Any], Dict[str, Any]]] = None
    output: Optional[str] = Field(
        default=None,
        description="Nombre de la variable donde se guarda el output de este step"
    )
    depends_on: List[str] = Field(
        default_factory=list,
        description="Steps de los que depende este (para DAG explícito)"
    )
    condition: Optional[str] = Field(
        default=None,
        description="Condición para ejecutar este step (expresión Python safe)"
    )
    on_error: Literal["stop", "skip", "retry"] = Field(
        default="stop",
        description="Comportamiento ante error en este step"
    )
    retry_count: int = Field(default=0, ge=0)
    timeout_seconds: Optional[int] = None

    model_config = {"extra": "allow"}  # Absorbe campos desconocidos del componente
```

### 3.2 Schedule

```python
class ScheduleConfig(BaseModel):
    """Configuración de schedule para ejecución periódica."""
    cron: Optional[str] = Field(default=None, description="Expresión cron: '0 8 * * 1'")
    interval_seconds: Optional[int] = Field(default=None, description="Intervalo en segundos")
    timezone: str = Field(default="UTC")
    enabled: bool = True
    max_instances: int = Field(default=1, ge=1, description="Instancias concurrentes máximas")

    @model_validator(mode="after")
    def validate_schedule_type(self):
        if self.cron is None and self.interval_seconds is None:
            raise ValueError("Debe especificar cron o interval_seconds")
        return self
```

### 3.3 Notificaciones

```python
class NotificationChannel(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    WEBHOOK = "webhook"
    TEAMS = "teams"

class NotificationConfig(BaseModel):
    type: NotificationChannel
    # Email
    to: Optional[List[str]] = None
    subject: Optional[str] = None
    # Slack/Teams
    channel: Optional[str] = None
    # Webhook
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    # Común
    message_template: Optional[str] = None
    include_result: bool = False

class TaskNotifications(BaseModel):
    on_success: List[NotificationConfig] = Field(default_factory=list)
    on_failure: List[NotificationConfig] = Field(default_factory=list)
    on_start: List[NotificationConfig] = Field(default_factory=list)
```

### 3.4 Modelo Principal: TaskDefinition

```python
class TaskDefinition(BaseModel):
    """
    Representación completa de una tarea Flowtask.
    Puede ser serializada a YAML o JSON para persistencia en Git.
    """
    # Identidad
    name: str = Field(description="Nombre único de la tarea (slug)")
    program: str = Field(description="Programa/tenant al que pertenece")
    description: Optional[str] = None
    version: str = Field(default="1.0.0")
    tags: List[str] = Field(default_factory=list)

    # Estado
    enabled: bool = True
    debug: bool = False

    # Parámetros de entrada
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Variables de entrada (pueden ser sobreescritas en ejecución)"
    )
    params_schema: Optional[Dict[str, Any]] = Field(
        default=None,
        description="JSON Schema para validar params"
    )

    # DAG de steps
    steps: List[Union[ComponentStep, Dict[str, Any]]] = Field(
        description="Lista de steps. Cada step es {ComponentName: config} o ComponentStep"
    )

    # Configuraciones opcionales
    schedule: Optional[ScheduleConfig] = None
    notifications: Optional[TaskNotifications] = None

    # Metadata de control (no se persiste en el YAML de la tarea)
    # Solo se usa en el contexto del toolkit
    _file_path: Optional[str] = None
    _raw_content: Optional[str] = None

    model_config = {"extra": "allow"}  # Tolerante a campos custom de Flowtask

    def to_yaml(self) -> str:
        """Serializa la tarea a YAML para persistir en Git."""
        import yaml
        data = self.model_dump(
            exclude_none=True,
            exclude={"params_schema"} if not self.params_schema else set()
        )
        return yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    def to_json(self) -> str:
        """Serializa la tarea a JSON."""
        return self.model_dump_json(exclude_none=True, indent=2)

    @classmethod
    def from_yaml(cls, content: str, program: str = "") -> "TaskDefinition":
        import yaml
        data = yaml.safe_load(content)
        if program and "program" not in data:
            data["program"] = program
        return cls(**data)

    @classmethod
    def from_json(cls, content: str) -> "TaskDefinition":
        import json
        return cls(**json.loads(content))
```

### 3.5 TaskExecutionRequest (para API REST)

```python
class TaskExecutionRequest(BaseModel):
    """Payload para ejecutar una tarea vía API REST."""
    program: str
    task_name: str
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Override de params de la tarea para esta ejecución"
    )
    long_running: bool = False
    timeout: float = 300.0
    max_retries: int = 3
    debug: bool = False
    # Identificador de ejecución para tracking
    execution_id: Optional[str] = None

class TaskExecutionResult(BaseModel):
    """Resultado de la ejecución de una tarea."""
    status: Literal["success", "error", "queued", "running", "timeout"]
    program: str
    task_name: str
    execution_id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    stacktrace: Optional[str] = None
    stdout: Optional[str] = None
    stats: Optional[Dict[str, Any]] = None
    duration_seconds: Optional[float] = None
    queued_at: Optional[str] = None
    completed_at: Optional[str] = None
```

### 3.6 GitPR Models (específicos para tareas)

```python
class TaskFileFormat(str, Enum):
    YAML = "yaml"
    JSON = "json"

class TaskEditRequest(BaseModel):
    """Solicitud de edición de una tarea en el repo Git."""
    program: str
    task_name: str
    task_definition: TaskDefinition
    format: TaskFileFormat = TaskFileFormat.YAML

    # PR metadata
    pr_title: Optional[str] = None  # Auto-generado si None
    pr_body: Optional[str] = None
    branch_name: Optional[str] = None  # Auto: "flowtask/edit/{program}/{task_name}"
    base_branch: str = "main"
    draft: bool = False
    labels: List[str] = Field(default_factory=lambda: ["flowtask", "task-edit"])

class TaskCreateRequest(BaseModel):
    """Solicitud de creación de una nueva tarea."""
    task_definition: TaskDefinition
    format: TaskFileFormat = TaskFileFormat.YAML
    pr_title: Optional[str] = None
    pr_body: Optional[str] = None
    base_branch: str = "main"
    draft: bool = True  # Crear como draft por defecto — requiere revisión
    labels: List[str] = Field(default_factory=lambda: ["flowtask", "new-task"])

class TaskPRResult(BaseModel):
    """Resultado de un PR de creación/edición de tarea."""
    pr_url: str
    pr_number: int
    branch_name: str
    base_branch: str
    program: str
    task_name: str
    file_path: str
    action: Literal["created", "modified"]
```

---

## 4. FlowtaskManagerToolkit: Diseño de la Interfaz

### 4.1 Estructura del Toolkit

```python
class FlowtaskManagerToolkit(AbstractToolkit):
    """
    Toolkit de alto nivel para gestionar el ciclo de vida completo
    de tareas Flowtask: descubrimiento, edición, PR y ejecución.
    
    Combina GitToolkit (para operaciones de repo) con las capacidades
    de ejecución ya existentes en FlowtaskToolkit.
    """
    
    exclude_tools = ("start", "stop", "cleanup")
    
    def __init__(
        self,
        # Git repo de tareas
        tasks_repository: str,          # "org/flowtask-tasks"
        tasks_base_path: str = "",      # Subdirectorio dentro del repo
        default_branch: str = "main",
        github_token: Optional[str] = None,
        # Flowtask API
        task_domain: Optional[str] = None,  # TASK_DOMAIN env var fallback
        http_timeout: float = 300.0,
        **kwargs
    )
```

### 4.2 Herramientas del Toolkit

#### Grupo 1: Descubrimiento e Introspección

```python
# ── list_tasks ──────────────────────────────────────────────────────────────
async def list_tasks(
    self,
    program: Optional[str] = None,   # Filtrar por programa
    tag: Optional[str] = None,       # Filtrar por tag
    enabled_only: bool = True,
) -> Dict[str, Any]:
    """
    Lista todas las tareas disponibles en el repositorio Git.
    Puede filtrar por programa/tenant y por tags.
    Devuelve metadata básica: name, program, description, schedule, enabled.
    """

# ── get_task ─────────────────────────────────────────────────────────────────
async def get_task(
    self,
    program: str,
    task_name: str,
) -> Dict[str, Any]:
    """
    Obtiene la definición completa de una tarea desde el repositorio Git.
    Devuelve TaskDefinition parseado más metadata del archivo (sha, last_modified).
    """

# ── validate_task ─────────────────────────────────────────────────────────────
async def validate_task(
    self,
    task_definition: Dict[str, Any],  # TaskDefinition como dict
) -> Dict[str, Any]:
    """
    Valida una definición de tarea contra el schema Pydantic.
    Devuelve errores de validación si los hay, o confirmación si es válida.
    No ejecuta la tarea.
    """
```

#### Grupo 2: Edición y PR

```python
# ── edit_task ─────────────────────────────────────────────────────────────────
async def edit_task(
    self,
    program: str,
    task_name: str,
    task_definition: Dict[str, Any],  # TaskDefinition completo como dict
    pr_title: Optional[str] = None,
    pr_body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """
    Modifica una tarea existente en el repo Git y abre un PR.
    
    Flujo interno:
    1. Serializa task_definition a YAML/JSON
    2. Determina el path del archivo: {tasks_base_path}/{program}/{task_name}.yaml
    3. Crea branch: flowtask/edit/{program}/{task_name}-{timestamp}
    4. Usa GitToolkit.create_pull_request con change_type="modify"
    5. Devuelve TaskPRResult
    """

# ── create_task ───────────────────────────────────────────────────────────────
async def create_task(
    self,
    task_definition: Dict[str, Any],
    pr_title: Optional[str] = None,
    draft: bool = True,
) -> Dict[str, Any]:
    """
    Crea una nueva tarea en el repo Git y abre un PR draft.
    
    Flujo:
    1. Valida que la tarea no existe ya (evitar duplicados)
    2. Genera YAML desde TaskDefinition
    3. Crea PR con change_type="add"
    """

# ── delete_task ───────────────────────────────────────────────────────────────
async def delete_task(
    self,
    program: str,
    task_name: str,
    reason: Optional[str] = None,
    draft: bool = True,
) -> Dict[str, Any]:
    """
    Propone la eliminación de una tarea vía PR.
    Usa change_type="delete" en GitToolkit.
    Siempre como draft por seguridad.
    """
```

#### Grupo 3: Ejecución

```python
# ── execute_task ──────────────────────────────────────────────────────────────
async def execute_task(
    self,
    program: str,
    task_name: str,
    params: Optional[Dict[str, Any]] = None,
    long_running: bool = False,
    timeout: float = 300.0,
) -> Dict[str, Any]:
    """
    Ejecuta una tarea vía la API REST de Flowtask.
    Permite override de params para esta ejecución.
    Soporta ejecuciones long_running (enqueue + status).
    """

# ── execute_task_local ────────────────────────────────────────────────────────
async def execute_task_local(
    self,
    program: str,
    task_name: str,
    debug: bool = True,
) -> Dict[str, Any]:
    """
    Ejecuta una tarea directamente usando la instancia local de Flowtask.
    Útil para testing/debug sin depender de la API.
    """

# ── execute_task_from_definition ─────────────────────────────────────────────
async def execute_task_from_definition(
    self,
    task_definition: Dict[str, Any],
    format: str = "yaml",
) -> Dict[str, Any]:
    """
    Ejecuta una tarea desde su definición YAML/JSON en memoria.
    Útil para probar cambios antes de hacer el PR.
    """

# ── get_task_status ───────────────────────────────────────────────────────────
async def get_task_status(
    self,
    program: str,
    task_name: str,
    execution_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Consulta el estado de una ejecución de tarea (para long_running=True).
    """
```

#### Grupo 4: Utilidades

```python
# ── list_components ───────────────────────────────────────────────────────────
async def list_components(self) -> Dict[str, Any]:
    """
    Lista todos los componentes Flowtask disponibles.
    Útil para que el agente sepa qué componentes puede usar al crear/editar tareas.
    """

# ── preview_task_yaml ─────────────────────────────────────────────────────────
async def preview_task_yaml(
    self,
    task_definition: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Genera y devuelve el YAML/JSON que se escribiría en el repo,
    sin hacer commit ni PR. Permite al usuario revisar antes de persistir.
    """

# ── diff_task ─────────────────────────────────────────────────────────────────
async def diff_task(
    self,
    program: str,
    task_name: str,
    proposed_definition: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Genera un diff unificado entre la tarea actual en el repo
    y la definición propuesta. Útil antes de abrir el PR.
    """
```

---

## 5. Flujos de Trabajo Principales

### Flujo A: Editar una tarea existente

```
Agent/User
    │
    ▼
[1] get_task(program, task_name)          → TaskDefinition actual desde Git
    │
    ▼
[2] LLM modifica TaskDefinition           → Nueva versión del dict
    │
    ▼
[3] validate_task(new_definition)         → Validación Pydantic
    │    ├─ Error → devolver errores al agente
    │    └─ OK ──► continuar
    ▼
[4] preview_task_yaml(new_definition)     → Ver YAML final (opcional)
    │
    ▼
[5] diff_task(program, task_name, new)    → Ver qué cambió (opcional)
    │
    ▼
[6] edit_task(program, task_name, new,    → PR abierto en GitHub
              pr_title, pr_body)          
    │
    ▼
[7] execute_task_from_definition(new)     → Test antes de merge (opcional)
    │
    ▼
    TaskPRResult {pr_url, pr_number, ...}
```

### Flujo B: Crear una nueva tarea desde cero

```
Agent/User describe qué debe hacer la tarea
    │
    ▼
[1] list_components()                     → Qué componentes existen
    │
    ▼
[2] LLM construye TaskDefinition         → Con steps válidos
    │
    ▼
[3] validate_task(definition)            → Verificar estructura
    │
    ▼
[4] execute_task_from_definition(def)    → Test en local (opcional)
    │
    ▼
[5] create_task(definition, draft=True)  → PR draft en GitHub
    │
    ▼
    TaskPRResult {pr_url, draft=True, ...}
```

### Flujo C: Ejecutar tarea con params custom

```
Agent recibe request: "Ejecuta employees_report para el Q1 2025"
    │
    ▼
[1] get_task("nextstop", "employees_report")   → Verificar que existe y está enabled
    │
    ▼
[2] execute_task(
        program="nextstop",
        task_name="employees_report",
        params={"start_date": "2025-01-01", "end_date": "2025-03-31"},
        long_running=False
    )
    │
    ▼
    TaskExecutionResult {status, result, stats, ...}
```

---

## 6. Integración con Infraestructura Existente

### 6.1 Reutilización de GitToolkit

`FlowtaskManagerToolkit` **no reimplementa** la lógica Git. Instancia y delega a `GitToolkit`:

```python
class FlowtaskManagerToolkit(AbstractToolkit):
    def __init__(self, ...):
        super().__init__(**kwargs)
        self._git = GitToolkit(
            default_repository=tasks_repository,
            default_branch=default_branch,
            github_token=github_token or os.getenv("GITHUB_TOKEN"),
        )
```

Para el path del archivo en el repo:
```python
def _task_file_path(self, program: str, task_name: str, fmt: TaskFileFormat) -> str:
    ext = ".yaml" if fmt == TaskFileFormat.YAML else ".json"
    base = f"{self.tasks_base_path}/{program}" if self.tasks_base_path else program
    return f"{base}/{task_name}{ext}"
```

### 6.2 Reutilización de FlowtaskToolkit

Para ejecución, puede **instanciar internamente** un `FlowtaskToolkit` o replicar la lógica de forma más directa (mejor: replicar para evitar anidamiento de toolkits que confunden al `ToolManager`):

```python
async def execute_task(self, program, task_name, params=None, long_running=False, ...):
    # Lógica directa, no delegando al FlowtaskToolkit
    # Evita que el ToolManager vea herramientas duplicadas
    ...
```

### 6.3 Registro en ToolkitRegistry

```python
# parrot/tools/registry.py
SUPPORTED_TOOLKITS = {
    ...
    "flowtask": FlowtaskToolkit,
    "flowtask_manager": FlowtaskManagerToolkit,  # ← nuevo
}
```

---

## 7. Consideraciones de Diseño

### 7.1 Resolución de paths en el repo

El repo de tareas puede tener estructura plana o jerárquica. Propongo un método de resolución que intenta múltiples convenciones:

```
{base_path}/{program}/{task_name}.yaml      ← preferido
{base_path}/{program}/{task_name}.json      ← fallback
{base_path}/{task_name}.yaml               ← si no hay subdirectorios por programa
```

### 7.2 Lectura de archivos desde GitHub API

Para `get_task()` y `list_tasks()`, usar la GitHub Contents API:
- `GET /repos/{owner}/{repo}/contents/{path}` → archivo individual (content en base64)
- `GET /repos/{owner}/{repo}/contents/{path}` donde path es directorio → lista de archivos

Esto evita clonar el repo y es consistente con lo que ya hace `GitToolkit`.

### 7.3 Caché de definiciones

Para `list_tasks()` que puede ser costoso, considerar caché con TTL:
```python
self._task_cache: Dict[str, Tuple[TaskDefinition, float]] = {}  # (definition, timestamp)
self._cache_ttl: float = 300.0  # 5 minutos
```

### 7.4 Serialización de steps

Los steps en Flowtask usan el formato `{ComponentName: {config}}` que no es directamente un `ComponentStep`. El modelo necesita un parser que convierta entre ambas representaciones:

```python
@staticmethod
def _parse_step(raw_step: Dict[str, Any]) -> ComponentStep:
    """Convierte {ComponentName: {config}} a ComponentStep."""
    component_name = next(iter(raw_step))
    config = raw_step[component_name] or {}
    return ComponentStep(
        component=component_name,
        config=config,
        input=config.get("input"),
        output=config.get("output"),
    )
```

### 7.5 Tensión con el modelo de datos de Flowtask

Flowtask tiene su propio schema interno que puede evolucionar independientemente. Los modelos Pydantic aquí son una **vista del agente** sobre las tareas — no necesitan ser isomorfos al schema interno de Flowtask. La estrategia de `extra="allow"` en `TaskDefinition` garantiza que campos desconocidos pasen through.

---

## 8. Estructura de Archivos Propuesta

```
parrot/tools/flowtask_manager/
├── __init__.py
├── toolkit.py              # FlowtaskManagerToolkit
├── models/
│   ├── __init__.py
│   ├── task.py             # TaskDefinition, ComponentStep, ScheduleConfig, etc.
│   ├── execution.py        # TaskExecutionRequest, TaskExecutionResult
│   └── git_ops.py          # TaskEditRequest, TaskCreateRequest, TaskPRResult
├── client/
│   ├── __init__.py
│   ├── git_client.py       # Wrapper fino sobre GitToolkit para operaciones de tasks
│   └── api_client.py       # HTTP client para Flowtask API REST
└── utils/
    ├── __init__.py
    ├── serializer.py       # to_yaml, from_yaml, to_json, from_json + validación
    └── path_resolver.py    # Lógica de resolución de paths en el repo
```

---

## 9. Preguntas Abiertas / Decisiones Pendientes

1. **¿Autenticación de la API Flowtask?** — El `FlowtaskToolkit` actual usa solo `TASK_DOMAIN` sin auth headers. ¿La API real requiere token/JWT? Si es así, el `FlowtaskManagerToolkit` necesita un mecanismo de auth configurable.

2. **¿GitLab vs GitHub?** — `GitToolkit` asume GitHub API. Si el repo de tareas está en GitLab, se necesita un backend diferente o abstraer la interfaz de `_git`.

3. **¿Validación previa al PR?** — ¿Debe `edit_task` rechazar automáticamente definiciones que fallen validación Pydantic, o es mejor validar explícitamente primero con `validate_task` y dejar que el agente decida?

4. **¿Soporte para dry-run de ejecución?** — Flowtask puede tener un modo dry-run a nivel de componente. ¿Exponer eso como parámetro en `execute_task`?

5. **¿Historial de ejecuciones?** — ¿Debe el toolkit consultar un historial de ejecuciones pasadas? Podría ser útil para el agente: "¿Cuándo fue la última vez que corrió esta tarea?"

6. **¿Notificaciones en creación/edición?** — ¿Se debe notificar a Slack/Teams cuando se crea/edita una tarea vía agente?

7. **Formato preferido YAML vs JSON** — ¿Hay convención establecida en el repo de tareas? ¿Se puede auto-detectar por extensión del archivo existente?

---

## 10. Resumen de Tasks para SDD

| # | Task | Dependencia |
|---|---|---|
| T1 | Definir modelos Pydantic (`task.py`, `execution.py`, `git_ops.py`) | — |
| T2 | `path_resolver.py` + `serializer.py` | T1 |
| T3 | `api_client.py` (HTTP client para API Flowtask) | T1 |
| T4 | `git_client.py` (wrapper sobre GitToolkit para tasks) | T2 |
| T5 | `FlowtaskManagerToolkit` — Grupo 1: Descubrimiento | T2, T4 |
| T6 | `FlowtaskManagerToolkit` — Grupo 2: Edición y PR | T1, T4 |
| T7 | `FlowtaskManagerToolkit` — Grupo 3: Ejecución | T1, T3 |
| T8 | `FlowtaskManagerToolkit` — Grupo 4: Utilidades | T5, T6 |
| T9 | Registro en `ToolkitRegistry` + tests de integración | T5-T8 |