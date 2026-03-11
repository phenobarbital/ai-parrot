# TASK-298 — Matrix Crew Agent Registry

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-296
**Parallel**: false
**Parallelism notes**: Imports MatrixCrewAgentEntry from TASK-296 config.py to construct MatrixAgentCard instances.

---

## Objective

Create a thread-safe in-memory agent registry (`MatrixCrewRegistry`) and the `MatrixAgentCard` model for tracking agent identity and runtime status within a Matrix crew.

## Files to Create/Modify

- `parrot/integrations/matrix/crew/registry.py` — new file

## Implementation Details

### MatrixAgentCard (Pydantic BaseModel)

Fields per spec section 3.2:
- `agent_name: str`
- `display_name: str`
- `mxid: str` — full `@user:server` MXID
- `status: str = "offline"` — one of: `ready`, `busy`, `offline`
- `current_task: str | None = None`
- `skills: list[str] = []`
- `joined_at: datetime | None = None`
- `last_seen: datetime | None = None`

Methods:
- `to_status_line() -> str` — render a single-line status for the pinned board, e.g.:
  - `"[ready] @analyst -- Financial Analyst | Skills: Stock analysis, Financial ratios"`
  - `"[busy: analyzing AAPL] @researcher -- Research Assistant"`
  - `"[offline] @assistant -- General Assistant"`

Reference: `parrot/integrations/telegram/crew/agent_card.py` for rendering pattern.

### MatrixCrewRegistry

Thread-safe registry using `asyncio.Lock`:

```python
class MatrixCrewRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, MatrixAgentCard] = {}
        self._lock = asyncio.Lock()

    async def register(self, card: MatrixAgentCard) -> None: ...
    async def unregister(self, agent_name: str) -> None: ...
    async def update_status(self, agent_name: str, status: str, current_task: str | None = None) -> None: ...
    async def get(self, agent_name: str) -> MatrixAgentCard | None: ...
    async def get_by_mxid(self, mxid: str) -> MatrixAgentCard | None: ...
    async def all_agents(self) -> list[MatrixAgentCard]: ...
```

- `register()` sets `joined_at` and `last_seen` to `datetime.utcnow()`, status to `"ready"`.
- `update_status()` updates `last_seen` timestamp along with status.
- `get_by_mxid()` iterates agents to find by MXID (small registry, O(n) is fine).

Reference: `parrot/integrations/telegram/crew/registry.py`.

## Acceptance Criteria

- [ ] `MatrixAgentCard` validates correctly with all fields.
- [ ] `to_status_line()` renders readable status for ready/busy/offline states.
- [ ] `MatrixCrewRegistry` CRUD operations work: register, unregister, get, get_by_mxid, all_agents.
- [ ] `update_status()` changes status and updates `last_seen`.
- [ ] Concurrent access is safe (asyncio.Lock protects all mutations).
