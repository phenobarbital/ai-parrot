# TASK-2244: Documentation — docs/research_tools.md

**Feature**: FEAT-426 — Research Tools for Agents
**Spec**: `sdd/specs/research-tools-for-agents.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-2243
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 6, and an explicit acceptance criterion in spec §5. Two things
in this feature are non-obvious enough that an undocumented user will get them
wrong:

1. `ResearchRouter` needs an **injected** LLM — it cannot reach the calling
   agent's model. Without docs, users will construct it bare and silently get
   heuristic-only routing.
2. The toolkits need the `ai-parrot-tools[research]` extra; without it, every
   method returns a `status="error"` result rather than crashing, which is
   easy to misread as "the API is down".

Write this only after TASK-2243, so the documented import paths and tool names
match what actually ships.

---

## Scope

- Create `docs/research_tools.md` covering: installation, the two toolkits and
  their ten tools, router construction with LLM injection, the result/citation
  model, the error contract, per-source caveats and rate limits, and worked
  examples.
- Verify every code sample in the doc actually runs (imports resolve, names
  match).

**NOT in scope**: code changes. If a doc example reveals a bug, report it and
open a follow-up task — do not fix implementation here.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `docs/research_tools.md` | CREATE | User-facing guide |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports (use these verbatim in examples)

```python
from parrot_tools.research import (
    OpenDataToolkit, AcademicResearchToolkit, ResearchRouter,
    ResearchResult, Citation,
)
```

### Tool Surface to Document (exactly these — no others)

```python
OpenDataToolkit          # 5 tools
    search_world_bank(query, indicator=None, country=None,
                      date_range=None, max_results=10)
    get_world_bank_indicator(indicator_id, country, year=None, date_range=None)
    search_eu_open_data(query, dataset_type=None, publisher=None, max_results=10)
    search_oecd_data(query, dataset=None, country=None, max_results=10)
    get_oecd_indicator(dataset_id, country, frequency=None)

AcademicResearchToolkit  # 5 tools
    search_crossref(query, author=None, year_range=None,
                    journal=None, max_results=10)
    search_pubmed(query, mesh_terms=None, date_range=None, max_results=10)
    search_semantic_scholar(query, fields_of_study=None, year=None,
                            open_access_only=False, max_results=10)
    search_arxiv(query, max_results=10, sort_by="relevance", category=None)
    get_paper_details(doi_or_id, source=None)

ResearchRouter(AbstractTool)     # 1 tool, name = "research"
    __init__(open_data=None, academic=None, llm=None)
    _execute(query, categories=None, max_results=10)
```

### Facts to State Correctly

| Topic | Fact |
|---|---|
| Extra | `pip install 'ai-parrot-tools[research]'` → `wbgapi`, `sdmx1`, `habanero`, `biopython`, `arxiv` |
| Router LLM | Injected via `llm=`; accepts an `AbstractClient` **or** a string resolved by `LLMFactory`. `llm=None` → keyword heuristics |
| No bot back-reference | Tools cannot reach the calling agent's LLM (framework invariant) |
| Categories | Exactly `open_data` and `academic` |
| Error contract | Failures arrive as `ResearchResult.status` in `{no_data, error}` with `error_message` — tools never raise |
| Citations | Every `status="success"` result carries a full `Citation` |
| World Bank | **No keyword search** — indicator codes / topics work far better than prose |
| OECD | Needs a dataflow id; use `search_oecd_data` to find one |
| PubMed | Set `NCBI_EMAIL` (required by NCBI); optional `NCBI_API_KEY` raises 3→10 req/s |
| Crossref | Set `CROSSREF_MAILTO` for the polite pool |
| Semantic Scholar | Optional `SEMANTIC_SCHOLAR_API_KEY`; free pool is shared globally → 429s happen |
| Oxford Academic | No API of its own — OUP DOIs (`10.1093/...`) resolve via Crossref |
| Caching | Redis-backed `ToolCache`; ~1 h indicators, ~24 h papers |

### Does NOT Exist — do NOT document

- ~~`MarketResearchToolkit`, Statista, Gallup, Gartner~~ — dropped from v1
  (spec §1 Non-Goals). Mention them **only** if writing a short "not covered"
  note, and say why.
- ~~An Oxford Academic source/tool~~
- ~~A `market` category for the router~~
- ~~Required API keys~~ — every key is optional

---

## Implementation Notes

### Suggested structure

1. **Overview** — what problem these tools solve vs. web search
2. **Installation** — the `research` extra; behaviour when it is missing
3. **Quick start** — one open-data example, one academic example
4. **The result model** — `ResearchResult`, `Citation`, and the `status` values
5. **Error contract** — failures are data, not exceptions; how to check `status`
6. **`OpenDataToolkit`** — the 5 tools, with the World Bank / OECD caveats
7. **`AcademicResearchToolkit`** — the 5 tools, with the PubMed / S2 caveats
8. **`ResearchRouter`** — construction, **LLM injection**, heuristic fallback
9. **Configuration** — the full env-var table
10. **Caching** — TTLs and how to tune them
11. **Not covered in v1** — one short paragraph on market research and why

### Worked example to include

```python
from parrot_tools.research import OpenDataToolkit, AcademicResearchToolkit, ResearchRouter

router = ResearchRouter(
    open_data=OpenDataToolkit(),
    academic=AcademicResearchToolkit(),
    llm="openai:gpt-4o-mini",      # injected classifier — required for LLM routing
)
agent = Agent(name="analyst", tools=[router])
```
Plus a direct-toolkit example that inspects `status` and `citation`.

### Key Constraints

- Follow the tone and structure of existing docs in `docs/`.
- Every code block must use the verified import paths above.
- Do not document parameters that do not exist — cross-check against the
  contract table before writing each signature.

### References in Codebase

- `docs/company_info.md` — comparable toolkit guide; match its structure
- `docs/hitl-confirmation.md` — feature-doc tone

---

## Acceptance Criteria

- [ ] `docs/research_tools.md` exists and covers all 11 sections above.
- [ ] All 10 toolkit tools plus the router are documented with correct,
      verified signatures.
- [ ] Router LLM injection is documented prominently, including the fact that
      `llm=None` degrades to heuristics and that tools cannot reach the
      agent's own LLM.
- [ ] The error contract is documented — failures as `status`, not exceptions.
- [ ] The env-var table lists `NCBI_EMAIL`, `NCBI_API_KEY`, `CROSSREF_MAILTO`,
      `SEMANTIC_SCHOLAR_API_KEY` and states that all are optional except the
      NCBI email recommendation.
- [ ] The `research` extra install command is present and correct.
- [ ] `MarketResearchToolkit` / Statista / Gallup / Gartner appear **only** in
      the "not covered in v1" note, if at all.
- [ ] Every import in every code block resolves against the shipped package
      (verify by running them).
- [ ] No documented parameter is absent from the real signatures.

---

## Test Specification

No automated tests. Manual verification:

```bash
source .venv/bin/activate
# Every documented import must resolve
python -c "from parrot_tools.research import (OpenDataToolkit, \
AcademicResearchToolkit, ResearchRouter, ResearchResult, Citation); print('ok')"

# Documented tool names must match reality
python - <<'PY'
from parrot_tools.research import OpenDataToolkit, AcademicResearchToolkit
print(sorted(t.name for t in OpenDataToolkit().get_tools()))
print(sorted(t.name for t in AcademicResearchToolkit().get_tools()))
PY
```
Diff both lists against the tool tables in the doc — they must match exactly.

---

## Agent Instructions

1. **Read the spec** — §2 (models, error contract), §5 (acceptance criteria),
   §7 (gotchas worth surfacing to users).
2. **Check** TASK-2243 is in `sdd/tasks/completed/`.
3. **Verify** the shipped tool names with the snippet above **before** writing
   the tool tables.
4. Update the index → `"in-progress"`.
5. **Write** the doc; run every code block.
6. **Verify** acceptance criteria; move to `completed/`; update index.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-08-17
**Notes**: `docs/research_tools.md` covers all 11 suggested sections
(overview, installation, quick start, result model, error contract, both
toolkits' 5 tools each with per-source caveats, `ResearchRouter` with
prominent LLM-injection documentation, env-var config table, caching
TTLs, "not covered in v1"). Verified tool names shipped
(`OpenDataToolkit`/`AcademicResearchToolkit` `get_tools()`) exactly match
the doc's tables before writing them. Every code block's imports were
actually run: `from parrot_tools.research import (...)`, `from
parrot.bots import Agent`, `ResearchRouter(...)` with both `llm=None` and
`llm="openai:gpt-4o-mini"`, and a full `Agent(name="analyst",
tools=[router])` construction (confirmed via log output: "Registered
tool: research"). Model field lists (`ResearchResult`, `Citation`,
`IndicatorValue`, `PaperResult`, `DatasetResult`) verified against
`model_fields` on the real classes.
**Deviations from spec**: none
