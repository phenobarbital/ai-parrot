# F003: Existing Matrix Crew Example Files

**Query**: find examples/matrix_crew/ + read swarm_example.py
**Source**: examples/matrix_crew/

## Files

| File | Status | Description |
|------|--------|-------------|
| matrix_crew.yaml | ✅ existing | Basic crew config (FEAT-044) |
| matrix_crew_example.py | ✅ existing | Basic crew runner |
| collaborative_crew.yaml | ✅ existing | Collaborative mode (FEAT-195) |
| collaborative_example.py | ✅ existing | Collaborative runner |
| swarm_crew.yaml | ✅ existing | FEAT-463 swarm config (channels, tunnels, space, collaborative) |
| swarm_example.py | ✅ existing | FEAT-463 swarm runner |
| MATRIX_CREW_GUIDE.md | ✅ existing | Comprehensive guide (needs swarm sections per TASK-2487) |

## Critical Gap in swarm_example.py (lines ~115-140)

`_setup_bots()` only logs a warning:
```python
logger.warning(
    "No real agents configured — edit _setup_bots() to register your agents."
)
```

The example cannot actually run end-to-end because no real Agent instances are registered with BotManager. The config references chatbot_ids like "web-researcher", "financial-analyst", "report-writer", "synthesis-agent" but nobody creates them.

## Implication for FEAT-464
The sample needs real agent instantiation with at least one working LLM backend. The swarm_example.py structure is good but incomplete — FEAT-464 should provide a self-contained, runnable version with real agents.
