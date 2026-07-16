---
type: Wiki Overview
title: FEAT-230 — Vendor flowtask's composable Workday interface and rebase WorkdayToolkit
  onto it
id: doc:sdd-proposals-workday-tooling-composable-interface-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim, is at `sdd/state/FEAT-230/source.md`.
relates_to:
- concept: mod:parrot.conf
  rel: mentions
- concept: mod:parrot.interfaces
  rel: mentions
- concept: mod:parrot.interfaces.soap
  rel: mentions
---

---
id: FEAT-230
title: Vendor flowtask's composable Workday interface into ai-parrot-tools and rebase WorkdayToolkit onto it
slug: workday-tooling-composable-interface
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-08
  summary_oneline: Vendor composable Workday interface into parrot_tools/interfaces/workday; rebase WorkdayToolkit; homologate 11 agent methods
overall_confidence: high
base_branch: dev
research_state: sdd/state/FEAT-230/
created: 2026-06-08
updated: 2026-06-08
---

# FEAT-230 — Vendor flowtask's composable Workday interface and rebase WorkdayToolkit onto it

> **Mode**: enrichment
> **Confidence**: high
> **Source**: `inline` (user description + 3-level plan + 11-method homologation list)
> **Audit**: [`sdd/state/FEAT-230/`](../state/FEAT-230/)

---

## 0. Origin

The original request, preserved verbatim, is at `sdd/state/FEAT-230/source.md`.

> En `flowtask/interfaces/workday/` hemos generado una interfaz composable para trabajar
> con Workday […]. Esta propuesta consta de 3 niveles: 1. copiar enteramente la interfaz
> a `parrot_tools/interfaces/workday`; 2. hacer que `WorkdayToolkit` use este composable
> en vez de tener el código in-line per-method; 3. cuando el toolkit esté homologado,
> garantizar que [11 métodos agent-facing] son ejecutables por el Toolkit de Workday.

**Initial signals** (extracted, not interpreted):
- Verbs: *copiar enteramente*, *use este composable*, *verificar/garantizar* → migration + refactor + homologation (no negation → not a bug).
- Named entities: `flowtask/interfaces/workday`, `parrot_tools/interfaces/workday`, `WorkdayToolkit`, `parrot_tools/workday/tool.py`, 11 agent methods.
- Components / labels: Workday, SOAP/WSDL, toolkit, agent tools.
- Acceptance criteria provided: yes — the 11-method executable checklist is the homologation gate.

---

## 1. Synthesis Summary

The request is a three-phase enrichment: (1) **vendor** the mature flowtask composable at
`flowtask/interfaces/workday/` (60 files, ~16.6k LOC: `WorkdayService(SOAPClient)` + `handlers/`
+ `models/` + `parsers/` + `config.py`) into a new `parrot_tools/interfaces/workday/` package;
(2) **rebase** the existing in-line `WorkdayToolkit` (`parrot_tools/workday/tool.py`, whose
`WorkdaySOAPClient` builds SOAP envelopes per-method) so each tool delegates to the composable's
`fetch()`/`call_operation()` instead of hand-built SOAP; (3) **homologate** by ensuring 11
agent-facing methods are callable as tools. Research confirms the vendoring is low-risk — the
flowtask `SOAPClient` and the core `parrot.interfaces.soap.SOAPClient` (which the toolkit already
imports) share a near-identical public API, so the composable can rebase onto the core base cleanly.
The dominant cost is **net-new work**: 9 of the 11 requested methods do not exist anywhere and form
a new "current-user / self-service" layer (including a **write** op, `request_my_time_off`).
Recommendation: proceed to `/sdd-spec` — localization is high-confidence and the only forks are
already resolved in §5.

---

## 2. Codebase Findings

> All entries grounded in `sdd/state/FEAT-230/findings/`. No fabricated paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `flowtask/interfaces/workday/service.py` *(source)* | `WorkdayService(SOAPClient)` | 111-… | composable to vendor: `fetch`/`fetch_models`/`get_custom_report`/`call_operation` | F001 |
| 2 | `flowtask/interfaces/workday/{handlers,models,parsers,config.py}` *(source)* | — | — | per-entity handlers, Pydantic models, SOAP parsers, `WorkdayConfig`+`get_wsdl_path` | F001 |
| 3 | `packages/ai-parrot/src/parrot/interfaces/soap.py` | `SOAPClient(ABC)` | 50-263 | core SOAP base — rebase target (near-identical API) | F002 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | `WorkdaySOAPClient(SOAPClient)` | 350-466 | **in-line** SOAP build (`_build_worker_reference`, `_build_request_criteria`, `_parse_worker_response`) — to be replaced | F003 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` | `WorkdayToolkit(AbstractToolkit)` | 472-1775 | ~16 `wd_*` async methods + `@tool_schema`; `METHOD_TO_SERVICE_MAP` WSDL routing | F003 |
| 6 | `packages/ai-parrot/src/parrot/tools/toolkit.py` | `AbstractToolkit.get_tools` | 337-425 | tool auto-gen: every **public async method** → a tool (name-based) | F004 |
| 7 | `packages/ai-parrot/src/parrot/conf.py` | `WORKDAY_*` | 595-608 | tenant/client/secret/token/wsdl/report creds already in core | F004 |

> New package to create: `packages/ai-parrot-tools/src/parrot_tools/interfaces/workday/`
> (no `parrot_tools/interfaces/` directory exists today — F002).

### 2.2 Constraints Discovered

- **Tools = public async methods.** `AbstractToolkit.get_tools()` iterates `dir(self)`, drops
  `_`-prefixed names, and keeps `inspect.iscoroutinefunction` results. *Implication*: each of the
  11 homologated methods must be a **public async method** on the toolkit (or its base) with a clear
  docstring; the docstring becomes the LLM tool description. *Evidence*: F004

- **Composable returns DataFrames.** `WorkdayService.fetch()` returns `pandas.DataFrame` and
  `fetch_models()` returns `list[Model]`. *Implication*: agent tools should return JSON-serializable
  dict/list, so the toolkit layer must convert composable output (use `fetch_models()` or
  `df.to_dict(orient="records")`, mirroring the existing `_flatten_entries` pattern in tool.py).
  *Evidence*: F001, F003

- **Two SOAPClient bases, one API.** flowtask's `WorkdayService` inherits
  `flowtask.interfaces.SOAPClient`; the toolkit already imports `parrot.interfaces.soap.SOAPClient`.
  Both expose `start/_get_bearer_token/get_transport/get_settings/get_client/bind_service/run/close/
  __aenter__/__aexit__`. *Implication*: rebasing the composable onto the core base is mechanical, not
  a rewrite. *Evidence*: F002

- **Config overlap.** `WORKDAY_*` already lives in core `parrot.conf`; the source ships its own
  `config.py:WorkdayConfig`/`get_wsdl_path`. *Implication*: the vendored `config.py` must read from
  `parrot.conf` (not `flowtask.conf`) to avoid a second source of truth. *Evidence*: F004, F001

- **Async-first + no `requests`/`httpx`-as-primary convention.** Per `.agent/CONTEXT.md`. The
  composable is already async (zeep AsyncClient). *Implication*: keep it async; route REST custom
  reports through the existing `HTTPService`. *Evidence*: F003

### 2.3 Recent History (Relevant)

Git history was not sampled in this pass (budget: 0 git calls — the request is a forward-looking
migration, not a regression hunt, so recent-change causality is not in question). The current
toolkit carries SDD lineage markers (`FEAT-027`, `TASK-101..105`) indicating the source composable
is a finished, tested artifact rather than a draft. *Evidence*: F001, F003

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`parrot_tools/interfaces/workday/`** — vendored composable package (`service.py`, `handlers/`,
  `models/`, `parsers/`, `config.py`, `utils/`), rebased onto `parrot.interfaces.soap.SOAPClient`
  and reading config from `parrot.conf`. *Evidence*: F001, F002
- **Current-user / self-service tool layer** on `WorkdayToolkit` — 9 net-new public async methods
  (see §2.2 homologation list). Each takes an **explicit `worker_id`** for identity (per §5 decision).
  *Evidence*: F005
- **`request_my_time_off`** — a **write** tool submitting an absence request via the Absence
  Management WSDL (in scope per §5). Requires a new write handler/parser in the vendored package.
  *Evidence*: F005

### What Changes

- **`parrot_tools/workday/tool.py`::`WorkdayToolkit`** — each `wd_*` method's in-line SOAP body is
  replaced by a delegation to the composable (`self._service.fetch(...)` / `.call_operation(...)`),
  with dict conversion at the toolkit boundary. `WorkdaySOAPClient` (in-line builders) is retired or
  reduced to a thin shim. *Evidence*: F003
- **`parrot_tools/workday/tool.py` imports** — point SOAP construction at the vendored composable
  instead of `WorkdaySOAPClient`. *Evidence*: F003

### What's Untouched (Non-Goals)

- The core `parrot.interfaces.soap.SOAPClient` itself — reused, not modified.
- `parrot.conf` `WORKDAY_*` keys — reused as-is.
- Session/identity wiring — out of scope this pass; identity is an explicit `worker_id` parameter
  (per §5), not session-derived.
- flowtask repo — read-only source; nothing is pushed back upstream.
- Recruiting/Staffing/Financial placeholder methods in `METHOD_TO_SERVICE_MAP` — not in the
  homologation list, left as-is.

### Patterns to Follow

- **Tool naming/docstrings** → `AbstractToolkit` auto-gen (F004): name the 11 methods exactly as the
  homologation list, each with a Google-style docstring (LLM tool description).
- **DataFrame→dict** → reuse `WorkdayToolkit._flatten_entries` / `df.to_dict(orient="records")`
  already in tool.py (F003).
- **Handler contract** → `WorkdayTypeBase(ABC).execute()` + `service.call_operation()` (F001/F007 in
  findings): new write handler for `request_my_time_off` follows the same base.
- **Composable lifecycle** → `async with WorkdayService(...) as svc` / `start()/close()` (F001).

### Integration Risks

- **DataFrame leakage into tool output.** If a `wd_*` method returns the raw `fetch()` DataFrame, the
  agent gets a non-serializable object. *Mitigation*: convert at the toolkit boundary; add a test
  asserting JSON-serializable returns. *Evidence*: F001, F003
- **Config drift.** Leaving the vendored `config.py` pointed at `flowtask.conf` would create a second
  credential source. *Mitigation*: rebase `config.py` onto `parrot.conf` `WORKDAY_*`. *Evidence*: F004
- **Write side-effects (`request_my_time_off`).** A real submit mutates Workday. *Mitigation*:
  guard with explicit confirmation/dry-run, gate behind the implementation spec's acceptance tests,
  and target the impl tenant first. *Evidence*: F005
- **Identity ambiguity for `current_user`/`my_` methods.** Resolved to explicit `worker_id` (§5) —
  the agent must resolve identity first (e.g. via `find_employee_id_by_name`). *Evidence*: F005

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | Source composable is `WorkdayService(SOAPClient)` + handlers/models/parsers/config, ~16.6k LOC / 60 files | F001 | high | full tree + service.py read |
| C2 | Core `parrot.interfaces.soap.SOAPClient` API ≈ flowtask's; rebase is mechanical | F002 | high | both public APIs enumerated and matched |
| C3 | Current `WorkdayToolkit` builds SOAP in-line per method (`WorkdaySOAPClient`) | F003 | high | direct read of tool.py:350-466, 472-619 |
| C4 | Each public async method auto-becomes a tool (`AbstractToolkit.get_tools`) | F004 | high | direct read of toolkit.py:337-425 |
| C5 | `WORKDAY_*` config already in core `parrot.conf` | F004 | high | grep conf.py:595-608 |
| C6 | 9 of 11 requested methods do not exist; net-new self-service layer | F005 | high | per-name grep across repo (minus .venv) |
| C7 | `request_my_time_off` is a write op with no current analog | F005 | high | grep NONE + semantic ("Submit") |
| C8 | Composable `fetch()` returns DataFrame; needs dict conversion for tools | F001, F003 | medium | source signature read; conversion path inferred from existing `_flatten_entries` |
| C9 | `parrot_tools/interfaces/` does not yet exist | F002 | high | `ls` returned "NO interfaces dir" |

Distribution: **8** high, **1** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Where should the vendored composable live?** — *Resolved*: `parrot_tools/interfaces/workday`
  (as originally requested), even though it diverges from the core `parrot.interfaces` convention.
  *Resolves*: C9, scope §3
- [x] **Rebase the composable onto which SOAPClient?** — *Resolved*: rebase onto
  `parrot.interfaces.soap.SOAPClient`; drop the flowtask base dependency.
  *Resolves*: C2, constraint §2.2
- [x] **How is the "current user" identity resolved?** — *Resolved*: explicit `worker_id`
  parameter on every `current_user`/`my_` method (no session-derived identity this pass).
  *Resolves*: C6 scope, risk §3
- [x] **Is `request_my_time_off` (write) in scope?** — *Resolved*: yes — include the write op
  against Absence Management; gate it behind acceptance tests + a dry-run/confirm guard.
  *Resolves*: C7, risk §3

### Unresolved (defer to spec / implementation)

- [ ] **DataFrame vs typed-model return at the tool boundary** — *Owner*: tbd (spec)
  *Blocks*: C8 — confirm whether to standardize on `fetch_models()` (typed) or
  `fetch()` + `to_dict()` for the homologated tools.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-230`** — *Rationale*: localization is high-confidence (C1–C5, C9), all four
architectural forks are resolved (§5), and the work decomposes cleanly into three task clusters
(vendor+rebase package · refactor toolkit to delegate · build+homologate the 11 methods incl. one
write). The single open question (C8) is a tactical detail the spec can fix, not an architectural
fork warranting brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-230`** — only if you want to revisit the placement decision (core
  `parrot.interfaces` vs `parrot_tools/interfaces`) or the identity model (explicit `worker_id` vs
  session-derived) before committing.
- **`/sdd-task FEAT-230`** — too coarse: this is multi-cluster work with a write op; skip the single-task path.
- **Manual review** — not needed; research was not truncated and findings are consistent.

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-230/state.json` |
| Source (raw) | `sdd/state/FEAT-230/source.md` |
| Findings (digests) | `sdd/state/FEAT-230/findings/F001..F005-*.md` |

**Budget consumed** (profile: default):
- Files read: 12 / 40
- Grep calls: 9 / 25
- Git calls: 0 / 10
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive migration + refactor +
homologation; no negation/regression in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal` |
| Source kind | inline |
| Operator | Jesus Lara |
| Decisions | placement=parrot_tools/interfaces/workday · base=parrot.interfaces.soap · identity=explicit worker_id · write=in-scope |
