# F006 — ExecutionMemory absent from AgentsFlow; NEW dead config knob
**Query**: G002 + follow-up grep · **Confidence**: high

- `flow/flow.py`: zero `ExecutionMemory` references (claim holds).
- NEW since brainstorm: `flow/definition.py:328` declares `enable_execution_memory: bool = True` ("Enable ExecutionMemory for result storage") — **zero consumers anywhere in flows/**. The declarative knob for S3b already exists but is unwired; S3b should wire it rather than invent a new ctor arg name.
