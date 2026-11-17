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
framework for AI agents (aiohttp, Pydantic v2).
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
ai-parrot has two kinds of documentation and one surface for both. `docs/` (338 markdown
files) mixes narrative/informative material (what parrot is, install, chapters, guides) with
deep technical material (memory compaction internals, toolkits, clients, A2UI outputs, the
SDD tooling itself), and `mkdocs.yml` renders all of it, plus a `mkdocstrings`-generated API
reference (`docs/api-reference/*.md`, core package only), into the GitHub Pages site at
`https://phenobarbital.github.io/ai-parrot/docs/`.

Three pains follow:

1. **The informative site is drowned by technical pages.** A newcomer landing on Pages
   meets 60+ nav entries, most of them implementation notes that only matter to someone
   reading the code. The site cannot become a clean "what is parrot, what does it do"
   front door while it also has to be the reference manual.
2. **Technical documentation is not a deliverable of the SDD flow.** `/sdd-spec` →
   `/sdd-task` → `/sdd-done` produce code, tests, ledger events and an E2E gate, but no
   documentation page. Whether a feature gets a technical page depends on the implementer
   remembering to write one under `docs/`. Hundreds of merged FEATs have no page at all.
3. **The generated API reference covers one of nine namespaces.** `mkdocstrings` is pointed
   at `packages/ai-parrot/src` only; `parrot_tools`, `parrot_loaders`, the server, the
   embeddings backends and the client packages have no reference. And `mkdocstrings`
   renders HTML only, so it cannot feed a markdown wiki.

**Who is affected**: developers integrating parrot (need argument-level reference plus
semantics and examples), the maintainers (want the Pages site to become informative),
and the SDD agents (need a deterministic place and format to write documentation into).

**Why now**: the GitHub Wiki of `phenobarbital/ai-parrot` was just bootstrapped (the
`ai-parrot.wiki.git` repository exists with a first Home page, branch `master`), and the
Pages site is about to be redesigned as an informative site in a follow-up spec. The
technical content must have a new home before `mkdocstrings` is removed from Pages.

### Constraints and goals
Decided with the user during discovery (Rounds 0–2):

- **Flow**: `type: feature`, base `dev`. Reaches `main` with the next release.
- **Two surfaces, strict roles**: GitHub Pages = informative (what/why/guides, written on
  demand by a human or an agent, outside the SDD flow). GitHub Wiki = technical reference
  (classes, arguments, parameters, return values, semantics, examples, gotchas).
- **The wiki reflects `main` only** — what is released on PyPI. Features merged to `dev`
  but not yet released do not appear until the release lands on `main`.
- **Source of truth is the monorepo.** The wiki repository is a publish target, never
  edited from the GitHub web UI. A workflow regenerates and pushes it.
- **Authored technical pages are organised by subsystem/component**, not per feature.
  A spec's Documentation chapter names which subsystem page(s) it creates or updates.
- **Generated API reference pages are produced only in CI** (not committed); the
  repository holds only authored pages.
- **Scope of generated reference**: public API (no underscore-prefixed names) of every
  Python distribution in the workspace.
- **Language**: English. Spanish pages that migrate are translated.
- **Migration moves, never copies**: technical documents leave `docs/` (and the mkdocs
  nav) when they enter the wiki source. One source of truth per topic.
- **Backfill**: one task writes subsystem pages for the main subsystems that have no
  technical doc today (bots/agents, clients, tools, memory, flows, skills, stores,
  loaders, MCP, server).
- **`/sdd-done` gate = warning only**, never blocking. Discipline stays with the reviewer.
  `type: hotfix` and `/sdd-brief` lanes are exempt entirely.
- **The SDD assets ship to other repositories** (`parrot sdd install` deploys
  `.claude/commands/sdd-*.md`, `sdd/templates/*`, twins under `.agents/skills/` and
  `.agent/workflows/`; `scripts/sdd/check_asset_sync.py` keeps `parrot/sdd/_assets/`
  byte-identical and CI enforces it). Every change to the template, the commands or the
  gate must be repo-neutral and must update all twins plus `_assets/`.
- **Never a moment without a published API reference.** `mkdocstrings` leaves the Pages
  site only in the final cut-over task, after the wiki sync has run green on `main`.
- Standard repo rules: aiohttp only, no `requests`/`httpx`, `uv` for dependencies,
  Google docstrings, 120 columns, tests next to the distribution.

---

### Recommended option / probable scope
**Option B** is recommended because:

- Static loading is the decisive property. The project has already seen that importing
  `parrot` boots Navigator settings and observability; a generator that imports 30
  distributions in CI would be fragile and slow (Option A/pdoc). griffe reads the AST.
- The renderer being ours is a cost we accept in exchange for GitHub-wiki-specific output
  (flat page names, `_Sidebar.md`, `[[links]]`), cross-links between authored and generated
  pages, and per-release source links. Off-the-shelf markdown generators (Option A) cannot
  produce that without post-processing that would be as large as the renderer.
- Shipping the pipeline as `parrot sdd techwiki` keeps it inside the SDD product: the
  Documentation chapter, the derived task, the `/sdd-done` warning and the publishing
  pipeline travel together to every repository that installs the SDD assets.
- Option C is the right long-term answer for multi-language reference but would block this
  feature on a wiki schema change. It is recorded as a follow-up.

What we trade off: a Python ≥ 3.11 optional extra, and ownership of a renderer with tests.

---

`griffe` (the engine underneath `mkdocstrings-python`) loads Python packages **statically**
(AST, no import) from search paths and exposes modules, classes, functions, parameters,
return annotations, docstring sections (Google style parsed into Parameters / Returns /
Raises / Examples). parrot ships a small renderer that walks the griffe tree and writes
one markdown page per public module (classes and functions as `##` sections, parameter
tables, source links to the tagged release on GitHub).

The feature adds a noun to the shipped SDD CLI, `parrot sdd techwiki`, with four verbs:

| Verb | Does |
|---|---|
| `api` | Generate the API reference pages for the configured packages into an output dir. |
| `bundle` | Assemble the publishable bundle: authored `wiki/**` + generated API + `Home.md` + `_Sidebar.md`, with wiki page naming and link rewriting. Fails on page-name collisions. |
| `check` | Read a spec's `docs:` frontmatter and report which declared pages exist/are missing in a worktree, as JSON. Exit 0 always with policy `required` (warning lane), 0 with `none`. |
| `sidebar` | Render only `_Sidebar.md`/`Home.md` from the bundle index (used by `bundle`, exposed for debugging). |

A new workflow `.github/workflows/techwiki.yml` runs on push to `main` (paths:
`wiki/**`, `packages/*/src/**`, `sdd/config.json`, the workflow itself) and on
`workflow_dispatch`: installs the workspace, runs `parrot sdd techwiki bundle --out
build/techwiki`, clones `ai-parrot.wiki.git` with the job's `GITHUB_TOKEN`
(`permissions: contents: write`), replaces its content with the bundle, commits
`techwiki: sync <sha>` and pushes. A concurrency group serialises runs.

The SDD flow gains a Documentation chapter: a `docs:` frontmatter key in
`sdd/templates/spec.md` (mirrors the `e2e:` precedent) plus a `## 10. Documentation`
section; `/sdd-task` derives one documentation task from it; `/sdd-done` runs
`techwiki check` in a new Step 4.6b and prints a warning line in the report.

✅ **Pros:**
- Static analysis: no imports, no side effects, no optional dependencies needed in CI.
  Works on every workspace package from `packages/*/src` search paths alone.
- Same docstring parser family the project already relies on (`mkdocstrings-python`
  uses griffe), so existing docstrings render identically.
- The renderer is ours: GitHub-wiki page naming, `_Sidebar.md`, cross-links from authored
  pages to generated reference pages (`[[Reference: parrot.memory.compaction]]`),
  per-release source links.
- The CLI noun ships with the SDD assets, so any repository using `parrot sdd` can adopt
  the same wiki pipeline (repo-neutral configuration in `sdd/config.json`).
- The gate (`techwiki check`) is a tiny, testable script in the same style as
  `check_e2e_closeout.py`.

❌ **Cons:**
- We own a renderer (~300–400 lines plus tests) and its edge cases (overloads,
  properties, dataclass/Pydantic fields, re-exports).
- `griffe` 2.4.1 requires Python ≥ 3.11 while the project floor is 3.10.1. It must be an
  optional extra (`ai-parrot[techwiki]`), never a core dependency.
- Running `parrot` in CI still imports the parrot package (CLI entry), so the job
  installs the core distribution like `docs.yml` already does.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `griffe` 2.4.1 | static Python API loader + Google docstring parser | `requires_python >=3.11`; optional extra `techwiki` |
| `jinja2` | page templates for the renderer | already in the environment (aiohttp-jinja2 / navigator); verify at spec time |
| `pyyaml` | spec frontmatter (`docs:` key) | already used by `sdd_meta` |
| GitHub Actions `GITHUB_TOKEN` | push to `<repo>.wiki.git` | `permissions: contents: write`; the wiki repo must already exist (it does) |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/sdd/cli.py` — `VERBS` map + `_mount` add the `techwiki`
  noun exactly like `tests`/`closeout`.
- `packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py` — shape of a closeout
  gate (`resolve_policy`, JSON report, exit code contract) to mirror for `techwiki check`.
- `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` — frontmatter parser
  already used by `parrot sdd docs parse`; `techwiki check` reads the `docs:` key through it.
- `sdd/templates/spec.md` — the `e2e:` frontmatter block and `### E2E Scenarios` are the
  pattern for `docs:` + `## 10. Documentation`.
- `.claude/commands/sdd-done.md` Step 4.6 (E2E gate) and Step 4.8 (closeout hooks) — insertion
  point and report style for Step 4.6b.
- `.claude/commands/sdd-task.md` §3 "Plan Task Decomposition" — where the derived
  documentation task is specified.
- `scripts/sdd/check_asset_sync.py` — `ASSET_SOURCES` already covers the files we change;
  run `--write` after editing commands/templates.
- `.github/workflows/docs.yml` — job skeleton (checkout, python, install) and the
  `paths:` filter idea.
- `mkdocs.yml` nav + `docs/index.md` "Browse the API" button + `requirements-docs.txt` —
  the cut-over task edits exactly these.

---

### Verified code anchors (paths only — open them yourself)
.agents/skills/sdd-done/SKILL.md
.claude/commands/sdd-done.md
.claude/commands/sdd-spec.md
.claude/commands/sdd-task.md
.github/workflows/docs.yml
.parrot/wiki.json
docs/api-reference/a2a.md
docs/index.md
docs/sdd/closeout-hooks.md
mkdocs.yml
pyproject.toml
requirements-docs.txt
sdd/CONVENTIONS.md
sdd/templates/sdd_hooks.example.toml
sdd/templates/spec.md

### Questions still open in the exploration document
- [ ] CLI noun name: `parrot sdd techwiki` is proposed to avoid colliding with `parrot wiki`
- [ ] ADRs: keep `docs/decisions/**` in place (wikitoolkit's `adr_globs` depend on it) and
- [ ] `docs/sdd/**` and `docs/wiki/**` (agent/tooling docs): `docs/sdd/WORKFLOW.md` is
- [ ] `docs/migration/**` (12 FEAT migration notes): technical (move) or informative
- [ ] Documentation chapter numbering: `## 10. Documentation` appended after §9 to avoid
- [ ] Release label on `Home.md`: `git describe --tags` on `main` (release tags) vs the
- [ ] Should `workflow_dispatch` from `dev` publish to a preview location (artifact only,
- [ ] Follow-up (not this feature): multi-language reference (Svelte admin UI, TS client)

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
