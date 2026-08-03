# TASK-2093: Integration tests, opt-in regression guard & documentation

**Feature**: FEAT-405 — Nova (AWS Bedrock) Dispatcher & Per-Agent Usage Report
**Spec**: `sdd/specs/novaclient-dev-loop.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2088, TASK-2091, TASK-2092
**Assigned-to**: unassigned

---

## Context

Final task. The previous ten cover their own units; this one proves the pieces
work **together** and that the feature is genuinely additive.

The single most important deliverable here is the **opt-in regression guard**
([R3]): a run that configures nothing must behave byte-identically to
pre-feature. Every default in this feature was chosen to preserve existing
behaviour — `claude-code` still develops, `codex` still reviews adversarially,
`ResearchNode` is untouched — and that promise needs a test, not just prose.

Also documents the `nova` backend and its config keys for operators.

---

## Scope

- Write the four integration tests named in spec §4.
- Add an explicit assertion that `nodes/research.py` is unmodified by this
  feature (guards the [R7] scope cut against a well-meaning future agent).
- Document the `nova` backend in `docs/`: the three seats, the verified model
  ids, the two credential paths (SigV4 vs Bedrock API key), all `DEV_LOOP_NOVA_*`
  keys, and the `DEV_LOOP_ADVERSARIAL_BACKEND` selector.
- Document the FEAT-404 soft dependency: until it lands, Bedrock-backed seats
  render `—` for rounds and tokens.
- Run the full dev_loop suite plus `ruff`/`mypy` on every changed file.

**NOT in scope**: new production code (all modules are complete by now); FEAT-404
itself; changing any default.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/flows/dev_loop/test_nova_integration.py` | CREATE | The four integration tests + the research.py guard |
| `docs/dev_loop/nova-backend.md` | CREATE | Operator documentation (check the actual `docs/` layout first) |
| `.agent/CONTEXT.md` | MODIFY | One line noting the `nova` dev-loop backend, if the file lists backends |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.flows.dev_loop.agent_builder import build_dispatcher
from parrot.flows.dev_loop.catalog import catalog_payload
from parrot.flows.dev_loop.code_review import CodeReviewDispatcherFactory
from parrot.flows.dev_loop.dispatchers import NovaCodeDispatcher      # TASK-2086
from parrot.flows.dev_loop.models import DevAgentSpec, NovaCodeDispatchProfile
from parrot.flows.dev_loop.usage_report import UsageReport            # TASK-2090
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/flows/dev_loop/models/base.py
class DevAgentSpec(BaseModel):                                        # line 388
    agent: DevAgentBackend                                            # line 396
    model: str = ""     # '' ⇒ backend default
class DevAgentPoolConfig(BaseModel): ...   # verify its exact field names before use

# packages/ai-parrot/src/parrot/flows/dev_loop/catalog.py
def catalog_payload(config_getter=None) -> Dict[str, Any]: ...        # line 277
ADVERSARIAL_BACKEND  # line 48 — config-resolved after TASK-2088

# packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
        dispatcher: ClaudeCodeDispatcher,                             # line 142
            subagent="sdd-research",                                  # line 284
# ^ BOTH must be unchanged — assert this
```

Existing test files to follow for style and fixtures:
`packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py`,
`test_dispatch_telemetry.py`, `test_codex_dispatcher.py`, `test_gemini_dispatcher.py`.

### Does NOT Exist

- ~~A live AWS integration test~~ — **do not** call real Bedrock. Mock the mantle
  endpoint and `NovaClient.ask`; these tests must run offline in CI
- ~~`pytest.mark.aws`~~ — no such marker convention exists here; do not invent one
- ~~A pre-existing `docs/dev_loop/` directory~~ — verify the real docs layout
  before creating a path; match the surrounding convention
- ~~FEAT-404's Bedrock round accumulation~~ — not landed; tests must pass with
  Bedrock seats reporting `—`

---

## Implementation Notes

### Pattern to Follow

Mock at the transport boundary, never above it — that is what keeps these tests
honest about the wiring while staying offline:

```python
# dev seat: stub the OpenAI-compatible client behind the mantle base URL
# adversarial: stub NovaClient.ask
# assert on the dispatcher/profile pair, the verdict shape, and the artifacts
```

### Key Constraints

- **Offline.** No AWS calls, no network. CI must not need credentials.
- The regression test must compare against a **captured** pre-feature baseline,
  not a hand-written expectation — capture it from the current implementation
  before the feature's behaviour can drift.
- The `research.py` guard should assert on the source (the two verified lines
  above), so it fails loudly if someone widens the dispatcher type later.
- Docs must state the FEAT-404 caveat explicitly — an operator seeing `—` for a
  Nova seat should find the explanation, not file a bug.

### References in Codebase

- `packages/ai-parrot/tests/flows/dev_loop/test_dispatch_telemetry.py` — closest
  precedent for asserting on telemetry/artifacts
- `packages/ai-parrot/tests/flows/dev_loop/test_dispatcher.py` — dispatcher test style
- `sdd/specs/novaclient-dev-loop.spec.md` §4 — the four integration tests to write
- `sdd/specs/novaclient-dev-loop.spec.md` §5 — the full acceptance-criteria list

---

## Acceptance Criteria

- [ ] `test_nova_dev_seat_end_to_end` — pool spec `{"agent":"nova"}` builds a
      dispatcher, the loop runs against a mocked mantle endpoint, and the
      `DevelopmentOutput` validates
- [ ] `test_nova_adversarial_gate_end_to_end` — the verdict is advisory and
      `files_modified == []`
- [ ] `test_usage_report_written_at_run_end` — `usage.json`, the markdown section
      and `usage.html` are all produced, with agents attributed to seats
- [ ] **`test_defaults_unchanged_without_nova`** — a run configuring nothing
      behaves identically to pre-feature (the [R3] guard)
- [ ] A guard test asserts `nodes/research.py` still declares
      `dispatcher: ClaudeCodeDispatcher` and `subagent="sdd-research"`
- [ ] All tests run **offline** — no AWS credentials, no network
- [ ] Full suite green: `pytest packages/ai-parrot/tests/flows/dev_loop/ -v`
- [ ] `ruff check` and `mypy` clean on every file changed across TASK-2083…2093
- [ ] Docs cover: three seats, verified model ids, both credential paths, all
      `DEV_LOOP_NOVA_*` keys, `DEV_LOOP_ADVERSARIAL_BACKEND`, and the FEAT-404 caveat
- [ ] Every acceptance criterion in spec §5 is satisfied or explicitly noted

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/dev_loop/test_nova_integration.py
from pathlib import Path
import pytest


class TestNovaDevSeat:
    async def test_nova_dev_seat_end_to_end(self, mocked_mantle, nova_pool_spec):
        """Pool spec -> dispatcher -> loop -> validated DevelopmentOutput."""


class TestNovaAdversarial:
    async def test_nova_adversarial_gate_end_to_end(self, mocked_nova_ask):
        verdict = ...
        assert verdict.files_modified == []
        assert all(getattr(f, "source", None) == "nova-adversarial"
                   for f in verdict.findings)


class TestUsageArtifacts:
    async def test_usage_report_written_at_run_end(self, completed_run, tmp_path):
        from parrot.flows.dev_loop.usage_report import UsageReport
        assert (tmp_path / "usage.json").exists()
        assert (tmp_path / "usage.html").exists()
        rep = UsageReport.model_validate_json((tmp_path / "usage.json").read_text())
        assert rep.agents


class TestOptInRegression:
    async def test_defaults_unchanged_without_nova(self, baseline_run):
        """[R3]: configuring nothing must behave exactly as before the feature."""
        from parrot.flows.dev_loop.catalog import catalog_payload
        assert catalog_payload()["adversarial_backend"] == "codex"

    def test_research_node_untouched(self):
        """[R7] guard: the research seat must stay Claude Code only."""
        src = Path("packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py").read_text()
        assert "dispatcher: ClaudeCodeDispatcher" in src
        assert 'subagent="sdd-research"' in src


class TestOffline:
    def test_no_boto_calls(self, no_network):
        """CI must not need AWS credentials."""
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above — **all of §4 and §5**
2. **Check dependencies** — verify TASK-2088, TASK-2091 and TASK-2092 are in
   `sdd/tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm `DevAgentPoolConfig`'s real field names before building fixtures
   - Confirm the actual `docs/` layout before creating a documentation path
   - Re-read spec §5 and check each criterion against the implemented code
   - If anything has changed, update the contract FIRST, then implement
4. **Update status** in `sdd/tasks/index/novaclient-dev-loop.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met — this is the task that certifies
   the whole feature, so walk spec §5 line by line
7. **Move this file** to `sdd/tasks/completed/TASK-2093-integration-tests-docs.md`
8. **Update index** → `"done"` and set `completed_at` on the index header
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.
**Spec §5 walkthrough**: list any acceptance criterion not satisfied and why.

**Deviations from spec**: none | describe if any
