---
id: F005
query: "BaseBot ask()/ask_stream() ctx usage"
type: read
file: packages/ai-parrot/src/parrot/bots/base.py
lines: 653-1175
---

BaseBot.ask() (line 653): accepts ctx, forwards to _build_kb_context() at line 830.
BaseBot.ask_stream() (line 1157): accepts ctx, forwards similarly.
BaseBot.conversation() (line 115): deprecated, forwards ctx to _build_kb_context().

ctx is NOT forwarded to:
- LLM client (llm_kwargs at lines 964-971)
- Memory classes
- Prompt pipeline middleware (gets a plain dict with agent_name, user_id, session_id)
