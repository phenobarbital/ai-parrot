# F001 — CodexCodeDispatcher already exists (queries Q001, Q004, Q010)

**Type**: read + grep
**Citations**:
- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatcher.py:936-1265` — `CodexCodeDispatcher`

Full async orchestration over `codex exec --json`:
- Command line (dispatcher.py:1128-1151): `codex exec --json --cd <cwd> --model <m> --sandbox <s> --ask-for-approval <p> --output-schema <schema.json> -o <out.json> [--ignore-user-config] [--ignore-rules] <prompt>`
- Mirrors `ClaudeCodeDispatcher.dispatch()` contract (brief + profile + output_model + run_id/node_id/cwd + SessionHost).
- Redis event streaming per JSONL stdout event (`dispatch.tool_use` / `dispatch.tool_result` / `dispatch.message`), semaphore concurrency cap, wall-clock timeout, structured Pydantic output validated from the `-o` file, cwd-under-worktree-base guard (dispatcher.py:1264).
- Prompt built by `_build_codex_prompt` (dispatcher.py:1153-1165): loads the SDD subagent body via `load_subagent_definition(profile.subagent)`.

**Implication**: the "invoke codex CLI as a sub-agent" plumbing is DONE. The request is not greenfield.
