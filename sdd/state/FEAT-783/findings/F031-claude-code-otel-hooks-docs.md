---
id: F031
query_id: X3
type: read
intent: "External probe: verify against official Claude Code documentation the three attribution facts the source marks 'implied, not stated', plus the hook payload fields and OTEL_RESOURCE_ATTRIBUTES / raw-bodies constraints."
executed_at: 2026-10-30T22:45:00Z
duration_ms: 240000
parent_id: null
depth: 0
lane: external
merged_from: ['FX-003']
---

# F031 — Claude Code docs: the sub-agent session join is UNDOCUMENTED, but a session-id env var exists that the source missed

## Summary

Official documentation (code.claude.com/docs, read 2026-10-30; local copies in
the session scratchpad) **does not state** whether a sub-agent's
`claude_code.api_request` carries the parent session's `session.id`. The source
document flagged this as "implied, not stated" and it stays exactly that — the
single fact spike **S1** exists to settle. `agent_id` and `parent_agent_id` ARE
documented on sub-agent events (v2.1.310+; installed build is 2.1.314), and
`agent.name` is documented on `api_request` with no stated introduction version.

Two corrections to the source document, both material to the design:

1. **`CLAUDE_CODE_SESSION_ID` is documented.** The source asserted "none
   documented" for an env var exposing the session id, and routed around it via
   `CLAUDE_ENV_FILE`. In fact the variable is set automatically in **Bash tool
   subprocesses, hook command subprocesses, and stdio MCP server subprocesses**.
2. **"`OTEL_RESOURCE_ATTRIBUTES` is set once per process" is NOT stated
   anywhere.** The source presented this as a hard constraint shaping the design
   ("cannot change per task inside a session"). The documented constraints are
   about formatting and key collisions, not read-once semantics.

`query_source=auxiliary` is **undefined** in the docs — nothing assigns title
generation or compaction to it. The source's plan to attribute "orchestration
overhead" via `auxiliary` rests on an undocumented assumption.

## Citations

- path: `https://code.claude.com/docs/en/env-vars`
  lines: n/a
  symbol: `CLAUDE_CODE_SESSION_ID`
  excerpt: |
    Set automatically to the current session ID in Bash and PowerShell tool
    subprocesses, hook command subprocesses, and stdio MCP server subprocesses.
    For Bash, PowerShell, and hooks this matches the `session_id` field in the
    hook JSON input and is updated on `/clear`.
    [an MCP server subprocess "retains the ID it was spawned with"; no version given]

- path: `https://code.claude.com/docs/en/monitoring-usage`
  lines: n/a
  symbol: `agent_id` (Standard attributes)
  excerpt: |
    identifier of the subagent that raised the event ... Events that carry it
    include a subagent's API and tool events ... Absent on main-session and
    in-process teammate events. ... Requires Claude Code v2.1.310 or later.

- path: `https://code.claude.com/docs/en/monitoring-usage`
  lines: n/a
  symbol: `parent_agent_id`
  excerpt: |
    the `agent_id` of the agent that spawned or last resumed the subagent that
    raised the event. Absent when that agent is the main session.
    Requires Claude Code v2.1.310 or later.

- path: `https://code.claude.com/docs/en/monitoring-usage`
  lines: n/a
  symbol: `session.id`
  excerpt: |
    session.id | Claude Code's own session ID, which `/clear` replaces
    [nothing states whether a subagent event carries the parent's value]

- path: `https://code.claude.com/docs/en/monitoring-usage`
  lines: n/a
  symbol: `query_source` (Cost / Token counters)
  excerpt: |
    Category of the subsystem that issued the request. One of "main",
    "subagent", or "auxiliary".
    The "subagent" category also counts requests from agent-based hooks,
    which emit no subagent event.
    [event docs instead say: such as "repl_main_thread", "compact", or a
     subagent name -- the two namings are never reconciled; "auxiliary" is
     never defined]

- path: `https://code.claude.com/docs/en/hooks`
  lines: n/a
  symbol: `SubagentStop input`
  excerpt: |
    agent_id (unique identifier for the subagent), agent_type,
    agent_transcript_path ("the subagent's own transcript stored in a nested
    subagents/ folder"), last_assistant_message ("the text content of the
    subagent's final response"), plus common fields session_id, prompt_id,
    cwd, transcript_path (the MAIN session transcript), scratchpad_dir.

- path: `https://code.claude.com/docs/en/hooks`
  lines: n/a
  symbol: `common input fields` / `SessionEnd`
  excerpt: |
    Common: session_id, prompt_id (matches the prompt.id OTel attribute;
    absent until the first user input), transcript_path, cwd, scratchpad_dir,
    permission_mode, effort, hook_event_name.
    SessionEnd: the field name is exactly `reason`
    (clear | resume | logout | prompt_input_exit | other).

- path: `https://code.claude.com/docs/en/monitoring-usage`
  lines: n/a
  symbol: `OTEL_RESOURCE_ATTRIBUTES` constraints
  excerpt: |
    comma-separated key=value pairs; No spaces allowed; only US-ASCII excluding
    control characters, whitespace, double quotes, commas, semicolons and
    backslashes; others percent-encoded.
    custom keys never override the standard attributes such as `user.id` or
    `session.id`: when a key collides, Claude Code keeps the built-in value.
    [vcs.* is the one exception; user.*/identity.* are ignored on gateway
     sessions; no statement that the variable is read once per process]

- path: `https://code.claude.com/docs/en/monitoring-usage`
  lines: n/a
  symbol: `OTEL_LOG_RAW_API_BODIES` / index.jsonl
  excerpt: |
    Claude Code also appends one JSON line to <dir>/index.jsonl for each
    successful response, with the fields timestamp, session_id, query_source,
    model, request_id, message_id, message_uuid, request_file, and
    response_file. ... The index file requires Claude Code v2.1.274 or later.
    [only SUCCESSFUL responses are indexed; ignored in project/local settings]

## Notes

`CLAUDE_CODE_SESSION_ID` in **stdio MCP server subprocesses** is the most
consequential line in this finding. The `parrot-sdd-coder` MCP server is exactly
such a subprocess, so the dev-loop engine can read the orchestrating Claude Code
session id directly inside `coder_begin_execution` and write the
`session_id -> (feat_id, task_id, attempt_uid, execution_id)` binding itself —
no `SessionStart` hook, no `cwd` heuristic, no LLM in the loop. The documented
caveat is that an MCP subprocess "retains the ID it was spawned with", so a
`/clear` mid-run makes the retained id stale; the hook remains the authority for
the main loop.

What the docs leave unstated, and which therefore must survive into the proposal
as risks rather than assumptions:
1. parent vs distinct `session.id` on sub-agent `api_request` (spike S1);
2. whether `prompt.id` appears on sub-agent events — this is the source's
   declared FALLBACK join, so S1 failing does not automatically leave a
   fallback standing;
3. what `auxiliary` covers, i.e. whether orchestration overhead is attributable;
4. whether a sub-agent's Bash/hook inherits the parent's `CLAUDE_CODE_SESSION_ID`;
5. `agent_id`/`agent_type` on `Stop`, `UserPromptSubmit`, `SessionStart`
   (only `SubagentStart`/`SubagentStop` document them; `SessionStart` documents
   `agent_type` only when started with `--agent`).

Failed API attempts never reach `index.jsonl` (successful responses only), so a
raw-bodies ingestor under-counts retried/errored requests that still consumed
input tokens. The collector path does not share this gap.

[cross-lane: type=grep, intent=does the parrot-sdd-coder MCP server read any CLAUDE_* env var today]
