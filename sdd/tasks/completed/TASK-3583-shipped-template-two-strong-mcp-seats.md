# TASK-3583: Stop shipping the roster that reproduces the zero-retry defect

**Feature**: FEAT-588 — Make the sdd-coder retry ladder reachable for complex/unknown tasks
**Spec**: `sdd/specs/fixgroup-47eb801095a6.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

**Discovered-from**: `issue:569e81756247` (ledger, severity major)

---

## Context

Implements spec §3 **Module 4** and goal **G4**.

The shipped toolkit template
(`packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml:31-34`)
declares `complexity.strong_models` as exactly
`{(codex, gpt-5.6-terra), (native, sonnet)}` — **one** MCP strong seat plus one
native strong seat. Since both retry selectors skip `kind: native`, every
complex/unknown task that starts on `gpt-5.6-terra` has an empty retry set. The
default configuration is the reproducing configuration, so every fresh install
hits this.

The operator's own `.parrot/mcp-toolkits.yaml` was already mitigated by hand on
2026-09-21 (a second strong MCP seat, `gpt-5.6-luna`, backend `codex` —
`.parrot/mcp-toolkits.yaml:106,114`), but that file is gitignored and
per-machine, so it fixes nothing for anyone else.

This is **defence in depth, not the fix**: with TASK-3580 landed, a
single-MCP-strong-seat roster retries onto the native seat instead of blocking.
Both are worth having — the template should not ship a roster that depends on
the fallback path to work at all.

---

## Scope

- Add a second strong **MCP** seat to the shipped template's `roster` list and
  to `complexity.strong_models`, mirroring the operator mitigation
  (`gpt-5.6-luna`, `kind: mcp`, `backend: codex`).
- Add a comment stating **why** two MCP strong seats are required — the retry
  ladder skips native seats, so one MCP strong seat means zero retries — so a
  future edit does not quietly drop back to one.
- Add a regression test asserting the shipped template resolves to at least two
  retry-capable (non-native) strong seats.

**NOT in scope**:
- `.parrot/mcp-toolkits.yaml` — gitignored, per-machine, already mitigated.
- Adding a `google_coding` seat. That backend is blocked by
  `issue:e7bdce192812` (`agy --sandbox` cannot read the schema the dispatcher
  writes to the host temp dir) — spec NG4. Do not add a seat that the probe
  will drop.
- Any engine, pool or model change — TASK-3580 and TASK-3582 own those files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` | MODIFY | Second strong MCP seat + rationale comment |
| `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py` | MODIFY | Regression test over the shipped template |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `b366bd774` on 2026-09-21.

### The template as it stands (`_toolkit_templates/sdd-coder.yaml:22-34`)
```yaml
      roster:
        - {label: qwen,        kind: mcp,    backend: nova,          model: qwen.qwen3-coder-480b-a35b-instruct}
        - {label: gemini,      kind: mcp,    backend: google-compat, model: gemini-3.5-flash}
        - {label: codex-spark, kind: mcp,    backend: codex,         model: gpt-5.3-codex-spark}
        - {label: haiku,       kind: native, model: haiku}
        - {label: gpt-5.6-terra, kind: mcp,  backend: codex,         model: gpt-5.6-terra}
        - {label: sonnet,      kind: native, model: sonnet}
      complexity:
        strong_models:
          - {canonical_model: gpt-5.6-terra, backend: codex, model: gpt-5.6-terra}
          - {canonical_model: sonnet-5, backend: native, model: sonnet}
```

### The operator mitigation to mirror (`.parrot/mcp-toolkits.yaml:106,114` — gitignored)
```yaml
        - {label: gpt-5.6-luna, kind: mcp,   backend: codex,         model: gpt-5.6-luna}
          - {canonical_model: gpt-5.6-luna, backend: codex, model: gpt-5.6-luna}
```

### Existing Imports available in the test module (`test_roster.py:1-15`)
```python
from parrot.flows.dev_loop.sdd_coder import ChunkAssigner, RosterConfig, RosterProbe, RosterSeat, available_seats
from parrot.flows.dev_loop.sdd_coder.roster import eligible_seats
from parrot.flows.dev_loop.sdd_coder.complexity_models import (
    ComplexityAssessment, ComplexityContract, ComplexityEvidence, ComplexityPolicy, StrongModelIdentity,
)
```

### Does NOT Exist
- ~~any test that reads `_toolkit_templates/sdd-coder.yaml`~~ — `grep -rln '_toolkit_templates\|sdd-coder.yaml' packages/ai-parrot/tests/` returns nothing. Yours is the first; do not look for a helper to reuse.
- ~~`RosterConfig.from_template()` / a template loader helper~~ — no such API. Read the YAML in the test (`yaml.safe_load`) and assert on the parsed mapping, or build a `RosterConfig` from it.
- ~~`RosterConfig.strong_models`~~ — nested as `complexity.strong_models`.
- ~~a `gemini-3.8-flash-high` / `google_coding` strong seat~~ — deliberately absent; blocked by `issue:e7bdce192812` (spec NG4).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py",
      "action": "MODIFY"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/roster.py#eligible_seats",
    "sym:packages/ai-parrot/src/parrot/flows/dev_loop/sdd_coder/models.py#RosterConfig"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Keep the file's existing alignment style — the roster entries are
  column-aligned flow mappings; match them.
- A seat must appear in **both** `roster` and `complexity.strong_models` to be
  eligible: `eligible_seats()` matches on the exact `(backend, model)` pair.
  Adding it to only one list silently does nothing.
- The template is YAML the MCP layer loads; keep it valid and parseable. Verify
  with `python -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]))" <path>`.

### References in Codebase
- `roster.py:241-280` `eligible_seats` — exactly how `(backend, model)` is matched,
  including `backend = "native" if seat.kind == "native"`.

---

## Implementation Blueprint

### Steps (in order)
1. Add the seat to `roster` — *why*: a model identity that is not a seat can
   never be probed or dispatched.
2. Add the matching identity to `complexity.strong_models` — *why*:
   `eligible_seats()` admits a seat only if its exact `(backend, model)` pair is
   listed; one without the other is a no-op.
3. Add the rationale comment — *why*: the previous single-strong-seat roster
   looked deliberate, which is how it survived; the next editor needs the reason.
4. Add the regression test — *why*: a comment does not fail CI.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` (MODIFY — roster)
```yaml
# occurrences: 1 (verified: grep -c -F '        - {label: gpt-5.6-terra, kind: mcp,  backend: codex,         model: gpt-5.6-terra}' packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml)
# AFTER — insert below `        - {label: gpt-5.6-terra, kind: mcp,  backend: codex,         model: gpt-5.6-terra}` (verified: sdd-coder.yaml:28)
        # A SECOND strong MCP seat is required, not optional: the retry ladder
        # (`SddCoderEngine._select_retry_seat`, `ChunkAssigner.retry_seat`) skips
        # `kind: native`, so with only one strong MCP seat a complex/unknown task
        # that fails attempt 1 has an empty retry set (issue:569e81756247).
        - {label: gpt-5.6-luna, kind: mcp,   backend: codex,         model: gpt-5.6-luna}
```
**Why**: mirrors the operator's verified mitigation. `codex` needs no extra
credentials beyond the CLI login the template already documents, so this adds
no new setup burden.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` (MODIFY — allowlist)
```yaml
# occurrences: 1 (verified: grep -c -F '          - {canonical_model: sonnet-5, backend: native, model: sonnet}' packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml)
# AFTER — insert below `          - {canonical_model: sonnet-5, backend: native, model: sonnet}` (verified: sdd-coder.yaml:34)
          - {canonical_model: gpt-5.6-luna, backend: codex, model: gpt-5.6-luna}
```
**Why**: `eligible_seats()` matches the exact `(backend, model)` pair, so the
seat added above is inert until it is listed here too.

### `packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py` (MODIFY)
```python
# AFTER — add a module-level test at the end of the file
def test_shipped_template_has_two_retry_capable_strong_seats():
    """FEAT-588 AC-8: the default roster must not be the zero-retry roster.

    The retry ladder skips `kind: native`, so a template whose strong-model
    allowlist resolves to one MCP seat gives every complex/unknown task an
    empty retry set (issue:569e81756247).
    """
    # FILL IN: locate the packaged template, yaml.safe_load it, resolve the
    # seats whose (backend, model) appear in complexity.strong_models, and
    # assert at least two of them have kind != "native" — bounded by AC-1.
    # Prefer importlib.resources over a hand-built relative path so the test
    # keeps working from an installed wheel.
    raise NotImplementedError
```
**Why**: asserting on *retry-capable* seats (non-native strong seats), not on a
seat count or a specific label, keeps the test meaningful if the roster is later
re-shuffled or `gpt-5.6-luna` is swapped for another model.

### FILL IN checklist
- [ ] the regression test body

---

## Acceptance Criteria

- [ ] AC-1 — the shipped template resolves to at least two strong seats with `kind != "native"`.
- [ ] AC-2 — the added seat appears in **both** `roster` and `complexity.strong_models` with an identical `(backend, model)` pair.
- [ ] AC-3 — the template still parses as valid YAML.
- [ ] AC-4 — a comment in the template states why two MCP strong seats are required, citing the retry ladder.
- [ ] AC-5 — no `google_coding` seat was added (spec NG4).
- [ ] `ruff check` and `black --check` clean on the test file.

## Validation Commands
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py -q`
- `pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_complexity_routing.py -q`

---

## Output

### Completion Note
(Agent fills this in when done)

## Completion Note

- Task: TASK-3583
- Feature: fixgroup-47eb801095a6
- Implementation SHA: 63dde6449e69462339a8f954abef1a9fb9e7acd0
- Closed at (UTC): 2026-09-21T22:10:11+00:00
- Fix commits: none

| Metric | Value |
|---|---|
| validation_refs | 1 |
| fix_commits | 0 |
| ac_verification | AC-1..AC-4 verified: second strong MCP seat gpt-5.6-luna added to both roster and complexity.strong_models with matching (backend,model) pair; YAML parses cleanly; rationale comment present citing issue:569e81756247; AC-5 respected (no google_coding seat added); test_shipped_template_has_two_retry_capable_strong_seats reuses the real eligible_seats() rather than a hand-rolled rule |
| merge_tier_validation | coder_run_validation (tier=merge, TASK-3582+TASK-3583) timed_out after 180s -- same deterministic pre-existing hang in packages/ai-parrot-integrations/tests/integrations/telegram/test_oauth2_integration.py already confirmed unrelated and filed as issue:1dbb2aac09ba |
| review_feedback_id | coder-review:c94222b1879ef486e84fe6ea |
| seat_summary | Seat: sonnet(native) · Backend: native · Model: sonnet · Attempts: 1 · Duration: 230.77s · Tokens: 112182(subagent total, 34 tool uses) |
| task_scoped_tests | pytest packages/ai-parrot/tests/flows/dev_loop/sdd_coder/test_roster.py test_complexity_routing.py -> 118 passed combined |
