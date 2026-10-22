<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
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

Original request:
> sometimes when a new ticket is creatd, user requires following certain rules
> (templating) on ticket description, explaining requirements, etc, adding
> template support for description can be usable for follow this ticket design,
> a template is a file with placeholders (like or potentially jinja2 template)
> where "description" of Jira ticket is composed before passed to the Jira
> ticket creation, template composition can be usable also for adding comments.

### Constraints and goals
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

### Recommended option / probable scope


### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-tools/src/parrot_tools/jira_config.py
packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py
packages/ai-parrot-tools/tests/unit/test_jiratoolkit_delegation.py
packages/ai-parrot/src/parrot/flows/dev_loop/nodes/research.py
packages/ai-parrot/src/parrot/template/engine.py

### Questions still open in the exploration document
Already resolved by the product owner (treat as fixed):
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

Still open:
- [ ] **Exact convention-lookup key shape and file extension** (e.g.
  `NAV/Bug.j2` vs `NAV/bug.j2`; case-folding of issuetype; `.j2` vs `.md`)
  — *Owner*: spec. *Blocks claims*: C10.
- [ ] **Length-guard behaviour** (reject vs truncate-with-marker) — *Owner*:
  spec. *Blocks claims*: C8.
- [ ] **Which Jira call fields are exposed to the template context** (and
  whether resolved values such as `assignee` accountId are included) —
  *Owner*: spec.

Also fixed since: convention files are `<project>/<issuetype>.j2` lowercase (comments: `<project>/comment.j2`), overflow truncates with a marker, context = call fields merged with template_params (params win).

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
