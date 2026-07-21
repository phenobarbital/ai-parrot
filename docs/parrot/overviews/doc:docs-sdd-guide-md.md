---
type: Wiki Overview
title: Guía de uso de los comandos `/sdd-*`
id: doc:docs-sdd-guide-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: SDD es nuestra forma de trabajar features con Claude Code. La regla
---

# Guía de uso de los comandos `/sdd-*`

> Guía práctica para developers de AI-Parrot. Explica cómo trabajamos con
> **Spec-Driven Development (SDD)** dentro de Claude Code: qué comandos
> existen, cuándo se usa cada uno y cómo encajan en el ciclo de una feature.
>
> Para la metodología completa y el contrato de los artefactos, ver
> [`WORKFLOW.md`](./WORKFLOW.md). Para la política de worktrees y el flow
> por tipos (`feature` / `hotfix`), ver `CLAUDE.md` en la raíz del repo.

---

## 1. Idea general

SDD es nuestra forma de trabajar features con Claude Code. La regla
fundamental es:

> **Las especificaciones son la única fuente de verdad (SSOT).**
> Primero se discute y diseña en documentos, después se decompone en
> tareas atómicas, y solo entonces se escribe código.

Esto nos da tres beneficios concretos:

1. **Reduce alucinaciones**: cada spec y cada tarea contienen un *Codebase
   Contract* con imports, firmas y entradas "Does NOT Exist" verificadas
   contra el código real.
2. **Permite paralelismo**: cada feature vive en su propio worktree y en
   su propio índice de tareas (`sdd/tasks/index/<feature>.json`), así
   varias features avanzan a la vez sin colisionar.
3. **Es auditable**: cada paso queda como commit en `dev` o en el branch
   de la feature, y opcionalmente sincronizado con un ticket de Jira.

---

## 2. El ciclo de vida de una feature

```
                                     ┌──────────────────┐
                                     │  /sdd-fromjira   │
                                     │  (opcional)      │
                                     └────────┬─────────┘
                                              ▼
       ┌──────────────────┐         ┌──────────────────┐
       │ /sdd-proposal    │   ó     │ /sdd-brainstorm  │
       │ (charla guiada)  │         │ (3 opciones +    │
       └────────┬─────────┘         │  recomendación)  │
                │                   └────────┬─────────┘
                ▼                            ▼
                       ┌──────────────────┐
                       │  /sdd-spec       │  ← spec aprobado en `dev`
                       └────────┬─────────┘
                                ▼
                       ┌──────────────────┐
                       │  /sdd-tojira     │  (opcional, exporta a Jira)
                       └────────┬─────────┘
                                ▼
                       ┌──────────────────┐
                       │  /sdd-task       │  ← crea TASK-* + worktree
                       └────────┬─────────┘
                                ▼
              cd .claude/worktrees/feat-<ID>-<slug>
                                │
                                ▼
       ┌──────────────────┐  loop  ┌──────────────────┐
       │  /sdd-start      │  ◄───  │  /sdd-next       │
       │  (implementa)    │        │  /sdd-status     │
       └────────┬─────────┘        └──────────────────┘
                │
                ▼
       ┌──────────────────┐
       │  /sdd-codereview │  (opcional, por tarea)
       └────────┬─────────┘
                ▼
       ┌──────────────────┐
       │  /sdd-done       │  ← merge feature → base, push, cleanup
       └──────────────────┘
```

Las flechas son lo importante: **cada comando consume el output del
anterior**. Si te saltas un paso, el siguiente no encontrará el artefacto
que necesita.

---

## 3. Tabla rápida de comandos

| Comando | Qué hace | Dónde se ejecuta | Output |
|---|---|---|---|
| `/sdd-proposal` | Charla guiada (Why/What) en lenguaje no técnico | `dev` | `sdd/proposals/<n>.proposal.md` |
| `/sdd-brainstorm` | 2+ rondas de Q&A + 3 opciones técnicas + recomendación | `dev` | `sdd/proposals/<n>.brainstorm.md` |
| `/sdd-fromjira` | Inicia un brainstorm desde un ticket Jira | `dev` | `sdd/proposals/<key>-<slug>.brainstorm.md` |
| `/sdd-spec` | Genera el spec formal con *Codebase Contract* | `dev` | `sdd/specs/<n>.spec.md` |
| `/sdd-tojira` | Sube el spec a Jira como Story (opcional subtasks) | `dev` | actualiza spec con `**Jira**: ...` |
| `/sdd-task` | Decompone el spec en `TASK-*` + crea worktree | `dev` (no en worktree) | `sdd/tasks/active/TASK-*.md` + `sdd/tasks/index/<n>.json` |
| `/sdd-status` | Tablero agregado de todas las features | cualquiera | print | 
| `/sdd-next` | Sugiere las siguientes tareas desbloqueadas | cualquiera | print |
| `/sdd-start` | Marca tarea `in-progress`, implementa, commitea, marca `done` | dentro del worktree | código + commits |
| `/sdd-codereview` | Revisión estructurada de una tarea completada | cualquiera | `sdd/reviews/TASK-*-review.md` |
| `/sdd-done` | Verifica, mergea feature → base, push, cleanup worktree | `dev` (no en worktree) | merge a `dev` (o snippet de PR si es hotfix) |

> **Tip de modelo**: `/sdd-status`, `/sdd-next` y `/sdd-done` están
> configurados para usar **Haiku** (son mecánicos). El resto usan
> Sonnet/Opus por defecto, porque requieren razonamiento.

---

## 4. Comandos en detalle

### 4.1. `/sdd-proposal` — Discusión inicial

Punto de entrada **suave** cuando todavía no tienes claro el alcance.
Charla en lenguaje no técnico (Why / What / Impact / Open Questions) y
opcionalmente al final genera el spec automáticamente.

```bash
/sdd-proposal multi-agent-handoff -- "queremos que un agente pueda
delegar una conversación a otro sin perder contexto"
```

Pregunta primero el **flow type** (`feature` vs `hotfix`) y el
`base_branch`. Lo guarda en el frontmatter del propuesto.

### 4.2. `/sdd-brainstorm` — Exploración estructurada

Punto de entrada **técnico**. Hace mínimo **dos rondas** de Q&A,
investiga el código existente, y produce **al menos 3 opciones** con
pros, contras y referencias a librerías y código del repo.

```bash
/sdd-brainstorm crew-result-storage -- "queremos persistir
los resultados de un AgentCrew en pgvector, redis, o disco"
```

Reglas que debes conocer:

- **No genera código de implementación**. Solo ideas, libs y referencias.
- Captura un **Code Context** verificado: cada clase/método citado se
  lee del archivo real con su path y línea.
- Marca las preguntas resueltas con `[x]` — `/sdd-spec` no las volverá a
  preguntar.

### 4.3. `/sdd-fromjira` — Bootstrap desde Jira

Si la feature ya existe como ticket de Jira, parte de ahí:

```bash
/sdd-fromjira NAV-8036
/sdd-fromjira NAV-8036 --complexity=fix     # Q&A mínimo
/sdd-fromjira NAV-8036 --skip-qa            # usa la descripción tal cual
```

Solo **lee** el ticket (nunca modifica Jira). Produce un brainstorm
estándar; a partir de ahí, sigue con `/sdd-spec`.

### 4.4. `/sdd-spec` — Especificación formal

Toma el brainstorm (o el proposal) y lo convierte en un spec formal con:

- Motivación, alcance y *Acceptance Criteria* concretos.
- **Codebase Contract** (§6): imports verificados, firmas exactas y
  sección "Does NOT Exist" — la mejor defensa contra alucinaciones.
- *Worktree Strategy* (per-spec o mixed).

```bash
/sdd-spec crew-result-storage
```

> Antes de scaffoldear, hace `git checkout <base_branch>` y
> `git pull --ff-only`. Si el working tree está dirty, aborta — no
> intenta hacer stash automático.

Cuando lo apruebes, marca `status: approved` en el spec.

### 4.5. `/sdd-tojira` — Exportar a Jira (opcional)

Sube el spec como Story al proyecto `NAV` (o el que indiques):

```bash
/sdd-tojira sdd/specs/crew-result-storage.spec.md
/sdd-tojira FEAT-147 --with-subtasks
/sdd-tojira FEAT-147 --ticket NAV-8036    # actualiza ticket existente
```

Usa **mcp-atlassian** si está disponible, con fallback a `curl`. Las
credenciales se cargan vía `navconfig` (`JIRA_INSTANCE`,
`JIRA_USERNAME`, `JIRA_API_TOKEN`).

### 4.6. `/sdd-task` — Decomposición en tareas

Decompone un spec **aprobado** en tareas atómicas (1–4h cada una) y
crea el worktree para esa feature:

```bash
/sdd-task sdd/specs/crew-result-storage.spec.md
```

Lo que hace:

1. Sincroniza el `base_branch` (checkout + pull --ff-only).
2. Crea `sdd/tasks/active/TASK-NNN-<slug>.md` por cada tarea.
3. Crea/actualiza el **índice por spec** en
   `sdd/tasks/index/<feature>.json` (un archivo por feature — sin
   colisiones entre features).
4. Commitea todo a `<base_branch>`.
5. Crea el worktree:
   `git worktree add -b feat-<ID>-<slug> .claude/worktrees/feat-<ID>-<slug> HEAD`

> **Importante**: `/sdd-task` se ejecuta desde el repo principal, **no**
> desde un worktree.

Cada tarea hereda un *Codebase Contract* específico de su scope, copiado
desde el §6 del spec y re-verificado contra el código actual.

### 4.7. `/sdd-status` — Tablero de tareas

Lectura agregada de todos los `sdd/tasks/index/*.json`:

```bash
/sdd-status                        # todas las features
/sdd-status crew-result-storage    # solo una
```

Agrupa por `in-progress` → `pending` → `done`, marca bloqueos y muestra
*orphans* (tareas sin atribución que rescató la migración FEAT-145).

### 4.8. `/sdd-next` — Siguiente tarea desbloqueada

Sugiere qué hacer ahora:

```bash
/sdd-next
```

Lo ordena por prioridad (high → medium → low) y luego por effort
(S → M → L → XL). Para cada tarea propone:

- Si la feature **ya tiene worktree activo**: el comando exacto
  `/sdd-start TASK-<NNN>` para correr **dentro** de ese worktree.
- Si no lo tiene: el `git worktree add` correspondiente.
- Si la tarea es `parallel: true`: opción de worktree propio.

### 4.9. `/sdd-start` — Implementar una tarea

El caballo de batalla. Acepta el ID o el slug:

```bash
cd .claude/worktrees/feat-147-crew-result-storage
/sdd-start TASK-1019
# ó
/sdd-start crew-result-storage-tests
```

Lo que hace, en orden:

1. Resuelve la tarea en los `sdd/tasks/index/*.json`.
2. Valida que `status == "pending"` y que todas sus `depends_on` están
   `done`. Si está bloqueada, **se detiene**.
3. Marca la tarea `in-progress`, hace commit del índice.
4. **Verifica el Codebase Contract**: hace `grep`/`read` de cada import
   y firma listados. Si algo cambió, actualiza el contrato del task
   *antes* de empezar a codear.
5. **Implementa**: crea/modifica los archivos del scope, corre lint y
   los tests del Acceptance Criteria.
6. Commitea con `feat(<feature-slug>): TASK-<NNN> — <title>`.
7. Mueve el archivo a `sdd/tasks/completed/`, actualiza el índice y
   commitea como `sdd: complete TASK-<NNN>`.

> Solo se detiene si una dependencia está rota, el spec es ambiguo, o
> tests fallan y no puede determinar el fix. Si no, sigue hasta `done`.

### 4.10. `/sdd-codereview` — Revisión por tarea (opcional)

Lee el archivo en `sdd/tasks/completed/` y todos los archivos que tocó,
y aplica una revisión estructurada (correctness, DRY/SOLID, performance,
security, docstrings, tests).

```bash
/sdd-codereview TASK-1019
/sdd-codereview crew-result-storage-tests
```

Output: un report markdown con verdict (`✅ Approved` / `⚠ Approved with
notes` / `❌ Needs changes`), tabla de Acceptance Criteria y findings
clasificados por severidad. Opcionalmente guarda en
`sdd/reviews/TASK-<NNN>-review.md`.

### 4.11. `/sdd-done` — Cerrar la feature

Cierra una feature desde el repo principal (no desde el worktree):

```bash
git checkout dev
/sdd-done FEAT-147
/sdd-done FEAT-147 --dry-run         # ver qué pasaría sin tocar nada
/sdd-done FEAT-147 --force           # cerrar aún con tareas con issues
/sdd-done FEAT-147 --resolve-jira    # transicionar el ticket a Done
```

Pasos:

1. Verifica que estás en `<base_branch>` (sale del worktree si hace
   falta).
2. Junta evidencia desde el worktree: commits que mencionan la tarea,
   archivos esperados existen, tests pasan.
3. Imprime el **Verification Report** (✅ / ⚠ / ❌ por tarea).
4. Mueve los `TASK-*.md` a `completed/`, actualiza el índice.
5. **Si es feature**: hace `git merge --no-edit feat-<ID>-<slug>` en
   `<base_branch>` y `git push origin <base_branch>`.
6. **Si es hotfix**: NO mergea a `main`. Imprime el snippet
   `gh pr create --base main` para que abras la PR a mano. Tras el
   merge, vuelves a correr con `--sync-dev` para llevar el cambio a
   `dev`.
7. Si pides `--resolve-jira`, transiciona el ticket (y subtasks) a
   "Done" / "Resolved".
8. Limpia el worktree: `git worktree remove ...`.

> **Regla no negociable**: `/sdd-done` **nunca** pushea a `main` ni abre
> una PR contra `main`, en ningún flag. Los hotfixes se merge a `main`
> solo vía PR manual.

---

## 5. Ejemplos completos

### 5.1. Feature nueva, idea poco madura

```bash
# 1. Charla guiada
/sdd-proposal agent-tracing -- "necesitamos trazas distribuidas
   en los AgentCrew para debugging"

# 2. Generar spec desde el proposal
/sdd-spec agent-tracing

# (Revisar el spec, marcar status: approved)

# 3. Decomponer y crear worktree
/sdd-task sdd/specs/agent-tracing.spec.md

# 4. Trabajar dentro del worktree
cd .claude/worktrees/feat-150-agent-tracing
/sdd-start TASK-001
/sdd-start TASK-002
# ...
/sdd-done FEAT-150
# (volver al repo principal)
```

### 5.2. Feature técnica con varias opciones que evaluar

```bash
# Brainstorm con 3 opciones
/sdd-brainstorm batch-embedding-pipeline -- "embeddings
   en batch nocturno: ¿celery, dramatiq o asyncio puro?"

# Convertir a spec (carry-forward de Code Context y opciones)
/sdd-spec batch-embedding-pipeline

/sdd-task sdd/specs/batch-embedding-pipeline.spec.md
# ... resto igual que arriba
```

### 5.3. Bug que viene desde Jira

```bash
/sdd-fromjira NAV-8036
# (responde el Q&A breve)
/sdd-spec ...
/sdd-tojira sdd/specs/<slug>.spec.md --ticket NAV-8036
/sdd-task sdd/specs/<slug>.spec.md

cd .claude/worktrees/feat-NNN-<slug>
/sdd-start ...
# Al terminar:
/sdd-done FEAT-NNN --resolve-jira
```

### 5.4. Hotfix urgente sobre `main`

```bash
# El brainstorm/proposal debe declarar type: hotfix, base_branch: main
/sdd-brainstorm fix-pgvector-deadlock
# (en Round 0 dices: hotfix → base_branch: main)

/sdd-spec fix-pgvector-deadlock
/sdd-task sdd/specs/fix-pgvector-deadlock.spec.md

cd .claude/worktrees/feat-NNN-fix-pgvector-deadlock
/sdd-start TASK-...

# Cierre del hotfix — NO mergea a main
git checkout main
/sdd-done FEAT-NNN
# Imprime el snippet gh pr create --base main → la abres tú

# Tras mergear la PR a main:
/sdd-done FEAT-NNN --sync-dev
# Esto propaga el hotfix a dev automáticamente
```

---

## 6. Reglas de oro (no las olvides)

1. **Nunca** uses `claude --worktree`. Siempre crea el worktree a mano
   desde la branch correcta (lo hace `/sdd-task` por ti).
2. **No** ejecutes `/sdd-task` ni `/sdd-done` dentro de un worktree —
   ambos viven en el repo principal sobre `<base_branch>`.
3. Cada comando que crea archivos **commitea solo esos archivos**. Si
   ves `git add .` o `git add -A` en una sesión SDD, es un bug — los
   comandos hacen `git reset HEAD` primero y stagean por nombre.
4. **El spec es la SSOT**. Si durante la implementación descubres que
   el spec está mal, actualiza el spec antes de seguir codeando — no
   improvises en el código.
5. **Codebase Contract no es decorativo**: si una tarea referencia un
   import o una firma, ese ítem fue verificado contra el código real.
   Si lo cambias, actualiza el contrato.
6. **Una tarea, un commit lógico**. `/sdd-start` lo hace solo.
7. **Hotfixes nunca se mergean automáticamente a `main`**. Solo PR
   manual. `/sdd-done` te recuerda esto en cada flag.

---

## 7. Estructura de archivos

```
sdd/
├── proposals/                       # brainstorms y proposals
│   ├── <feature>.brainstorm.md
│   └── <feature>.proposal.md
├── specs/                           # specs aprobados (SSOT)
│   └── <feature>.spec.md
├── tasks/
│   ├── active/TASK-NNN-<slug>.md    # tareas en pending / in-progress
│   ├── completed/TASK-NNN-<slug>.md # tareas done (con Completion Note)
│   └── index/                       # índice por spec (FEAT-145)
│       ├── <feature>.json           # un archivo por feature
│       └── _orphans.json            # rescatadas por la migración
├── reviews/                         # output de /sdd-codereview
├── templates/                       # plantillas (no editar a la ligera)
└── WORKFLOW.md                      # contrato y schemas

.claude/
├── commands/                        # implementación de los slash commands
│   └── sdd-*.md
├── agents/
│   ├── sdd-worker.md                # agente autónomo de tareas
│   ├── sdd-research.md
│   └── sdd-qa.md
└── worktrees/                       # worktrees efímeros (ignorado en git)
    └── feat-<ID>-<slug>/
```

---

## 8. Modo autónomo: el agente `sdd-worker`

Si quieres dejar a Claude implementando una feature **completa** sin
intervención, lanza `sdd-worker` dentro del worktree:

```bash
cd .claude/worktrees/feat-150-agent-tracing
claude --agent sdd-worker --model sonnet --verbose

# En background:
tmux new -s feat-150 \
  "claude --agent sdd-worker --model sonnet --verbose"
# Ctrl+B, D para detach; tmux attach -t feat-150 para volver
```

El agente ejecuta todas las tareas del feature en orden de dependencias,
commitea por tarea y respeta exactamente el alcance del spec (no
rediseña).

---

## 9. Cuándo NO usar SDD

No vale la pena el ceremonial cuando:

- Es un cambio puramente de docs.
- Es un fix de un solo commit (un typo, un version bump, etc.).
- Es exploración pura (`/sdd-brainstorm` ya cubre el "no implementes
  todavía", pero si no hay intención de implementar, ni eso hace falta).
- Una feature tiene una sola tarea — un worktree añade overhead sin
  beneficio. Trabaja en un branch normal.

Para todo lo demás (features con varios módulos, refactors con riesgo,
hotfixes que requieren validación, integraciones nuevas), sigue el
ciclo SDD completo.

---

## 10. Referencias

- Metodología SDD completa: [`WORKFLOW.md`](./WORKFLOW.md)
- Política de worktrees y flow types (FEAT-145): `CLAUDE.md`
- Templates: `sdd/templates/{brainstorm,proposal,spec,task}.md`
- Implementación de los comandos: `.claude/commands/sdd-*.md`
- Agentes asociados: `.claude/agents/sdd-{worker,research,qa}.md`
