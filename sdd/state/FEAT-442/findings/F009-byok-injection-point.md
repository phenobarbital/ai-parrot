# F009 — BYOK injection point confirmed at new line
**Query**: G007 · **Confidence**: high

`clients/factory.py:273` `init_params.update(kwargs)` then :276 `client_class(**init_params)` — per-instance `api_key=` injection via `LLMFactory.create(...)` works today and has no callers. (Brainstorm cited :179; mechanism unchanged, line drifted.)
