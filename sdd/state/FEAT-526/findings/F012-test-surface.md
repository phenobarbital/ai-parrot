# F012 — Existing test + smoke surface a new client must join

- `tests/clients/test_openai_compatible_defaults.py` — `WIRE_SUBCLASSES` roster;
  `test_no_gpt_default_leak`, `test_invoke_chain_never_yields_gpt`,
  `test_ask_payload_model_never_leaks_gpt`.
- `tests/clients/test_openai_base_parity.py` — `WIRE_SUBCLASSES` +
  `_ASK_FUNNEL_ROSTER` / `_ASK_STREAM_FUNNEL_ROSTER` / `_INVOKE_FUNNEL_ROSTER` /
  `_OPENAI_TOOL_FORMAT_ROSTER`.
- `examples/clients/smoke/` — 8 credential-gated scripts + `_runner.py`.
  Each: skips cleanly (exit 0) without creds, else builds via
  `LLMFactory.create("provider:model")` inside `async with client:` and runs
  three legs — `ask()`, `ask()` + one `@tool`, `invoke()`.
- An untracked `tests/e2e/` directory currently exists in the working tree
  (not from this session).

**Worktree gotcha** (from the same doc): editable-install `.pth` entries point
at the *main* checkout, so a bare `python script.py` inside a worktree silently
imports main-checkout code. Prepend the worktree's `src` dirs via `PYTHONPATH`
and ensure compiled `.so` files exist before trusting smoke results.
