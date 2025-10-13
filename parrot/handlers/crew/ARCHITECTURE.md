# AgentCrew REST API - Arquitectura del Sistema

## 🏗️ Vista General de la Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│                        Cliente / Usuario                         │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ HTTP Requests
                         │
┌────────────────────────▼────────────────────────────────────────┐
│                      CrewHandler (BaseView)                      │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  PUT    /api/v1/crew          → Create Crew              │  │
│  │  GET    /api/v1/crew          → List/Get Crews           │  │
│  │  POST   /api/v1/crew/execute  → Execute Crew (async)     │  │
│  │  PATCH  /api/v1/crew/job      → Get Job Status/Results   │  │
│  │  DELETE /api/v1/crew          → Delete Crew              │  │
│  └──────────────────────────────────────────────────────────┘  │
└──────────────┬──────────────────────────────────┬───────────────┘
               │                                   │
               │ Crew Management                   │ Job Management
               │                                   │
┌──────────────▼───────────────┐    ┌─────────────▼──────────────┐
│      BotManager               │    │      JobManager             │
│  ┌─────────────────────────┐ │    │  ┌──────────────────────┐  │
│  │ • add_crew()            │ │    │  │ • create_job()       │  │
│  │ • get_crew()            │ │    │  │ • execute_job()      │  │
│  │ • list_crews()          │ │    │  │ • get_job()          │  │
│  │ • remove_crew()         │ │    │  │ • list_jobs()        │  │
│  │ • get_crew_stats()      │ │    │  │ • delete_job()       │  │
│  └─────────────────────────┘ │    │  │ • get_stats()        │  │
│                               │    │  └──────────────────────┘  │
│  Stores:                      │    │                             │
│  _crews: Dict[str, Tuple[    │    │  Stores:                    │
│    AgentCrew,                 │    │  jobs: Dict[str, CrewJob]   │
│    CrewDefinition             │    │  tasks: Dict[str, Task]     │
│  ]]                           │    │                             │
└──────────────┬────────────────┘    └─────────────┬──────────────┘
               │                                    │
               │ Crew Execution                     │ Async Execution
               │                                    │
┌──────────────▼────────────────────────────────────▼──────────────┐
│                          AgentCrew                                │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Execution Modes:                                          │  │
│  │                                                             │  │
│  │  • SEQUENTIAL                                              │  │
│  │    Input → Agent1 → Agent2 → Agent3 → Output              │  │
│  │                                                             │  │
│  │  • PARALLEL                                                │  │
│  │    Input → [Agent1, Agent2, Agent3] → Outputs             │  │
│  │                                                             │  │
│  │  • FLOW (DAG)                                              │  │
│  │    Input → Agent1 → [Agent2, Agent3] → Agent4 → Output    │  │
│  │                                                             │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  Components:                                                      │
│  • agents: Dict[str, Agent]                                       │
│  • shared_tool_manager: ToolManager                               │
│  • workflow_graph: Dict[str, AgentNode]  (for flow mode)         │
│  • execution_log: List[Dict]                                      │
└────────────────────────────┬──────────────────────────────────────┘
                             │
                             │ Agent Execution
                             │
┌────────────────────────────▼──────────────────────────────────────┐
│                      Individual Agents                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │  BaseAgent   │  │   Chatbot    │  │ Custom Agent │            │
│  │              │  │              │  │              │            │
│  │ • LLM Client │  │ • LLM Client │  │ • LLM Client │            │
│  │ • Tools      │  │ • Tools      │  │ • Tools      │            │
│  │ • Memory     │  │ • Memory     │  │ • Memory     │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
└───────────────────────────────────────────────────────────────────┘
```

## 📊 Flujo de Datos

### 1. Creación de Crew (PUT)

```
Cliente
  │
  │ PUT /api/v1/crew
  │ {crew_definition}
  │
  ▼
CrewHandler.put()
  │
  │ 1. Valida CrewDefinition (Pydantic)
  │ 2. Crea instancias de agentes
  │ 3. Configura tools
  │ 4. Setup flow relations (si flow mode)
  │
  ▼
BotManager.add_crew()
  │
  │ Almacena: (AgentCrew, CrewDefinition)
  │
  ▼
Response {crew_id, status}
```

### 2. Ejecución de Crew (POST)

```
Cliente
  │
  │ POST /api/v1/crew/execute
  │ {crew_id, query}
  │
  ▼
CrewHandler.post()
  │
  │ 1. Obtiene crew de BotManager
  │ 2. Crea job en JobManager
  │ 3. Define función async de ejecución
  │
  ▼
JobManager.execute_job()
  │
  │ 1. Crea asyncio.Task
  │ 2. Actualiza job status → RUNNING
  │
  ▼
AgentCrew.run_[sequential|parallel|flow]()
  │
  │ Ejecuta agentes según modo
  │
  ▼
JobManager
  │
  │ 1. Actualiza job status → COMPLETED
  │ 2. Almacena resultado
  │
  ▼
Response {job_id, status}
```

### 3. Obtención de Resultados (PATCH)

```
Cliente
  │
  │ PATCH /api/v1/crew/job?job_id=xxx
  │
  ▼
CrewHandler.patch()
  │
  │ 1. Obtiene job de JobManager
  │ 2. Verifica status
  │
  ▼
Response {
  status,
  result (if completed),
  error (if failed)
}
```

## 🔄 Ciclo de Vida de un Job

```
┌─────────────┐
│   PENDING   │ ← Job creado
└──────┬──────┘
       │
       │ execute_job() llamado
       │
┌──────▼──────┐
│   RUNNING   │ ← Ejecución iniciada
└──────┬──────┘
       │
       ├──────────┐
       │          │
┌──────▼──────┐  │
│  COMPLETED  │  │ ← Ejecución exitosa
└─────────────┘  │
                 │
           ┌─────▼──────┐
           │   FAILED   │ ← Ejecución fallida
           └────────────┘
```

## 🧩 Componentes Principales

### CrewHandler
- **Responsabilidad**: Endpoints REST
- **Dependencias**: BotManager, JobManager
- **Entrada**: HTTP Requests (JSON)
- **Salida**: HTTP Responses (JSON)

### BotManager
- **Responsabilidad**: Gestión de crews
- **Almacenamiento**: Dict de crews
- **Operaciones**: CRUD de crews

### JobManager
- **Responsabilidad**: Ejecución asíncrona
- **Almacenamiento**: Dict de jobs
- **Operaciones**: Crear, ejecutar, monitorear jobs

### AgentCrew
- **Responsabilidad**: Orquestación de agentes
- **Modos**: Sequential, Parallel, Flow
- **Entrada**: Query/Task
- **Salida**: CrewResult

## 📦 Modelos de Datos

```
CrewDefinition
├── crew_id: str
├── name: str
├── execution_mode: ExecutionMode
├── agents: List[AgentDefinition]
├── flow_relations: List[FlowRelation]
└── metadata: Dict

AgentDefinition
├── agent_id: str
├── agent_class: str
├── config: Dict
├── tools: List[str]
└── system_prompt: str

CrewJob
├── job_id: str
├── crew_id: str
├── status: JobStatus
├── query: str
├── result: Any
├── error: str
└── timestamps: ...

CrewResult (from AgentCrew)
├── output: str
├── results: List[str]
├── agent_ids: List[str]
├── agents: List[AgentExecutionInfo]
├── execution_log: List[Dict]
└── metadata: Dict
```

## 🔗 Interacciones entre Componentes

```
┌────────────────┐
│   Cliente      │
└───────┬────────┘
        │
        │ 1. Crear Crew
        ▼
┌────────────────┐     ┌────────────────┐
│  CrewHandler   │────▶│  BotManager    │
└───────┬────────┘     └────────────────┘
        │
        │ 2. Ejecutar Crew
        ▼
┌────────────────┐     ┌────────────────┐
│  CrewHandler   │────▶│  JobManager    │
└───────┬────────┘     └───────┬────────┘
        │                      │
        │                      │ 3. Ejecutar async
        │                      ▼
        │              ┌────────────────┐
        │              │  AgentCrew     │
        │              └───────┬────────┘
        │                      │
        │                      │ 4. Ejecutar agentes
        │                      ▼
        │              ┌────────────────┐
        │              │  Agents        │
        │              └───────┬────────┘
        │                      │
        │                      │ 5. Retornar resultado
        │                      │
        │ 6. Obtener resultado │
        ▼                      │
┌────────────────┐             │
│  CrewHandler   │◀────────────┘
└───────┬────────┘
        │
        │ 7. Response
        ▼
┌────────────────┐
│   Cliente      │
└────────────────┘
```

## 🎯 Patrones de Diseño Utilizados

### 1. Repository Pattern
- BotManager actúa como repositorio de crews
- JobManager actúa como repositorio de jobs

### 2. Factory Pattern
- CrewHandler crea instancias de AgentCrew
- Creación dinámica de agentes basada en AgentDefinition

### 3. Async Pattern
- Ejecución no bloqueante con asyncio
- Jobs tracked con futures/tasks

### 4. Strategy Pattern
- Diferentes modos de ejecución (Sequential, Parallel, Flow)
- Selección dinámica basada en execution_mode

### 5. Observer Pattern
- JobManager permite polling de estado
- Jobs notifican cambios de estado

## 🔒 Consideraciones de Concurrencia

```
┌─────────────────────────────────────────┐
│         Ejecuciones Concurrentes        │
├─────────────────────────────────────────┤
│                                         │
│  Job 1: Crew A → Running               │
│         [Agent1] [Agent2] [Agent3]      │
│                                         │
│  Job 2: Crew B → Running               │
│         [Agent1] [Agent2]               │
│                                         │
│  Job 3: Crew A → Pending               │
│         (en cola)                       │
│                                         │
└─────────────────────────────────────────┘
```

- Cada job se ejecuta en su propio asyncio.Task
- No hay límite de crews concurrentes (configurable)
- max_parallel_tasks limita agentes paralelos dentro de un crew
- JobManager mantiene estado independiente por job

## 📈 Escalabilidad

### Vertical
- Aumentar max_parallel_tasks
- Reducir cleanup_interval
- Aumentar recursos del servidor

### Horizontal
- Jobs son stateless (resultado en memoria)
- Puede distribuirse con Redis/DB compartida
- Load balancing en múltiples instancias

### Optimizaciones Futuras
- Queue system (Redis, RabbitMQ)
- Persistent storage (PostgreSQL)
- Caching (Redis)
- Webhooks para notificaciones
- Streaming de resultados parciales

---

**Arquitectura diseñada para AI-Parrot 🦜**
