# TASK-5621: activate_expert mode + expert.* span attributes

**Feature**: FEAT-890 — Expert stages, dispatch modes, generic gate host and SDD expert delegation
**Spec**: `sdd/specs/expert-stages-and-delegation.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: S
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2.4 / Module 6, AC10. OpenTelemetry is an optional extra (`opentelemetry-api` is listed in an extra in packages/ai-parrot/pyproject.toml:846), so attribute setting must degrade to a no-op when it is not installed.

---

## Scope

- Add keyword `mode: str | None = None` to `activate_expert` (default keeps every caller working).
- Inside the context set `expert.slug`, `expert.tier`, `expert.stage`, `expert.mode` on the current span via a guarded import of `opentelemetry.trace`.
- Tests with and without opentelemetry (monkeypatch the import).

**NOT in scope**: tier→seat (TASK-5626).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/experts/activation.py` | MODIFY | mode kwarg + span attrs |
| `packages/ai-parrot/tests/experts/test_activation_otel.py` | CREATE | tests |

---

## Codebase Contract

> Verified against `6adcc8976e` (dev). Re-check line numbers before editing.

### Verified Imports
```python
from parrot.observability.context import agent_identity, usage_attribution  # verified: context.py:89,184 (already imported by activation.py)
```

### Existing Signatures to Use
```python
async def activate_expert(expert: "ExpertAgent", *, run_id: str | None, stage: str | None) -> AsyncIterator["ExpertAgent"]  # activation.py:15
# body: name = expert.bundle.manifest.name; seat = f"{stage}.{name}" if stage else name; with agent_identity(name), usage_attribution(run_id, seat): yield expert
```

### Does NOT Exist
- ~~`parrot.flows.dev_loop` imports inside `parrot/bots/flows/core/gates/` or `parrot/experts/`~~ — forbidden (spec Decisions `gate-core-independent-of-dev-loop`).
- ~~HelixDB client / `HelixGateStore`~~ — no client in the repo; spec §8 Q1 open — do NOT implement.
- ~~`ExpertManifest.stage`~~, ~~`RosterSeat.tier`~~, ~~`WikiSource.remember`~~, ~~`DecisionService.propose`/`.record`~~ — do not exist.
- ~~`expert.*` span attributes~~ — none exist anywhere yet.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/experts/activation.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/experts/test_activation_otel.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/experts/activation.py#activate_expert"
  ]
}
```

---

## Implementation Notes

- Conventions: `.claude/rules/codebase-conventions.md` (Pydantic v2, Google docstrings, `self.logger`, async I/O, no print).
- Worktree tests need `PYTHONPATH=packages/ai-parrot/src` (plus `packages/ai-parrot-integrations/src` / `packages/ai-parrot-tools/src` when touched).

---

## Implementation Blueprint

### Steps (in order)
1. Edit signature + body.
2. Add helper.
3. Tests.

### Blocks

```python
# packages/ai-parrot/src/parrot/experts/activation.py  (MODIFY)
# AFTER — signature of `async def activate_expert(` (verified: activation.py:15; occurrences: 1)
async def activate_expert(
    expert: "ExpertAgent", *, run_id: str | None, stage: str | None, mode: str | None = None
) -> AsyncIterator["ExpertAgent"]:
    ...
        with agent_identity(name), usage_attribution(run_id, seat):
            _set_expert_span_attributes(name, expert.bundle.manifest.tier.value, stage, mode)
            yield expert

def _set_expert_span_attributes(slug: str, tier: str, stage: str | None, mode: str | None) -> None:
    """Best-effort OTEL attributes; no-op without opentelemetry or a recording span."""
    try:
        from opentelemetry import trace
    except ImportError:
        return
    # FILL IN: span = trace.get_current_span(); skip None values; set the four expert.* attributes
```
**Why**: `tier.value` gives the lowercase enum value (ExpertTier is a str Enum, models.py:74).

### FILL IN checklist
- [ ] attribute setting
- [ ] tests (in-memory span exporter if opentelemetry-sdk is present, else monkeypatched trace)

---

## Acceptance Criteria

- [ ] AC10.
- [ ] Existing `test_agent_activation.py` passes.

## Validation Commands
- `pytest packages/ai-parrot/tests/experts/test_activation_otel.py -q`
- `pytest packages/ai-parrot/tests/experts/test_agent_activation.py -q`

---

## Agent Instructions

1. Verify the Codebase Contract before writing code; fix stale entries in this file first.
2. Implement only the files listed above.
3. Run `ruff check --fix` on touched files and the Validation Commands.
4. Commit code, then close the task with `parrot sdd task close TASK-5621 expert-stages-and-delegation verified`.

---

## Completion Note


- Task: TASK-5621
- Feature: expert-stages-and-delegation
- Implementation SHA: ee29b636b6966482af372aabf320a238b1242fbf
- Closed at (UTC): 2026-11-13T22:01:20+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| seat_summary | Seat: gpt-5.6-sol · Backend: codex · Model: gpt-5.6-sol · Attempts: 1 · Duration: 166.5s · Tokens: n/a |
