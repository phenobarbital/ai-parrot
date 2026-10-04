---
id: F021
query_id: Q021
type: read
intent: TaskMemoryToolsMixin tool signatures/step keys/statuses; WorkingMemoryToolkit composition; backing store & scoping
executed_at: 2026-09-24T23:21:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F021 — TaskMemoryToolsMixin: 10 opt-in wm_* tools, label-addressed steps, revisioned updates, TaskScope-keyed stores

## Summary
The mixin defines ten tools, listed in `TASK_TOOL_METHODS`. `begin_task(goal, constraints, steps, plan_complete)` takes step dicts with required keys `label` and `title`, and optional `description`, `required` (default True) and `depends_on_labels`. `update_step` requires `expected_revision` and a status, which is one of pending, running, blocked, completed, failed, cancelled or superseded; a completed step's `evidence_refs` must be exact `artifact_id@version` strings. `WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit)` uses `tool_prefix="wm"`. When no `task_memory` is passed it hides all ten tools through `exclude_tools`, so the feature is opt-in. State lives in a `TaskMemory` composition root over a `BaseTaskMemoryStore` (InMemory or Postgres) plus an artifact store. Every read and write is scoped by a trusted `TaskScope(chatbot_id, user_id, session_id)` that the runtime supplies, never a tool argument.

## Citations
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 91-102
  symbol: `TASK_TOOL_METHODS`
  excerpt: |
    TASK_TOOL_METHODS: tuple = ("begin_task", "update_plan", "update_step", "record_decision",
        "set_resume_hint", "recall_task", "list_task_events", "list_task_artifacts",
        "select_task", "update_task")
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 129-155
  symbol: `TaskMemory.__init__`
  excerpt: |
    def __init__(self, store: Any, artifacts: Any, scope: TaskScope,
                 config: Optional[TaskMemoryConfig] = None, *, association: Any = None,
                 cache: Any = None, omission_store: Any = None) -> None:
        self.service = TaskMemoryService(store, self.config, artifacts=artifacts)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 237-256
  symbol: `_StepSpecInput`, `BeginTaskInput`
  excerpt: |
    label: str = Field(..., description="Request-local label, unique in this call, ...")
    title: str = Field(max_length=Limits.MAX_STEP_TITLE, description="Short step title")
    description: str = Field(default="", ...)
    required: bool = Field(default=True, ...)
    depends_on_labels: List[str] = Field(default_factory=list, ...)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 274-286
  symbol: `UpdateStepInput`
  excerpt: |
    expected_revision: int = Field(ge=0, description="The revision you believe is current")
    status: str = Field(description="One of: pending, running, blocked, completed, failed, cancelled, superseded")
    evidence_refs: List[str] = Field(default_factory=list,
        description="Exact artifact versions as 'artifact_id@version'. A bare alias is rejected.")
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 397-435
  symbol: `TaskMemoryToolsMixin.begin_task`
  excerpt: |
    @tool_schema(BeginTaskInput)
    async def begin_task(self, goal: str, constraints: Optional[List[str]] = None,
                         steps: Optional[List[dict]] = None, plan_complete: bool = False) -> dict:
        specs = [InitialStepSpec(label=s["label"], title=s["title"], description=s.get("description", ""),
                 required=s.get("required", True), depends_on_labels=tuple(s.get("depends_on_labels", ())),
                 completion_policy=CompletionPolicy()) for s in (steps or [])]
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 529-538
  symbol: `TaskMemoryToolsMixin.update_step`
  excerpt: |
    async def update_step(self, task_id: str, step_id: str, expected_revision: int, status: str,
                          evidence_refs: Optional[List[str]] = None, note: Optional[str] = None,
                          reason: Optional[str] = None) -> dict:
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 664-664
  symbol: `TaskMemoryToolsMixin.set_resume_hint`
  excerpt: |
    async def set_resume_hint(self, task_id: str, next_action: str, step_id: Optional[str] = None) -> dict:
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/tools.py`
  lines: 772-782
  symbol: `TaskMemoryToolsMixin.recall_task`
  excerpt: |
    async def recall_task(self, task_id: Optional[str] = None, max_tokens: int = 2500,
                          recent_calls_limit: int = 8) -> dict:
        Read-only: appends nothing, loads no payloads, runs no tools, and
        **does not select a task**.
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 47-89
  symbol: `WorkingMemoryToolkit`
  excerpt: |
    class WorkingMemoryToolkit(TaskMemoryToolsMixin, AbstractToolkit):
        tool_prefix: str = "wm"
        exclude_tools: tuple[str, ...] = ("store",)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/tool.py`
  lines: 141-155
  symbol: `WorkingMemoryToolkit.__init__` (opt-in)
  excerpt: |
    # FEAT-538: task memory is OPT-IN. `task_memory=None` (the default)
    self._task_memory: Optional[Any] = task_memory
    if task_memory is None:
        # AC13: the ten wm_* task tools are hidden ENTIRELY when task memory is off
        self.exclude_tools = (*type(self).exclude_tools, *TASK_TOOL_METHODS)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/models.py`
  lines: 571-587
  symbol: `TaskScope`
  excerpt: |
    class TaskScope(_TaskModel):
        """Trusted runtime identity every read and write is checked against."""
        chatbot_id: str = Field(min_length=1, ...)
        user_id: str = Field(min_length=1, ...)
        session_id: str = Field(min_length=1, ...)
- path: `packages/ai-parrot/src/parrot/tools/working_memory/task_memory/config.py`
  lines: 628-646
  symbol: `TaskMemoryRuntime.task_memory`
  excerpt: |
    def task_memory(self, scope: Any, **kwargs: Any) -> Any:
        """Build a composition root over the SHARED stores."""
        from .tools import TaskMemory
        return TaskMemory(self.store, self.artifacts, scope, self.config, **kwargs)

## Notes
- The step dict shape the brainstorm assumed (label/title/description/required/depends_on_labels) is CORRECT.
- Guided mode must pass `expected_revision` on every `update_step`, and completing a step goes through evidence validation, which needs artifact refs. A "step done" signal without evidence may be rejected, depending on `CompletionPolicy`, which I did not inspect.
- The scope includes `session_id`, so a guided procedure does not carry across sessions unless the caller uses `select_task` or the durable `association` store. Without that store, selection is in-process only (TaskMemory docstring, L121-124).
- Store classes: `InMemoryTaskMemoryStore` (store/memory.py L141) and `PostgresTaskMemoryStore` (store/postgres.py L428).

