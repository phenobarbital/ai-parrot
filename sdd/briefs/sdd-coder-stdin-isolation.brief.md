---
kind: brief
slug: sdd-coder-stdin-isolation
key: 995ad869e502
base_branch: dev
source:
  type: ledger
  ref: issue:995ad869e502
  url: null
jira_issue_key: null
ledger_issue: issue:995ad869e502
created: 2026-10-27
---

# Brief: MCP-served subprocesses must not inherit the JSON-RPC stdin socket

<!-- FEAT-698. One brief = one fix. Task files live in sdd/briefs/<slug>/tasks/. -->

## Problem

`parrot-sdd-coder` disconnects in the middle of a feature run. The host reports

```
Error: Connection closed
Error: No such tool available: mcp__parrot-sdd-coder__coder_begin_execution.
Its MCP server 'parrot-sdd-coder' has disconnected.
```

on an in-flight `coder_wait`. Claude Code reconnects a *fresh* server, which has
no memory of the execution: the next call returns `job_not_found`, the job
journal under `<worktree>/.sdd-coder/jobs/` stays frozen at `state: "running"`
forever, the attempt sub-worktrees are abandoned, and the orchestrator stops
with nothing merged.

Four occurrences are recorded in
`~/.cache/claude-cli-nodejs/-home-jesuslara-proyectos-ai-parrot/mcp-logs-parrot-sdd-coder/`:
2026-10-22T00:00:56Z, and 2026-10-27 at 02:52:20Z, 12:01:06Z and 12:06:25Z. The
last three are all FEAT-753 / TASK-4780 dispatched to the `glm` seat; two of
them died at T+197 s and T+198 s after `coder_run_chunk` — the same agent
trajectory replayed, reaching the same fatal command at the same point.

## Root cause

`StdioMCPServer.start()` ends its serve loop on stdin EOF and then exits 0
without a word:

```python
# packages/ai-parrot/src/parrot/mcp/local_server.py:87-89
line = await loop.run_in_executor(None, sys.stdin.readline)
if not line:
    break
```

Claude Code hands a stdio MCP server **socketpairs**, not pipes — verified on a
live server: `/proc/<pid>/fd/0 -> socket:[1811051]`. `shutdown()` on a socket is
a socket-level operation shared by every descriptor that refers to it, across
every process, unlike `close()`.

`LLMCodeDispatcher._run_argv` — the executor behind the coder model's
`run_command` / `search_files` / `apply_patch` tools — spawns its children with
fd 0 **inherited** whenever there is no stdin payload, which is the normal case:

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:2214
stdin=asyncio.subprocess.PIPE if stdin is not None else None,   # None == inherit
```

So any descendant of a model-issued command that shuts stdin down makes the
**server's** `readline` return `""`, and the server exits cleanly and silently.
Reproduced minimally against a socketpair, spawning exactly as `_run_argv` does:

```
inherit_stdin=True   child=shutdown  -> EOF  -> server exits silently
inherit_stdin=True   child=noop      -> blocked (healthy)
inherit_stdin=False  child=shutdown  -> blocked (healthy)
inherit_stdin=False  child=noop      -> blocked (healthy)
```

This is the same defect class as the already-landed hotfix
`sdd/specs/codex-dispatch-stdin-isolation.spec.md`, which set
`stdin=DEVNULL` in `dispatchers/codex.py:579` for the Codex seats. `llm.py` and
three further spawn sites were never covered.

### Ruled out

| Candidate | Evidence against |
|---|---|
| OOM kill | No OOM in `journalctl -k`; 34 GiB available |
| Crash (SIGSEGV/SIGBUS) | `coredumpctl list` empty, and `core_pattern` is wired to `systemd-coredump`, so a crash signal would have been captured |
| Native `.so` rebuilt under the running process | No `.so` under `packages/` has a 2026-10-27 mtime |
| Host-initiated shutdown | Claude Code logs `Sending SIGINT to MCP server process` when it stops a server; absent at all four deaths |
| Python exception | No traceback on the server's stderr |

## Research findings

**Verified spawn sites that inherit the server's stdin** (no `stdin=` passed, or
the `None` branch) — every anchor below was verified with
`test -e <path> && sed -n '<line>p' <path>`:

| Anchor | Line content | Served by |
|---|---|---|
| `dispatchers/llm.py:2214` | `stdin=asyncio.subprocess.PIPE if stdin is not None else None,` | nova / google-compat / zai / grok seats |
| `dispatchers/google_coding.py:407` | `return await asyncio.create_subprocess_exec(` | `google_coding` dev-loop backend |
| `sdd_coder/background.py:668` | `process = await asyncio.create_subprocess_exec(` | supervised validation runs |
| `sdd_coder/background.py:1010` | `owned_process = await asyncio.create_subprocess_exec(` | chained validation invocations |
| `tools/repo/toolkit.py:360` | `proc = await asyncio.create_subprocess_exec(` | `parrot-bounded-source` MCP server |

**Already isolated** (the shape to copy): `dispatchers/codex.py:579` and
`procs.py:124`, both `stdin=asyncio.subprocess.DEVNULL,`.

**Seat exposure.** `NovaCodeDispatcher`, `GoogleCompatCodeDispatcher`,
`ZaiCodeDispatcher` and the Grok dispatcher all subclass `LLMCodeDispatcher`
and therefore all route through `_run_argv`. From the roster in
`.parrot/mcp-toolkits.yaml`, that exposes the **glm, minimax, qwen, mistral and
gemini** seats. The `codex` seats (`gpt-5.6-terra`, `gpt-5.6-sol`) and the
native seats (`haiku`, `sonnet`, `opus`) are not exposed — the native seats
spawn nothing from the server at all.

**Blast radius** of `LLMCodeDispatcher._run_argv`
(`wikitoolkit symbols blast`): callers are `_tool_search_files` (L1627),
`_tool_apply_patch` (L1893) and `_tool_run_command` (L1956), all reached via
`_run_tool` (L1520). Confined to `dispatchers/llm.py` plus
`tests/flows/dev_loop/test_worktree_environment.py`. No cross-package surface.

**Prior art for the regression test.**
`packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py:503` already
asserts `captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL` against a
patched `create_subprocess_exec`, and L509-529 holds a real-child integration
harness for the same property. Its docstring records `issue:bde3a98caed2`: a
*relative* `PYTHONPATH=packages/ai-parrot/src` silently resolved to the primary
checkout because importing `parrot` makes navconfig `chdir`, so the harness ran
the pre-fix launcher. Any new integration harness must pin an **absolute**
`PYTHONPATH` and keep the `samefile` guard.

**Related ledger issues on these files** (`wikitoolkit ledger context`):
`issue:7a366d6004de` (low, open) — `ai-parrot-server` keeps an older duplicate
`StdioMCPServer` at `packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py`
with the same serial loop. `parrot mcp-local` uses the core server, not that
one, so it is out of scope here but would need the same EOF logging if it is
ever put in front of a dispatcher. `issue:455ae7a3d8ea` (minor, open) —
`coder_run_validation` leaves a pending handle when the selector rejects the
request; unrelated to stdin, but it touches `background.py`.

## Decisions

1. **Fix all five spawn sites**, including `tools/repo/toolkit.py:360` in the
   `parrot-bounded-source` server. It is the identical one-line defect with the
   identical exposure, so the class is closed rather than the instance.
2. **No EOF guard in the serve loop — log only.** With `stdin=DEVNULL`, a stdin
   EOF can only mean the host genuinely closed the channel, and the server must
   still exit then; refusing to exit would orphan it. Both silent-exit paths get
   a log line instead, so a recurrence is visible rather than invisible.
3. `_run_argv` keeps honouring a real stdin payload: only the `None` branch
   becomes `DEVNULL`, so `stdin=PIPE` when a payload is supplied is unchanged.
4. No Delegation Contract on either task — both take the normal implementation
   route.

## Fix plan

- **HOTFIX-995ad869e502-1** — Isolate stdin at all five spawn sites and assert
  it per site. One-line change each, plus a unit test per site patching
  `asyncio.create_subprocess_exec` and asserting the `stdin` kwarg is `DEVNULL`
  (mirroring `test_codex_dispatcher.py:503`), plus one real-child integration
  regression over a socketpair proving the parent's read no longer EOFs.
- **HOTFIX-995ad869e502-2** — Make both silent exits observable: log on the
  stdin-EOF break in `local_server.py` and before `os._exit(0)` in the SIGTERM
  handler in `local_cli.py`, each naming which path was taken and how many tool
  calls were in flight, with tests asserting both lines.

The tasks are independent and may run in parallel; they share no file.

## Validation commands

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_merge_scope_and_bg_wait.py -q`
- `pytest packages/ai-parrot/tests/tools/repo/test_readonly_toolkit.py -q`
- `pytest packages/ai-parrot/tests/mcp/test_local_server.py -q`
