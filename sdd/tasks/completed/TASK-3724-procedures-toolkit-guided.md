# TASK-3724: ProceduresToolkit proc_* tools + guided mode (M11)

**Feature**: FEAT-601 — Procedure Graph (training agent)
**Spec**: `sdd/specs/training-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3710, TASK-3723
**Assigned-to**: unassigned

---

## Context

Spec §3 **Module 11** (`toolkit.py`, `guided.py`), goals G5/G6/G10/G11, resolved questions Q5 (task memory owns guided state), Q6 (tips visible immediately, curator-retirable), Q7 (`proc_set_equipment_serial`), Q8 (`proc_find_part`), Q10 (synthetic evidence ref). `ProceduresToolkit(TaskMemoryToolsMixin, AbstractToolkit)` exposes one action per tool with `tool_prefix="proc"`; every tool runs `_gate()` (the shared `ProcedureRetrieval.authorize`, TASK-3720) before any read or write; writes are confirming tools. Guided mode ("guíame") composes the existing task-memory commands; completion records a `WORKFLOW_PATTERN` episode.

Covers spec §4 tests `test_toolkit_tool_names_and_confirming`, `test_guided_roundtrip`, `test_completion_records_workflow_pattern_episode`, `test_find_part_traversal`, `test_set_equipment_serial_validates`; AC9, AC15, AC20, AC21.

---

## Scope

- Create `parrot_tools/procedures/toolkit.py` with `ProceduresToolkit` and the tools listed in the §3 M11 skeleton: `find_procedure`, `get_steps`, `get_step`, `prerequisites`, `media_for_step`, `tips_for_step`, `related_equipment`, `find_part`, `set_equipment_serial`, `add_tip`, `retire_tip`, `verification_queue`, `verify_procedure`, `start_guided`, `next_step`, `mark_done`, `resume_guided`.
- Hide the raw inherited task-memory commands (`TASK_TOOL_METHODS`) from the LLM (`exclude_tools`) — guided tools call them internally, so the model cannot bypass the procedure plan.
- Create `parrot_tools/procedures/guided.py` with `task_steps_for` and `record_completion`.
- Write `test_toolkit.py` and `test_guided.py`.

**NOT in scope**: `ProceduresAgent` / transport adapter (TASK-3725); the answer pipeline itself (TASK-3723 — tools that return procedure content call `service.answer` or the retrieval + assembly path, they do not re-implement it); tip graph writes (TASK-3710 — call `add_tip`/`retire_tip`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/procedures/toolkit.py` | CREATE | `ProceduresToolkit` (proc_* tools) |
| `packages/ai-parrot-tools/src/parrot_tools/procedures/guided.py` | CREATE | Task-step mapping + completion episode |
| `packages/ai-parrot-tools/tests/procedures/test_toolkit.py` | CREATE | Tool names, confirming set, gate, find_part, serial |
| `packages/ai-parrot-tools/tests/procedures/test_guided.py` | CREATE | Guided round trip + episode |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from __future__ import annotations
import logging
from typing import Any, Optional
from parrot.tools.toolkit import AbstractToolkit                                              # verified: tools/toolkit.py:203
from parrot.tools.working_memory.task_memory.tools import TASK_TOOL_METHODS, TaskMemoryToolsMixin   # verified: task_memory/tools.py:91, 368
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace     # verified: memory/episodic/models.py:20, 29, 214
# created by TASK-3699 (packages/ai-parrot/src/parrot/knowledge/manuals/models.py)
from parrot.knowledge.manuals.models import normalize_serial
# created by TASK-3710 (packages/ai-parrot/src/parrot/knowledge/manuals/tips.py)
from parrot.knowledge.manuals.tips import add_tip, retire_tip
# created by TASK-3720 / 3721 / 3723
from parrot_tools.procedures.retrieval import AuthorizationDenied, PatternPlan, RequestContext
from parrot_tools.procedures.assembly import AssembledProcedure
from parrot_tools.procedures.service import ProceduresAnswerService
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/toolkit.py
class AbstractToolkit(ABC):                       # line 203
    return_direct: bool = False                   # line 232
    exclude_tools: tuple[str, ...] = ()           # line 240
    tool_prefix: str | None = None                # line 254
    prefix_separator: str = "_"                   # line 257
    confirming_tools: frozenset = frozenset()     # line 272 — UNPREFIXED method names
    def get_tools(...)                            # line 494 — public async methods become tools

# packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py
TASK_TOOL_METHODS: tuple = ("begin_task", "update_plan", "update_step", "record_decision", "set_resume_hint",
                            "recall_task", "list_task_events", "list_task_artifacts", "select_task", "update_task")  # line 91-102
class TaskMemoryToolsMixin:                       # line 368 — requires self._task_memory (TaskMemory, line 105)
    async def begin_task(self, goal, constraints=None, steps=None, plan_complete=False) -> dict   # line 398
        # step dict keys: label, title, description?, required?, depends_on_labels? (437-445)
        # returns {"status","association_durable","task_id","revision","steps":[{"step_id","title"}],"state"} (458-465)
        # NOTE: returned step_id is the RUNTIME task-step id, NOT the label
    async def update_step(self, task_id, step_id, expected_revision: int, status: str, evidence_refs=None, note=None, reason=None)  # line 529
    async def set_resume_hint(self, task_id: str, next_action: str, step_id: Optional[str] = None) -> dict  # line 664
    async def select_task(self, task_id: str) -> dict                                                        # line 687
    async def recall_task(self, task_id=None, max_tokens=2500, recent_calls_limit=8) -> dict                 # line 772
# Composition precedent: packages/ai-parrot/src/parrot/tools/working_memory/tool.py:47 (class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit))
#   and :141-155 — `self._task_memory = task_memory`; when None, `self.exclude_tools = (*type(self).exclude_tools, *TASK_TOOL_METHODS)` on the INSTANCE

# packages/ai-parrot/src/parrot/tools/working_memory/task_memory/models.py
class CompletionPolicy(_TaskModel):   # line 683 — default mode AGENT_ASSERTED: needs ≥1 evidence ref AND a note (require_note=True, line 702)
class TaskScope(_TaskModel):          # line 571 — chatbot_id, user_id, session_id (trusted runtime identity)

# packages/ai-parrot/src/parrot/memory/episodic/store.py
class EpisodicMemoryStore:
    async def record_episode(self, namespace: MemoryNamespace, situation: str, action_taken: str, outcome: EpisodeOutcome,
                             outcome_details=None, error_type=None, error_message=None,
                             category: EpisodeCategory = EpisodeCategory.TOOL_EXECUTION, importance=None,
                             related_tools=None, related_entities=None, metadata=None, generate_reflection=True,
                             ttl_days=None) -> EpisodicMemory    # line 106-122
# packages/ai-parrot/src/parrot/memory/episodic/models.py:36 — EpisodeCategory.WORKFLOW_PATTERN = "workflow_pattern"

# template (do not import): packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py
#   class ContractsToolkit(AbstractToolkit): line 39; confirming_tools frozenset line 55; exclude_tools line 57; _gate line 84

# created by TASK-3710 — add_tip(graph_store, ctx, *, step_id, text, author_employee_id, source_revision, now=...) -> Tip;
#                        retire_tip(graph_store, ctx, *, tip_id, by) -> None
```

### Does NOT Exist
- ~~`EpisodeCategory.PROCEDURE_COMPLETED`~~ — use `WORKFLOW_PATTERN` + metadata (F022); do NOT modify `EpisodeCategory` (AC15).
- ~~A task-memory change for guided mode~~ — Q10: `evidence_refs=[f"procedure:{procedure_id}@{revision}"]` + a note satisfies the default policy.
- ~~`author_employee_id` as a tool argument~~ — always `request_context.employee_id` (trusted); forged attribution is an AC9 denial.
- ~~`begin_task` returning labels as step ids~~ — it returns runtime ids; keep a label→runtime map.
- ~~A `proc_begin_task` / `proc_update_step` LLM tool~~ — hidden via `exclude_tools`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/toolkit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/src/parrot_tools/procedures/guided.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_toolkit.py", "action": "CREATE"},
    {"path": "packages/ai-parrot-tools/tests/procedures/test_guided.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/tools/toolkit.py#AbstractToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py#TaskMemoryToolsMixin",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py#TaskMemoryToolsMixin.begin_task",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py#TaskMemoryToolsMixin.update_step",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py#TaskMemoryToolsMixin.select_task",
    "sym:packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py#TaskMemoryToolsMixin.recall_task",
    "sym:packages/ai-parrot/src/parrot/memory/episodic/store.py#EpisodicMemoryStore.record_episode"
  ]
}
```

---

## Implementation Notes

### Decisions fixed here
- `confirming_tools = frozenset({"add_tip", "verify_procedure", "retire_tip"})` (unprefixed, frozenset like `ContractsToolkit`).
- `exclude_tools = ("get_tools", "get_tools_sync", *TASK_TOOL_METHODS)` at class level — guided wrappers call the mixin methods directly; when `task_memory is None`, also hide the guided tools on the instance (`start_guided`, `next_step`, `mark_done`, `resume_guided`).
- Curator tools (`retire_tip`, `verification_queue`, `verify_procedure`) gate with `curator_only=True`.
- `mark_done(task_id, step_id, note=None)`: `step_id` is the **procedure** step id (the `begin_task` label). Map it to the runtime task-step id via the `steps` list `begin_task` returned (cache per `task_id` in `self._guided[task_id] = {"procedure_id", "manual_id", "revision", "labels": {label: runtime_id}}`), and on a cache miss via `recall_task`. Always pass `expected_revision`, `status="completed"`, `evidence_refs=[f"procedure:{procedure_id}@{revision}"]`, `note=note or "completed by technician"` — the default `CompletionPolicy` requires both an evidence ref **and** a note.
- When the last required step completes, call `guided.record_completion(...)` once.
- `set_equipment_serial(serial)`: validate with `normalize_serial(serial, format=f)` against the formats present in the resolved manual's `serial_ranges`; store with `self.request_context = self.request_context.model_copy(update={"equipment_serial": serial})` — never persisted elsewhere. No formats ⇒ accept as-is.
- `find_part(media_id, callout)` runs the `part_for_callout` pattern via `service.retrieval.execute_graph(PatternPlan(pattern="part_for_callout", bind_vars={"media_id": ..., "callout": ...}), ctx)`.
- Every tool returns a bounded JSON-serializable `dict`; `AuthorizationDenied` is caught and returned as `{"status": "denied", "reason": ...}` (tools must not raise into the ReAct loop).
- Docstrings are LLM-facing tool descriptions — write them for the model (what it does, args, returns).

### Key Constraints (all FEAT-601 tasks)
- Tests inside a worktree: `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-tools/src:packages/ai-parrot-integrations/src pytest <file> -q` — the shared `.venv` is editable-installed against the main checkout, so a bare `pytest` imports the wrong branch.
- Ontology symbols are imported from submodules only (`parrot.knowledge.ontology.schema/graph_store/tenant/parser/authorization`), never the package root (AC17, FEAT-540 lazy root).
- No new third-party dependency (AC18). `ruff check` (TID251 bans `requests`/`httpx`/langchain) and `black --check` (line-length 120) must pass.
- Google-style docstrings and strict type hints everywhere; Pydantic v2 models for data; `logger = logging.getLogger(__name__)` / `self.logger`, never `print`.
- async all the way down — no blocking I/O inside `async def`.

### References in Codebase
- `packages/ai-parrot-tools/src/parrot_tools/contracts/toolkit.py` — gate + confirming pattern
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py:47-155` — mixin composition
- `packages/ai-parrot/tests/tools/working_memory/` — task-memory test fixtures (look for an in-memory `TaskMemory` builder before writing one)

---

## Implementation Blueprint

### Steps (in order)
1. Write `guided.py` first — *because* the toolkit's guided tools import both helpers.
2. Write the toolkit class attributes + `__init__` + `_gate` (block 1) — *because* the tool-name/confirming test depends only on them.
3. Write read tools (block 2), then write/curator tools (block 3), then guided tools (block 4).
4. Write tests; for guided round-trip reuse an existing in-memory `TaskMemory` fixture if one exists under `packages/ai-parrot/tests/tools/working_memory/` (verify), else build one from its public constructor (`TaskMemory(store, artifacts, scope, association=TaskAssociationStore(...))`).

### `packages/ai-parrot-tools/src/parrot_tools/procedures/guided.py` (CREATE)
```python
"""Guided-mode helpers: procedure → task-memory plan, completion episode (FEAT-601 M11, Q5/Q10)."""
from __future__ import annotations

import logging
from typing import Any

from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome
from parrot_tools.procedures.assembly import AssembledProcedure

logger = logging.getLogger(__name__)


def task_steps_for(procedure: AssembledProcedure) -> list[dict[str, Any]]:
    """Map ordered steps to ``begin_task`` step dicts (label = procedure step id, linear dependencies)."""
    steps: list[dict[str, Any]] = []
    previous: str | None = None
    for view in procedure.steps:
        # FILL IN: read the step id/order/text attribute names from StepView (TASK-3700)
        label = view.step_id
        steps.append({
            "label": label,
            "title": f"{view.order}. {view.text[:80]}",
            "description": view.text,
            "required": True,
            "depends_on_labels": [previous] if previous else [],
        })
        previous = label
    return steps


async def record_completion(episodic: Any, *, namespace: Any, procedure: AssembledProcedure, user_id: str) -> None:
    """Record a WORKFLOW_PATTERN episode for a completed guided procedure (no EpisodeCategory change)."""
    if episodic is None:
        return
    await episodic.record_episode(
        namespace,
        situation=f"guided procedure {procedure.procedure.title}",
        action_taken="completed every required step",
        outcome=EpisodeOutcome.SUCCESS,
        category=EpisodeCategory.WORKFLOW_PATTERN,
        metadata={
            "procedure_id": procedure.procedure.procedure_id,
            "manual_id": procedure.revision.card_snapshot.get("manual_id"),  # FILL IN: take manual_id from ProcedureView if it carries one — bounded by TASK-3700 fields
            "revision": procedure.revision.revision,
            "user_id": user_id,
        },
    )
```
**Why**: labels = procedure step ids make the task plan traceable to the graph; linear `depends_on_labels` enforces order (G1).

### `packages/ai-parrot-tools/src/parrot_tools/procedures/toolkit.py` (CREATE) — block 1/4
```python
"""Procedures toolkit — one action per tool, every call gated (FEAT-601 M11)."""
from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.knowledge.manuals.models import normalize_serial
from parrot.knowledge.manuals.tips import add_tip as _add_tip
from parrot.knowledge.manuals.tips import retire_tip as _retire_tip
from parrot.tools.toolkit import AbstractToolkit
from parrot.tools.working_memory.task_memory.tools import TASK_TOOL_METHODS, TaskMemoryToolsMixin
from parrot_tools.procedures.guided import record_completion, task_steps_for
from parrot_tools.procedures.retrieval import AuthorizationDenied, PatternPlan, RequestContext
from parrot_tools.procedures.service import ProceduresAnswerService

logger = logging.getLogger(__name__)
MAX_ROWS = 50
GUIDED_TOOLS: tuple[str, ...] = ("start_guided", "next_step", "mark_done", "resume_guided")


class ProceduresToolkit(TaskMemoryToolsMixin, AbstractToolkit):
    """Read assembly procedures, guide a technician step by step, and curate tips.

    Args:
        service: The shared release service (TASK-3723).
        request_context: The TRUSTED request context — never derived from tool arguments.
        library: Optional ``ManualLibrary`` for curator verification.
        task_memory: Optional ``TaskMemory``; guided tools are hidden without it.
        episodic: Optional ``EpisodicMemoryStore`` for completion episodes.
    """

    name: str = "procedures"
    tool_prefix: str = "proc"
    confirming_tools: frozenset = frozenset({"add_tip", "verify_procedure", "retire_tip"})
    exclude_tools: tuple[str, ...] = ("get_tools", "get_tools_sync", *TASK_TOOL_METHODS)

    def __init__(self, *, service: ProceduresAnswerService, request_context: RequestContext, library: Any | None = None,
                 task_memory: Any | None = None, episodic: Any | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.service = service
        self.request_context = request_context
        self.library = library
        self._task_memory = task_memory
        self.episodic = episodic
        self._guided: dict[str, dict[str, Any]] = {}
        if task_memory is None:
            self.exclude_tools = (*type(self).exclude_tools, *GUIDED_TOOLS)

    def _gate(self, *, pattern: Optional[str] = None, curator_only: bool = False) -> None:
        """Run the shared entry gate for this toolkit's trusted context."""
        self.service.retrieval.authorize(self.request_context, pattern=pattern, curator_only=curator_only)

    @staticmethod
    def _denied(exc: AuthorizationDenied) -> dict[str, Any]:
        return {"status": "denied", "reason": exc.reason}
```

### `toolkit.py` — block 2/4: read tools
```python
    async def find_procedure(self, query: str, equipment: Optional[str] = None) -> dict:
        """Find procedures for a piece of equipment. Returns candidates or a clarification — never guesses."""
        try:
            self._gate(pattern="procedures_for_equipment")
            # FILL IN: retrieval.resolve_equipment / resolve_procedure; Clarification ⇒ {"status":"clarification",...}
            return {}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def get_steps(self, procedure_id: str) -> dict:
        """Return the verified, ordered steps of a procedure (with figures, hazards and citations)."""
        # FILL IN: gate; service.answer over a procedure_steps plan for procedure_id; return the released answer
        #          model_dump (incomplete answers are returned as such) — bounded by AC7/AC8
        return {}

    async def get_step(self, procedure_id: str, order: int) -> dict:
        """Return one step with its prerequisites, hazards and media."""
        return {}  # FILL IN: as get_steps with step_detail/step_order

    async def prerequisites(self, procedure_id: str) -> dict:
        """Everything to have ready before starting: parts, tools, hazards."""
        return {}  # FILL IN: procedure_prerequisites

    async def media_for_step(self, step_id: str) -> dict:
        """Figures and video segments illustrating a step (presigned per call)."""
        return {}  # FILL IN: gate; step_detail rows → MediaView; presign via service (never store URLs)

    async def tips_for_step(self, step_id: str) -> dict:
        """Active technician tips attached to a step."""
        return {}  # FILL IN: tips_for_procedure rows filtered to step_id; exclude orphaned/inactive (AC6)

    async def related_equipment(self, equipment_id: str) -> dict:
        """Equipment sharing a module with this one."""
        return {}  # FILL IN: equipment_sharing_module

    async def find_part(self, media_id: str, callout: str) -> dict:
        """Which part is callout N in an exploded view (e.g. "which one is part 7?")."""
        try:
            self._gate(pattern="part_for_callout")
            plan = PatternPlan(pattern="part_for_callout", bind_vars={"media_id": media_id, "callout": callout})
            rows = await self.service.retrieval.execute_graph(plan, self.request_context)
            # FILL IN: no row ⇒ {"status":"not_found"}; else part_number/name/confidence — bounded by AC21
            return {"status": "ok", "parts": rows[:MAX_ROWS]}
        except AuthorizationDenied as exc:
            return self._denied(exc)
```

### `toolkit.py` — block 3/4: serial, tips, curator
```python
    async def set_equipment_serial(self, serial: str) -> dict:
        """Record the serial number of the unit being worked on (asked once per session)."""
        try:
            self._gate()
            # FILL IN: collect formats from the resolved manual's serial_ranges; validate with
            #          normalize_serial(serial, format=f) for at least one format (ValueError on all ⇒ invalid);
            #          no formats ⇒ accept — bounded by Q7 / test_set_equipment_serial_validates
            self.request_context = self.request_context.model_copy(update={"equipment_serial": serial})
            return {"status": "ok", "equipment_serial": serial}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def add_tip(self, step_id: str, text: str) -> dict:
        """Attach a field tip to a step. Author is the authenticated technician."""
        try:
            self._gate(pattern="tips_for_procedure")
            if not self.request_context.employee_id:
                raise AuthorizationDenied("tips require an authenticated employee identity")
            # FILL IN: await _add_tip(graph_store, ctx, step_id=..., text=..., author_employee_id=
            #          self.request_context.employee_id, source_revision=<current revision>) — bounded by AC9 (no forged author)
            return {}
        except AuthorizationDenied as exc:
            return self._denied(exc)

    async def retire_tip(self, tip_id: str) -> dict:
        """Retire a tip (curators only)."""
        return {}  # FILL IN: _gate(curator_only=True); await _retire_tip(..., by=self.request_context.user_id)

    async def verification_queue(self, limit: int = 20) -> dict:
        """Procedures and figures waiting for curator review (curators only)."""
        return {}  # FILL IN: _gate(curator_only=True); catalog.verification_queue(limit=min(limit, MAX_ROWS))

    async def verify_procedure(self, procedure_id: str) -> dict:
        """Mark a procedure as verified (curators only)."""
        return {}  # FILL IN: _gate(curator_only=True); library.verify_procedure(manual_id, procedure_id, user=...)
```

### `toolkit.py` — block 4/4: guided mode
```python
    async def start_guided(self, procedure_id: str) -> dict:
        """Start guiding the technician through a procedure, one step at a time."""
        # FILL IN: gate; assemble via the service path; blocked/incomplete ⇒ return it, no task; else
        #          res = await self.begin_task(goal=<title>, steps=task_steps_for(assembled), plan_complete=True);
        #          cache labels→runtime ids from res["steps"] (same order) in self._guided[res["task_id"]]
        return {}

    async def next_step(self, task_id: str) -> dict:
        """Return the next pending step with its figures and warnings."""
        return {}  # FILL IN: recall_task(task_id) → first pending step → get_step view; set_resume_hint

    async def mark_done(self, task_id: str, step_id: str, note: Optional[str] = None) -> dict:
        """Mark the current step done and move on."""
        # FILL IN: map procedure step_id → runtime id; read revision via recall_task; update_step(task_id, runtime_id,
        #          expected_revision=rev, status="completed", evidence_refs=[f"procedure:{pid}@{revision}"],
        #          note=note or "completed by technician"); last required step ⇒ record_completion(...) once —
        #          bounded by Q10 / AC15
        return {}

    async def resume_guided(self) -> dict:
        """Resume where the technician left off ("¿dónde me quedé?"), even in a new session."""
        return {}  # FILL IN: durable association (TaskAssociationStore via TaskMemory) → select_task → next_step
```
**Why this shape**: the mixin's raw commands are excluded from the tool surface but remain callable as `self.begin_task(...)`; every read/write passes `_gate`.

### Test files (CREATE)
`test_toolkit.py` and `test_guided.py` — start from the Test Specification below.

### FILL IN checklist
- [ ] `guided.task_steps_for` / `record_completion` — StepView/ProcedureView field names (TASK-3700)
- [ ] read tools — service/retrieval wiring; bounded by AC7/AC8
- [ ] `find_part` — result projection; AC21
- [ ] `set_equipment_serial` — format validation; Q7
- [ ] `add_tip` / `retire_tip` / curator tools — AC9
- [ ] guided tools — label map, expected_revision, evidence ref + note, single completion episode; AC15

---

## Acceptance Criteria

- [ ] Every generated tool name starts with `proc_`; `proc_begin_task`/`proc_update_step`… are absent; `confirming_tools == {"add_tip","verify_procedure","retire_tip"}`.
- [ ] A context without a read role gets `{"status": "denied"}` from every tool; curator tools deny a technician (AC9).
- [ ] `add_tip` author is always `request_context.employee_id`.
- [ ] Guided round trip: `start_guided` → `next_step` → `mark_done` (with `expected_revision`, evidence ref, note) → `resume_guided` in a new session selects the same task (AC15).
- [ ] Completing the last step records exactly one `WORKFLOW_PATTERN` episode with `procedure_id`/`manual_id`/`revision` metadata; `EpisodeCategory` unchanged.
- [ ] `proc_find_part` returns the part for a callout label (AC21); `proc_set_equipment_serial` validates and stores only on the context (AC20).

---

## Validation Commands

- `pytest packages/ai-parrot-tools/tests/procedures/test_toolkit.py -q`
- `pytest packages/ai-parrot-tools/tests/procedures/test_guided.py -q`

---

## Test Specification

```python
# packages/ai-parrot-tools/tests/procedures/test_toolkit.py
from parrot_tools.procedures.toolkit import ProceduresToolkit

from ._doubles import make_context


def test_toolkit_tool_names_and_confirming():
    """Names proc_*; confirming set; _gate denies without role."""
    # FILL IN: toolkit over a stub service; names = {t.name for t in toolkit.get_tools()};
    #          assert all(n.startswith("proc_")) and "proc_begin_task" not in names
    ...


async def test_tools_deny_without_role():
    # FILL IN: make_context(roles=()) ⇒ every read tool returns {"status": "denied", ...}
    ...


async def test_find_part_traversal():
    """proc_find_part returns the Part for a callout label via part_for_callout."""
    ...


async def test_set_equipment_serial_validates():
    """Serial validated against the manual's formats; stored on the trusted context only."""
    ...


# packages/ai-parrot-tools/tests/procedures/test_guided.py
async def test_guided_roundtrip():
    """start_guided → next_step → mark_done (expected_revision) → resume_guided across a new session."""
    ...


async def test_completion_records_workflow_pattern_episode():
    """record_episode called with WORKFLOW_PATTERN and procedure metadata."""
    # FILL IN: fake episodic with an AsyncMock record_episode; complete all steps; assert one call with
    #          category=EpisodeCategory.WORKFLOW_PATTERN and metadata keys procedure_id/manual_id/revision
    ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/training-agent.json` → `"in-progress"` with your session ID
5. **Implement** — start from the Implementation Blueprint blocks, complete every
   `# FILL IN:` marker, and never change a signature or path the blueprint fixes
6. **Verify** all acceptance criteria are met
7. **Move this file** to `sdd/tasks/completed/`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note


- Task: TASK-3724
- Feature: training-agent
- Implementation SHA: 9734b19c1f555b83fd6c15962659e1150694596b
- Closed at (UTC): 2026-09-25T18:59:18+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-terra - Backend: codex - Model: gpt-5.6-terra - Attempts: 1 - Duration: ~361s - Tokens: n/a |
