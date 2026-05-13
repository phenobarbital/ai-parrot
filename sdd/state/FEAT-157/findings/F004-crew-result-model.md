---
id: F004
query: "CrewResult data model"
type: read
file: packages/ai-parrot/src/parrot/models/crew.py
---

## CrewResult Dataclass (models/crew.py, lines 60-97)

```python
@dataclass
class CrewResult:
    output: Any
    responses: Dict[str, ResponseType]
    summary: str = ""
    agents: List[AgentExecutionInfo] = []
    execution_log: List[Dict[str, Any]] = []
    total_time: float = 0.0
    status: Literal['completed', 'partial', 'failed'] = 'completed'
    errors: Dict[str, str] = {}
    metadata: Dict[str, Any] = {}
```

- `status` is one of: 'completed', 'partial', 'failed'
- Determined by `determine_run_status(success_count, failure_count)`
- This is the object hooks should receive as their primary argument
