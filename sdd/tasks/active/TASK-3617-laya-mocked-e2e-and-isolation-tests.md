# TASK-3617: Mocked end-to-end suite, interleaved isolation test, and opt-in real/live suites

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3616, TASK-3611
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 5**'s two named test modules. The unit module carries
`test_request_local_model_isolation` (interleaved scoped dispatch calls on one agent instance,
independent model kwargs, unchanged defaults) and a cross-module confident-negative check. The
integration module carries the mocked end-to-end run (fake protocol worker + fake client ⇒ all
reports, no downloads, no credentials) and the two explicit opt-in suites — real CPU scenarios and
live paired routing — which **skip with a reason** when prerequisites are absent and are never
presented as live evidence (spec §4).

Opt-in switches (environment): `LAYA_EVAL_WORKER_PYTHON`, `LAYA_EVAL_CHECKPOINT`,
`LAYA_EVAL_REVISION` enable the real CPU test; additionally `LAYA_EVAL_LIVE=1`,
`LAYA_EVAL_PRIMARY_API_MODEL`, `LAYA_EVAL_CHEAP_API_MODEL`, `LAYA_EVAL_MAX_LIVE_CALLS` and
`ANTHROPIC_API_KEY` enable the live test. Test logs go to `artifacts/logs/laya_evaluation_pytest.log`.

---

## Scope

- Create `packages/ai-parrot/tests/unit/test_laya_evaluation.py`.
- Create `packages/ai-parrot/tests/integration/test_laya_evaluation.py`.

**NOT in scope**: producing the real reports for review (TASK-3618 runs the opt-in suites); any `artifacts/laya/*.py` change.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/unit/test_laya_evaluation.py` | CREATE | Interleaved isolation + confident negative end-to-end through scenarios |
| `packages/ai-parrot/tests/integration/test_laya_evaluation.py` | CREATE | Mocked e2e via `evaluate.main`; opt-in real CPU; opt-in live pairs |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21.

### Verified Imports
```python
from parrot.models.basic import CompletionUsage            # verified: packages/ai-parrot/src/parrot/models/basic.py:48
from parrot.models.responses import AIMessage              # verified: packages/ai-parrot/src/parrot/models/responses.py:75
from artifacts.laya import evaluate                        # TASK-3616: main(argv) -> int; build_live_agent(config); run_evaluation
from artifacts.laya.routing import _DECISION, LayaEvaluationAgent   # TASK-3611
from artifacts.laya.models import RouteDecision, EvaluationConfig   # TASK-3605
```

### Existing Signatures to Use
```python
# packages/ai-parrot/tests/integration/__init__.py exists; integration/conftest.py (autouse) points PARROT_HOME at a temp dir
# packages/ai-parrot/tests/unit/ has NO __init__.py -> module basename `test_laya_evaluation` must stay unique under unit/ (it is)
# root pytest.ini: asyncio_mode = auto; markers `live`, `integration`, `real_llm` registered (pytest.ini + packages/ai-parrot/pyproject.toml:1010-1016)
# TASK-3610 test module defines FAKE_CHILD (a fake protocol worker script) — copy the script text here; do not import across test modules
# TASK-3616: evaluate.main() honours EvaluationConfig.worker_module only through parse_args_to_config (no CLI flag) -> monkeypatch
#   `evaluate.parse_args_to_config` to return a config with worker_module="<fake module>" for the mocked e2e
```

### Does NOT Exist
- ~~a `--worker-module` CLI flag~~ — deliberately absent (spec §2 fixes the flag set); the mocked e2e swaps it via monkeypatch.
- ~~automatic skip → pass conversion~~ — a skipped opt-in test is reported as skipped; TASK-3618 must show real output, not a skip line.
- ~~network or credentials in the default run~~ — the mocked suite must pass offline with `ANTHROPIC_API_KEY` unset.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/tests/unit/test_laya_evaluation.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/integration/test_laya_evaluation.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/models/responses.py#AIMessage",
    "sym:packages/ai-parrot/src/parrot/models/basic.py#CompletionUsage"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Unit module imports `artifacts.*` — add the same 5-parent `sys.path` shim used by
  `tests/unit/laya_eval/conftest.py` at the top of the module (guarded), because this file lives one
  directory up and does not load that conftest.
- The mocked e2e writes to `tmp_path`; the fake client for live mocking is injected by
  monkeypatching `evaluate.build_live_agent` to return a duck-typed agent with `ask_routed` and `configure`.
- Opt-in tests: `pytest.mark.live` for the paired routing test; both opt-in tests call
  `pytest.skip("<which env var is missing>")` at the top.
- Append a one-line summary per test run to `artifacts/logs/laya_evaluation_pytest.log`
  (`mkdir -p`; `logs/` is git-ignored) via a module-level autouse fixture.

---

## Implementation Blueprint

### Steps (in order)
1. Unit module: isolation test with two interleaved tasks on one `__new__`-built agent — *why*: spec §3 M5 skeleton names it; it proves the hook, not the CLI.
2. Integration module: mocked e2e first — *why*: it is the default, credential-free evidence path.
3. Add the two opt-in tests with explicit skips — *why*: spec §4 "skipped tests are never presented as live execution evidence".
4. `git add` both (normal paths; not ignored).

### `packages/ai-parrot/tests/unit/test_laya_evaluation.py` (CREATE)
```python
"""FEAT-589 M5 — request-local model isolation and confident-negative regression (spec §3 Module 5, §4)."""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from parrot.models.basic import CompletionUsage  # noqa: E402
from parrot.models.responses import AIMessage  # noqa: E402

from artifacts.laya.models import INJECTION_QUESTION_ID, PredictionResult, RouteDecision  # noqa: E402
from artifacts.laya.routing import _DECISION, LayaEvaluationAgent  # noqa: E402
from artifacts.laya.scenarios import injection_verdict  # noqa: E402


class _SlowFakeClient:
    """Records ask kwargs and yields control so two scoped calls interleave."""

    def __init__(self):
        self.model = "client-default"
        self.calls: list[dict] = []

    async def ask(self, **kwargs):
        await asyncio.sleep(0.01)
        self.calls.append(dict(kwargs))
        await asyncio.sleep(0.01)
        return AIMessage(input=kwargs.get("prompt", ""), output="x", model=kwargs.get("model") or self.model, provider="fake",
                         usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


def _agent(client) -> LayaEvaluationAgent:
    agent = LayaEvaluationAgent.__new__(LayaEvaluationAgent)   # BasicAgent.__init__ builds a Google client (agent.py:114-116)
    agent.logger, agent._llm, agent.name = logging.getLogger("t"), client, "iso"
    return agent


async def test_request_local_model_isolation() -> None:
    """Interleave scoped dispatch calls and verify independent model kwargs and unchanged defaults."""
    client = _SlowFakeClient()
    agent = _agent(client)

    async def scoped(model: str, prompt: str):
        decision = RouteDecision(choice="cheap", selected_model=model, confidence=0.9, reason="cheap")
        token = _DECISION.set(decision)
        try:
            return await agent.execute_llm_call(client, "ask", prompt=prompt, use_tools=False)
        finally:
            _DECISION.reset(token)

    a, b = await asyncio.gather(scoped("model-A", "pa"), scoped("model-B", "pb"))
    by_prompt = {c["prompt"]: c["model"] for c in client.calls}
    assert by_prompt == {"pa": "model-A", "pb": "model-B"} and (a.model, b.model) == ("model-A", "model-B")
    assert client.model == "client-default" and _DECISION.get() is None


async def test_unscoped_call_after_scoped_ones_has_no_model():
    # FILL IN: after the interleaved calls, a plain execute_llm_call has no "model" kwarg — bounded by spec §3 M3 "unbound decision leaves parent behavior unchanged"
    raise NotImplementedError


def test_confident_negative_end_to_end_verdict():
    res = PredictionResult(request_id="r", status="ok", answers={INJECTION_QUESTION_ID: {"type": "noul", "noul": 0.01, "confidence": 0.99}})
    assert injection_verdict(res, 0.5) == "clean"
```
**Why**: spec §3 M5 skeleton `test_request_local_model_isolation` and §4 "Model isolation".

### `packages/ai-parrot/tests/integration/test_laya_evaluation.py` (CREATE)
```python
"""FEAT-589 M5 — mocked end-to-end evaluation; opt-in real CPU and live paired routing (spec §4 Integration Tests)."""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from parrot.models.basic import CompletionUsage
from parrot.models.responses import AIMessage

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from artifacts.laya import evaluate  # noqa: E402

LOG = REPO_ROOT / "artifacts" / "logs" / "laya_evaluation_pytest.log"
FIXTURES = REPO_ROOT / "artifacts" / "laya" / "fixtures"
FAKE_CHILD = textwrap.dedent('''
    # FILL IN: copy TASK-3610's FAKE_CHILD script text; answer noul 0.9 for states containing "ignore", 0.1 otherwise;
    #          choice questions -> first option with probability 0.7 and confidence 0.85 — bounded by "all three scenarios produce samples"
''')


@pytest.fixture(autouse=True)
def _log_run(request):
    yield
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{request.node.nodeid}\t{getattr(request.node, 'rep_call', None) and request.node.rep_call.outcome}\n")


class _FakeAgent:
    async def configure(self):
        return None

    async def ask_routed(self, question, decision, **kwargs):
        return AIMessage(input=question, output="Paris", response="Paris", model=decision.selected_model, provider="claude",
                         raw_response={"model": f"{decision.selected_model}-real"}, usage=CompletionUsage(prompt_tokens=2, completion_tokens=1, total_tokens=3))


def test_mocked_end_to_end_produces_all_reports(tmp_path, monkeypatch):
    (tmp_path / "fake_child.py").write_text(FAKE_CHILD, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.setattr(evaluate, "build_live_agent", lambda cfg: _FakeAgent())
    real_parse = evaluate.parse_args_to_config

    def patched(argv):
        cfg, fixtures = real_parse(argv)
        return cfg.model_copy(update={"worker_module": "fake_child"}), fixtures

    monkeypatch.setattr(evaluate, "parse_args_to_config", patched)
    rc = evaluate.main(["--worker-python", sys.executable, "--checkpoint-path", str(tmp_path), "--checkpoint-revision", "fake",
                        "--output-dir", str(tmp_path / "out"), "--repeats", "2", "--warmup", "1", "--live",
                        "--primary-api-model", "P", "--cheap-api-model", "C", "--max-live-calls", "40"])
    report = json.loads((tmp_path / "out" / "results.json").read_text())
    assert rc == 0 and report["status"] == "complete"
    assert set(report["metrics"]["scenarios"]) == {"injection", "routing", "grounded"}
    assert {s["arm"] for s in report["samples"] if s["scenario"] == "routing"} == {"local", "primary", "routed"}
    assert (tmp_path / "out" / "report.md").exists() and "regex_baseline" in report["metrics"]


def _real_env() -> dict[str, str] | None:
    keys = ("LAYA_EVAL_WORKER_PYTHON", "LAYA_EVAL_CHECKPOINT", "LAYA_EVAL_REVISION")
    return {k: os.environ[k] for k in keys} if all(os.environ.get(k) for k in keys) else None


async def test_real_cpu_scenarios(tmp_path) -> None:
    """Opt-in run of all scenarios with real local inference; distinguish unavailable live evidence."""
    env = _real_env()
    if env is None:
        pytest.skip("real CPU run not requested: set LAYA_EVAL_WORKER_PYTHON, LAYA_EVAL_CHECKPOINT, LAYA_EVAL_REVISION")
    # FILL IN: evaluate.main([...env..., "--output-dir", tmp_path/"real", "--repeats", "3", "--warmup", "1"]) -> rc in (0, 3);
    #          report.environment.worker.device == "cpu"; every scenario has n_cases > 0 and n_error == 0;
    #          without --live the report is "incomplete" with the "--live not requested" limitation (NOT a failure) — spec §4
    raise NotImplementedError


@pytest.mark.live
async def test_live_paired_routing(tmp_path) -> None:
    # FILL IN: skip unless _real_env() and LAYA_EVAL_LIVE=1 and PRIMARY/CHEAP/MAX_LIVE_CALLS and ANTHROPIC_API_KEY are set;
    #          run with --live; assert both arms present, every ok sample has actual_model (else the test FAILS: unverified model evidence),
    #          usage recorded per arm, used calls <= cap — spec §4 "Live paired routing"
    raise NotImplementedError
```
**Why**: spec §4 Integration Tests table, row by row. The mocked test asserts the `complete` path
with a fake live agent so the cap/pair/evidence code executes end-to-end without credentials.

### FILL IN checklist
- [ ] unit `test_unscoped_call_after_scoped_ones_has_no_model`
- [ ] integration `FAKE_CHILD` script; `test_real_cpu_scenarios`; `test_live_paired_routing`
- [ ] pytest hook for `rep_call` (a small `pytest_runtest_makereport` hookwrapper in the module) or simplify the log line to the nodeid only

---

## Acceptance Criteria

- [ ] AC-1 — Interleaved scoped calls carry their own `model`; client default and ContextVar are untouched afterwards.
- [ ] AC-2 — The mocked e2e exits 0 with `status: complete`, three scenario metric blocks, three routing arms and a regex baseline — offline, no credentials.
- [ ] AC-3 — Both opt-in tests skip with an explanatory reason when their env vars are absent; they never pass silently.
- [ ] AC-4 — `artifacts/logs/laya_evaluation_pytest.log` receives one line per executed test.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/test_laya_evaluation.py -q`
- `pytest packages/ai-parrot/tests/integration/test_laya_evaluation.py -q`

---

## Test Specification

See the CREATE blocks above.

---

## Agent Instructions

1. Read spec §3 Module 5 and §4 "Integration Tests".
2. Confirm TASK-3616 and TASK-3611 are completed.
3. Implement from the Blueprint; run both Validation Commands with `ANTHROPIC_API_KEY` unset; commit; move this file; update the index; fill the Completion Note — include the skip reasons printed by the opt-in tests.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
