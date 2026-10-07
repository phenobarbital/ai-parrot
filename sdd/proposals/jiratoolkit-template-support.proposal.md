---
id: FEAT-637
title: JiraToolkit template support — Jinja2 composition of issue descriptions and comment bodies
slug: jiratoolkit-template-support
type: feature
mode: enrichment
status: review
# id is PROVISIONAL (max existing + 1); /sdd-spec reserves the definitive one via reserve_ids.py
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-10-07
  summary_oneline: Add template support (file with placeholders / Jinja2) to compose Jira ticket descriptions and comments in JiraToolkit
overall_confidence: medium
base_branch: dev
projects: [ai-parrot-tools]
tags: [jira, jiratoolkit, templates, jinja2, tool-configuration]
research_state: sdd/state/FEAT-637/
created: 2026-10-07
updated: 2026-10-07
---

# FEAT-637 — JiraToolkit template support: Jinja2 composition of issue descriptions and comment bodies

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-637/`](../state/FEAT-637/)

---

## 0. Origin

The original request, preserved verbatim. The full source is at `sdd/state/FEAT-637/source.md`.

> sometimes when a new ticket is creatd, user requires following certain rules
> (templating) on ticket description, explaining requirements, etc, adding
> template support for description can be usable for follow this ticket design,
> a template is a file with placeholders (like or potentially jinja2 template)
> where "description" of Jira ticket is composed before passed to the Jira
> ticket creation, template composition can be usable also for adding comments.

**Initial signals** (extracted, not interpreted):
- Verbs: "adding template support", "composed before passed", "can be usable" → additive feature, no failure
- Named entities: JiraToolkit, Jira ticket creation, description, comments, template file, placeholders, Jinja2
- Components / labels: none (inline source)
- Acceptance criteria provided: no

---

## 1. Synthesis Summary

JiraToolkit should let an operator (and, optionally, the agent) compose the
`description` of a new or updated issue and the `body` of a comment from a
Jinja2 template instead of a raw string. Today all three write paths in
`packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` —
`jira_create_issue`, `jira_update_issue`, `jira_add_comment` — pass the text
to the pycontribs client verbatim, so there is one clean insertion point per
method (C1). The framework already ships an async Jinja2 engine,
`parrot.template.TemplateEngine`, and `jinja2>=3.1` is a hard dependency of
both core and ai-parrot-tools, so no new dependency is needed (C2, C3). The
engine's defaults need two Jira-specific overrides: autoescape **off**
(Jira wiki markup is not HTML) and `StrictUndefined` kept on so a template
with missing required placeholders fails loudly (C4, U3). Configuration
follows the toolkit's own `_cfg()` / `JIRA_DEFAULT_*` / `workflow_paths`
precedents: a `templates_dir` kwarg (env `JIRA_TEMPLATES_DIR`) plus an
in-memory `templates` mapping, explicit `template=` per call with a
`<PROJECT>/<issuetype>` → `_default` convention fallback (U1, U2). The
recommendation is to proceed straight to `/sdd-spec`.

---

## 2. Codebase Findings

> All entries are grounded in the research findings persisted at
> `sdd/state/FEAT-637/findings/`. **No fabricated paths or symbols.**

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `JiraToolkit.jira_create_issue` | 1781-1914 | create entrypoint; `issue_fields["description"] = description` at 1872-1873 is the insertion point | F002, F005 |
| 2 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `JiraToolkit.jira_add_comment` | 2027-2092 | comment entrypoint; `jira.add_comment(issue, body, …)` at 2049-2053 | F002, F006 |
| 3 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `JiraToolkit.jira_update_issue` | 1916-2000 | update entrypoint; `update_fields["description"]` at 1955-1958 | F002, F006 |
| 4 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `CreateIssueInput` | 375-405 | `@tool_schema` for create; new `template` / `template_params` fields go here | F005 |
| 5 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `AddCommentInput` | 455-467 | `@tool_schema` for comment; same new fields | F006 |
| 6 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `UpdateIssueInput` | 408-437 | `@tool_schema` for update; same new fields | F002 |
| 7 | `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py` | `JiraToolkit.__init__` | 698-853 | `_cfg()` resolution; `JIRA_DEFAULT_*` (757-772) and `workflow_paths` per-project map (774-803) precedents | F007 |
| 8 | `packages/ai-parrot-tools/src/parrot_tools/jira_config.py` | `JiraToolkitConfig` | 12-24 | Agent Studio surface (`extra="forbid"`) — unchanged unless templates become operator-configurable there | F007 |
| 9 | `packages/ai-parrot/src/parrot/template/engine.py` | `TemplateEngine` | 47-242 | shared async Jinja2 engine: `render`, `render_string`, `add_templates`, `add_template_dir` | F008 |
| 10 | `packages/ai-parrot/src/parrot/template/engine.py` | `JinjaConfig` | 26-44 | engine config; defaults `StrictUndefined` + `select_autoescape([… "j2","jinja","jinja2"])` | F008 |
| 11 | `packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py` | `INIT_PARAMS_BASELINE` / `test_init_signature_unchanged` | 23-39, 105-107 | pins the exact constructor signature | F013 |
| 12 | `packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py` | `ResearchNode._render_body` | 959-978 | existing hand-built f-string description; reference consumer (non-goal to migrate) | F011, F015 |

### 2.2 Constraints Discovered

- **Verbatim pass-through, no conversion stage.** Description and body reach
  pycontribs `JIRA.create_issue` / `add_comment` / `update` unchanged; there
  is no markdown→wiki-markup or ADF step anywhere in the toolkit path (the
  only ADF usage is `/sdd-tojira`'s curl fallback on REST v3).
  *Implication*: the rendered template **is** the final Jira markup; it must
  not be HTML-escaped and nothing downstream reformats it.
  *Evidence*: F005, F006, F014

- **TemplateEngine defaults are HTML-oriented.** `JinjaConfig.autoescape =
  select_autoescape(["html","xml","j2","jinja","jinja2"])` — a template file
  named `bug.j2` would be escaped — and `undefined = StrictUndefined`. The
  engine's `__init__` raises `ValueError` if a template dir does not exist.
  *Implication*: build the Jira engine with `JinjaConfig(autoescape=False)`,
  keep `StrictUndefined` (U3), and construct it lazily / tolerate a missing
  dir so toolkit construction never fails because templates are absent.
  *Evidence*: F008

- **No new dependency.** `jinja2>=3.1` is declared in
  `packages/ai-parrot/pyproject.toml` and `packages/ai-parrot-tools/pyproject.toml`.
  *Evidence*: F009

- **Two coexisting template conventions.** ai-parrot-tools document tools
  (msword / powerpoint / pdfprint) take `templates_dir: Optional[Path]`; core
  `infographic_toolkit` takes `template_dirs` + in-memory `templates` and
  wraps `TemplateEngine`.
  *Implication*: expose `templates_dir` + `templates` on JiraToolkit and
  delegate to `TemplateEngine` internally (U1).
  *Evidence*: F010

- **Config precedence precedent.** Every setting resolves through `_cfg(key)`
  (explicit kwarg > navconfig > env). `workflow_paths` already implements a
  per-project override map keyed by upper-cased project with a `_DEFAULT`
  sentinel.
  *Implication*: `JIRA_TEMPLATES_DIR` fits; template auto-selection by
  `<PROJECT>/<issuetype>` → `_default` can mirror the workflow lookup (U2).
  *Evidence*: F007

- **Constructor signature is pinned by a test.** `test_init_signature_unchanged`
  asserts the exact parameter tuple.
  *Implication*: adding `templates_dir` / `templates` kwargs must update
  `INIT_PARAMS_BASELINE` in the same task — a deliberate baseline change.
  *Evidence*: F013

- **All 10 external callers use keyword args.** One `jira_create_issue`
  caller (dev_loop `ResearchNode`) and nine `jira_add_comment` callers
  (jira_specialist, dev_loop nodes); none passes template-related names.
  *Implication*: new optional params are backward compatible; no-template
  calls keep today's behaviour byte-for-byte.
  *Evidence*: F011

- **Jira description cap.** `ResearchNode` enforces `_MAX_DESCRIPTION_CHARS
  = 30_000` (Atlassian limit 32 767) with summarize-then-truncate.
  *Implication*: a template fed large params can overflow; the renderer
  should guard the length (truncate with marker, or fail clearly).
  *Evidence*: F015

### 2.3 Recent History (Relevant)

14 commits on `jiratoolkit.py` in 120 days, all by the repo owner. None
touches description/body composition — no in-flight work collides with this
feature.

| Commit | When | Author | Message | Touched files |
|--------|------|--------|---------|---------------|
| `5bafcf8a9` | 2026-09-29 | Jesus Lara | fix(jiratoolkit): forward is_internal in jira_add_comment | `jiratoolkit.py` |
| `7f9c3e708` | 2026-09-23 | Jesus | feat(tool-configuration-agentstudio): TASK-3650 — JiraToolkitConfig + config_options(default_project) | `jiratoolkit.py`, `jira_config.py` |
| `1e94ac244` | 2026-08-24 | Jesus | feat(jira-extractor-llmwiki): TASK-2402 — JiraToolkit delegation refactor | `jiratoolkit.py` |
| `cded602e1` | 2026-07-26 | Jesus | fix(jiratoolkit): treat raised JIRAError 401/403 as definitive rejection | `jiratoolkit.py` |

*Evidence*: F012

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **Template rendering seam in `JiraToolkit`** — a lazily built
  `parrot.template.TemplateEngine` with `JinjaConfig(autoescape=False)`
  (StrictUndefined retained), loaded from `templates_dir` (kwarg, else
  `JIRA_TEMPLATES_DIR` via `_cfg`) plus an optional in-memory
  `templates: Mapping[str, str]` (U1). Absent configuration ⇒ engine is
  `None` and every write path behaves exactly as today.
- **Template selection** (U2) — explicit `template=<name>` wins; otherwise
  convention lookup `<PROJECT>/<issuetype>` → `<PROJECT>/_default` →
  `_default` (names resolved only through the engine's loader, never
  path-joined by the toolkit); otherwise no template.
- **Optional `template` + `template_params` parameters** on
  `jira_create_issue`, `jira_update_issue` and `jira_add_comment` (U4, U5).
  Render context = the call's own fields (`project`, `summary`, `issuetype`,
  `labels`, `components`, `priority`, `description` / `body`, `issue`, …) ∪
  `template_params`, so a template can wrap the caller's text as
  `{{ description }}` — composition, not replacement.
- **`jira_list_templates` read tool** — lists discoverable template names
  (filesystem + in-memory) so the agent can choose one (U4).
- **Strict missing-placeholder policy** (U3) — a missing variable fails the
  tool call with an error that names the missing variables, before any Jira
  request is made.
- **Length guard** — rendered text over the Jira cap is rejected (or
  truncated with a marker) with a clear message, mirroring `ResearchNode`.
- **Unit tests** in `packages/ai-parrot-tools/tests/unit/` using the existing
  `_FakeJIRA` / `AsyncMock` pattern: render-on-create, render-on-comment,
  render-on-update, convention fallback order, explicit-overrides-convention,
  strict missing var, raw Jira markup survives (no escaping), missing
  template error, no-template ⇒ unchanged payload, `jira_list_templates`.

### What Changes

- **`jiratoolkit.py`::`jira_create_issue`** — render before
  `issue_fields["description"]` is set. *Evidence*: F005
- **`jiratoolkit.py`::`jira_add_comment`** — render `body` before `_run()`.
  *Evidence*: F006
- **`jiratoolkit.py`::`jira_update_issue`** — render before
  `update_fields["description"]`. *Evidence*: F006
- **`jiratoolkit.py`::`CreateIssueInput` / `UpdateIssueInput` /
  `AddCommentInput`** — add `template: Optional[str]`,
  `template_params: Optional[Dict[str, Any]]` (with `x-exclude-form` where
  appropriate, as `fields` does). *Evidence*: F005, F006
- **`jiratoolkit.py`::`JiraToolkit.__init__`** — add `templates_dir`,
  `templates` kwargs; resolve `JIRA_TEMPLATES_DIR` via `_cfg`. *Evidence*: F007
- **`tests/unit/test_jiratoolkit_delegation.py`::`INIT_PARAMS_BASELINE`** —
  extend the tuple. *Evidence*: F013

### What's Untouched (Non-Goals)

- Markdown→ADF / wiki-markup conversion — none exists; templates emit final markup.
- `JiraInterface` (read-only) and the pycontribs client.
- `JiraToolkitConfig` (Agent Studio) — not required by U1; may be a follow-up.
- Migrating `ResearchNode._render_body` or `/sdd-tojira` to templates — possible follow-up.
- Templating `summary` or non-text fields.

### Patterns to Follow

- Lazy `TemplateEngine` on the toolkit with a `JinjaConfig` override
  (`infographic_toolkit.py` 307-321). *Evidence*: F010, F008
- `_cfg()` + `JIRA_DEFAULT_*` precedence (explicit kwarg > navconfig > env).
  *Evidence*: F007
- `workflow_paths` per-project map with `_DEFAULT` sentinel for convention
  lookups. *Evidence*: F007
- `_FakeJIRA` / `_FakeReadInterface` test doubles. *Evidence*: F013

### Integration Risks

- **HTML-escaping Jira markup**: `{code}`, `*bold*`, `<` become entities.
  Mitigation: `JinjaConfig(autoescape=False)` + a test asserting raw markup
  survives. *Evidence*: F008, F014
- **StrictUndefined with LLM-supplied params**: a missing key aborts the
  call. Mitigation (U3, accepted): surface the missing names in the tool
  error so the agent can retry with the right params. *Evidence*: F008
- **Template names originate from the LLM**: possible traversal attempt.
  Mitigation: names resolve only through Jinja's `FileSystemLoader` /
  `DictLoader` (which reject `..` segments); the toolkit never joins paths.
  *Evidence*: F008
- **Rendered text > 32 767 chars** → Jira 400. Mitigation: length guard as
  above. *Evidence*: F015
- **Signature-pin test** fails on the new kwargs. Mitigation: update
  `INIT_PARAMS_BASELINE` deliberately in the same task. *Evidence*: F013

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | The only places description/body are shaped are `jira_create_issue` 1872-1873, `jira_update_issue` 1955-1958, `jira_add_comment` 2049-2053; all pass strings verbatim | F005, F006 | high | direct read of all three methods |
| C2 | A shared async Jinja2 `TemplateEngine` exists in core and is used by three consumers | F008, F010 | high | file read + consumer grep |
| C3 | No new dependency required | F009 | high | pyproject grep |
| C4 | Default autoescape would corrupt Jira markup for `*.j2`/`*.jinja` templates; must be disabled | F008, F014 | high | `select_autoescape` list read directly; no conversion stage exists |
| C5 | Optional `template` / `template_params` params are backward compatible with all 10 callers | F011 | high | every call site uses kwargs; none passes those names |
| C6 | `templates_dir` + `JIRA_TEMPLATES_DIR` (+ in-memory `templates`) is the convention-consistent config surface | F007, F010 | medium → resolved by U1 | two conventions coexist; user chose dir + mapping |
| C7 | Adding a constructor kwarg requires updating `INIT_PARAMS_BASELINE` | F013 | high | assertion read directly |
| C8 | A length guard against the 32 767-char cap belongs in the renderer | F015 | medium | enforced today only in `ResearchNode`; toolkit ownership is a design choice |
| C9 | Agent Studio (`JiraToolkitConfig`) needs `templates_dir` | F007 | low → resolved by U1 (not required) | nothing indicates operator configuration there is needed |
| C10 | Per-project/issuetype auto-selection is wanted in addition to explicit names | F007 | low → resolved by U2 (yes, as fallback) | precedent exists; intent confirmed by user |

Distribution: **6** high, **2** medium, **2** low (both low claims resolved in §5).

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **U1 — Where do templates live / how are they configured?** —
  *Resolved*: Dir + in-memory mapping — `templates_dir` kwarg /
  `JIRA_TEMPLATES_DIR` env for files, plus an optional
  `templates={name: source}` mapping for programmatic use (mirrors
  infographic_toolkit). Agent Studio exposure not required.
  *Resolves claims*: C6, C9
- [x] **U2 — How is a template selected?** — *Resolved*: Explicit wins,
  convention fallback — `template='bug'` when given; otherwise look up
  `<PROJECT>/<issuetype>` then `_default` (like workflow_paths); otherwise
  no template. *Resolves claims*: C10
- [x] **U3 — Missing placeholder policy?** — *Resolved*: Strict — fail with
  names: the tool call fails with a clear error listing the missing
  variables (StrictUndefined). *Resolves claims*: C4
- [x] **U4 — LLM-facing or operator-only?** — *Resolved*: Both — operator
  config auto-applies a default; the agent may list templates
  (`jira_list_templates`) and override by name via a `template` tool
  parameter. *Resolves claims*: C5
- [x] **U5 — Include `jira_update_issue`?** — *Resolved*: Create + comment +
  update — same `template` / `template_params` seam on all three write
  paths. *Resolves claims*: C1

### Unresolved (defer to spec / implementation)

- [ ] **Exact convention-lookup key shape and file extension** (e.g.
  `NAV/Bug.j2` vs `NAV/bug.j2`; case-folding of issuetype; `.j2` vs `.md`)
  — *Owner*: spec. *Blocks claims*: C10.
- [ ] **Length-guard behaviour** (reject vs truncate-with-marker) — *Owner*:
  spec. *Blocks claims*: C8.
- [ ] **Which Jira call fields are exposed to the template context** (and
  whether resolved values such as `assignee` accountId are included) —
  *Owner*: spec.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-637`** — *Rationale*: localization is high-confidence
(C1–C5, C7), there is a single shared engine to reuse and no new dependency;
the five product decisions are now resolved, leaving only spec-level
details. No architectural fork warrants a brainstorm.

### Alternatives

- **`/sdd-brainstorm FEAT-637`** — only if you want to weigh a toolkit-agnostic
  "template mixin" reusable by other toolkits (msword/powerpoint/pdfprint
  currently each build their own Environment) against the Jira-local seam
  proposed here.
- **`/sdd-task FEAT-637`** — not recommended: the work spans constructor,
  three write paths, three input models, a new tool and a test baseline.
- **Manual review** — not needed; research was complete (no skipped queries).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-637/state.json` |
| Source (raw) | `sdd/state/FEAT-637/source.md` |
| Research plan | `sdd/state/FEAT-637/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-637/findings/F001-*.md` … `F015-*.md` |
| Synthesis (JSON) | `sdd/state/FEAT-637/synthesis.json` |
| Synthesis reasoning | not persisted |

**Budget consumed** (profile `default`):
- Files read: 14 / 40
- Grep calls: 9 / 25
- Git calls: 1 / 10
- Wall time: ~420s / 300s (over budget on wall clock; all 15 queries completed, none skipped)
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (additive verbs,
no negation or failure signal in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Jesus Lara (via Claude Code) |
