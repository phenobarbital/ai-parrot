# HOTFIX-995ad869e502-1: Isolate stdin at every MCP-served subprocess spawn site

**Feature**: BRIEF-995ad869e502 — MCP-served subprocesses must not inherit the JSON-RPC stdin socket
**Spec**: `sdd/briefs/sdd-coder-stdin-isolation.brief.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

A stdio MCP server's fd 0 **is** its JSON-RPC input channel, and Claude Code
backs it with a socketpair. Five spawn sites let a child inherit that
descriptor; because `shutdown()` is socket-level rather than fd-level, any
descendant that shuts stdin down makes the *server's* `readline` return `""`,
and `StdioMCPServer.start()` then breaks out of its serve loop and exits 0.
That is the `Connection closed` / `has disconnected` failure in
`issue:995ad869e502`, observed four times.

`dispatchers/codex.py:579` and `procs.py:124` already pass
`stdin=asyncio.subprocess.DEVNULL` for exactly this reason (hotfix
`sdd/specs/codex-dispatch-stdin-isolation.spec.md`). This task applies the same
one-line guarantee to the five sites that were missed, and pins it with a test
per site so the class cannot reopen.

See the brief's "Research findings" for the seat-exposure table and the blast
radius.

---

## Scope

- Pass `stdin=asyncio.subprocess.DEVNULL` at each of the five spawn sites listed
  under "Files to Create / Modify".
- In `LLMCodeDispatcher._run_argv`, change **only** the `None` branch: a real
  stdin payload must still be delivered over `asyncio.subprocess.PIPE`.
- Add one unit test per site that patches `asyncio.create_subprocess_exec`,
  invokes the production code path, and asserts the captured `stdin` kwarg is
  `asyncio.subprocess.DEVNULL`.
- Add one integration regression proving a real child spawned the way
  `_run_argv` spawns cannot EOF a socketpair its parent is reading.

**NOT in scope**: the silent-exit logging in `parrot/mcp/local_server.py` and
`parrot/mcp/local_cli.py` (that is HOTFIX-995ad869e502-2); any process-group /
`start_new_session` change; the duplicate `StdioMCPServer` in
`packages/ai-parrot-server/src/parrot/mcp/transports/stdio.py`
(`issue:7a366d6004de`); `issue:455ae7a3d8ea`'s pending-handle bug in
`background.py`; any change to allowed-command policy, timeouts or sandboxing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` | MODIFY | `_run_argv`: `None` branch -> `DEVNULL` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` | MODIFY | `_create_process`: add `stdin=DEVNULL` |
| `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` | MODIFY | both validation spawns: add `stdin=DEVNULL` |
| `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` | MODIFY | `_run_argv`: add `stdin=DEVNULL` |
| `packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py` | MODIFY | per-site assertion + socketpair regression |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py` | MODIFY | per-site assertion |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_merge_scope_and_bg_wait.py` | MODIFY | per-site assertions (both spawns) |
| `packages/ai-parrot/tests/tools/repo/test_readonly_toolkit.py` | MODIFY | per-site assertion |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: VERIFIED references from this worktree (base `origin/dev`, HEAD
> `8e7d19e57`). Every line below was checked with
> `test -e <path> && sed -n '<line>p' <path>`. Use them verbatim.

### Verified Imports

```python
import asyncio  # already imported in all four source modules; use asyncio.subprocess.DEVNULL
```

No new import is required at any site — every one of the four source modules
already spawns through `asyncio.create_subprocess_exec`.

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py:2199-2244
class LLMCodeDispatcher:
    async def _run_argv(
        self,
        argv: Sequence[str],
        *,
        cwd: str,
        timeout: int,
        stdin: Optional[str] = None,
    ) -> Dict[str, Any]:  # line 2199
        ...
        # line 2214 (verbatim):
        #     stdin=asyncio.subprocess.PIPE if stdin is not None else None,

# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py:406
    async def _create_process(self, command: Sequence[str], cwd: str) -> Any:
        # line 407 (verbatim): return await asyncio.create_subprocess_exec(

# packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py
    # line 668  (verbatim): process = await asyncio.create_subprocess_exec(
    # line 1010 (verbatim): owned_process = await asyncio.create_subprocess_exec(
    # both already pass start_new_session=True and stderr=asyncio.subprocess.STDOUT

# packages/ai-parrot/src/parrot/tools/repo/toolkit.py:360
class ReadOnlyRepoToolkit:
    async def _run_argv(self, argv: Sequence[str], *, timeout: float | None = None) -> dict[str, Any]:  # line 334
        # line 360 (verbatim): proc = await asyncio.create_subprocess_exec(

# The shape to copy, already correct:
# packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:579
#     stdin=asyncio.subprocess.DEVNULL,
# packages/ai-parrot/src/parrot/flows/dev_loop/procs.py:124
#     stdin=asyncio.subprocess.DEVNULL,

# Prior-art test assertion to mirror:
# packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py:503
#     assert captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL
```

### Does NOT Exist

- ~~a shared spawn helper used by all five sites~~ — each site calls
  `asyncio.create_subprocess_exec` directly; do **not** invent one, and do not
  reroute these sites through `procs.run_bounded` (it changes timeout, process
  group and return-code semantics).
- ~~`LLMCodeDispatcher._create_process`~~ — that hook exists on the Codex and
  Google-coding dispatchers, not on `LLMCodeDispatcher`.
- ~~`stdin` parameter on `ReadOnlyRepoToolkit._run_argv`~~ — its signature is
  `(self, argv, *, timeout=None)`; do not add one.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/src/parrot/tools/repo/toolkit.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_merge_scope_and_bg_wait.py", "action": "MODIFY"},
    {"path": "packages/ai-parrot/tests/tools/repo/test_readonly_toolkit.py", "action": "MODIFY"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py#LLMCodeDispatcher._run_argv",
    "sym:packages/ai-parrot/src/parrot/tools/repo/toolkit.py#ReadOnlyRepoToolkit._run_argv",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/procs.py#run_bounded"
  ]
}
```

---

## Implementation Notes

### Key Constraints

- One kwarg per site. Do not reorder, rename or restructure anything else in
  these functions — `background.py`'s two sites in particular must keep
  `start_new_session=True` and `stderr=asyncio.subprocess.STDOUT` exactly as they
  are, because the supervisor's log drain depends on the merged stream.
- `DEVNULL` is correct rather than `PIPE` left unwritten: an unwritten `PIPE`
  would make a child that reads stdin block forever instead of seeing EOF, which
  is the Codex hang the earlier hotfix was written for.
- `ruff check` enforces this repo's import bans; no new imports are needed.

### References in Codebase

- `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/codex.py:568-583` —
  the fixed launcher, including the docstring explaining *why* DEVNULL.
- `packages/ai-parrot/src/parrot/flows/dev_loop/procs.py:92-140` — the same
  guarantee in the shared bounded runner.

---

## Implementation Blueprint

### Steps (in order)

1. Change the four source sites — *why*: each is an independent one-line
   guarantee; none depends on another.
2. Add the per-site unit assertions — *why*: a patched
   `create_subprocess_exec` pins the kwarg without needing a real child.
3. Add the socketpair integration regression in
   `test_llm_code_dispatcher.py` — *why*: proves the *property* (a child can no
   longer EOF its parent's read), not just the kwarg.
4. Run the validation commands.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py` (MODIFY)

```python
# occurrences: 1 (verified: grep -c 'stdin=asyncio.subprocess.PIPE if stdin is not None else None,' packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/llm.py)
# REPLACE line 2214 (verified: dispatchers/llm.py:2214)
                stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
```

**Why**: fd 0 of this process is the MCP JSON-RPC socket. Inheriting it lets a
model-issued command's descendant `shutdown()` it and EOF the server's own read.
A supplied payload still needs a real pipe, so only the `None` branch changes.

### `packages/ai-parrot/src/parrot/flows/dev_loop/dispatchers/google_coding.py` (MODIFY)

```python
# AFTER — insert directly below `*command,` inside the call opened at line 407
# (verified: google_coding.py:407 `return await asyncio.create_subprocess_exec(`)
            stdin=asyncio.subprocess.DEVNULL,
```

### `packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/background.py` (MODIFY)

```python
# TWO sites. Insert `stdin=asyncio.subprocess.DEVNULL,` as a sibling kwarg in each:
#   line 668  `process = await asyncio.create_subprocess_exec(`        (verified)
#   line 1010 `owned_process = await asyncio.create_subprocess_exec(`  (verified)
# Keep start_new_session=True and stderr=asyncio.subprocess.STDOUT untouched.
            stdin=asyncio.subprocess.DEVNULL,
```

### `packages/ai-parrot/src/parrot/tools/repo/toolkit.py` (MODIFY)

```python
# AFTER — insert directly below `*argv,` inside the call opened at line 360
# (verified: tools/repo/toolkit.py:360 `proc = await asyncio.create_subprocess_exec(`)
            stdin=asyncio.subprocess.DEVNULL,
```

**Why**: this toolkit is served by the `parrot-bounded-source` stdio MCP server,
so it has the identical exposure.

### Test shape (apply per site)

```python
# FILL IN: per test module, patch asyncio.create_subprocess_exec, call the real
# code path, and assert the kwarg — mirroring test_codex_dispatcher.py:503
assert captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL
```

### FILL IN checklist

- [ ] One assertion per site, in the site's own test module (4 modules, 5 sites).
- [ ] Socketpair integration regression in `test_llm_code_dispatcher.py`: parent
      holds a `socket.socketpair()` as fd 0, spawns a real child through the
      production `_run_argv`, the child tries `shutdown()` on fd 0, and the
      parent's read must still **not** reach EOF. Pin an **absolute**
      `PYTHONPATH` and keep a `samefile` guard on the imported module —
      `issue:bde3a98caed2` (recorded in `test_codex_dispatcher.py:509-529`) was
      caused by a relative `PYTHONPATH` resolving to the primary checkout after
      navconfig `chdir`, so the harness silently exercised the pre-fix code.

---

## Acceptance Criteria

- [ ] All five spawn sites pass `stdin=asyncio.subprocess.DEVNULL`; `grep -c` over
      the four source files shows no remaining inherited-stdin spawn.
- [ ] `_run_argv` still delivers a supplied stdin payload over `PIPE` (covered by
      an explicit test).
- [ ] One per-site assertion exists for each of the five sites and fails if the
      kwarg is removed.
- [ ] The socketpair regression fails against the pre-fix launcher and passes
      after the change.
- [ ] `background.py`'s two sites still pass `start_new_session=True` and
      `stderr=asyncio.subprocess.STDOUT`.
- [ ] No linting errors: `ruff check` on every modified file.

---

## Validation Commands

> File-level pytest only — no directories, no package roots.

- `pytest packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_google_coding_dispatcher.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_merge_scope_and_bg_wait.py -q`
- `pytest packages/ai-parrot/tests/tools/repo/test_readonly_toolkit.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/test_codex_dispatcher.py -q`

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_llm_code_dispatcher.py (additions)
import asyncio

import pytest


class TestRunArgvStdinIsolation:
    @pytest.mark.asyncio
    async def test_run_argv_without_payload_uses_devnull(self, monkeypatch, tmp_path):
        """fd 0 is the JSON-RPC channel: a child must never inherit it."""
        captured: dict = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            raise FileNotFoundError("stop before spawning")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
        # FILL IN: build the dispatcher the way this module's other tests do and
        # await _run_argv(["ls"], cwd=str(tmp_path), timeout=5)
        assert captured["kwargs"]["stdin"] is asyncio.subprocess.DEVNULL

    @pytest.mark.asyncio
    async def test_run_argv_with_payload_still_uses_pipe(self, monkeypatch, tmp_path):
        """A supplied payload must still reach the child over a real pipe."""
        # FILL IN: same harness, stdin="hello"
        assert captured["kwargs"]["stdin"] is asyncio.subprocess.PIPE

    @pytest.mark.asyncio
    async def test_child_cannot_eof_parents_socketpair_stdin(self, tmp_path):
        """Integration regression for issue:995ad869e502.

        The parent holds a socketpair as its own fd 0 — exactly the shape Claude
        Code gives a stdio MCP server — and spawns a real child through the
        production launcher. The child shuts fd 0 down; the parent's read must
        still block rather than return b"" (which is what made the server exit).
        """
        # FILL IN: absolute PYTHONPATH + samefile guard (see issue:bde3a98caed2)
```
