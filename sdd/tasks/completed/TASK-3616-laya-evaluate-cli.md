# TASK-3616: `python -m artifacts.laya.evaluate` — configuration, orchestration, exit codes

**Feature**: FEAT-589 — Evaluate Laya for typed classification and agent model routing
**Spec**: `sdd/specs/laya-adoption.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3606, TASK-3607, TASK-3610, TASK-3611, TASK-3612, TASK-3613, TASK-3614, TASK-3615
**Assigned-to**: unassigned

---

## Context

Implements the `evaluate.py` half of spec §3 **Module 4** and §2 "New Public Interfaces": the
supported entry point `python -m artifacts.laya.evaluate` from the repository root. CLI flags map
1:1 to `EvaluationConfig` fields with hyphenated names, plus `--fixtures` (directory; default
`artifacts/laya/fixtures`). `--help` works without Laya. The output directory must be new or
empty. Exit codes: 0 complete exploratory run, 2 invalid CLI configuration, 3 incomplete/error
report. Configuration errors raise before execution; operational failures become report content.

`run_evaluation()` starts the worker, runs the requested scenarios through
`scenarios.run_local_scenario`, computes route decisions, and — only when `--live` passed
preflight — builds one direct `AnthropicClient`, one `LayaEvaluationAgent`, and runs the paired
calls. Without live inputs it still performs real local routing inference and marks the report
`incomplete` with the reason (spec §2). Missing worker prerequisites yield a structured
`incomplete` report with actionable instructions (spec §2), never a stack trace.

---

## Scope

- Create `artifacts/laya/evaluate.py`: `build_parser`, `parse_args_to_config`, `collect_environment`,
  `build_live_agent`, `run_evaluation`, `main`.
- Write `packages/ai-parrot/tests/unit/laya_eval/test_laya_evaluate_cli.py`.

**NOT in scope**: the mocked end-to-end suite and real-CPU opt-in (TASK-3617); README (TASK-3618).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `artifacts/laya/evaluate.py` | CREATE | CLI + async orchestration + exit codes |
| `packages/ai-parrot/tests/unit/laya_eval/test_laya_evaluate_cli.py` | CREATE | `--help`, exit 2 paths, no-live-by-default, incomplete report on missing worker |

---

## Codebase Contract (Anti-Hallucination)

> Verified against `dev` @ `1a7ccd5a1` on 2026-09-21.

### Verified Imports
```python
from parrot.clients.anthropic import AnthropicClient   # verified: packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/__init__.py:1
from artifacts.laya.models import (SCENARIOS, EvaluationCase, EvaluationConfig, EvaluationReport, SampleResult, load_cases, manifest_sha256)  # TASK-3605/3606
from artifacts.laya.runtime import LayaWorker, WorkerStartupError                     # TASK-3610
from artifacts.laya.routing import LayaEvaluationAgent                                 # TASK-3611
from artifacts.laya.reporting import load_prices, summarize, write_report              # TASK-3612
from artifacts.laya.live import LiveCallBudget, LivePreflightError, load_rubrics, preflight_live, run_live_routing_pairs  # TASK-3613/3615
from artifacts.laya.scenarios import QUESTION_SCHEMAS, route_decisions_for, run_local_scenario, run_regex_baseline       # TASK-3614
```

### Existing Signatures to Use
```python
# packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py:128
class AnthropicClient(AbstractClient):
    def __init__(self, api_key: str = None, base_url: str = "https://api.anthropic.com", backend: AnthropicBackend = "direct", ..., **kwargs)
    #   :173  self.api_key = api_key or config.get("ANTHROPIC_API_KEY")   -> pass nothing; env supplies the key
    #   :269  def _resolve_model(self, model) -> str  -> string ids pass through DirectBackend.translate_model unchanged (backends.py:86)
# packages/ai-parrot/src/parrot/bots/abstract.py:274  AbstractBot.__init__(self, name="Nav", system_prompt=None, llm=..., tools=None, ..., **kwargs)
# packages/ai-parrot/src/parrot/bots/agent.py:69      BasicAgent.__init__(self, name="Agent", agent_id="agent", use_llm="google", llm=None, tools=None,
#                                                     system_prompt=None, human_prompt=None, use_tools=True, instructions=None, dataframes=None, **kwargs)
#   :114-116 imports+instantiates GoogleGenAIClient unconditionally; :122-129 when llm is given: self.client = self.configure_llm(llm=..., ...); self._llm = self.client
# packages/ai-parrot/src/parrot/interfaces/tools.py:316  def configure_llm(self, llm: Union[str, Callable] = None, **kwargs) -> AbstractClient
# packages/ai-parrot/src/parrot/bots/abstract.py:1500 async def configure(self, app=None) -> None   -> call once before ask (spec §6)
# artifacts/laya/reporting.py (TASK-3612): write_report raises FileExistsError on a non-empty dir — pre-check the same rule BEFORE inference (exit 2)
```

### Does NOT Exist
- ~~`parrot.clients.anthropic.AnthropicClient(model="anthropic:opus-5")` resolving to a real id~~ — `anthropic:opus-5` is the *label*; the API id is `--primary-api-model` (spec §2). The label is recorded, never sent.
- ~~`ClaudeModel.OPUS_5`~~ — absent (`models.py:4-32`); do not map.
- ~~`from parrot.clients.claude import ...` / `parrot/clients/anthropic.py`~~ — not current source (spec §6).
- ~~`--overwrite`~~ — no such flag (spec §2 "never overwrite an existing report implicitly").
- ~~a `python -m artifacts.laya` package `__main__`~~ — the entry point is the module `artifacts.laya.evaluate`.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "artifacts/laya/evaluate.py", "action": "CREATE"},
    {"path": "packages/ai-parrot/tests/unit/laya_eval/test_laya_evaluate_cli.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py#AnthropicClient",
    "sym:packages/ai-parrot/src/parrot/bots/abstract.py#AbstractBot.configure",
    "sym:packages/ai-parrot/src/parrot/interfaces/tools.py#ToolInterface.configure_llm"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Heavy imports (`parrot.*`, `LayaWorker`) happen inside functions so `--help` and exit-2 paths are fast and Laya-free.
- Exit-2 conditions (before any process starts): argparse errors, Pydantic `ValidationError`
  on `EvaluationConfig`, `LivePreflightError`, non-empty `--output-dir`, missing fixture file,
  `load_cases` `ValueError`, `--price-file` errors.
- Exit-3 conditions: `WorkerStartupError` (report `status="incomplete"` with `limitations=[error_message, "see artifacts/laya/README.md"]`),
  any scenario with fatal worker errors, live requested-but-not-configured (`incomplete`), or an unexpected exception (`status="error"`).
- `report.status == "complete"` only when every requested scenario ran without fatal errors and
  (if `--live`) all pairs ran; `--live` absent ⇒ routing evaluation `incomplete` with the
  limitation "live routing not executed: --live not requested" (spec §2).
- Secrets: never log or serialize the API key; the config has no key field.
- `environment` = python version, platform, `worker.ready` fields (packages, checkpoint hash/revision,
  device, torch threads, load_ms), `startup_ms`, `peak_rss_kb` (+ `"peak_rss_unit": "kB"`, `"peak_rss_reason"` when null), `os.cpu_count()`.

---

## Implementation Blueprint

### Steps (in order)
1. `build_parser` + `parse_args_to_config` — *why*: every flag is a config field; keep the mapping mechanical.
2. `run_evaluation` — *why*: orchestrates M2/M3/M4 in the spec's order and owns the `incomplete` semantics.
3. `build_live_agent` — *why*: the only place a real client/agent is constructed; isolate it for mocking.
4. `main` with the exit-code ladder — *why*: spec §2 exit codes are an acceptance criterion.
5. Tests; `git add -f`.

### `artifacts/laya/evaluate.py` (CREATE — parser and config)
```python
"""CLI entry point for the Laya CPU evaluation: ``python -m artifacts.laya.evaluate`` (spec §2, §3 Module 4)."""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from artifacts.laya.models import SCENARIOS, EvaluationCase, EvaluationConfig, EvaluationReport, SampleResult, load_cases, manifest_sha256

logger = logging.getLogger("artifacts.laya.evaluate")
DEFAULT_FIXTURES = Path(__file__).resolve().parent / "fixtures"
EXIT_OK, EXIT_CONFIG, EXIT_INCOMPLETE = 0, 2, 3


def build_parser() -> argparse.ArgumentParser:
    """One flag per EvaluationConfig field (hyphenated), plus --fixtures. Works without Laya installed."""
    p = argparse.ArgumentParser(prog="python -m artifacts.laya.evaluate", description="FEAT-589 exploratory Laya CPU evaluation (no adoption gate).")
    p.add_argument("--worker-python", type=Path, required=True, help="interpreter of the isolated Laya environment (see artifacts/laya/README.md)")
    p.add_argument("--checkpoint-path", type=Path, required=True)
    p.add_argument("--checkpoint-revision", required=True)
    p.add_argument("--scenario", choices=("all", *SCENARIOS), default="all")
    p.add_argument("--live", action="store_true", help="make real Anthropic calls (requires --primary-api-model, --cheap-api-model, --max-live-calls > 0, ANTHROPIC_API_KEY)")
    p.add_argument("--primary-label", default="anthropic:opus-5", help="requested primary preference; recorded, never sent to the provider")
    p.add_argument("--primary-api-model", default=None, help="verified provider identifier for the primary model")
    p.add_argument("--cheap-api-model", default=None)
    p.add_argument("--max-live-calls", type=int, default=0)
    p.add_argument("--max-output-tokens", type=int, default=256)
    p.add_argument("--injection-threshold", type=float, default=0.5)
    p.add_argument("--routing-threshold", type=float, default=0.8)
    p.add_argument("--startup-timeout-s", type=float, default=300.0)
    p.add_argument("--prediction-timeout-s", type=float, default=30.0)
    p.add_argument("--warmup", type=int, default=3)
    p.add_argument("--repeats", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output-dir", type=Path, required=True, help="must be new or empty")
    p.add_argument("--price-file", type=Path, default=None)
    p.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    return p


def parse_args_to_config(argv: Sequence[str] | None) -> tuple[EvaluationConfig, Path]:
    """Parse argv; raise ValueError (-> exit 2) for any configuration problem detectable before execution."""
    ns = build_parser().parse_args(argv)
    fixtures = ns.fixtures
    kwargs = {k: v for k, v in vars(ns).items() if k != "fixtures"}
    try:
        config = EvaluationConfig(**kwargs)
    except ValidationError as exc:
        raise ValueError(f"invalid configuration: {exc}") from None
    if config.output_dir.exists() and any(config.output_dir.iterdir()):
        raise ValueError(f"--output-dir {config.output_dir} is not empty; choose a new directory")
    # FILL IN: preflight_live(config) (LivePreflightError is a ValueError); for each requested scenario require fixtures/<scenario>.jsonl exists;
    #          if routing requested require fixtures/routing_rubrics.json; load_prices(config.price_file) — all raise ValueError — bounded by spec §2 exit code 2
    return config, fixtures
```
**Why this shape**: argparse `dest` names equal the config field names exactly, so `EvaluationConfig(**vars)`
is the whole mapping (spec §2 "CLI flags correspond to EvaluationConfig fields using hyphenated names").

### `artifacts/laya/evaluate.py` (CREATE — continued: orchestration and main)
```python
def collect_environment(worker: Any | None) -> dict[str, Any]:
    """Reproducibility block (spec §4): python/platform/cpu + worker ready fields + RSS with unit/reason."""
    env: dict[str, Any] = {"python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(), "worker": None}
    if worker is not None and worker.ready is not None:
        env["worker"] = worker.ready.model_dump()
        env["startup_ms"] = worker.startup_ms
        env["peak_rss_kb"] = worker.peak_rss_kb
        env["peak_rss_unit"] = "kB" if worker.peak_rss_kb is not None else None
        env["peak_rss_reason"] = None if worker.peak_rss_kb is not None else "ru_maxrss unit not kB on this platform or never reported"
    return env


def build_live_agent(config: EvaluationConfig) -> Any:
    """Construct ONE direct AnthropicClient (key from env) and the evaluation Agent; live mode only."""
    from parrot.clients.anthropic import AnthropicClient  # verified: parrot/clients/anthropic/__init__.py:1
    from artifacts.laya.routing import LayaEvaluationAgent

    client = AnthropicClient(backend="direct", model=config.primary_api_model)  # per-call model overrides come from the routing hook
    return LayaEvaluationAgent(name="laya-routing-eval", llm=client, use_tools=False, system_prompt="Answer concisely in English.")


async def run_evaluation(config: EvaluationConfig, cases: list[EvaluationCase]) -> EvaluationReport:
    """Run requested scenarios, preserving incomplete evidence and enforcing the logical-call cap."""
    from artifacts.laya.runtime import LayaWorker, WorkerStartupError
    from artifacts.laya.scenarios import QUESTION_SCHEMAS, route_decisions_for, run_local_scenario, run_regex_baseline

    wanted = list(SCENARIOS) if config.scenario == "all" else [config.scenario]
    by_scenario = {s: [c for c in cases if c.scenario == s] for s in wanted}
    samples: list[SampleResult] = []
    limitations: list[str] = ["smoke datasets: not representative production accuracy estimates (spec §4)"]
    metrics: dict[str, Any] = {}
    status = "complete"
    worker = LayaWorker(config)
    try:
        async with worker:
            for scenario in wanted:
                local, first = await run_local_scenario(worker, by_scenario[scenario], config)
                samples.extend(local)
                if any(s.error_code in ("inference_timeout", "worker_failed") for s in local):
                    status = "incomplete"
                if scenario == "injection":
                    metrics["regex_baseline"] = run_regex_baseline(by_scenario[scenario])
                if scenario == "routing":
                    decisions = route_decisions_for(first, config)
                    metrics["route_decisions"] = {k: v.model_dump() for k, v in decisions.items()}
                    # FILL IN: if config.live: agent = build_live_agent(config); await agent.configure();
                    #              samples += await run_live_routing_pairs(agent, cases, decisions, config, LiveCallBudget(config.max_live_calls), load_rubrics(...));
                    #              if any call_cap_reached -> status="incomplete" + limitation
                    #          else: status="incomplete"; limitations.append("live routing not executed: --live not requested (local routing inference did run)")
                    #          — bounded by spec §2 "otherwise perform real local routing inference and mark downstream evaluation incomplete"
    except WorkerStartupError as exc:
        status = "incomplete"
        limitations += [f"{exc.error_code}: {exc}", "worker prerequisites missing — follow artifacts/laya/README.md 'Isolated environment' and 'Checkpoint snapshot'"]
    from artifacts.laya.reporting import load_prices, summarize
    metrics.update(summarize(samples, load_prices(config.price_file)))
    return EvaluationReport(status=status, config=config, environment=collect_environment(worker), question_schemas=QUESTION_SCHEMAS,
                            fixture_sha256={}, samples=samples, metrics=metrics, limitations=limitations)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse configuration, run the async evaluation, write reports and return a documented exit code."""
    logging.basicConfig(level=os.environ.get("LAYA_EVAL_LOGLEVEL", "INFO"), stream=sys.stderr)
    try:
        config, fixtures = parse_args_to_config(argv)
        wanted = list(SCENARIOS) if config.scenario == "all" else [config.scenario]
        cases = [c for s in wanted for c in load_cases(fixtures / f"{s}.jsonl", s)]
        hashes = {s: manifest_sha256(fixtures / f"{s}.jsonl") for s in wanted}
    except ValueError as exc:
        logger.error("%s", exc)
        return EXIT_CONFIG
    from artifacts.laya.reporting import write_report
    try:
        report = asyncio.run(run_evaluation(config, cases))
    except Exception as exc:  # unexpected: still write an error report, never a bare traceback to the user
        logger.exception("evaluation failed")
        report = EvaluationReport(status="error", config=config, limitations=[f"unexpected failure: {type(exc).__name__}: {exc}"])
    report.fixture_sha256 = hashes
    json_path, md_path = write_report(report, config.output_dir)
    logger.info("wrote %s and %s (status=%s)", json_path, md_path, report.status)
    return EXIT_OK if report.status == "complete" else EXIT_INCOMPLETE


if __name__ == "__main__":
    sys.exit(main())
```
**Why**: the `try/except WorkerStartupError` path is spec §2's "Missing dependencies/snapshot produce
a structured incomplete report and actionable instructions"; the exit ladder is §2's 0/2/3.
`AnthropicClient(backend="direct", model=...)` — `model` is an `AbstractClient` kwarg
(`**kwargs` forwarded, `client.py:139`); confirm the kwarg name with `grep -n "self.model" packages/ai-parrot/src/parrot/clients/base.py`
before relying on it (`# FILL IN: verify`).

### `packages/ai-parrot/tests/unit/laya_eval/test_laya_evaluate_cli.py` (CREATE)
```python
"""FEAT-589 M4 — CLI configuration paths: --help without Laya, exit 2 cases, no live by default, incomplete report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from artifacts.laya import evaluate

FIXTURES = Path(__file__).resolve().parents[5] / "artifacts" / "laya" / "fixtures"


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return ["--worker-python", sys.executable, "--checkpoint-path", str(tmp_path), "--checkpoint-revision", "r",
            "--output-dir", str(tmp_path / "out"), "--repeats", "1", "--warmup", "0", *extra]


def test_help_works_without_laya(capsys):
    with pytest.raises(SystemExit) as ei:
        evaluate.main(["--help"])
    assert ei.value.code == 0 and "--primary-api-model" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [
    ["--injection-threshold", "1.5"],
    ["--live"],                                              # missing live inputs -> preflight
    ["--fixtures", "/nonexistent/dir"],
])
def test_configuration_errors_exit_2_before_any_process(tmp_path, extra, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert evaluate.main(_argv(tmp_path, *extra)) == 2


def test_non_empty_output_dir_exits_2(tmp_path):
    (tmp_path / "out").mkdir(); (tmp_path / "out" / "x").write_text("x")
    assert evaluate.main(_argv(tmp_path)) == 2


def test_missing_worker_module_yields_incomplete_report_exit_3(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = evaluate.main(_argv(tmp_path, "--scenario", "injection", "--startup-timeout-s", "20") + ["--worker-python", sys.executable])
    # the real artifacts.laya.worker runs without laya -> dependency_missing -> WorkerStartupError -> incomplete
    assert rc == 3
    report = json.loads((tmp_path / "out" / "results.json").read_text())
    assert report["status"] == "incomplete" and any("dependency_missing" in l for l in report["limitations"])
    assert "README" in " ".join(report["limitations"]) and report["fixture_sha256"].keys() == {"injection"}


def test_no_live_calls_by_default(tmp_path, monkeypatch):
    # FILL IN: monkeypatch evaluate.build_live_agent to raise AssertionError; run routing scenario with a fake worker module
    #          (reuse TASK-3610's FAKE_CHILD via --worker-python + PYTHONPATH and EvaluationConfig.worker_module through a monkeypatched
    #          parse_args_to_config); assert exit 3, status incomplete, limitation mentions "--live not requested" — bounded by spec §4 "No calls by default"
    raise NotImplementedError
```
**Why**: spec §2 exit codes and §4 "Live configuration/cap: No calls by default; missing IDs fail preflight".

### FILL IN checklist
- [ ] `evaluate.py::parse_args_to_config` — preflight, fixture/rubric existence, price file
- [ ] `evaluate.py::run_evaluation` — live branch vs incomplete limitation
- [ ] `evaluate.py::build_live_agent` — verify the client `model` kwarg name
- [ ] `test_laya_evaluate_cli.py::test_no_live_calls_by_default`

---

## Acceptance Criteria

- [ ] AC-1 — `python -m artifacts.laya.evaluate --help` exits 0 in the workspace venv (no Laya).
- [ ] AC-2 — Invalid thresholds, missing live inputs with `--live`, missing fixtures and a non-empty output dir all exit 2 with no process started.
- [ ] AC-3 — A worker that cannot start yields `results.json` + `report.md` with `status: incomplete`, the stable error code and README instructions, exit 3.
- [ ] AC-4 — Without `--live`, `build_live_agent` is never called and the report says why routing is incomplete.
- [ ] `ruff check artifacts/laya/evaluate.py` clean.

## Validation Commands
- `pytest packages/ai-parrot/tests/unit/laya_eval/test_laya_evaluate_cli.py -q`

---

## Test Specification

See the CREATE block above.

---

## Agent Instructions

1. Read spec §2 "Overview", live paragraphs and "New Public Interfaces"; §3 Module 4.
2. Confirm all eight dependencies are completed; re-verify `client.py:128/173`, `agent.py:114-129`, `tools.py:316`.
3. Implement from the Blueprint; run the Validation Command and `python -m artifacts.laya.evaluate --help`.
4. `git add -f` both files; commit; move this file; update the index; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-coder (codex, model=gpt-5.6-terra, attempt_uid=ada7ffcc9b3c4de1a74130077264dc57), consolidated by sdd-worker orchestrator
**Date**: 2026-09-22
**Notes**: Created `artifacts/laya/evaluate.py`: `build_parser`/`parse_args_to_config` (CLI flags map 1:1
to `EvaluationConfig`, `--fixtures` defaults to `artifacts/laya/fixtures`, output-dir-not-empty and
missing-fixture/rubric preflight before execution), `collect_environment`, `build_live_agent` (one direct
`AnthropicClient` + `LayaEvaluationAgent`), `run_evaluation` (starts `LayaWorker`, runs requested
scenarios through `run_local_scenario`, computes route decisions, runs live pairs only when `--live`
preflight passes, else marks the report `incomplete` with the reason — never a stack trace on missing
worker prerequisites) and `main` (exit codes 0/2/3 exactly as specified). Merge-tier validation initially
failed (`No module named artifacts.laya.evaluate`) — the FOURTH and final occurrence of this model's
gitignore-force-add defect on this feature (TASK-3605, TASK-3611, TASK-3614, TASK-3616; 4/4 of its
CREATE-under-`artifacts/`-deliveries on this feature). Orchestrator force-added the unmodified file
(commit e8bc4da1ac47f39935d09b5dd6b917ea834dd01b) and recorded the pattern as model feedback
(coder-feedback:298a2946b86d3c0a452654ca). Full suite then 89/89 passed, 1 skipped; verified
`python -m artifacts.laya.evaluate --help` exits 0 without Laya installed (AC-2).

**Deviations from spec**: none
