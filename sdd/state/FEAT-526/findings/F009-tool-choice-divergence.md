# F009 — `tool_choice` must be `"auto"` on Meta — and parrot already complies

**External** (`docs/tool-calling.md`, Guidelines): *"Only `"auto"` (the default)
is supported on both Chat Completions and the Responses API; `"none"`,
`"required"`, and named function choices return **HTTP 400** (`only "auto" is
supported for tool_choice`)."*

**Codebase check** — what the shared funnel actually sends:
- `openai_base.py:639` → `args["tool_choice"] = "auto"`
- `openai_base.py:979` → `args["tool_choice"] = "auto"`
- (`groq.py` does send `"required"`/`"none"` at :422/:568 — but GroqClient
  overrides its own path and is not on the shared funnel for those calls.)

**Conclusion**: `OpenAIBaseClient`'s own emissions are already Meta-legal.
This is a **compatibility confirmation, not a blocker** — but it is a real
constraint on any future caller that tries to force a tool, and deserves an
explicit regression test rather than being left implicit.
