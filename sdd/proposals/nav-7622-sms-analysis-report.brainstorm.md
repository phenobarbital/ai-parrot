# Brainstorm: SMS Analysis Report Dashboard for NavAPI

**Date**: 2026-03-04
**Author**: Claude
**Status**: exploration
**Jira**: [NAV-7622](https://trocglobal.atlassian.net/browse/NAV-7622)
**Recommended Option**: Option B

---

## Problem Statement

NAV currently has call detail reports for voice calls but **no equivalent reporting for SMS traffic**. Stakeholders need visibility into inbound and outbound SMS activity — including session-level analysis (sentiment, compliance, resolution) — to achieve parity with the call report.

**Who is affected:**
- **NAV Operations** — No SMS analytics for monitoring team performance
- **QA/Compliance** — Cannot review SMS sessions the same way they review calls
- **Management** — Missing a complete picture of contact center activity (calls + SMS)

**Source Data:**
- SMS detail records from Zoom (inbound/outbound)
- SMS session recordings (per conversation thread)
- Analysis pipeline output (sentiment, compliance, etc.) — same logic as calls

## Constraints & Requirements

- **Mirror the call report** — SMS report fields and analysis must use the same logic/metrics as the existing call detail report.
- **Data source is Zoom** — SMS records come from the same Zoom platform as calls.
- **Dashboard in navapi** — The report endpoint(s) live in `navigator-agent-server` (aiohttp + navigator-api).
- **SMS recordings accessible** — Each SMS session must link to conversation transcripts.
- **Data refresh cadence** — Must match NAV standards (likely periodic ETL or on-demand).
- **Access permissions** — Same permission model as call reports.
- **NAV data structures** — Analysis logic may need minor adaptation for SMS-specific fields.

---

## Options Explored

### Option A: REST API Endpoint + SQL Views (Server-Side Report)

Build a dedicated REST endpoint in `navigator-agent-server` that queries pre-built SQL views for SMS detail and serves JSON to the frontend.

**Approach:**
- Create a new `plugins/agents/sms_report/` module in `navigator-agent-server`.
- Define SQL views (`vw_sms_detail`, `vw_sms_analysis`) on the NAV database that join SMS records with their analysis results.
- Build an aiohttp handler (using `navigator-api` patterns) that accepts filter params (date range, agent, direction) and returns paginated results.
- SMS session transcripts linked as a foreign key in the detail view.
- Analysis fields (sentiment score, compliance flag, resolution status) populated by a batch ETL job that mirrors the call analysis pipeline.

**API Design:**
```
GET /api/v1/reports/sms?start_date=2026-03-01&end_date=2026-03-04&direction=inbound
GET /api/v1/reports/sms/{session_id}/transcript
GET /api/v1/reports/sms/summary?group_by=agent&period=daily
```

**Pros:**
- Clean separation: SQL views handle data shaping, API handles access control + pagination
- Fast queries via pre-computed views and indexes
- Familiar pattern — mirrors how call reports likely work
- Easy to extend with new filters or aggregations
- Cacheable at the API layer

**Cons:**
- Requires database schema access to create views
- SQL views need maintenance if source schema changes
- ETL pipeline for SMS analysis must be built separately (or adapted from calls)
- No AI-powered analysis — purely structured data

**Effort:** Medium

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-api` | HTTP handler framework | Already in project |
| `asyncdb` | Async database queries | Already in project |
| `pydantic` | Request/response schemas | Already in project |

**Existing Code to Reuse:**
- Existing call report SQL views/logic (as template)
- `navigator-agent-server/agents/hr.py` — Handler pattern for reference
- `navigator-api` handler conventions

---

### Option B: PandasAgent-Powered SMS Dashboard (AI-Assisted Analysis)

Use ai-parrot's `PandasAgent` and `DatasetManager` to create an SMS analysis agent that can load SMS data, run analysis, and serve results as a dashboard endpoint.

**Approach:**
- Define an `SMSDataset` configuration in `DatasetManager` that loads SMS detail from DB.
- Create an SMS analysis bot (similar to existing agents in `agents/`) that uses `PandasAgent` for data operations.
- The bot loads SMS data as a DataFrame, applies analysis logic (sentiment, compliance), and exposes results via the existing bot handler API.
- Dashboard endpoint fetches the pre-analyzed dataset and serves it as structured JSON.
- Leverage ai-parrot's output formatters (`table`, `json`, `markdown`) for rendering.

**Architecture:**
```
[Zoom SMS Data] → [DB/ETL] → [DatasetManager] → [PandasAgent]
                                                       ↓
                                              [SMS Analysis Bot]
                                                       ↓
                                            [Dashboard API Endpoint]
```

**Pros:**
- Leverages existing `PandasAgent` + `DatasetManager` infrastructure
- AI-powered analysis: can run LLM-based sentiment/compliance analysis on SMS content
- Flexible — analysts can query the data in natural language
- Output formatters already handle table/JSON/markdown rendering
- Consistent with ai-parrot's agent architecture

**Cons:**
- More complex than a simple SQL →  API approach
- PandasAgent loads data into memory — may not scale for very large datasets
- Requires defining SMS-specific dataset configurations
- LLM calls for analysis add latency and cost

**Effort:** Medium-High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.tools.dataset_manager` | Dataset loading/management | Already in project |
| `parrot.tools.pythonpandas` | PandasAgent for data analysis | Already in project |
| `parrot.outputs.formats.*` | Output rendering | Already in project |

**Existing Code to Reuse:**
- `parrot/tools/dataset_manager.py` — `DatasetManager` for loading datasets
- `parrot/tools/pythonpandas.py` — `PandasAgent` for DataFrame operations
- `parrot/bots/data.py` — Data bot pattern
- `agents/hr.py` — Agent registration pattern in navapi

---

### Option C: Scheduled ETL + Materialized Dashboard Data (Pre-Computed)

Build a background task that periodically fetches SMS data from Zoom, runs the analysis pipeline, and writes results to a materialized table. The dashboard API reads from this table.

**Approach:**
- Create a scheduled task using `AgentSchedulerManager` (already in navapi) that runs daily/hourly.
- The task connects to Zoom API to fetch SMS records, processes them through the analysis pipeline (same logic as calls), and writes results to a `sms_report` table.
- A simple REST endpoint reads from `sms_report` with filtering and pagination.
- SMS transcripts stored as JSON in a dedicated column or linked table.
- Analysis scores (sentiment, compliance) computed during ETL and stored.

**Task Flow:**
```
[Scheduler] → [Zoom API fetch] → [Analysis Pipeline] → [sms_report table]
                                                              ↓
                                                     [REST API endpoint]
```

**Pros:**
- Dashboard queries are fast (pre-computed data)
- Analysis runs in background — no API latency
- Scheduler infrastructure already exists in navapi (`AgentSchedulerManager`)
- Clean separation between data generation and data serving
- Can use `BackgroundQueue` for heavy processing

**Cons:**
- Data is not real-time (depends on refresh cadence)
- ETL logic must be built and maintained
- Zoom API integration adds external dependency
- Requires handling API rate limits, pagination, and error recovery

**Effort:** High

**Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `parrot.scheduler` | Task scheduling | Already in navapi |
| `navigator.background` | Background task queue | Already in navapi |
| `asyncdb` | Database operations | Already in project |
| Zoom API client | SMS data fetch | Needs to be built/integrated |

**Existing Code to Reuse:**
- `app.py` — `AgentSchedulerManager` and `BackgroundQueue` setup
- Call report ETL pipeline (as template for SMS pipeline)
- Existing Zoom integration patterns (if any)

---

## Recommendation

**Option B (PandasAgent-Powered SMS Dashboard)** is recommended because:

1. **Leverages existing infrastructure** — `PandasAgent`, `DatasetManager`, and output formatters are already battle-tested in ai-parrot. This avoids building everything from scratch.

2. **AI-powered analysis** — Unlike a pure SQL approach, this can run LLM-based sentiment/compliance analysis on SMS text content, matching the "same logic as call reports" requirement.

3. **Consistent architecture** — Follows the same agent pattern as `hr.py` and other agents in navapi, keeping the codebase consistent.

4. **Extensible** — Natural language querying via bot interface allows stakeholders to ask ad-hoc questions beyond fixed report views.

**However**, for very high data volumes or strict real-time requirements, a **hybrid of Options A + B** might be better: SQL views for structured queries + PandasAgent for AI-powered analysis overlays.

---

## Feature Description

### User-Facing Behavior

1. **SMS Detail Report** — A paginated table showing all inbound/outbound SMS sessions with:
   - Timestamp, direction (inbound/outbound), agent, customer
   - Sentiment score, compliance flag, resolution status
   - Link to SMS transcript

2. **SMS Summary Dashboard** — Aggregated metrics:
   - Total SMS volume (inbound vs outbound) by period
   - Average sentiment score by agent/team
   - Compliance rate
   - Response time distribution

3. **SMS Transcript Viewer** — Ability to click into a session and see the full SMS conversation thread.

### Internal Behavior

```
SMSReportDataset:
  → DatasetManager.load("sms_detail", filters={date_range, direction, agent})
  → PandasAgent processes DataFrame:
     - Apply sentiment analysis per message
     - Calculate compliance scores
     - Aggregate session-level metrics
  → Results cached and served via API handler
```

### Edge Cases & Error Handling

| Scenario | Behavior |
|---|---|
| No SMS data for date range | Return empty result set with metadata |
| Zoom API unavailable | Gracefully degrade, show cached/stale data |
| Large dataset (>100k records) | Paginate, apply server-side filters before loading |
| Missing analysis fields | Return partial data with null analysis fields |
| Permission denied | Return 403 with appropriate message |

---

## Capabilities

### New Capabilities
- `sms-report-dataset`: DatasetManager config for SMS detail data
- `sms-analysis-agent`: Agent/bot that runs SMS analysis via PandasAgent
- `sms-dashboard-api`: REST endpoints for SMS report + summary + transcript

### Modified Capabilities
- `agent-scheduler` (potentially): Add scheduled refresh for SMS analysis
- `frontend-dashboard` (future): UI components to render SMS report

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `navigator-agent-server/agents/` | new file | SMS analysis agent |
| `navigator-agent-server/plugins/` | new file | SMS report handler/tool |
| `navigator-agent-server/settings/` | modifies | SMS dataset configuration |
| `ai-parrot/parrot/tools/` | potentially | SMS-specific tool if needed |
| `navigator-frontend-next` | future | Dashboard UI (separate ticket) |
| Database | new views/tables | SMS detail views or materialized tables |

---

## Open Questions

- [ ] **Where is the existing call report?** — Need to locate the call detail report codebase to mirror its structure. Which repo/module contains the call report? *Owner: Team*
- [ ] **Zoom API access** — Do we already have a Zoom API client for SMS data, or does the data come via ETL dump to a database? *Owner: Data Engineering*
- [ ] **Database schema** — What does the SMS raw data schema look like? Is it already in the NAV database or needs to be imported? *Owner: Data Engineering*
- [ ] **Analysis pipeline** — Is the call analysis pipeline (sentiment, compliance) already packaged as a reusable module, or tightly coupled to call-specific logic? *Owner: AI Team*
- [ ] **Frontend scope** — Is the dashboard UI part of this ticket or a separate one? The Jira ticket focuses on data/API. *Owner: Product*
- [ ] **Data volume** — How many SMS sessions per day should the system handle? This affects whether PandasAgent or SQL views are more appropriate. *Owner: Data Engineering*
