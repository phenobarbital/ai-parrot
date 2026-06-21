# Guía — Cómo ejecutar los ejemplos de Dev-Loop (server + UI)

> Guía práctica en español para levantar los ejemplos de la orquestación
> **Dev-Loop** (FEAT-129 + FEAT-132 + FEAT-250). Para el detalle exhaustivo
> de cada endpoint, payload y nodo, ver el [`README.md`](./README.md) de esta
> misma carpeta — esta guía es el "cómo lo arranco" resumido.

---

## 1. Qué hay en esta carpeta

```
examples/dev_loop/
├── README.md          ← referencia completa (endpoints, payloads, nodos)
├── GUIA.md            ← este documento
├── e2e_demo.py        ← demo end-to-end SIN servicios externos (cero setup)
├── quickstart.py      ← flujo real, un run programático y sale (sin UI)
├── server.py          ← servidor aiohttp: flujo real + WebSocket multiplexado
└── static/
    └── index.html     ← cliente UI (JS vanilla, sin build step)
```

El flujo es un `AgentsFlow` de 8 nodos:

```
IntentClassifier → [BugIntake →] Research → Development → QA →
DeploymentHandoff → Close          (con un FailureHandler fan-in on_error)
```

`e2e_demo.py`, `quickstart.py` y `server.py` cablean el **mismo flujo real**.
La única diferencia es cómo se dispara y qué se simula:

| Script | Servicios externos | Interfaz | Para qué |
|---|---|---|---|
| `e2e_demo.py` | **todos simulados** en proceso | ninguna (stdout) | Ver la mecánica sin montar nada |
| `quickstart.py` | **reales** | ninguna (stdout) | Embeber el flujo en tu propio servicio |
| `server.py` + UI | **reales** | HTTP + WebSocket + UI | Ver el stream de eventos en vivo |

---

## 2. Setup común (una sola vez)

El repo es un **workspace `uv`** (`[tool.uv.workspace]` en el `pyproject.toml`
raíz). Un solo sync instala todos los paquetes del workspace en editable
dentro de `.venv`:

```bash
uv sync
source .venv/bin/activate
```

> **Regla del proyecto:** activa SIEMPRE el venv (`source .venv/bin/activate`)
> antes de cualquier comando `python` / `uv` / `pip`.

---

## 3. Opción rápida — demo sin servicios externos (`e2e_demo.py`)

La forma más rápida de ver el flujo completo funcionando. Ejecuta el motor
REAL (`AgentsFlow` scheduler, OR-join routing, semáforo del `DevLoopRunner`,
telemetría de ciclo de vida FEAT-176) end-to-end, pero **cada servicio externo
está simulado en proceso**: el dispatcher de Claude Code devuelve salidas
predefinidas, las llamadas a Jira se registran en memoria, los XADD de Redis
los captura un cliente fake, y `git push` / `gh pr create` son no-ops que
devuelven una URL de PR falsa.

**No requiere Redis, ni `claude` CLI, ni Jira, ni API keys.**

```bash
source .venv/bin/activate
python examples/dev_loop/e2e_demo.py
```

Corre 6 escenarios e imprime, para cada uno: nodos ejecutados/fallidos/saltados,
el `FlowResult`, el audit trail simulado de Jira, los eventos del stream
`flow:{run_id}:flow`, y el timeline tipado de eventos FEAT-176:

1. **Bug, happy path** — `IntentClassifier → BugIntake → Research → Development
   → QA → DeploymentHandoff → Close`; PR draft abierto + `Close` transiciona Jira.
2. **Enhancement** — `bug_intake` se salta (routing por `kind`).
3. **QA falla (determinista)** — `deployment_handoff` + `close` saltados;
   comentario de escalación + "Needs Human Review" + reasignación.
4. **Error duro en Development** — el fan-in `on_error` dispara
   `failure_handler`; `qa`/`deployment_handoff`/`close` saltados; estado `partial`.
5. **Code-review falla (gate FEAT-250)** — los criterios deterministas pasan
   pero el veredicto `sdd-codereview` falla, así que el gate de QA bloquea.
6. **Revision mode (FEAT-250 G6)** — `DevLoopRunner.run_revision(RevisionBrief)`
   corre el flujo corto `development → qa → revision_handoff → close`,
   actualizando un PR existente en vez de abrir uno nuevo.

Úsalo como plantilla para cablear el flujo en tu propio harness: todo lo
específico de la simulación vive en las clases `Simulated*`/`Fake*`
(`SimulatedDispatcher`, `SimulatedJira`, `SimulatedGit`, `FakeRedis`, `FakeLLM`).

> ### ⚠️ Los `[ERROR]` / `[WARNING]` del escenario 4 son **esperados**
>
> El **escenario 4** ("Error duro en Development") inyecta a propósito un crash
> en el nodo `development` (`fail_at_node="development"` en `e2e_demo.py`, que
> lanza `RuntimeError("simulated subagent crash in 'development'")`). Verás en
> consola algo como:
>
> ```
> [dispatch] development  → subagent 'sdd-worker'
> [ERROR]   ... parrot.fsm.development(fsm.py:108) :: Agent development execution failed
> [WARNING] ... Node 'development' failed: simulated subagent crash in 'development'
> [INFO]    ... Node 'qa' skipped (no incoming edge fired)
> ```
>
> **Esto no es un fallo del demo** — es la ruta de error funcionando: el flujo
> captura la excepción, el fan-in `on_error` dispara el `FailureHandler`, y
> `qa`/`deployment_handoff`/`close` se saltan. El run reporta `status: partial`
> (no una excepción sin manejar) y el script continúa con los escenarios 5 y 6
> hasta imprimir `Done.`.
>
> Esos `[ERROR]`/`[WARNING]` son **logs**, no el resultado del proceso — salen
> porque `e2e_demo.py` fija `logging.basicConfig(level=logging.WARNING)`.
> El resultado correcto del escenario 4 es:
>
> ```
> status   : partial
> failed   : ['development']                         ← el crash simulado, a propósito
> executed : ['intent_classifier', 'bug_intake', 'research', 'failure_handler']
> skipped  : ['close', 'deployment_handoff', 'qa']
> ```
>
> Si el ruido te molesta, sube el nivel de log a `CRITICAL` en
> `e2e_demo.py` (`logging.basicConfig(level=logging.CRITICAL)`). Para confirmar
> de un vistazo que **todo** el demo pasó, basta con ver `Done.` al final y que
> los otros cinco escenarios salgan `status: completed`.

---

## 4. Server + UI en vivo (`server.py` + `static/index.html`)

### 4.1. Prerrequisitos del modo real

A diferencia del demo, `server.py` (y `quickstart.py`) cablean el flujo real
**sin fakes**. Necesitas además del setup común:

| Requisito | Por qué |
|---|---|
| `uv pip install jira` | `JiraToolkit` importa el paquete `jira` de forma lazy |
| **Redis** en `REDIS_URL` (default `redis://localhost:6379/0`) | Dos streams por run + el multiplexador |
| `ANTHROPIC_API_KEY` (o la key del provider que use el SDK) | `ClaudeAgentClient` (FEAT-124) |
| `claude` CLI en `$PATH`, autenticado | El SDK hace shell-out a él |
| `gh` CLI autenticado | `DeploymentHandoffNode` abre el PR |
| Cuenta de servicio Jira: `JIRA_INSTANCE`, `JIRA_USERNAME`, `JIRA_API_TOKEN`, `JIRA_PROJECT`, `FLOW_BOT_JIRA_ACCOUNT_ID` | Crear/transicionar tickets como `flow-bot` |
| Identidades reporter/escalación: `JIRA_REPORTER_ACCOUNT_ID`, `JIRA_ESCALATION_ACCOUNT_ID` | Aceptan email o accountId; `FLOW_BOT_JIRA_ACCOUNT_ID` es el fallback |
| `AWS_PROFILE` (default `cloudwatch`) + `CLOUDWATCH_LOG_GROUP` (default `fluent-bit-cloudwatch`) | `ResearchNode` trae excerpts de logs |
| `DEV_LOOP_SUMMARY_LLM` (default `anthropic:claude-haiku-4-5-20251001`) | Modelo para resumir logs cuando exceden el cap de 32 767 chars de Atlassian |
| `DEV_LOOP_PLAN_LLM` (default `""` → cae a `DEV_LOOP_SUMMARY_LLM`) | Override opcional del modelo para el comentario de plan-summary (FEAT-132) |

Redis local rápido:

```bash
docker run --rm -p 6379:6379 redis:7
```

### 4.2. Arrancar el servidor

```bash
source .venv/bin/activate
python examples/dev_loop/server.py
# abre http://localhost:8080
```

`server.py` construye el mismo flujo que `quickstart.py` y expone:

| Endpoint | Método | Propósito |
|---|---|---|
| `/` | GET | Sirve el cliente UI |
| `/api/flow/run` | POST | Inicia un run real; body = `WorkBrief`/`BugBrief` JSON (o `{}` para el sample) |
| `/api/flow/{run_id}/ws` | GET | `flow_stream_ws` — WebSocket multiplexado |
| `/api/flow/{run_id}/replay` | GET | Dump JSON de todos los eventos del run |

### 4.3. La UI

`static/index.html` es un único archivo estático **sin build step**:

- **8 paneles**, uno por nodo (IntentClassifier, BugIntake, Research,
  Development, QA, Handoff, Close, Failure), con pills de estado
  (`idle / queued / running / passed / failed`).
- **"Start dev-loop run"** hace POST a `/api/flow/run`, recibe un `run_id`,
  y abre el WebSocket a `/api/flow/{run_id}/ws?view=both&replay=true`.
- Cada evento se añade bajo el panel de su nodo; el color de la pill sigue
  `dispatch.queued / started / completed / failed` y los eventos a nivel de
  flujo (`flow.bug_brief_validated` / `flow.pr_opened` / `flow.completed`).
- **"Reconnect"** reproduce el historial antes de retomar el tail en vivo
  (útil tras un corte de red).

### 4.4. Disparar un run por curl (sin UI)

El mismo endpoint se puede manejar desde la CLI:

```bash
curl -X POST http://localhost:8080/api/flow/run \
  -H 'Content-Type: application/json' \
  -d '{
    "kind": "enhancement",
    "summary": "Order webhook signature mismatch on retries",
    "affected_component": "etl/orders/webhook.yaml",
    "description": "Observado en prod 2026-04-28; solo falla el segundo retry. Ver OPS-4321.",
    "acceptance_criteria": [
      "ruff check .",
      "mypy --no-incremental"
    ],
    "log_group": "fluent-bit-cloudwatch",
    "time_window_minutes": 90,
    "existing_issue_key": "NAV-8241"
  }'
```

Omite `existing_issue_key` para auto-detectar duplicados o crear ticket nuevo.

### 4.5. Routing por `kind` (FEAT-132)

| Radio UI | JSON | Issuetype Jira | Path del flujo |
|---|---|---|---|
| Bug (default) | `"bug"` | Bug | `IntentClassifier → BugIntake → Research → …` |
| Enhancement | `"enhancement"` | Story | `IntentClassifier → Research → …` (salta BugIntake) |
| New Feature | `"new_feature"` | New Feature | `IntentClassifier → Research → …` (salta BugIntake) |

### 4.6. Sintaxis de los acceptance criteria

Cada criterio es **una línea** en el textarea (o un elemento del array JSON).
El parser lo clasifica por el primer token:

| Línea | Clasificado como | Comportamiento |
|---|---|---|
| `task etl/customers/sync.yaml` | `ShellCriterion` | QA corre el comando, exige exit code 0 |
| `ruff check .` | `ShellCriterion` | idem |
| `pytest tests/loaders/test_csv.py -v` | `ShellCriterion` | idem |
| `The customer count must equal 1500 after a sync` | `ManualCriterion` | solo texto — se adjunta al ticket; QA auto-pasa; revisor humano firma |

Heads de shell permitidos (configurable vía `ACCEPTANCE_CRITERION_ALLOWLIST`):
`task`, `flowtask`, `pytest`, `ruff`, `mypy`, `pylint`. Las líneas que no
empiezan por uno de esos se tratan como criterios manuales.

---

## 5. Variante programática (`quickstart.py`)

Mismo flujo real que el server, pero un solo run y sale:

```bash
source .venv/bin/activate
python examples/dev_loop/quickstart.py
```

Qué hace:

1. Construye un `ClaudeCodeDispatcher` con el semáforo global de
   `CLAUDE_CODE_MAX_CONCURRENT_DISPATCHES`.
2. Construye un `JiraToolkit` de cuenta de servicio + los toolkits de logs
   (CloudWatch + ES).
3. Llama a `build_dev_loop_flow(...)` (factory en `parrot/flows/dev_loop/flow.py`).
4. Corre el `BugBrief` de ejemplo (un `etl/customers/sync.yaml` roto a propósito)
   a través de `flow.run_flow(...)`.
5. Imprime las salidas finales por nodo.

Es la referencia canónica para embeber el dev-loop en tu propio servicio.

---

## 6. Layout de streams (referencia)

```
flow:{run_id}:flow                  ← BugIntake + DeploymentHandoff + eventos de flujo
flow:{run_id}:dispatch:research     ← cada evento de Claude Code del dispatch de Research
flow:{run_id}:dispatch:development  ← idem Development
flow:{run_id}:dispatch:qa           ← idem QA
```

El multiplexador (`parrot.flows.dev_loop.streaming.FlowStreamMultiplexer`) los
fusiona por timestamp, filtra por `?view=`, y emite envelopes planos que la UI
consume tal cual:

```json
{"source": "dispatch", "node_id": "qa",
 "event_kind": "dispatch.completed",
 "ts": 1714388261.42, "payload": {"output_model": "QAReport"}}
```

---

## 7. Troubleshooting

| Síntoma | Causa / arreglo |
|---|---|
| **UI atascada en "idle"** | Revisa logs del server; `IntentClassifierNode` lanza `ValueError` si un `ShellCriterion.command` usa un head fuera del allowlist |
| **`DispatchExecutionError: cwd outside WORKTREE_BASE_PATH`** | Pon `WORKTREE_BASE_PATH` al padre del worktree que devolvió `ResearchNode`, o deja el default `.claude/worktrees` y no sobrescribas `worktree_path` |
| **`gh: command not found`** | Instala + `gh auth login` antes de llegar a `DeploymentHandoffNode` |
| **`SDK timeout`** | Sube `ClaudeCodeDispatchProfile.timeout_seconds` (default 1800s) en los perfiles por nodo en `parrot/flows/dev_loop/nodes/*.py` |
| **`ImportError: Please install the 'jira' package`** | `uv pip install jira` (solo modo real) |

---

## 8. Resumen — qué ejecutar según lo que quieras

| Quiero… | Comando | Setup |
|---|---|---|
| Ver el flujo sin montar nada | `python examples/dev_loop/e2e_demo.py` | solo `uv sync` |
| Embeberlo en mi servicio | `python examples/dev_loop/quickstart.py` | modo real (§4.1) |
| Verlo en vivo con UI | `python examples/dev_loop/server.py` → `http://localhost:8080` | modo real (§4.1) |
