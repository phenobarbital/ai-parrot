# TASK-3125: Integration suite — end-to-end chunk in a git sandbox, MCP server build, opt-in live Gemini round-trip

**Feature**: FEAT-549 — `sdd-worker` as Orchestrator of Parallel `sdd-coder` Sub-Agents
**Spec**: `sdd/specs/sdd-worker-subagents.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3118, TASK-3122
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 and §4 Integration Tests. Unit tests live with their modules
(TASK-3115…3122); this task adds what only makes sense across modules: a full chunk
through `SddCoderToolkit` → engine → fake dispatchers → real git sandbox (AC-1, AC-13,
AC-14, AC-15), the `parrot mcp-local` server build from the tracked example yaml (AC-3),
the FEAT-323 regression run (AC-16), and the **opt-in** live Gemini round-trip that guards
the `thought_signature` fix (AC-4; marker `live`, skipped without `GEMINI_API_KEY`).

---

## Scope

- `test_integration_chunk.py`: two-wave index, 3-seat roster, fake dispatcher builder that really writes files and commits in the attempt worktree; asserts concurrency (overlapping timestamps), sequential merges, journal, Redis-absent single warning, orphan listing.
- `test_mcp_local_serves_sdd_coder` from `examples/sdd-coder-mcp.yaml`.
- `test_gemini_compat_live_roundtrip` (`@pytest.mark.live`, skip without key) using `GoogleCompatCodeDispatcher` primitives.
- Register the `live` marker in `packages/ai-parrot/pyproject.toml` `[tool.pytest.ini_options]` if not present.
- Run the full `tests/flows/dev_loop` suite and record the result in the Completion Note.

**NOT in scope**: new production code (fix defects found here in the owning task's file, noting it in the Completion Note), docs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py` | CREATE | end-to-end sandbox tests |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py` | CREATE | server build from example yaml |
| `packages/ai-parrot/tests/flows/dev_loop/test_google_compat_live.py` | CREATE | opt-in live round-trip |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `markers = ["live: needs provider credentials; opt-in with -m live"]` (only if `markers` absent) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
import asyncio, json, os, time
from pathlib import Path
import pytest
from parrot.flows.dev_loop.sdd_coder import SddCoderToolkit, SddCoderEngine, RosterConfig, RosterSeat, RosterProbe   # TASK-3115..3122
from parrot.flows.dev_loop.models import DevelopmentOutput, LLMCodeDispatchProfile          # verified: models/__init__.py
from parrot.flows.dev_loop.dispatchers import DispatchExecutionError                       # verified: dispatchers/__init__.py:37-49
from parrot.mcp.toolkit_server import create_toolkit_mcp_server                             # verified: toolkit_server.py:29 (config_path override at :69)
from parrot.flows.dev_loop import GoogleCompatCodeDispatcher, GoogleCompatCodeDispatchProfile   # TASK-3118
from navconfig import config                                                                # verified in use: google/client.py:189
```

### Existing Signatures to Use
```python
# pyproject.toml:964-965   [tool.pytest.ini_options]  asyncio_mode = "auto"     (async tests need no decorator)
# tests/flows/dev_loop/test_worktree_manager.py:16-52  _run_git(*args, cwd), _write_and_commit(repo, filename, content, message), git_sandbox fixture
# tests/flows/dev_loop/sdd_coder/conftest.py (TASK-3120)  git_sandbox_feature → (worktree, feature_branch, base_path, index_path); three_seat_roster; noop_probe
# tests/flows/dev_loop/test_agent_pool.py:23-80  FakeDispatcher shape: async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, **kw)
# StdioMCPServer (parrot/mcp/local_server.py:36) — tools registered on the server object; read :36-60 for the attribute holding them (unverified — check before use)
# GoogleCompatCodeDispatcher (TASK-3118): _create_compat_client(llm, model_args=None) → client with async _chat_completion(model, messages, use_tools=True, **kwargs);
#   _completion_args(profile, tools); _tool_call_to_openai_dict(call); LLMCodeDispatcher._tool_schemas(output_model) (llm.py:1123); _response_message/_message_tool_calls (llm.py:2143-2160)
```

### Does NOT Exist
- ~~network access in the default test run~~ — every non-`live` test uses fakes; `live` is opt-in.
- ~~`GEMINI_API_KEY` in `os.environ`~~ — read via `config.get("GEMINI_API_KEY")`; skip when falsy.
- ~~a pytest `live` marker today~~ — check `pyproject.toml` `[tool.pytest.ini_options]` for `markers`; add only if missing (`--strict-markers` may be on).
- ~~`DevAgentPool` in the assertions~~ — the engine does not use it; assert on the fake dispatcher's captured `cwd` per attempt instead.

---

## Implementation Notes

### Key Constraints
- The fake dispatcher must do real work in `cwd`: write the task's listed file, `git add`, `git commit` — so fidelity + merge paths are exercised for real.
- Concurrency proof: each fake records `(start, end)` monotonic times; assert at least one pair overlaps for a 3-task chunk.
- Redis: construct with `redis_url="redis://127.0.0.1:1/0"`; assert with `caplog` that at most one WARNING mentions Redis after a full chunk (AC-15). If the dispatchers still warn per event, log the finding for the engine task (open a Completion Note deviation) rather than silencing here.
- Live test: one `read_file` tool call → echo assistant turn via `_tool_call_to_openai_dict` (with `extra_content`) → tool result → second completion must return `finish_reason == "stop"` (spec §6 variant C).

### References in Codebase
- spec §6 "Spike evidence" — the exact live sequence to reproduce.
- `docs/mcp-local-toolkits.md` — `parrot mcp-local --list` behaviour if the server-build test needs it.

---

## Implementation Blueprint

### Steps (in order)
1. `test_integration_chunk.py` — *why*: AC-1/13/14/15 need the real git + toolkit path, not unit fakes.
2. `test_mcp_local.py` — *why*: AC-3's "server lists exactly seven tools" is only true if `examples/sdd-coder-mcp.yaml` and the class path are right.
3. `test_google_compat_live.py` + marker — *why*: AC-4 regression guard for the 400 that the spike found.
4. Full `pytest packages/ai-parrot/tests/flows/dev_loop -v` (AC-16) and `-m live` manually once; paste both summaries in the Completion Note.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_integration_chunk.py` (CREATE — skeleton)
```python
"""End-to-end: toolkit → engine → fake dispatchers → real git sandbox (FEAT-549 AC-1, AC-13, AC-14, AC-15)."""
from __future__ import annotations

import asyncio, time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from parrot.flows.dev_loop.dispatchers import DispatchExecutionError
from parrot.flows.dev_loop.models import DevelopmentOutput, LLMCodeDispatchProfile
from parrot.flows.dev_loop.sdd_coder import RosterConfig, RosterSeat, SddCoderEngine, SddCoderToolkit

from .conftest import run_git  # FILL IN: expose the async git helper from conftest (TASK-3120)


class CommittingFakeDispatcher:
    """Writes the task's listed file in `cwd`, commits, returns DevelopmentOutput. Records timing + cwd per call."""

    def __init__(self, label: str, mode: str = "ok") -> None:
        self.label, self.mode, self.calls = label, mode, []   # calls: list of dict(cwd, start, end, subagent)

    async def dispatch(self, *, brief, profile, output_model, run_id, node_id, cwd, session_host=None, labels=None):
        start = time.monotonic(); await asyncio.sleep(0.05)
        # FILL IN: if self.mode == "fail": raise DispatchExecutionError(f"{self.label} down")
        #          target = f"pkg/{brief.task_id.lower()}.py" (must match the fixture's listed path); write + `git add -A` + `git commit -m feat(...)` in cwd via run_git
        #          if self.mode == "extra": also write pkg/extra.py before committing; if self.mode == "dirty": write pkg/untracked.py AFTER committing
        self.calls.append(dict(cwd=cwd, start=start, end=time.monotonic(), subagent=profile.subagent))
        return DevelopmentOutput(files_changed=[], commit_shas=[], summary=f"{self.label} done")


def make_builder(modes: Dict[str, str]):
    fakes: Dict[str, CommittingFakeDispatcher] = {}
    def builder(spec, *, redis_url, max_concurrent, stream_ttl_seconds, **_):
        fake = fakes.setdefault(spec.agent, CommittingFakeDispatcher(spec.agent, modes.get(spec.agent, "ok")))
        return fake, LLMCodeDispatchProfile()
    return builder, fakes


async def test_full_chunk_merges_and_runs_concurrently(git_sandbox_feature, three_seat_roster, noop_probe, caplog):
    worktree, feature_branch, base_path, _ = git_sandbox_feature
    builder, fakes = make_builder({})
    engine = SddCoderEngine(roster=three_seat_roster, probe=noop_probe, redis_url="redis://127.0.0.1:1/0",
                            worktree_base_path=str(base_path), dispatcher_builder=builder)
    plan = await engine.plan("FEAT-549", str(worktree))
    ids = [t.task_id for t in plan.chunks[0].tasks if not t.native]
    job = await engine.run_chunk("FEAT-549", str(worktree), ids)
    done = await engine.wait(job.job_id, 30)
    assert done.state == "done" and {t.outcome for t in done.tasks} == {"merged"}
    # FILL IN: assert every fake call's cwd startswith(str(base_path)) and contains "-a1"; assert overlap between two calls (AC-1);
    #          assert `git log --oneline feature_branch` gained len(ids) commits; assert (worktree/".sdd-coder/jobs"/f"{job.job_id}.json").exists();
    #          assert sum("redis" in r.message.lower() for r in caplog.records if r.levelname == "WARNING") <= 1  (AC-15)


async def test_partial_completion_and_orphans(git_sandbox_feature, three_seat_roster, noop_probe): ...
    # FILL IN: modes {"nova": "fail", "codex": "extra"} ⇒ one task retried on another seat (attempts 2, distinct labels), one fidelity_violation kept as branch;
    #          a subsequent plan() lists the kept branch in orphan_branches (AC-14) and pending still contains it


async def test_merge_conflict_leaves_feature_clean(git_sandbox_feature, three_seat_roster, noop_probe): ...
    # FILL IN: two tasks whose listed file is the SAME path with different content ⇒ second is merge_conflict; `git status --porcelain` in worktree == "" (AC-13)
```
**Why this shape**: the fake is the only test double — everything else (engine, worktrees, merges, journal) is real, which is what makes the S1/S5 guarantees observable.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_mcp_local.py` (CREATE)
```python
from pathlib import Path
from parrot.flows.dev_loop.sdd_coder import roster as roster_mod
from parrot.mcp.toolkit_server import create_toolkit_mcp_server

EXPECTED = {f"coder_{n}" for n in ("plan", "run_chunk", "prepare_native", "merge", "wait", "status", "cleanup")}

def test_mcp_local_serves_sdd_coder(monkeypatch):
    async def fake_probe(self, roster):  # all seats available, no network
        return [roster_mod.SeatProbeResult(label=s.label, kind=s.kind, backend=s.backend, available=True, model_used=s.model) for s in roster.seats]
    monkeypatch.setattr(roster_mod.RosterProbe, "probe", fake_probe)
    server = create_toolkit_mcp_server("sdd-coder", root=Path("."), config_path="examples/sdd-coder-mcp.yaml")
    # FILL IN: read local_server.py:36-60 for the registry attribute; assert {t.name for t in <tools>} == EXPECTED
```

### `packages/ai-parrot/tests/flows/dev_loop/test_google_compat_live.py` (CREATE)
```python
import json, pytest
from navconfig import config
from parrot.flows.dev_loop import GoogleCompatCodeDispatcher, GoogleCompatCodeDispatchProfile
from parrot.flows.dev_loop.models import DevelopmentOutput

pytestmark = pytest.mark.live

@pytest.mark.skipif(not (config.get("GEMINI_API_KEY") or config.get("GOOGLE_API_KEY")), reason="needs GEMINI_API_KEY (opt-in live test)")
async def test_gemini_compat_live_roundtrip():
    d = GoogleCompatCodeDispatcher(max_concurrent=1, redis_url="redis://127.0.0.1:1/0", stream_ttl_seconds=60)
    profile = GoogleCompatCodeDispatchProfile()
    client = d._create_compat_client(profile.llm, model_args={"temperature": 0.0, "max_tokens": 256})
    tools = d._tool_schemas(DevelopmentOutput); args = d._completion_args(profile, tools)
    messages = [{"role": "system", "content": "You are a coding agent. Use tools."}, {"role": "user", "content": "Read README.md now."}]
    r1 = await d._chat_completion(client=client, model=profile.model, messages=messages, args=args)
    calls = d._message_tool_calls(d._response_message(r1)); assert calls, "expected a tool call"
    messages.append({"role": "assistant", "content": "", "tool_calls": [d._tool_call_to_openai_dict(c) for c in calls]})
    messages += [{"role": "tool", "tool_call_id": d._tool_call_id(c), "content": json.dumps({"content": "# README"})} for c in calls]
    r2 = await d._chat_completion(client=client, model=profile.model, messages=messages, args=args)   # would be HTTP 400 without extra_content
    assert d._finish_reason(r2) in ("stop", "tool_calls")
```
**Why**: reproduces spec §6 variant C through the dispatcher's own primitives, so a regression in `_tool_call_to_openai_dict` fails here first.

### `packages/ai-parrot/pyproject.toml` (MODIFY — only if no `markers` key exists)
```toml
# occurrences: 1 (verified: grep -c '^asyncio_mode = "auto"$' packages/ai-parrot/pyproject.toml)
# AFTER — insert below `asyncio_mode = "auto"` (verified: pyproject.toml:965)
markers = ["live: needs provider credentials; opt-in with -m live"]
```

### FILL IN checklist
- [ ] `CommittingFakeDispatcher.dispatch` modes; bounded by AC-1/AC-13/AC-14/AC-22
- [ ] server tool-registry attribute; bounded by `local_server.py:36-60`
- [ ] `pyproject.toml` marker only when absent (check `grep -n markers`)

---

## Acceptance Criteria

- [ ] Full chunk: 3 tasks `merged`, overlapping dispatch intervals, 3 new commits on the feature branch, journal file present, ≤ 1 Redis warning (AC-1, AC-15).
- [ ] Partial: retry on a different seat recorded; `fidelity_violation` branch kept and listed as orphan on the next plan (AC-14).
- [ ] Conflict: feature worktree clean after `merge_conflict` (AC-13).
- [ ] `create_toolkit_mcp_server("sdd-coder", config_path="examples/sdd-coder-mcp.yaml")` lists exactly the seven tools (AC-3).
- [ ] `pytest packages/ai-parrot/tests/flows/dev_loop -v` passes with no regression in FEAT-323 suites (AC-16); `pytest -m live packages/ai-parrot/tests/flows/dev_loop/test_google_compat_live.py` passes once with credentials (paste output in the Completion Note) (AC-4).

---

## Test Specification

See the blueprint blocks above (the tests ARE the deliverable).

---

## Agent Instructions

1. **Read the spec** §4 Integration Tests, §5 AC-1/3/4/13/14/15/16, §6 Spike evidence.
2. **Check dependencies** — TASK-3118 and TASK-3122 completed.
3. **Verify the Codebase Contract** — read `local_server.py:36-60`, `conftest.py` from TASK-3120, `pyproject.toml:960-975`.
4. **Update status** in the per-spec index → `"in-progress"`.
5. **Implement**; run the default suite AND the live test once.
6. **Verify** all acceptance criteria; record both pytest summaries in the Completion Note.
7. **Move this file** to `sdd/tasks/completed/TASK-3125-sdd-coder-integration-tests.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
