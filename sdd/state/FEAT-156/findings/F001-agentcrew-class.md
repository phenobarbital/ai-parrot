---
id: F001
query: "AgentCrew class definition and constructor"
type: read
file: packages/ai-parrot/src/parrot/bots/orchestration/crew.py
lines: 148-267
---

AgentCrew (line 148) inherits from PersistenceMixin, SynthesisMixin.
Constructor accepts: name, agents (List), shared_tool_manager, max_parallel_tasks,
llm, auto_configure, truncation_length, truncate_context_summary, embedding_model,
enable_analysis, dimension, index_type, agent_execution_timeout, persist_results,
result_storage, **kwargs.

`self.agents` is a `Dict[str, Union[BasicAgent, AbstractBot]]` — keyed by name.

NO factory methods exist. No `from_definition`, `from_config`, `from_dict`,
or any `@classmethod` on the class.
