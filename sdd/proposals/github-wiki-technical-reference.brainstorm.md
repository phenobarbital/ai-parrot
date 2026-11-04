---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: the base_branch in sdd/config.json (or any non-hotfix branch)
# - type: hotfix              → base_branch MUST be the hotfix_base in sdd/config.json
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use the project areas of your
#   repository (`sdd/CONVENTIONS.md` § Project areas, or the `projects` list in
#   `sdd/config.json`). Unknown values warn, not fail.
projects: [ai-parrot, sdd-tooling, docs]
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: [docs, github-wiki, api-reference, sdd-flow, mkdocs, griffe]
---

# Brainstorm: GitHub Wiki as the Technical Reference (`github-wiki-technical-reference`)

**Date**: 2026-11-04
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

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

## Constraints & Requirements

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

## Options Explored

### Option A: `pydoc-markdown` (or `pdoc`) + hand-maintained wiki folder + sync Action

Use an off-the-shelf markdown API generator. `pydoc-markdown` renders markdown natively;
`pdoc` renders HTML and would need custom Jinja templates to emit markdown. A `wiki/`
folder in the repo holds authored pages; a GitHub Action concatenates generated + authored
output and pushes to `ai-parrot.wiki.git`.

✅ **Pros:**
- Fastest to a first result: no renderer to write.
- `pydoc-markdown` understands Google docstrings and emits parameter tables.

❌ **Cons:**
- `pydoc-markdown` 4.8.2 is in maintenance mode (its `docspec` parser lags modern
  typing syntax; PEP 695/`type` statements and `TypeAliasType` are not handled); its
  markdown layout is not configurable enough to produce one page per class with our
  cross-links, and its GitHub-wiki link style is not supported.
- `pdoc` **imports** every module. `import parrot` boots Navigator settings, the
  observability auto-boot and the pricing calculator (visible as DEBUG/INFO/WARNING lines
  on every CLI start). Importing 30 distributions in CI means installing every optional
  dependency and tolerating side effects, or getting partial output.
- Neither tool knows the workspace layout; the "which packages, which public names"
  policy would live in shell glue in the workflow.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydoc-markdown` 4.8.2 | docstrings → markdown | `requires_python >=3.7,<4.0`; maintenance mode |
| `pdoc` 16.0.0 | docstrings → HTML (templates for md) | imports modules; `>=3.10` |

🔗 **Existing Code to Reuse:**
- `.github/workflows/docs.yml` — the Pages job (checkout, setup-python, pip install) is the
  template for the wiki sync job.

---

### Option B: `griffe` static loader + parrot-owned markdown renderer + `parrot sdd techwiki` CLI + sync Action  ← recommended

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

### Option C (unconventional): render the API reference from the wikitoolkit symbol plane

`wikitoolkit build` already produces a structural symbol plane for Python, TS/JS, Svelte,
Rust and PHP (`wikitoolkit symbols outline <file>` returns qualname, signature, one-line
doc, line range). A renderer over that plane could emit reference pages for **every**
language in the monorepo, including the Svelte admin UI, with no new dependency.

✅ **Pros:**
- Multi-language for free; the admin UI and the TypeScript client would get reference
  pages too.
- Zero new dependencies; reuses the plane that the post-commit hook keeps fresh.

❌ **Cons:**
- The plane stores a **one-line** doc summary and a flattened signature string, not parsed
  docstring sections. Parameter tables, Returns/Raises and Examples would require
  extending the ingestion schema (a wiki schema bump, FEAT-557 territory) before any page
  could be rendered.
- Couples documentation publishing to a full `wikitoolkit build` in CI (minutes on this
  repo, 143k pages) and to the SQLite plane format.
- Generated pages would mirror files, not Python packages; re-exports and public-API
  filtering are not represented.

📊 **Effort:** High (schema work dominates)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `wikitoolkit` (in-repo) | symbol plane | would need schema extension |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py` — `symbols outline` JSON output.

---

## Recommendation

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

## Feature Description

### User-Facing Behavior

**Readers** open `https://github.com/phenobarbital/ai-parrot/wiki` and find:

- `Home` — a short index: subsystem pages on the left, "API Reference" by package below,
  the release the wiki was built from (tag + commit), and a link to the informative site.
- `_Sidebar` — sections per subsystem (Bots & Agents, Clients, Tools & Toolkits, Memory,
  Flows, Skills, Stores & Embeddings, Loaders, MCP, Server & Handlers, Integrations,
  Outputs/A2UI, Security, SDD Tooling, …) followed by an "API Reference" section with
  one entry per distribution.
- **Subsystem pages** (authored): purpose, public entry points with links to the generated
  reference, configuration and parameter semantics, runnable usage examples, gotchas,
  related pages. Written in English.
- **Reference pages** (generated): one page per public module, e.g.
  `Reference: parrot.memory.compaction` with classes, methods, functions, parameter tables,
  returns, raises, examples from docstrings, and a "source" link to the file at the
  released tag.

**Spec authors** see a new `docs:` frontmatter key and a `## 10. Documentation` chapter in
the spec template. For a feature they list the subsystem pages to create or update
(`wiki/<section>/<page>.md`), optionally the API modules whose docstrings the feature must
complete. `/sdd-spec` prompts for the chapter when the flow type is `feature`; hotfixes and
briefs get `docs.policy: none`.

**Implementers** get one more task per feature: "Documentation — write/extend
`<pages>`", last in the dependency graph, with `parrot sdd techwiki check` as its
validation command. Pages are written in the feature worktree next to the code and merge
with it.

**`/sdd-done`** prints a `Docs: required — ok (2 pages)` or `Docs: required — WARNING: 1
page missing (wiki/memory/compaction.md)` line in the verification report and in the PR
body's Evidence section. It never blocks.

**Maintainers** see the wiki update itself a few minutes after every push to `main`,
with a commit on the wiki repo that names the source commit.

### Internal Behavior

1. **Repository layout**
   - `wiki/` — authored pages, one directory per sidebar section
     (`wiki/memory/conversation-compaction.md`). Each page has a one-line YAML frontmatter
     `title:` (optional `order:`), an H1, and standard markdown with relative links to other
     authored pages and `ref:` links to generated reference pages
     (`[compaction](ref:parrot.memory.compaction)`).
   - `wiki/_index.yaml` — section titles and order (the only hand-maintained navigation
     input).
   - `sdd/config.json` gains a `techwiki` object: `source_dir`, `packages` (list of
     `{dist, src, roots}`), `wiki_remote`, `site_url`, `exclude` globs.
2. **`techwiki api`** loads each configured root with `griffe.load(search_paths=[...])`,
   filters public members (no leading underscore, not in `__all__`-excluded sets), and
   renders one markdown page per module through Jinja templates. Deterministic output
   (sorted members, stable anchors) so a rerun on the same commit produces no diff.
3. **`techwiki bundle`** copies authored pages, generates reference pages, converts every
   page to a GitHub-wiki page name (`<Section>-<Title>` with `-` for spaces; the title
   comes from frontmatter or H1; a literal hyphen in a title is rejected because GitHub
   rewrites it to U+2010 "‐", which breaks links), rewrites relative and `ref:` links to
   wiki page links, writes `Home.md` and `_Sidebar.md`, and fails on duplicate page names
   or dangling links. Output is a flat directory ready to push.
4. **`techwiki check`** parses the spec frontmatter (`docs.policy`, `docs.pages`) and
   reports `{policy, status, present[], missing[]}` as JSON. Exit codes: `0` (ok, or
   warning), `2` (usage/config error, malformed policy). It never returns a blocking code.
5. **Workflow `techwiki.yml`**: on push to `main` (filtered paths) and manual dispatch.
   Steps: checkout, `uv sync --package ai-parrot --extra techwiki`, `parrot sdd techwiki
   bundle --out build/techwiki --release "$(git describe --tags)"`, clone wiki repo with
   `GITHUB_TOKEN`, `rsync --delete` bundle into it, commit `techwiki: sync <short-sha>`
   (skip if no diff), push. `workflow_dispatch` on a non-`main` ref uploads the bundle as
   an artifact instead of pushing (preview mode).
6. **SDD flow changes** (all twins + `_assets/` + manifest):
   - `sdd/templates/spec.md`: `docs:` frontmatter block (policy `required|none`, `pages`,
     `api_modules`) and `## 10. Documentation` chapter with a page-template checklist.
   - `sdd/templates/techwiki-page.md`: the authored page skeleton (Purpose, Public API,
     Configuration, Usage, Gotchas, Related).
   - `/sdd-spec`: asks for the chapter on `type: feature`; writes `policy: none` for
     hotfix; `/sdd-brief` never adds the key.
   - `/sdd-task` §3: one `docs` task per spec with `docs.policy: required`, depends on the
     implementation tasks that create the documented symbols; validation command
     `parrot sdd techwiki check --spec <spec> --root .`.
   - `/sdd-done` Step 4.6b: run `techwiki check`, carry the line into Step 5 report and
     Step 12 output; `--force` unchanged. Specs without a `docs:` key (every spec written
     before this feature) report `Docs: unset — skipped`.
7. **Migration**: a mapping table (spec-level) moves technical directories from `docs/`
   to `wiki/<section>/` with `git mv`, translates Spanish pages, rewrites links, removes
   the entries from `mkdocs.yml` nav and adds a redirect note in `docs/index.md`
   ("Technical reference moved to the Wiki"). Exclusions: `docs/sdd/WORKFLOW.md` and
   anything `@`-included by `CLAUDE.md`, `docs/decisions/**` (the wikitoolkit ADR plane
   globs it; the bundle *includes* these files read-only instead of moving them — my
   call, see Open Questions), `docs/superpowers/**`, informative chapters/guides/INSTALL.
8. **Backfill**: subsystem pages for bots/agents, clients, tools/toolkits, memory, flows
   (crew/flow), skills, stores/embeddings, loaders, MCP, server/handlers, written from the
   code and the existing specs; each links to its generated reference pages.
9. **Cut-over** (last task, after the sync workflow has run green on `main` at least once):
   remove `mkdocstrings` from `mkdocs.yml` plugins and `requirements-docs.txt`, delete
   `docs/api-reference/`, drop the nav block, replace the "Browse the API" button with a
   link to the wiki, update `docs/index.md` "Contributing". `docs.yml` keeps running for
   the informative site.

### Edge Cases & Error Handling

- **Page-name collision** (two authored pages or an authored page vs a generated one
  flatten to the same wiki name): `bundle` fails with both source paths listed. CI fails
  loudly; nothing is pushed.
- **Dangling link** in an authored page: `bundle` fails and names the page and target.
  `techwiki check` does not validate links (that is the bundler's job), so a feature PR
  does not break on links; the sync job on `main` does. Mitigation: `techwiki bundle
  --dry-run` is also offered as an optional `pre_pr` closeout hook (`sdd_hooks.toml`).
- **Title with a literal hyphen** (`ai-parrot`): rejected by `bundle` with a hint to use
  a space or an en-dash-free title, because GitHub stores it as U+2010 (`ai‐parrot`) and
  `[[ai-parrot]]` would then point to a different page.
- **Wiki repo missing or token lacks write**: the push step fails; the bundle is still
  uploaded as a workflow artifact for inspection.
- **No diff after regeneration**: the workflow exits green without a commit.
- **Spec frontmatter `docs.policy` with an unknown value**: `techwiki check` exits 2 with
  a message; `/sdd-done` reports `Docs: invalid policy` and continues (warning lane).
- **Spec without `docs:` key** (pre-existing specs): `Docs: unset — skipped`.
- **griffe cannot parse a file** (syntax error, Cython `.pyx`): the module is skipped and
  listed in a `techwiki-report.json` so the gap is visible; Cython modules are out of scope
  for generated reference in v1 (their `.pyi` stubs, when present, are loaded instead).
- **Python 3.10 environment**: `parrot sdd techwiki api|bundle` print a clear error
  ("requires the techwiki extra on Python ≥ 3.11"); `check` and `sidebar` do not need
  griffe and keep working everywhere.
- **Concurrent pushes to `main`**: the workflow concurrency group queues the second run;
  the last one wins, which is correct because it reflects the newer commit.

---

## Capabilities

### New Capabilities
- `techwiki-api-reference`: griffe-based markdown API reference generator for the
  configured workspace packages (`parrot sdd techwiki api`).
- `techwiki-bundle`: publishable GitHub-wiki bundle (authored + generated, page naming,
  link rewriting, `Home.md`, `_Sidebar.md`, collision/dangling checks).
- `techwiki-sync-workflow`: `.github/workflows/techwiki.yml` pushing the bundle to
  `ai-parrot.wiki.git` on `main`.
- `spec-documentation-chapter`: `docs:` frontmatter + `## 10. Documentation` in the spec
  template, the authored page template, `/sdd-spec` prompting.
- `sdd-docs-task-derivation`: `/sdd-task` emits one documentation task per `required`
  spec.
- `sdd-done-docs-warning`: `/sdd-done` Step 4.6b runs `techwiki check` and reports.
- `techwiki-migration`: technical `docs/**` directories moved into `wiki/`, translated,
  nav cleaned.
- `techwiki-backfill`: subsystem pages for the main subsystems.
- `pages-api-reference-cutover`: `mkdocstrings` and `docs/api-reference/` removed from
  the Pages site.

### Modified Capabilities
- `sdd-flow-types-and-per-spec-index` (FEAT-145) — spec template and command twins gain
  the Documentation chapter and the warning step.
- `sdd-asset-packaging` (FEAT-633 M6) — `_assets/` manifest regenerated for the changed
  commands/templates; new template file added to `ASSET_SOURCES` coverage
  (`sdd/templates/*` glob already matches).
- `docs-site` (`mkdocs.yml`, `docs.yml`) — nav shrinks to informative content; plugin list
  loses `mkdocstrings`.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/cli.py` (`VERBS`) | extends | new `techwiki` noun with `api`, `bundle`, `check`, `sidebar` verbs |
| `packages/ai-parrot/src/parrot/sdd/scripts/` | extends | new modules `techwiki_api.py`, `techwiki_bundle.py`, `techwiki_check.py` (+ templates under `parrot/sdd/techwiki_templates/`) |
| `packages/ai-parrot/pyproject.toml` | extends | optional extra `techwiki = ["griffe>=2.4,<3; python_version >= '3.11'"]` |
| `sdd/config.json` | extends | `techwiki` configuration object (repo-neutral keys) |
| `sdd/templates/spec.md` | modifies | `docs:` frontmatter + `## 10. Documentation` |
| `sdd/templates/techwiki-page.md` | new | authored page skeleton |
| `.claude/commands/sdd-spec.md`, `sdd-task.md`, `sdd-done.md` + twins (`.agents/skills/sdd-*/SKILL.md`, `.agent/workflows/sdd-*.md`) | modifies | chapter prompting, docs task derivation, Step 4.6b |
| `packages/ai-parrot/src/parrot/sdd/_assets/` + `manifest.json` | regenerated | `scripts/sdd/check_asset_sync.py --write`; CI check must stay green |
| `.github/workflows/techwiki.yml` | new | sync job; `permissions: contents: write` |
| `.github/workflows/docs.yml` | modifies | `paths:` loses `packages/ai-parrot/src/parrot/**` after cut-over (no more docstring dependency) |
| `mkdocs.yml`, `requirements-docs.txt`, `docs/index.md`, `docs/api-reference/` | modifies / deletes | cut-over task |
| `docs/<technical dirs>` → `wiki/<section>/` | moves | migration task; `git mv` keeps history |
| `wikitoolkit` plane | depends on | `wiki/**/*.md` is indexed automatically (`.md` in `include_suffixes`); no config change. `docs/decisions/**` stays where the ADR globs expect it |
| `tests/sdd_scripts/` | extends | text-contract tests for the three command twins (pattern: `test_sdd_done_hooks_contract.py`), unit tests for the three scripts, a bundle fixture repo |
| `/sdd-brief`, hotfix lane | unchanged | no `docs:` key, `Docs: unset — skipped` |

Breaking changes: none for library users. For documentation readers, URLs under
`phenobarbital.github.io/ai-parrot/docs/api-reference/` and the moved technical pages
stop resolving on the Pages site after cut-over (a redirect note is left on `docs/index.md`).

---

## Code Context

### User-Provided Code

None — the user provided the wiki bootstrap URL:
`https://github.com/phenobarbital/ai-parrot/wiki/Welcome-to-ai%E2%80%90parrot!`
(note the `%E2%80%90` = U+2010 hyphen GitHub substituted for the literal `-` in
"ai-parrot"; this is the page-naming gotcha the bundler guards against).

### Verified Codebase References

#### Classes & Signatures
```python
# From packages/ai-parrot/src/parrot/sdd/cli.py:237
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {
    "worktree": {...}, "task": {...}, "ids": {...}, "spec": {...}, "brief": {...},
    "docs": {  # line 284 — existing noun: parse / taxonomy / resolve-flow / list / backfill / migrate-index
        ...
    },
    "tests": {...}, "closeout": {...}, "hooks": {...},
}

# From packages/ai-parrot/src/parrot/sdd/cli.py:316
def _mount(noun: click.Group, verb: str, module: str, prefix: tuple[str, ...], help_: str) -> None:
    """Mount ``noun verb [args…]`` → ``parrot.sdd.scripts.<module>.main([*prefix, *args])`` (C30 item 2)."""

# From packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py:53
def resolve_policy(spec_path: Path) -> str:
    """Return the spec's E2E policy, or ``invalid`` when it is malformed."""
# From packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py:201
def main(argv: Optional[Sequence[str]] = None) -> int:
    """Exit 0 when closeout may proceed, 1 when it must abort."""

# From packages/ai-parrot/src/parrot/sdd/scripts/sdd_meta.py:34
def main(argv: Sequence[str] | None = None) -> int:
    """CLI for shell callers: ``parse``, ``taxonomy`` and ``resolve-flow`` subcommands."""
# re-exports the parser from parrot.knowledge.wiki.ledger.sdd_meta (sdd_meta.py:15)

# From packages/ai-parrot/src/parrot/sdd/installer.py:1064
def install_sdd_integration(
    root: Path,
    hosts: Sequence[str] = ("claude",),
    *,
    keep_edits: bool = False,
    dry_run: bool = False,
    portable: bool = False,
    base_branch: str | None = None,
    push_base: bool = False,
    hotfix_base: str | None = None,
    dangerous_guard: bool = True,
    sdd_coder: bool = True,
) -> list[str]:
    """Deploy packaged SDD assets for ``hosts`` into ``root``, replacing older or hand-edited copies."""

# From scripts/sdd/check_asset_sync.py:28
ASSET_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (".claude/commands/sdd-*.md", HOST_ORDER),
    (".agents/skills/sdd-*/SKILL.md", ("codex", "google")),
    (".agent/workflows/sdd-*.md", ("google",)),
    ("sdd/templates/*", HOST_ORDER),
    ...
)
```

#### Verified Imports
```python
# These imports have been confirmed to work:
from parrot.sdd.cli import VERBS, _mount                     # packages/ai-parrot/src/parrot/sdd/cli.py:237,316
from parrot.sdd.scripts.check_e2e_closeout import resolve_policy, main   # check_e2e_closeout.py:53,201
from parrot.sdd.scripts import sdd_meta                      # sdd_meta.py:34
```

#### Key Attributes & Constants
- `sdd/templates/spec.md:13-22` — commented `# e2e:` frontmatter block (comment at line 13, key at line 21; precedent for `docs:`).
- `VERBS` (`cli.py:237`) and `ASSET_SOURCES` (`check_asset_sync.py:28`) are module-level constants, not
  def/class symbols — verified by reading the files, not by the symbol probe.
- `sdd/templates/spec.md` — `## 7. Implementation Notes & Constraints` … `## 9. Design Research Cross-Check` then `## Revision History`; the new chapter goes in as `## 10. Documentation` to avoid renumbering §8/§9, which other commands cite by number.
- `.claude/commands/sdd-done.md` — `### 4.6. Verify E2E Evidence (FEAT-581)` and `### 4.8. Closeout Hooks — pre_pr (FEAT-764)`: Step 4.6b sits between them.
- `.claude/commands/sdd-task.md` — `### 3. Plan Task Decomposition`: documentation task rule goes here.
- `.claude/commands/sdd-spec.md` — already runs `wikitoolkit spec governing sdd/specs/<feature-name>.spec.md`; Documentation prompting is added next to it.
- `.agents/skills/sdd-done/SKILL.md` — codex/google twin of `/sdd-done` (must be edited in lock-step; `check_asset_sync.py --check` fails otherwise).
- `.github/workflows/docs.yml` — triggers on `push: branches: [main]` with `paths:` including `packages/ai-parrot/src/parrot/**`; jobs `build` (pip install `requirements-docs.txt`, editable install of core, `mkdocs build`, overlay `landing/`) and `deploy` (`actions/deploy-pages@v5`).
- `mkdocs.yml:54` — `- mkdocstrings:` plugin (python handler, `paths: [packages/ai-parrot/src]`); `mkdocs.yml:299` — `- API Reference:` nav block (10 entries).
- `docs/index.md:17` — `[Browse the API →](api-reference/index.md){ .md-button }`; `docs/index.md:136` — "API reference is generated by mkdocstrings…".
- `docs/api-reference/a2a.md:3` — `::: parrot.a2a` (all 9 reference pages are mkdocstrings directives).
- `requirements-docs.txt:3` — `mkdocstrings[python]>=1.0.8`.
- `docs/sdd/closeout-hooks.md` + `sdd/templates/sdd_hooks.example.toml` — `pre_pr` command hooks (optional `techwiki bundle --dry-run` hook).
- `.parrot/wiki.json` — `include_suffixes` contains `.md`; `decisions.adr_globs = ["docs/adr/**/*.md", "docs/adrs/**/*.md", "docs/decisions/**/*.md"]` (why `docs/decisions/` must not move).
- GitHub: `gh repo view` → `hasWikiEnabled: true`, public; `git ls-remote https://github.com/phenobarbital/ai-parrot.wiki.git` → `refs/heads/master` exists (bootstrapped 2026-11-04).
- PyPI (checked 2026-11-04): `griffe 2.4.1` (`>=3.11`), `pydoc-markdown 4.8.2` (`>=3.7,<4.0`), `pdoc 16.0.0` (`>=3.10`).
- `docs/` inventory: 338 markdown files; technical candidates for migration (by directory):
  architecture (11), dev_loop (10), api-reference (10, deleted at cut-over), frontend (8),
  tools (7), integrations (7), outputs (6), clients (6), wiki (5), toolkits (5), testing (4),
  prompts (4), memory (4), knowledge (4), security (3), runbooks (3), roost (3),
  pipelines (3), orchestration (3), events (3), auth (3), voice (2), messaging (2),
  interfaces (2), features (2), experts (2), cli (2), api (2), agents (2), skills, scheduler,
  report-builder, operations, mcp, install, graphindex, flows, files, executors,
  execution_plan, eval, design, configuration, agentstudio (1 each). Informative (stay):
  index, INSTALL, config, tools_quick, chapters (7), guides (6), examples, migration (12,
  decide at spec), branding, postman, aws, landing.

### Does NOT Exist (Anti-Hallucination)
- ~~`wiki/` directory at the repo root~~ — does not exist yet (created by this feature).
- ~~`.github/workflows/techwiki.yml`~~ / any wiki-sync workflow — none exists.
- ~~`parrot sdd techwiki`~~ noun, ~~`parrot/sdd/scripts/techwiki_*.py`~~ — do not exist.
- ~~`griffe`~~ in any `pyproject.toml` or the venv — not a dependency today (only reachable
  through `mkdocstrings[python]` in `requirements-docs.txt`, which is not installed in the
  workspace venv).
- ~~`docs:` key in spec frontmatter~~, ~~`## 10. Documentation` chapter~~ — not in the
  template.
- ~~`sdd/CONVENTIONS.md` § Project areas content~~ — the section exists but is an empty
  placeholder; `projects:` values in use are observed from existing specs (`ai-parrot`,
  `sdd-tooling`, `docs`, `ai-parrot-tools`, `ai-parrot-server`, …).
- ~~a `parrot docs` top-level group~~ — the top-level CLI has `wiki` (wikitoolkit) and
  `sdd docs` (frontmatter helpers), nothing for publishing.

---

## Parallelism Assessment

- **Internal parallelism**: high in the middle, serial at both ends.
  - Independent lanes after the config/schema task: (a) `techwiki api` renderer, (b)
    `techwiki check` + spec template + `/sdd-spec`/`/sdd-task`/`/sdd-done` twins, (c)
    authored page template + backfill content.
  - `bundle` depends on (a) and the page template; migration depends on the bundle's
    naming/link rules; the workflow depends on `bundle`; cut-over depends on the workflow
    having run on `main` (a human-observed precondition recorded in the task's Completion
    Note, since `/sdd-done` runs before the merge).
- **Cross-feature independence**: shares `.claude/commands/sdd-*.md`, their twins,
  `sdd/templates/spec.md` and `parrot/sdd/_assets/` with any in-flight spec that edits the
  SDD commands (check `sdd/tasks/index/*.json` with `status != done` touching those paths
  before `/sdd-task`; FEAT-799 `claude-install-welcome-wizard` touches the installer, not
  the commands). `mkdocs.yml`/`docs/**` are otherwise uncontended.
- **Recommended isolation**: `mixed` — one feature worktree; the renderer, the gate/flow
  twins and the content tasks can run as parallel coder seats; migration, workflow and
  cut-over are `parallel: false` because they touch many files and `mkdocs.yml`.
- **Rationale**: the renderer and the SDD-flow changes share no files; the content tasks
  only add files under `wiki/`. Serialising the three cross-cutting tasks avoids merge
  conflicts on `mkdocs.yml`, `docs/index.md` and `_assets/manifest.json`.

---

## Open Questions

- [ ] CLI noun name: `parrot sdd techwiki` is proposed to avoid colliding with `parrot wiki`
  (wikitoolkit). Alternatives: `reference`, `handbook`. — *Owner: Jesus*
- [ ] ADRs: keep `docs/decisions/**` in place (wikitoolkit's `adr_globs` depend on it) and
  let the bundle include them read-only under a "Decisions" section, instead of moving them
  — my call; confirm or change `adr_globs` and move them. — *Owner: Jesus*
- [ ] `docs/sdd/**` and `docs/wiki/**` (agent/tooling docs): `docs/sdd/WORKFLOW.md` is
  `@`-included by `CLAUDE.md` and must stay; should the rest of `docs/sdd/` and `docs/wiki/`
  (cheatsheet, inbox, lint, standup, schema-plane) move to the wiki "SDD Tooling" /
  "LLM Wiki" sections or stay on Pages as guides? — *Owner: Jesus*
- [ ] `docs/migration/**` (12 FEAT migration notes): technical (move) or informative
  (stay)? Proposed: move. — *Owner: Jesus*
- [ ] Documentation chapter numbering: `## 10. Documentation` appended after §9 to avoid
  renumbering §8 Open Questions / §9 Design Research, which `/sdd-task`, `/sdd-done` and
  tests cite by number. Accept, or renumber in a dedicated follow-up? — *Owner: Jesus*
- [ ] Release label on `Home.md`: `git describe --tags` on `main` (release tags) vs the
  `ai-parrot` version from `pyproject.toml`. Proposed: both. — *Owner: Claude (spec)*
- [ ] Should `workflow_dispatch` from `dev` publish to a preview location (artifact only,
  proposed) or to a second wiki-like branch? Proposed: artifact only in v1. — *Owner: Jesus*
- [ ] Follow-up (not this feature): multi-language reference (Svelte admin UI, TS client)
  via the wikitoolkit symbol plane (Option C). — *Owner: Jesus*
