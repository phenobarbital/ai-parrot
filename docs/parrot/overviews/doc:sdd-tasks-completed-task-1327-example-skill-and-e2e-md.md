---
type: Wiki Overview
title: 'TASK-1327: Example skill `financial_projection_variance` + e2e tests + docs'
id: doc:sdd-tasks-completed-task-1327-example-skill-and-e2e-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Bundles the three final deliverables for FEAT-197:'
relates_to:
- concept: mod:parrot.models.infographic
  rel: mentions
- concept: mod:parrot.models.infographic_templates
  rel: mentions
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.tools.infographic_toolkit
  rel: mentions
---

# TASK-1327: Example skill `financial_projection_variance` + e2e tests + docs

**Feature**: FEAT-197 — Infographic Toolkit
**Spec**: `sdd/specs/infographictoolkit.spec.md` (Module 9 + integration tests + docs)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1323, TASK-1324, TASK-1325, TASK-1326, TASK-1322
**Parallel**: false
**Assigned-to**: unassigned

---

## Context

Bundles the three final deliverables for FEAT-197:

1. **Example skill** (Module 9): the reference `/financial_variance`
   markdown skill demonstrating the full contract — frontmatter triggers,
   DataFrame computation instructions, and a mandatory closing
   `infographic_render(...)` call.
2. **End-to-end integration tests** (§4 of the spec): exercise the chat
   path → middleware → tool loop → toolkit → artifact persist → HTTP
   envelope.
3. **Documentation** (§5 of the spec): toolkit reference page + CSP /
   signed-URL operations note in `docs/`.

The skill body relies on the toolkit (TASK-1323 + 1324), the enhance
pipeline (TASK-1325), the post-loop branch (TASK-1326), and the public
HTML route (TASK-1322).

---

## Scope

### 9.1 Example skill

- Pick a representative agent (look for an existing agents directory the
  team uses for finance demos — `grep` `AGENTS_DIR` configuration).
- Create `AGENTS_DIR/<agent>/skills/financial_projection_variance.md`
  with YAML frontmatter:
  ```yaml
  ---
  name: financial_projection_variance
  triggers: ['/financial_variance']
  description: Multi-dataset financial variance dashboard.
  ---
  ```
- Body MUST:
  - Tell the LLM to compute three DataFrames via `python_repl_pandas`:
    daily revenue, daily EBITDA, cumulative revenue.
  - Tell the LLM the mandatory closing tool call:
    `infographic_render(template_name="financial_projection_variance",
    theme="dark", mode="enhance", blocks=[...], data_variables=["rev_daily",
    "ebitda_daily", "rev_cumulative"], enhance_brief="...")`.
  - List the positional contract for the template (4 hero cards + 2 DoD
    bar charts + 1 cumulative line chart).

If the template `financial_projection_variance` is not already in the
registry, register it via a small Python registration block in
`parrot/models/infographic_templates.py` (or in a sibling registration
module). This template needs `js_bundles=[JSBundle(name="echarts",
scope="cdn", url=..., sri_hash=...)]` to exercise the SRI whitelist path.

### 9.2 End-to-end integration tests

Create `packages/ai-parrot/tests/integration/test_infographic_e2e.py`
with these scenarios (cf. spec §4 integration test table):

- `test_e2e_slash_skill_end_to_end`
- `test_e2e_output_mode_request`
- `test_e2e_html_serving`
- `test_e2e_enhance_fallback`
- `test_e2e_validation_error_surfaced`
- `test_e2e_legacy_get_infographic_untouched`

These should run against an aiohttp `TestClient` with the LLM client
mocked (use the existing test harness pattern — search
`packages/ai-parrot/tests/integration/` for one that mocks `AbstractClient.completion`).

### 9.3 Documentation

- `docs/toolkits/infographic_toolkit.md` — public reference for the
  four tools, the error codes, the request flow diagram (copy from
  spec §2), and the `output_mode=infographic` HTTP API.
- `docs/operations/infographic_csp_and_signed_urls.md` — env vars
  (`INFOGRAPHIC_FRAME_ANCESTORS`, `INFOGRAPHIC_SIGNING_KEY`), CSP set,
  signature scheme, 7-day cap, observability (which log lines fire on
  validation failure vs. enhance fallback).

**NOT in scope**:
- Production tuning (CDN cache, rate-limits).
- Additional templates beyond `financial_projection_variance`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `agents/<agent>/skills/financial_projection_variance.md` | CREATE | Example skill markdown. |
| `packages/ai-parrot/src/parrot/models/infographic_templates.py` | MODIFY | Register `financial_projection_variance` template. |
| `packages/ai-parrot/tests/integration/test_infographic_e2e.py` | CREATE | Six e2e scenarios. |
| `docs/toolkits/infographic_toolkit.md` | CREATE | Toolkit reference. |
| `docs/operations/infographic_csp_and_signed_urls.md` | CREATE | Ops note. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.infographic_toolkit import (
    InfographicToolkit, InfographicRenderResult,
    InfographicValidationError,
)
from parrot.models.outputs import OutputMode
from parrot.models.infographic import JSBundle
from parrot.models.infographic_templates import (
    BlockSpec, InfographicTemplate, infographic_registry,
)
from parrot.models.infographic import BlockType
```

### Existing Signatures to Use

```python
# parrot/skills/file_registry.py
class SkillFileRegistry:
    # Loads .md skills with YAML frontmatter from AGENTS_DIR/<agent>/skills/
    def get(self, trigger: str) -> Optional[SkillDefinition]: ...
```

```python
# parrot/skills/middleware.py:16-74
def create_skill_trigger_middleware(registry, bot, priority=-10): ...
# - Strips `/trigger` from the user query.
# - Sets bot._active_skill.
```

```python
# parrot/bots/abstract.py:2613-2640
# _build_request_prompt() injects the skill's template_body as a
# transient PromptLayer for the single turn.
```

### Does NOT Exist
- ~~`/!skill` parsing in `AgentTalk.post()`~~ — activation uses `/trigger`
  middleware ONLY.
- ~~`financial_projection_variance` template~~ — registered by this task.

---

## Implementation Notes

### Skill body template

Skills are markdown. The body becomes the LLM instructions injected
transiently. Keep it under ~500 tokens. Example:

```markdown
---
name: financial_projection_variance
triggers: ['/financial_variance']
description: Multi-dataset financial variance dashboard.
---

You are producing a financial variance infographic.

1. Using `python_repl_pandas`, compute these three DataFrames from the
   session's pre-loaded data:
   - `rev_daily`: columns [day, revenue]
   - `ebitda_daily`: columns [day, ebitda]
   - `rev_cumulative`: columns [day, cumulative_revenue]

2. Build four `hero_card` blocks summarising:
   - Total revenue for the period.
   - Total EBITDA for the period.
   - EBITDA margin (EBITDA / revenue).
   - Largest single-day swing.

3. Build two `chart` blocks (bar, DoD): one for revenue, one for EBITDA.
4. Build one `chart` block (line) for cumulative revenue.

5. Close the turn by calling:

   infographic_render(
       template_name="financial_projection_variance",
       theme="dark",
       mode="enhance",
       blocks=[hero_card_block, chart_rev, chart_ebitda, chart_cum],
       data_variables=["rev_daily", "ebitda_daily", "rev_cumulative"],
       enhance_brief="Add tooltips and hover interactivity using ECharts.",
   )

The tool result is the final answer — do NOT summarise it.
```

### Template registration

```python
# parrot/models/infographic_templates.py (append near other TEMPLATE_* blocks)
TEMPLATE_FINANCIAL_PROJECTION_VARIANCE = InfographicTemplate(
    name="financial_projection_variance",
    description="4 hero cards + 2 DoD bar charts + 1 cumulative line chart.",
    block_specs=[
        BlockSpec(block_type=BlockType.HERO_CARD, min_items=4, max_items=4),
        BlockSpec(block_type=BlockType.CHART, required=True),
        BlockSpec(block_type=BlockType.CHART, required=True),
        BlockSpec(block_type=BlockType.CHART, required=True),
    ],
    default_theme="dark",
    js_bundles=[
        JSBundle(name="echarts", scope="cdn",
                 url="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js",
                 sri_hash="sha384-PLACEHOLDER_REPLACE_BEFORE_MERGE"),
    ],
)
infographic_registry.register(TEMPLATE_FINANCIAL_PROJECTION_VARIANCE)
```

**Note**: the SRI hash for the CDN script is a placeholder — replace with
the genuine `openssl dgst -sha384 -binary echarts.min.js | base64` value
before merging.

### Integration test pattern

```python
# packages/ai-parrot/tests/integration/test_infographic_e2e.py
import pytest
from aiohttp.test_utils import TestClient
from parrot.models.outputs import OutputMode


@pytest.mark.asyncio
async def test_e2e_slash_skill_end_to_end(app_client: TestClient, mock_llm_loop):
    # Configure mock_llm_loop to produce the toolkit call sequence:
    #   python_repl_pandas (computes rev_daily, ebitda_daily, rev_cumulative)
    #   infographic_render(template_name=..., mode="enhance", ...)
    resp = await app_client.post(
        "/api/v1/agents/talk/<agent-id>",
        json={"input": "/financial_variance Q4 2025"},
    )
    body = await resp.json()
    assert resp.status == 200
    assert body["output_mode"] == "infographic"
    assert "artifact_id" in body
    assert isinstance(body["data"], list) and len(body["data"]) == 3
```

### Key Constraints
- Don't ship a real working `sri_hash` you can't justify — placeholder is
  fine for v1 if documented loudly. Otherwise compute the genuine hash.
- E2E tests MUST mock the LLM. No real provider calls in CI.
- Docs are markdown; do NOT add diagrams as image assets in this task.

---

## Acceptance Criteria

- [ ] `/financial_variance` triggers the skill via `SkillRegistry`.
- [ ] The example skill body explicitly names the four required tool
      calls (the three DataFrame computations plus the closing
      `infographic_render`).
- [ ] `infographic_registry.get("financial_projection_variance")` returns
      a template with the documented 4-block contract and a `js_bundles`
      entry.
- [ ] All six e2e tests in `test_infographic_e2e.py` pass.
- [ ] `docs/toolkits/infographic_toolkit.md` exists and lists all four
      tools + the nine validation error codes.
- [ ] `docs/operations/infographic_csp_and_signed_urls.md` exists and
      documents `INFOGRAPHIC_FRAME_ANCESTORS`, the signature scheme, and
      the 7-day cap.
- [ ] `pytest packages/ai-parrot/tests/integration/test_infographic_e2e.py -v` passes.
- [ ] Legacy `POST /api/v1/agents/infographic/{id}` test remains green
      (regression guard inside this task's suite).

---

## Test Specification

```python
# packages/ai-parrot/tests/integration/test_infographic_e2e.py
import pytest
from parrot.models.outputs import OutputMode


@pytest.mark.asyncio
async def test_e2e_slash_skill_end_to_end(app_client, mock_llm_loop_financial):
    resp = await app_client.post(
        "/api/v1/agents/talk/<agent-id>",
        json={"input": "/financial_variance Q4 2025"},
    )
    body = await resp.json()
    assert body["output_mode"] == OutputMode.INFOGRAPHIC.value
    assert body["artifact_id"]
    assert len(body["data"]) == 3


@pytest.mark.asyncio
async def test_e2e_output_mode_request(app_client, mock_llm_loop_financial):
    resp = await app_client.post(
        "/api/v1/agents/talk/<agent-id>",
        json={"input": "produce the Q4 dashboard",
              "output_mode": "infographic"},
    )
    body = await resp.json()
    assert body["output_mode"] == "infographic"


@pytest.mark.asyncio
async def test_e2e_html_serving(app_client, persisted_artifact_token):
    resp = await app_client.get(
        f"/api/v1/artifacts/public/{persisted_artifact_token.sig}/"
        f"{persisted_artifact_token.artifact_id}.html"
    )
    assert resp.status == 200
    assert resp.content_type == "text/html"
    assert "Content-Security-Policy" in resp.headers


@pytest.mark.asyncio
async def test_e2e_enhance_fallback(app_client, mock_llm_loop_malicious_enhance):
    resp = await app_client.post(
        "/api/v1/agents/talk/<agent-id>",
        json={"input": "/financial_variance Q4 2025"},
    )
    body = await resp.json()
    assert body["metadata"]["enhanced"] is False  # silently fell back


@pytest.mark.asyncio
async def test_e2e_validation_error_surfaced(app_client, mock_llm_loop_bad_blocks):
    resp = await app_client.post(
        "/api/v1/agents/talk/<agent-id>",
        json={"input": "/financial_variance Q4 2025"},
    )
    body = await resp.json()
    assert body["error"]["code"] in {
        "SLOT_MISSING", "SLOT_TYPE_MISMATCH", "SLOT_ITEM_COUNT_INVALID",
    }


@pytest.mark.asyncio
async def test_e2e_legacy_get_infographic_untouched(app_client, mock_llm_legacy):
    resp = await app_client.post(
        "/api/v1/agents/infographic/<agent-id>",
        json={"query": "produce a single infographic",
              "template": "basic"},
    )
    assert resp.status == 200  # legacy path unchanged
```

---

## Agent Instructions

1. Confirm TASK-1322, 1323, 1324, 1325, 1326 are all merged before
   starting — this task validates the integrated path.
2. Register the new template, then write the skill markdown.
3. Build the e2e harness incrementally (one test at a time, each with
   focused mock fixtures).
4. Write the two doc pages last — once the behaviour is verified.
5. Run the full integration suite + the legacy infographic regression:
   `pytest packages/ai-parrot/tests/integration/ -v`.
6. Move to `sdd/tasks/completed/` and update the per-spec index, then
   call `/sdd-done FEAT-197`.

---

## Completion Note

*(Agent fills this in when done)*
