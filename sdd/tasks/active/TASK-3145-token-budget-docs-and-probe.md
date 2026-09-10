# TASK-3145: `docs/clients/token-budgets.md` and the Opt-In Strict-Qualification Probe Script

**Feature**: FEAT-550 — Cumulative Question Token Budgets for Bedrock and Mantle
**Spec**: `sdd/specs/token-budget-bedrock.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3141, TASK-3143
**Assigned-to**: unassigned

---

## Context

Module 6 (spec §3 M6), documentation + tooling half. Two deliverables:

1. `docs/clients/token-budgets.md` — configuration, the §2.3 default-reserve worked
   example, estimated-mode limits, scope/resume/snapshot trust contract, retention,
   unsupported coverage, and the strict-qualification **status and procedure** (AC:
   "documented, and not marketed as qualified strict Bedrock support on botocore 1.35.36").
2. `examples/clients/smoke/smoke_token_budget_qualification.py` — an **opt-in** probe that
   refuses to run without explicit `--model`, `--endpoint`/`--region`, `--budget`, and
   `--i-accept-paid-inference`; compares counted full inputs against normalized actual
   usage, verifies output/reasoning bounds across tool/cache/stream variants, records exact
   SDK versions and request fingerprints, and writes a **sanitized** deterministic findings
   JSON to `artifacts/logs/` (spec §2.5). It never edits `STRICT_QUALIFICATIONS`.

Runs in parallel with TASK-3144 (no shared files).

---

## Scope

- Write `docs/clients/token-budgets.md` (~250 lines) with sections: What this is / When
  to use / Configuration (table from spec §2.1) / Worked example (§2.3 numbers) / How
  accounting works (§2.2 formulas, normalization per provider, estimated overrun) /
  Finalization (§2.3 table) / Streaming and cancellation / Retries and SDK ownership
  (§2.4) / Scopes, children, suspension, resume and snapshots (§2.6 trust boundary,
  retention 1024 / 3600 s, `release()`) / Coverage matrix (Bedrock Converse, Nova text,
  Mantle; everything else `BudgetUnsupported`) / Strict mode status (empty registry,
  installed botocore 1.35.36 lacks CountTokens, how to qualify) / Error reference (8 codes)
  / Related files.
- Write the probe script following `examples/clients/smoke/_runner.py` conventions
  (plain script, exit 0 with `SKIPPED` when not opted in, no pytest markers).
- Add a one-line pointer to the new doc in `docs/clients/bedrock-mantle.md` "Related files"
  list and, if a docs index exists (`grep -rn "openai-compatible.md" docs/ --include=*.md -l`),
  in that index too.

**NOT in scope**: running the probe (needs credentials and paid inference), adding any
qualification record, editing production adapters.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/clients/token-budgets.md` | CREATE | Feature documentation |
| `examples/clients/smoke/smoke_token_budget_qualification.py` | CREATE | Opt-in qualification probe |
| `docs/clients/bedrock-mantle.md` | MODIFY | Add related-file pointer |

---

## Codebase Contract (Anti-Hallucination)

> Verified against dev `755c61347` on 2026-09-11 plus TASK-3132..3143 declared outputs.

### Verified Imports (probe script)
```python
from parrot.clients.amazon import BedrockConverseClient, BedrockMantleClient, NovaClient     # verified: amazon/__init__.py:1
from parrot.clients.amazon.budget import BedrockBudgetAdapter, MantleBudgetAdapter, fingerprint   # TASK-3139 / TASK-3142
from parrot.clients.amazon.budget_qualifications import QualificationKey, installed_sdk_versions, probe_count_tokens_support   # TASK-3139
from parrot.clients.budget import TokenBudgetPolicy                                         # TASK-3133 re-export
import argparse, asyncio, json, hashlib, os, pathlib, sys, time                              # stdlib
```

### Existing Signatures to Use
```python
# examples/clients/smoke/_runner.py:1-30 — module docstring documents the smoke conventions: plain script, credential-gated,
#   exits 0 with a SKIPPED message before touching the network; `run_smoke(...)` helper (read the file for its exact signature before reusing it —
#   the probe may not need it and can stay standalone).
# docs/clients/bedrock-mantle.md:1-14 — doc header style: title, **Audience**, **Related files** bullet list, `---`, `## What This Is`.
#   NOTE its Related-files paths still cite pre-extraction `packages/ai-parrot/src/parrot/clients/nova/mantle.py`; the new doc MUST use the
#   satellite paths (`packages/ai-parrot-client-amazon/src/parrot/clients/amazon/...`) — spec §6 "older wiki documents cite pre-extraction provider paths".
# artifacts/logs/ — the repo's evidence directory (CLAUDE.md "Save evidence to artifacts/logs/"); create it if absent.
# Installed versions to state verbatim in the doc (spec §2.5): aioboto3=13.2.0, aiobotocore=2.15.2, boto3=1.35.36, botocore=1.35.36, openai=3.3.1, tiktoken=0.9.0, pydantic=2.12.5
```

### Does NOT Exist
- ~~A qualified strict entry~~ — the doc must state the registry ships empty and strict mode is a refusal path on the inspected environment.
- ~~A Runtime `CountTokens` call in the probe on botocore 1.35.36~~ — the probe must call `probe_count_tokens_support()` first and, when `False`, record `"count_method": "local_estimate"` and mark strict qualification **not achievable** on this SDK.
- ~~Automatic execution in CI~~ — no pytest collection (file lives under `examples/`, no `test_` prefix), and the script exits 0 without the opt-in flag.
- ~~Writing credentials or raw prompts to `artifacts/logs/`~~ — findings are sanitized: model id, region/endpoint host, versions, request fingerprints (sha256), counted vs actual numbers, pass/fail per variant.

---

## Implementation Notes

### Key Constraints
- Doc worked example must reproduce spec §2.3 exactly: `B=10,000`, `F=1,500`, rounds
  `2,000+500` and `3,000+700`, `A_work=2,300`, `A_final=3,800`, final input `3,200` → cap `600`;
  final input `4,000` → partial without inference.
- Doc must include the estimated-mode caveat ("estimates are not proofs; overrun is recorded
  unclamped") and the snapshot trust statement ("process-local; after restart the application
  is the only authority; do not accept snapshots from public HTTP/tool inputs").
- Probe variants: `plain`, `tools`, `cache` (only if the model supports cachePoint), `stream`,
  and for Mantle `schema`; each variant runs **one** request with an explicit small budget and
  records `{variant, fingerprint, counted_input, actual_input, actual_output, cap_sent, cap_respected, method}`.
- Findings file name: `artifacts/logs/token_budget_qualification_<provider>_<model-slug>_<UTC-timestamp>.json`;
  also print a compact PASS/FAIL table. Never write a `QualificationRecord` — print the exact
  `QualificationKey(...)` literal a reviewer would add manually if evidence is accepted.

### References in Codebase
- `examples/clients/smoke/smoke_mantle.py` — argument/credential gating style.
- `docs/clients/openai-compatible.md` — hierarchy doc to cross-link (Mantle inherits `OpenAIBaseClient`).

---

## Implementation Blueprint

### Steps (in order)
1. Write the doc from the spec sections listed in Scope — *why*: AC requires configuration, finalization, snapshot trust/retention, unsupported coverage and qualification procedure to be documented.
2. Write the probe skeleton with argument gating and SKIPPED exit — *why*: opt-in is a hard requirement (spec §2.5 "No automatic paid probes run in CI").
3. Implement variant runners and the sanitized findings writer.
4. Add the cross-link in `bedrock-mantle.md`; run `ruff check examples/clients/smoke/smoke_token_budget_qualification.py`.

### `docs/clients/token-budgets.md` (CREATE — outline; fill prose from the spec)
```markdown
# Question Token Budgets (Bedrock Converse, Nova text, Bedrock Mantle)

**Audience**: Engineers who need a cumulative token ceiling for one user question — every model request, tool round, retry, fallback and same-process child call — with a protected final-answer reserve.

**Related files**:
- `packages/ai-parrot/src/parrot/clients/budget.py` — `QuestionBudget` ledger + public re-exports
- `packages/ai-parrot/src/parrot/clients/budget_scope.py` — `BudgetScope`, `BudgetRegistry`, entry adapters
- `packages/ai-parrot/src/parrot/models/token_budget.py` — records (`TokenBudgetPolicy`, `BudgetReport`, `BudgetSnapshot`, …)
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget.py` — Bedrock / Mantle adapters
- `packages/ai-parrot-client-amazon/src/parrot/clients/amazon/budget_qualifications.py` — strict registry (empty)
- `examples/clients/smoke/smoke_token_budget_qualification.py` — opt-in qualification probe
- `sdd/specs/token-budget-bedrock.spec.md` — full design (FEAT-550)

---

## What This Is
<!-- FILL IN: 2 paragraphs from spec §1 Problem Statement + Goals; state clearly what it is NOT (spec §1 Non-Goals). -->

## Configuration
<!-- FILL IN: table copied from spec §2.1 (token_budget / budget_mode / final_answer_reserve / budget_scope / budget_snapshot) + omission-vs-None rule + child conflict rule. Code sample: BaseBot(..., token_budget=10_000) and bot.ask(q, token_budget=10_000). -->

## Worked Example (default 15% reserve)
<!-- FILL IN: spec §2.3 numbers verbatim; show the resulting BudgetReport fields. -->

## How Accounting Works
<!-- FILL IN: B/F/C/U/R, A_work, A_final; admission O = min(M, A - I) >= m; per-provider normalization table (Converse cache sum, native body, Mantle aggregates); estimated overrun unclamped; unknown usage separate. -->

## Finalization and Partial Results
<!-- FILL IN: spec §2.3 condition/result table; flags budget_exhausted / finalization_attempted / finalized / answer_complete; stop_reason="budget_exhausted"; AIMessage.metadata["token_budget"]; InvokeResult.budget_report. -->

## Streaming, Cancellation, Retries
<!-- FILL IN: spec §2.4 — one sentinel, no sentinel guaranteed on cancel, hidden SDK retries disabled via with_options(max_retries=0) / BotoConfig total_max_attempts=1, per-attempt reservations. -->

## Scopes, Children, Suspension and Snapshots
<!-- FILL IN: spec §2.6 — ContextVar scope, registry (1024 / 3600 s, release()), nonce, BudgetStateMissing/ResumeConflict/SnapshotInvalid, trust boundary sentence, "do not accept snapshots from public inputs". -->

## Coverage
| Client | ask | ask_stream | resume | invoke | Notes |
|---|---|---|---|---|---|
| `BedrockConverseClient` | ✅ | ✅ | ✅ | ✅ | Converse + native `invoke_model` text guarded |
| `NovaClient` (text) | ✅ | ✅ | ✅ | ✅ | inherited; audio/image/video out of scope |
| `BedrockMantleClient` | ✅ | ✅ | ✅ | ✅ | estimated mode only |
| every other client | ❌ `BudgetUnsupported` before inference | | | | including other `OpenAIBaseClient` subclasses |

## Strict Mode Status
<!-- FILL IN: registry ships EMPTY; installed botocore 1.35.36 lacks Runtime CountTokens; strict requests fail with BudgetUnsupported before inference; qualification procedure (probe → review evidence in artifacts/logs → add QualificationRecord by hand → tests). Not marketed as qualified strict Bedrock support. -->

## Error Reference
<!-- FILL IN: 8 codes from spec §2 Data Models, one line each, which ones the bot boundary translates (only budget_exhausted). -->
```
**Why this shape**: mirrors the header/section style of `docs/clients/bedrock-mantle.md`; every `FILL IN` names the spec section that bounds it so the doc cannot drift from the design.

### `examples/clients/smoke/smoke_token_budget_qualification.py` (CREATE)
```python
"""Opt-in strict-qualification probe for question token budgets (FEAT-550, spec §2.5).

Refuses to run without --model, --region/--endpoint, --budget and --i-accept-paid-inference.
Never mutates STRICT_QUALIFICATIONS; writes sanitized findings to artifacts/logs/ and prints
the QualificationKey a reviewer could add by hand if the evidence is accepted.

Usage:
    python examples/clients/smoke/smoke_token_budget_qualification.py \
        --provider bedrock --model claude-haiku-4-5 --region us-east-1 --budget 4000 --i-accept-paid-inference
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from parrot.clients.amazon.budget_qualifications import installed_sdk_versions, probe_count_tokens_support

VARIANTS = ("plain", "tools", "stream", "cache", "schema")


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=("bedrock", "nova", "mantle"), required=False)
    p.add_argument("--model")
    p.add_argument("--region")
    p.add_argument("--endpoint", help="Mantle base_url override")
    p.add_argument("--budget", type=int)
    p.add_argument("--variants", default=",".join(VARIANTS))
    p.add_argument("--i-accept-paid-inference", action="store_true")
    return p.parse_args()


def _opted_in(a: argparse.Namespace) -> bool:
    return bool(a.provider and a.model and (a.region or a.endpoint) and a.budget and a.i_accept_paid_inference)


async def _run_variant(client: Any, adapter: Any, variant: str, budget: int) -> dict[str, Any]:
    """One budgeted request; compare counted input vs normalized actual usage; check the cap was respected."""
    # FILL IN: build the variant's request (tools → a trivial @tool; stream → ask_stream; cache → cachePoint block if supported; schema → Mantle response_format);
    #          call with token_budget=budget; read report from AIMessage.metadata["token_budget"]; compute counted vs actual from the report's
    #          counting_methods/input_tokens; return the sanitized record described in Key Constraints. Bounded by spec §2.5 probe requirements.
    raise NotImplementedError


async def main() -> int:
    a = _parse()
    if not _opted_in(a):
        print("SKIPPED: qualification probe requires --provider --model --region|--endpoint --budget --i-accept-paid-inference")
        return 0
    versions = installed_sdk_versions("botocore", "aiobotocore", "aioboto3", "openai", "tiktoken")
    count_tokens_available = probe_count_tokens_support()
    # FILL IN: construct the client (BedrockConverseClient / NovaClient / BedrockMantleClient) and adapter; run selected variants sequentially;
    #          findings = {"provider", "model", "endpoint": region-or-host, "sdk_versions": versions, "count_tokens_available": count_tokens_available,
    #                      "results": [...], "strict_achievable": count_tokens_available and all(r["cap_respected"] and r["counted_input"] == r["actual_input"] ...)}
    #          write to artifacts/logs/token_budget_qualification_<provider>_<model-slug>_<utc>.json; print PASS/FAIL table and the QualificationKey literal.
    #          Bounded by spec §2.5 "record exact versions/request fingerprints" and "No automatic paid probes".
    raise NotImplementedError


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```
**Why this shape**: the gate (`_opted_in`) is evaluated before any client construction so the script is safe to run accidentally; version capture and the `CountTokens` probe make the findings self-describing (spec §2.5).

### `docs/clients/bedrock-mantle.md` (MODIFY)
```markdown
<!-- occurrences: 1 (verified: grep -c 'docs/clients/openai-compatible.md' docs/clients/bedrock-mantle.md) -->
<!-- AFTER — insert below the line `- `docs/clients/openai-compatible.md` — the shared `OpenAIBaseClient` hierarchy (FEAT-438)` (verified: bedrock-mantle.md:13) -->
- `docs/clients/token-budgets.md` — cumulative question token budgets on Mantle / Bedrock (FEAT-550)
```
**Why**: discoverability from the existing Mantle doc.

### FILL IN checklist
- [ ] every `<!-- FILL IN -->` section of the doc, bounded by the cited spec section
- [ ] `smoke_token_budget_qualification.py::_run_variant` and `main` bodies; bounded by spec §2.5
- [ ] docs index pointer if an index exists

---

## Acceptance Criteria

- [ ] `docs/clients/token-budgets.md` exists and covers: configuration table, §2.3 worked example with exact numbers, finalization table, streaming/cancellation, retries/SDK ownership, scope/resume/snapshot trust + retention, coverage matrix, strict-mode status (empty registry, botocore 1.35.36 lacks CountTokens), error reference
- [ ] Doc uses only satellite paths for Amazon files (no `packages/ai-parrot/src/parrot/clients/bedrock.py` / `nova/mantle.py`)
- [ ] `python examples/clients/smoke/smoke_token_budget_qualification.py` with no arguments prints `SKIPPED…` and exits 0 without importing `aioboto3`/`openai` network clients
- [ ] Probe never writes to `STRICT_QUALIFICATIONS`; findings path is under `artifacts/logs/` and contains no credentials or raw prompts
- [ ] `ruff check examples/clients/smoke/smoke_token_budget_qualification.py` clean; markdown renders (no broken tables)
- [ ] `docs/clients/bedrock-mantle.md` links to the new doc

---

## Test Specification

No pytest for this task. Manual checks:

```bash
source .venv/bin/activate
python examples/clients/smoke/smoke_token_budget_qualification.py ; echo "exit=$?"   # expect SKIPPED, exit=0
python - <<'EOF'
import re, pathlib
doc = pathlib.Path("docs/clients/token-budgets.md").read_text()
for needle in ("10,000", "1,500", "2,300", "3,800", "600", "4,000", "BudgetUnsupported", "1.35.36", "BudgetSnapshot", "release()"):
    assert needle in doc, needle
print("doc ok")
EOF
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §1, §2.1–§2.6, §5 (doc-related ACs)
2. **Check dependencies** — TASK-3141 and TASK-3143 in `sdd/tasks/completed/` (so the doc describes shipped behaviour)
3. **Verify the Codebase Contract** — confirm the adapter/qualification module names before citing them
4. **Update status** in `sdd/tasks/index/token-budget-bedrock.json` → `"in-progress"`
5. **Implement** from the Blueprint
6. **Verify** all acceptance criteria (run the manual checks above)
7. **Move this file** to `sdd/tasks/completed/TASK-3145-token-budget-docs-and-probe.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**:

**Deviations from spec**: none | describe if any
