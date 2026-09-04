# TASK-2839: Smoke script + client documentation

**Feature**: FEAT-526 — Meta Model API (Muse Spark) LLM Client
**Spec**: `sdd/specs/meta-llm-client.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2837
**Assigned-to**: unassigned

---

## Context

Completes **Module 5** and satisfies step 7 of the seven-step recipe in
`docs/clients/openai-compatible.md` ("Add a smoke script … and a doc page if the
provider has enough provider-specific surface to warrant one"). Meta clearly
qualifies: a second protocol, a training-consent tier, and a reasoning-budget
gotcha all need documenting.

Touches only two new files, so it can run in a separate worktree if desired.

---

## Scope

- `examples/clients/smoke/smoke_meta.py` following the existing `main_for(...)`
  one-liner pattern.
- `docs/clients/meta.md` following `docs/clients/bedrock-mantle.md`'s structure.

**NOT in scope**: any production-code change; the live pytest suite (TASK-2838).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `examples/clients/smoke/smoke_meta.py` | CREATE | Credential-gated smoke script |
| `docs/clients/meta.md` | CREATE | Client documentation |

---

## Codebase Contract (Anti-Hallucination)

### Verified smoke-runner API
```python
# examples/clients/smoke/_runner.py
def calculator(expression: str) -> str                # :37  shared tool fixture
class LegResult                                       # :54
class SmokeResult                                     # :63
def check_env_vars(env_vars: list[str]) -> str | None # :77
async def _run_leg(name: str, coro) -> LegResult      # :94
async def run_smoke(...)                              # :102
def print_summary(result: SmokeResult) -> int         # :181
def main_for(provider=..., model=..., env_vars=[...]) # :196
```

### THE EXACT PATTERN — `smoke_openrouter.py` (complete file, verified)
```python
"""FEAT-438 smoke script — OpenRouter (OpenRouterClient)."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="openrouter",
        model="deepseek/deepseek-r1",
        env_vars=["OPENROUTER_API_KEY"],
    )
```
Each script runs three legs: `ask()`, `ask()` + one `@tool`, and `invoke()`;
skips cleanly with `SKIPPED (no <ENV_VAR>)` and exit 0 when creds are absent.

Existing peers: `smoke_{groq,mantle,moonshot,nvidia,openai,openrouter,vllm_local,zai}.py`

### Does NOT Exist
- ~~A pytest-based smoke script~~ — these are **plain scripts**, never wired
  into CI. Run manually: `python examples/clients/smoke/smoke_meta.py`.
- ~~`docs/clients/meta.md`~~ — you are creating it.
- ~~`MODEL_API_KEY` in this environment~~ — gate on `META_API_KEY`.

---

## Implementation Notes

### Smoke script
Use `main_for(provider="meta", model="muse-spark-1.3-contributor",
env_vars=["META_API_KEY"])`. Put the Contributor-tier warning in the module
docstring so nobody adopts the model id by copy-paste without seeing it.

### `docs/clients/meta.md` MUST cover
1. **Quickstart** — `LLMFactory.create("meta:muse-spark-1.3")` inside
   `async with client:`.
2. **Credentials** — the `api_key` → `META_API_KEY` → `MODEL_API_KEY` chain, and
   the explicit warning that it never falls back to `OPENAI_API_KEY`.
3. **⚠️ The reasoning-budget gotcha** — measured live, 199 of 210 output tokens
   were reasoning for a one-word answer; a low `max_tokens` yields empty visible
   text. State the raised default and why. *This is the single most useful
   paragraph in the document.*
4. **⚠️ Contributor tier** — `-contributor` models grant Meta permission to
   train on prompts and completions. Synthetic/test prompts only; never a
   default.
5. **The two protocols** — what `use_responses` selects, and the capability
   table (search grounding and token counting are Responses-only).
6. **Constraints** — `tool_choice` must be `"auto"`; `logprobs` unsupported;
   `reasoning_content` redacted; annotations observed empty.
7. **Model catalog** — the 7 live-verified ids and the 1,048,576 context window.

### Worktree gotcha (include in the doc)
Running a smoke script directly from inside `.claude/worktrees/<feature>/` will
silently import the **main** checkout's code — the editable-install `.pth`
entries point there. Prepend the worktree's `src` dirs via `PYTHONPATH` and
ensure the compiled `.so` files exist before trusting results.

---

## Acceptance Criteria

> **Correction discovered during implementation**: the "ask" leg CANNOT
> report PASS for Muse Spark — see the Completion Note. Verified live on
> both wire protocols; not a `MetaClient` defect, and out of scope to fix
> (would require editing the shared `_runner.py`).

- [ ] `python examples/clients/smoke/smoke_meta.py` exits 0 with `SKIPPED`
      when `META_API_KEY` is unset.
- [ ] With credentials, all three legs report `PASS`.
- [ ] The script uses `main_for(...)` — no bespoke runner logic.
- [ ] `docs/clients/meta.md` covers all seven points above.
- [ ] The reasoning-budget gotcha and the Contributor-tier warning are both
      present and prominent.
- [ ] `ruff check examples/clients/smoke/smoke_meta.py` clean.

---

## Test Specification

No unit tests — these are documentation and a manual script. Verify by running:
```bash
python examples/clients/smoke/smoke_meta.py            # with creds -> 3x PASS
env -u META_API_KEY python examples/clients/smoke/smoke_meta.py   # -> SKIPPED, exit 0
```

---

## Agent Instructions

1. Read `docs/clients/openai-compatible.md` (step 7) and
   `docs/clients/bedrock-mantle.md` (structure to follow).
2. Confirm TASK-2837 is in `sdd/tasks/completed/`.
3. Implement, run the script both ways, verify acceptance criteria.
4. Move to `sdd/tasks/completed/`, set `done` in the index, fill the note.

---

## Completion Note

**Completed by**: sdd-worker (Claude)
**Date**: 2026-09-04
**Notes**: Created `examples/clients/smoke/smoke_meta.py` using the exact
`main_for(...)` one-liner pattern (no bespoke runner logic), and
`docs/clients/meta.md` covering all 7 required points plus the worktree
gotcha. `ruff` clean.

Ran the smoke script live with credentials:
```
[meta:muse-spark-1.3-contributor] ask        FAIL — AssertionError: ask() returned an empty response
[meta:muse-spark-1.3-contributor] ask+tool   PASS
[meta:muse-spark-1.3-contributor] invoke     PASS
```

**Deviations from spec**: **The "ask" leg cannot pass for Muse Spark, on
either wire protocol.** `_runner.py`'s shared `_ask_plain()` leg hardcodes
`max_tokens=64` (by design, shared across every provider's smoke script;
this task's scope explicitly forbids editing `_runner.py`). Verified live
during implementation that Muse Spark exhausts a 64-token budget on hidden
reasoning before emitting any visible text on **both** paths:
- Responses: `ask()` returns empty `.output` (no exception).
- Chat Completions: raises `openai.LengthFinishReasonError` — reasoning
  tokens: 61/64.

This is the live, first-hand reproduction of the exact F015 finding this
whole feature was built around (`docs/clients/meta.md`'s reasoning-budget
gotcha section exists specifically because of it) — not a `MetaClient`
defect, and not fixable without either editing the shared harness (out of
scope) or the model simply not being viable for a 64-token smoke check.
Documented prominently in `docs/clients/meta.md` (§ Smoke Script and Live
Tests) so nobody mistakes the "ask" FAIL for a regression. `ask+tool` and
`invoke` legs pass because they either allow a tool round trip (which
apparently better anchors the model into non-reasoning-dominant output for
this task's prompt) or use a below-the-radar simple reply. `AC17`
("all three legs PASS") is therefore not achievable as written for this
provider; a follow-up could add a `min_max_tokens` override parameter to
`run_smoke()`/`main_for()` in `_runner.py` for reasoning-heavy providers,
but that is a shared-file change outside this task's scope.

Also verified: could not empirically confirm the `SKIPPED` exit-0 path
locally, because `META_API_KEY` is defined in the main repo's `env/.env`
and loaded by `navconfig` independent of shell-level `env -u` removal —
the same limitation would apply to every existing sibling smoke script
using a key also present in `env/.env` (e.g. `OPENROUTER_API_KEY`). The
`check_env_vars()`/`main_for()` code path itself is unchanged from the
already-proven pattern used by 8 other smoke scripts, so this is a
test-environment limitation, not a code-correctness concern.
