---
type: feature
base_branch: dev
projects: [ai-parrot, sdd-tooling, docs]
tags: [docs, github-wiki, api-reference, sdd-flow, mkdocs, griffe]
---

# Feature Specification: GitHub Wiki as the Technical Reference

**Feature ID**: FEAT-801
**Date**: 2026-11-04
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 2.1.0
**Exploration**: `sdd/proposals/github-wiki-technical-reference.brainstorm.md` (accepted, Option B)

---

## 1. Motivation & Business Requirements

### Problem Statement

ai-parrot has two kinds of documentation and one surface for both. `docs/` (338 markdown files,
118 of them at the top level) mixes narrative material (what parrot is, install, chapter
overviews, guides) with deep technical material (memory compaction internals, toolkits, clients,
A2UI outputs, the SDD tooling itself), and `mkdocs.yml` renders all of it, plus a
`mkdocstrings`-generated API reference (`docs/api-reference/*.md`, core package only), into the
GitHub Pages site at `https://phenobarbital.github.io/ai-parrot/docs/`.

1. **The informative site is drowned by technical pages.** A newcomer landing on Pages meets
   more than 80 nav entries, most of them implementation notes. The site cannot become a clean
   "what is parrot" front door while it is also the reference manual.
2. **Technical documentation is not a deliverable of the SDD flow.** `/sdd-spec` → `/sdd-task`
   → `/sdd-done` produce code, tests, ledger events and an E2E gate, but no documentation page.
   Hundreds of merged FEATs have no technical page.
3. **The generated API reference covers one of nine Python namespaces** and renders HTML only,
   so it cannot feed a markdown wiki.

The GitHub Wiki of `phenobarbital/ai-parrot` was bootstrapped on 2026-11-04
(`ai-parrot.wiki.git`, branch `master`, one Home page). The technical content needs its new home
before `mkdocstrings` leaves the Pages site; the Pages redesign itself is a separate, later spec.

### Goals

- G1. Publish a technical reference on the GitHub Wiki: authored subsystem pages (semantics,
  configuration, examples, gotchas) plus a generated API reference for the public API of every
  Python distribution in the workspace.
- G2. The monorepo is the single source of truth: a versioned `wiki/` tree plus generated pages,
  pushed to `ai-parrot.wiki.git` by a workflow on every push to `main`. The wiki reflects released
  code only.
- G3. Make technical documentation a deliverable of every `type: feature` spec: a `docs:`
  frontmatter key and a `## 10. Documentation` chapter in the spec template, one documentation task
  derived by `/sdd-task`, and a warning-only check in `/sdd-done`.
- G4. Move the technical documents out of `docs/` (and the mkdocs nav) into `wiki/`, in English,
  and backfill subsystem pages for the main subsystems that have none.
- G5. Remove `mkdocstrings` and `docs/api-reference/` from the Pages site only after the wiki sync
  has run green on `main`, so there is never a moment without a published API reference.

### Non-Goals (explicitly out of scope)

- Redesigning the GitHub Pages site as the informative front door (follow-up spec
  `github-pages-informative-site`).
- Generated reference for non-Python code (Svelte admin UI, TypeScript client). The brainstorm's
  Option C (wikitoolkit symbol plane renderer) is recorded as a follow-up.
- Editing the wiki from the GitHub web UI; every sync overwrites it.
- A blocking documentation gate. The user chose warning-only; discipline stays with the reviewer.
- Publishing a preview wiki from `dev`. `workflow_dispatch` on a non-`main` ref uploads the bundle
  as an artifact only.
- Backfilling a page per merged FEAT. Backfill is per subsystem (G4).
- `pydoc-markdown`/`pdoc` (import-based generators) were rejected in the brainstorm (Option A).

---

## Governing Decisions

<!-- decision-audit: input_digest=sha256:e298362cba74b8b5f3f1fc93c6c3162940e1cb814d71cbc3af5d89e532b142eb evaluation_digest=sha256:45a9135245f5a89fc1774169e79f3158f5b64674b3a693ad9f7647602815ee16 rules_version=1 status=pass -->

No eligible decisions govern subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools

## 2. Architectural Design

### Overview

Two surfaces with strict roles. **GitHub Pages** stays the informative site (unchanged by this
spec except for the cut-over in M9). **GitHub Wiki** becomes the technical reference, assembled
from two layers and published from the monorepo:

- **Authored pages** live in `wiki/<section>/<page>.md`, organised by subsystem (not per
  feature), written in English, with a one-line YAML frontmatter (`title`, optional `order`,
  optional `summary`). They link to each other with relative paths and to generated reference
  pages with the `ref:` scheme (`[compaction](ref:parrot.memory.compaction)`). The navigation
  input is `wiki/_index.yaml` (section ids, titles, order).
- **Generated reference pages** are produced only at publish time by `parrot sdd techwiki api`,
  which loads every configured package **statically** with `griffe` (no imports, so no Navigator
  or observability side effects, no optional dependencies) and renders one markdown page per
  public module through Jinja templates: classes, methods, functions, parameter tables, returns,
  raises, examples, and a source link to the file at the published ref.

`parrot sdd techwiki bundle` merges both layers into a flat, publish-ready directory: it computes
GitHub wiki page names, rewrites links, includes `docs/decisions/**` read-only under a
"Decisions" section, writes `Home.md`, `_Sidebar.md` and a `techwiki-manifest.json` (source
path / module → page name), and fails on page-name collisions or dangling links.
`.github/workflows/techwiki.yml` publishes on the **release boundary**: it runs on
`release: [published]` (the same event that drives the PyPI publish in `release.yml`), checks
out the release tag, runs the bundle and pushes it to `ai-parrot.wiki.git` with the job's
`GITHUB_TOKEN`. An ordinary push to `main` (a hotfix merge ahead of a tag) therefore never
publishes unreleased code (design research S3). A read-only `bundle --dry-run` runs in PR CI
so dangling links and renderer failures surface before merge (S11).

The SDD flow gains a Documentation chapter: `docs:` frontmatter (`policy: required|none`,
`pages: [wiki/...]`, optional `api_modules`) plus `## 10. Documentation` in
`sdd/templates/spec.md`; `/sdd-spec` writes it for `type: feature` (`policy: none` for hotfix;
`/sdd-brief` never adds the key); `/sdd-task` derives one documentation task, last in the graph;
`/sdd-done` Step 4.6b runs `parrot sdd techwiki check` and prints a `Docs:` line in the report and
the PR body. The check never blocks and `--force` does not interact with it.

All SDD-flow assets (commands, twins, templates) are repo-neutral because `parrot sdd install`
ships them to other repositories; `techwiki` configuration lives in `sdd/config.json` under a
`techwiki` key with defaults that work for any Python repo.

Resolved brainstorm/clarification decisions reflected here: CLI noun `techwiki` (collision-free
with `parrot wiki`); `docs/decisions/**` stays in place (wikitoolkit `adr_globs` read it) and the
bundle includes it; `docs/sdd/**` (except `WORKFLOW.md` and anything `@`-included by `CLAUDE.md`),
`docs/wiki/**` and `docs/migration/**` move to the wiki; the chapter is numbered `## 10.` so §8/§9,
cited by number elsewhere, keep their numbers.

### Component Diagram

```
monorepo (dev → main)
├── wiki/                          authored pages (M4 template, M7 migration, M8 backfill)
│   ├── _index.yaml                sections + order
│   ├── memory/conversation-compaction.md
│   └── ...
├── docs/decisions/*.md            ADRs (unchanged; included read-only by bundle)
├── sdd/config.json  { "techwiki": {...} }                       (M1)
├── packages/ai-parrot/src/parrot/sdd/
│   ├── cli.py            VERBS["techwiki"] = api | bundle | check | sidebar   (M1)
│   ├── techwiki/         config.py · naming.py · api.py · bundle.py · check.py · templates/*.md.j2  (M1–M3, M5)
│   └── scripts/          techwiki_api.py · techwiki_bundle.py · techwiki_check.py (thin main() shims)  (M1–M3, M5)
└── .github/workflows/techwiki.yml                                 (M6)
        release published ──▶ checkout <tag> ──▶ uv sync --extra techwiki
                          ──▶ parrot sdd techwiki bundle --out build/techwiki --release <tag>
                          ──▶ git clone <repo>.wiki.git ──▶ rsync --delete ──▶ commit "techwiki: sync <tag> (<sha>)" ──▶ push
        pull_request      ──▶ parrot sdd techwiki bundle --dry-run --json  (read-only; report as artifact)

SDD flow (M4, M5):
  sdd/templates/spec.md  docs: {policy, pages, api_modules} + "## 10. Documentation"
  /sdd-spec  ──writes chapter──▶ /sdd-task ──derives docs task──▶ /sdd-done 4.6b ──▶ parrot sdd techwiki check
```

### Integration Points

| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VERBS["techwiki"]` | `parrot sdd` click group | `_mount()` loop at module bottom | `packages/ai-parrot/src/parrot/sdd/cli.py:237`, `:316` |
| `parrot.sdd.techwiki.config.TechwikiConfig` | `SddConfig` | new optional field `techwiki: TechwikiConfig \| None` | `packages/ai-parrot/src/parrot/sdd/config.py:19` |
| `parrot.sdd.techwiki.check.resolve_docs_policy` | spec frontmatter | same split-and-`yaml.safe_load` rules as `resolve_policy` | `packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py:53` |
| `/sdd-done` Step 4.6b | `parrot sdd techwiki check` | bash block, JSON stdout, `Docs:` line | `.claude/commands/sdd-done.md:237` (4.6), `:331` (4.8) |
| `/sdd-task` docs task rule | `## 10. Documentation` + `docs:` | §3 planning rule + §4 task generation | `.claude/commands/sdd-task.md:117`, `:259` |
| `/sdd-spec` chapter prompting | `sdd/templates/spec.md` | §5 scaffold hint next to the E2E hint | `.claude/commands/sdd-spec.md:566` |
| `techwiki.yml` | `ai-parrot.wiki.git` | `GITHUB_TOKEN`, `permissions: contents: write`; trigger `release: [published]` like `release.yml` (`release: [created]`) | `.github/workflows/docs.yml:1` (job skeleton), `.github/workflows/release.yml:3-5` |
| `_assets/` + `manifest.json` | changed commands/templates | `scripts/sdd/check_asset_sync.py --write` | `scripts/sdd/check_asset_sync.py:28`; CI `.github/workflows/ci.yml:127` |
| `docs/index.md`, `mkdocs.yml`, `requirements-docs.txt` | cut-over | M9 edits | `docs/index.md:17`, `mkdocs.yml:54`, `:299`, `requirements-docs.txt:3` |
| wikitoolkit plane | `wiki/**/*.md` | automatic (`.md` in `include_suffixes`) | `.parrot/wiki.json` |

### Data Models

```python
# parrot/sdd/techwiki/config.py — Pydantic v2, extra="forbid"
class TechwikiPackage(BaseModel):
    dist: str                       # "ai-parrot-tools"
    src: str                        # "packages/ai-parrot-tools/src"  (griffe search path, repo-relative)
    roots: list[str]                # ["parrot_tools"]  (top-level import names to load)

class TechwikiConfig(BaseModel):
    source_dir: str = "wiki"
    index_file: str = "wiki/_index.yaml"
    packages: list[TechwikiPackage] = []
    include_adrs: list[str] = ["docs/decisions/**/*.md"]   # read-only inclusion
    adr_section: str = "Decisions"
    reference_section: str = "API Reference"
    site_url: str | None = None      # informative site link on Home
    source_url: str | None = None    # "https://github.com/<owner>/<repo>" for source links
    exclude: list[str] = []          # glob patterns under source_dir

# spec frontmatter (sdd/templates/spec.md)
docs:
  policy: required            # required | none ; absent key = "unset"
  pages:
    - wiki/memory/conversation-compaction.md
  api_modules:                # optional; docstring completeness expectation, informational
    - parrot.memory.compaction

# parrot sdd techwiki check — stdout JSON
{"policy": "required|none|unset|invalid", "status": "ok|warning|skipped|invalid",
 "present": ["wiki/..."], "missing": ["wiki/..."], "empty": ["wiki/..."],
 "reason_codes": ["docs_required_missing_pages", "docs_page_empty", "docs_page_no_title", "docs_api_module_syntax"]}

# bundle report — build/techwiki/techwiki-report.json
{"release": "v2.1.0", "commit": "<sha>", "authored": N, "generated": N, "adrs": N,
 "skipped_modules": [{"module": "...", "reason": "..."}], "collisions": [], "dangling": []}
# bundle manifest — build/techwiki/techwiki-manifest.json  (S9: stable traceability of every link target)
{"pages": [{"id": "wiki/memory/conversation-compaction.md", "name": "Memory-Conversation-Compaction", "section": "memory", "kind": "authored"},
           {"id": "ref:parrot.memory.compaction", "name": "Reference-parrot.memory.compaction", "section": "api", "kind": "generated"}]}
```

### New Public Interfaces

| Interface | Kind | Purpose |
|---|---|---|
| `parrot sdd techwiki api --out DIR [--root PATH] [--release TAG]` | CLI | generate reference pages |
| `parrot sdd techwiki bundle --out DIR [--root PATH] [--release TAG] [--dry-run] [--json]` | CLI | assemble the publishable bundle; exit 1 on collision/dangling |
| `parrot sdd techwiki check --spec PATH [--root PATH] [--json]` | CLI | docs chapter check; exit 0 (ok/warning/skipped), 2 (usage/invalid) |
| `parrot sdd techwiki sidebar --out DIR [--root PATH]` | CLI | render `Home.md`/`_Sidebar.md` only |
| `parrot.sdd.techwiki.naming.page_name(section, title) -> str` | Python | GitHub wiki page-name rules |
| `parrot.sdd.techwiki.naming.rewrite_links(text, resolver) -> str` | Python | relative/`ref:` → wiki links |
| `ai-parrot[techwiki]` extra | packaging | `griffe>=2.4,<3`, `jinja2>=3.1` (self-contained: jinja2 is otherwise only in the `agents` extra); the package floor is already `>=3.11,<3.14`, so no marker is needed |

---

## 3. Module Breakdown

> Interface Skeletons carry `# verified: path:NN` for every line that touches existing code. Bodies
> belong to `/sdd-task` blueprints.

### Module 1: `techwiki` configuration, naming and CLI noun (`M1`)

**Files**: CREATE `packages/ai-parrot/src/parrot/sdd/techwiki/__init__.py`, `config.py`,
`naming.py`; MODIFY `packages/ai-parrot/src/parrot/sdd/config.py`,
`packages/ai-parrot/src/parrot/sdd/cli.py`, `packages/ai-parrot/pyproject.toml`,
`sdd/config.json`; CREATE `packages/ai-parrot/tests/sdd/test_techwiki_config.py`,
`packages/ai-parrot/tests/sdd/test_techwiki_naming.py`.

```python
# parrot/sdd/techwiki/config.py
class TechwikiPackage(BaseModel): ...          # see §2 Data Models
class TechwikiConfig(BaseModel): ...

def load_techwiki_config(root: Path) -> TechwikiConfig:
    """Return the `techwiki` section of sdd/config.json (defaults when absent)."""

# parrot/sdd/config.py                                     # verified: packages/ai-parrot/src/parrot/sdd/config.py:19
class SddConfig(BaseModel):
    ...
    #: FEAT-801 — technical-wiki pipeline settings; ``None`` means defaults.
    techwiki: TechwikiConfig | None = None                 # new field after `projects` (config.py:35)

# parrot/sdd/techwiki/naming.py
class PageNameError(ValueError):
    """Raised for a title GitHub would rewrite (literal '-') or an empty title."""

def page_name(section: str | None, title: str) -> str:
    """Return the GitHub wiki page name: `<Section>-<Title>` with spaces as '-'.

    Raises PageNameError when the title contains a literal hyphen: GitHub stores it as U+2010
    ('‐'), so `[[Title]]` links would point at a different page.
    """

def page_title(path: Path, text: str) -> str:
    """Frontmatter `title`, else the first H1, else the file stem in Title Case."""

def rewrite_links(text: str, resolver: Callable[[str], str | None]) -> str:
    """Rewrite relative `.md` links and `ref:<module>` links to `[[Page Name]]`; unknown targets
    are returned by the resolver as None and collected by the caller as dangling."""

# parrot/sdd/cli.py                                        # verified: packages/ai-parrot/src/parrot/sdd/cli.py:237
VERBS["techwiki"] = {
    "api": ("techwiki_api", (), "Generate the markdown API reference for the configured packages."),
    "bundle": ("techwiki_bundle", (), "Assemble the publishable GitHub-wiki bundle (authored + API + ADRs)."),
    "check": ("techwiki_check", (), "Report a spec's declared documentation pages (never blocking)."),
    "sidebar": ("techwiki_bundle", ("--sidebar-only",), "Render Home.md and _Sidebar.md only."),
}
```

`pyproject.toml`: add `techwiki = ["griffe>=2.4,<3", "jinja2>=3.1"]` to
`[project.optional-dependencies]` (jinja2 is declared explicitly because core only gets it through
the `agents` extra, `pyproject.toml:476`; the package floor is `>=3.11,<3.14` at line 18, so griffe
needs no Python marker), and `"techwiki/templates/*.j2"` to the `"parrot.sdd"` package-data list. `sdd/config.json`: add the `techwiki` object listing the nine Python
distributions (`ai-parrot`, `ai-parrot-tools`, `ai-parrot-loaders`, `ai-parrot-pipelines`,
`ai-parrot-server`, `ai-parrot-embeddings`, `ai-parrot-integrations`, `ai-parrot-advisors`,
`ai-parrot-visualizations`), `site_url`, `source_url`.

### Module 2: API reference generator (`M2`) — depends on M1

**Files**: CREATE `packages/ai-parrot/src/parrot/sdd/techwiki/api.py`,
`packages/ai-parrot/src/parrot/sdd/techwiki/templates/module.md.j2`,
`packages/ai-parrot/src/parrot/sdd/scripts/techwiki_api.py`,
`packages/ai-parrot/tests/sdd/test_techwiki_api.py`,
`packages/ai-parrot/tests/sdd/fixtures/techwiki_pkg/` (a tiny sample package).

```python
# parrot/sdd/techwiki/api.py
@dataclass(frozen=True)
class RenderedPage:
    module: str            # "parrot.memory.compaction"
    section: str           # reference_section
    title: str             # "Reference: parrot.memory.compaction"
    body: str

class GriffeUnavailable(RuntimeError):
    """griffe is not importable: install `ai-parrot[techwiki]`."""

def load_packages(cfg: TechwikiConfig, root: Path) -> list["griffe.Module"]:
    """Statically load every configured root with griffe.load(search_paths=[root/src]).
    PEP 420 namespace roots (`parrot` split across distributions) are loaded with every
    configured `src` on the search path at once, so satellite subpackages merge into one tree."""

def is_public(obj: "griffe.Object") -> bool:
    """Rendering rules (S8, fixed here, golden-tested):
    - name does not start with `_` (`__init__` is merged into its class, like mkdocstrings' merge_init_into_class);
    - when the module defines `__all__`, only those names; otherwise every non-underscore member;
    - an alias (re-export) renders as a one-line "re-exported from `<target>`" link, never a duplicate body;
    - `@overload` stubs are collapsed into one entry listing each signature;
    - properties render under "Attributes" with their return annotation;
    - Pydantic/dataclass fields render under "Fields" (name, annotation, default, Field description);
    - nested classes render under their parent with a dotted heading."""

def render_module(mod: "griffe.Module", *, template: "jinja2.Template", source_url: str | None,
                  release: str | None) -> RenderedPage | None:
    """Render one page; None when the module has no public member."""

def generate(cfg: TechwikiConfig, root: Path, *, release: str | None) -> tuple[list[RenderedPage], list[dict]]:
    """Return (pages, skipped) — skipped lists modules griffe could not parse."""

# parrot/sdd/scripts/techwiki_api.py
def main(argv: Sequence[str] | None = None) -> int:
    """`--out DIR --root PATH --release TAG --json --strict`; exit 0, 2 on usage/config error,
    3 when griffe is unavailable (message names the extra), 4 with `--strict` when any module
    was skipped (parse failure) — the sync workflow runs `--strict` so coverage never shrinks silently (S8)."""
```

Deterministic output: members sorted by source order within a class and alphabetically across
modules; stable anchors; a rerun on the same commit yields no diff (AC-4). The fixture package's
rendered output is frozen as golden files under `tests/sdd/fixtures/techwiki_golden/` and compared
byte-for-byte (S8); skipped modules are always printed on stderr and listed first in the report.

### Module 3: Bundle assembler, Home and Sidebar (`M3`) — depends on M1, M2

**Files**: CREATE `packages/ai-parrot/src/parrot/sdd/techwiki/bundle.py`,
`templates/home.md.j2`, `templates/sidebar.md.j2`,
`packages/ai-parrot/src/parrot/sdd/scripts/techwiki_bundle.py`,
`packages/ai-parrot/tests/sdd/test_techwiki_bundle.py`,
`packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/` (mini repo: `wiki/`, `_index.yaml`,
`docs/decisions/one.md`).

```python
# parrot/sdd/techwiki/bundle.py
@dataclass
class BundlePage:
    source: Path | None        # authored/ADR source, None for generated
    section: str
    title: str
    name: str                  # GitHub page name (naming.page_name)
    body: str

@dataclass
class BundleReport:
    release: str | None; commit: str | None
    authored: int; generated: int; adrs: int
    skipped_modules: list[dict]; collisions: list[dict]; dangling: list[dict]
    def ok(self) -> bool: ...

def collect_authored(cfg: TechwikiConfig, root: Path) -> list[BundlePage]: ...
def collect_adrs(cfg: TechwikiConfig, root: Path) -> list[BundlePage]: ...
def assemble(cfg: TechwikiConfig, root: Path, *, release: str | None, commit: str | None,
             with_api: bool = True) -> tuple[list[BundlePage], BundleReport]:
    """Collect, name, rewrite links, detect collisions/dangling; never writes."""
def write_bundle(pages: list[BundlePage], report: BundleReport, cfg: TechwikiConfig, out: Path) -> None:
    """Flat directory: <name>.md per page + Home.md + _Sidebar.md + techwiki-report.json + techwiki-manifest.json.
    Every link is resolved through the manifest (source path or `ref:` module id → page name), never through
    a title string, so a page rename changes one manifest row (S9)."""

# parrot/sdd/scripts/techwiki_bundle.py
def main(argv: Sequence[str] | None = None) -> int:
    """`--out DIR --root PATH --release TAG --dry-run --json --sidebar-only`;
    exit 0 ok, 1 collisions/dangling (report still written), 2 usage/config, 3 griffe unavailable."""
```

### Module 4: Spec template Documentation chapter and authored-page template (`M4`)

**Files**: MODIFY `sdd/templates/spec.md`; CREATE `sdd/templates/techwiki-page.md`; MODIFY
`.claude/commands/sdd-spec.md`, `.agents/skills/sdd-spec/SKILL.md`,
`.agent/workflows/sdd-spec.md`; regenerate `packages/ai-parrot/src/parrot/sdd/_assets/`
(`scripts/sdd/check_asset_sync.py --write`); CREATE
`tests/sdd_scripts/test_feat801_doc_contract.py`.

- `sdd/templates/spec.md` frontmatter: a commented `# docs:` block after the `# e2e:` block
  (`policy: required | none`, `pages: []`, `api_modules: []`) with the same "absent = unset,
  invalid never coerced" wording as `e2e`.
- `## 10. Documentation` inserted before `## Revision History`: purpose of the chapter, the
  page list (one bullet per `wiki/<section>/<page>.md`, create vs update), API modules whose
  docstrings must be complete, and the rule "hotfix/brief: `policy: none`; feature: `required`".
- The template's generic §5 line `- [ ] Documentation updated in \`docs/\`` becomes
  `- [ ] Documentation pages declared in §10 exist under \`wiki/\` (\`parrot sdd techwiki check\`)` (S6).
  `sdd/templates/task.md` has no documentation wording to update (verified: no `docs/` mention).
- `sdd/templates/techwiki-page.md`: frontmatter (`title`, `summary`), sections *Purpose · Public
  API (links to `ref:` pages) · Configuration & parameters · Usage examples · Gotchas · Related*.
- `/sdd-spec` §5 scaffold hint "Documentation chapter (FEAT-801)" next to the E2E hint, in all
  three twins (the `.agent/workflows/` twin must stay byte-identical to the command modulo
  frontmatter — `tests/sdd_scripts/test_command_twin_parity.py`).

### Module 5: `techwiki check`, `/sdd-task` docs task, `/sdd-done` Step 4.6b (`M5`) — depends on M1

**Files**: CREATE `packages/ai-parrot/src/parrot/sdd/techwiki/check.py`,
`packages/ai-parrot/src/parrot/sdd/scripts/techwiki_check.py`,
`packages/ai-parrot/tests/sdd/test_techwiki_check.py`; MODIFY `.claude/commands/sdd-task.md`,
`.agents/skills/sdd-task/SKILL.md`, `.agent/workflows/sdd-task.md`,
`.claude/commands/sdd-done.md`, `.agents/skills/sdd-done/SKILL.md`,
`.agent/workflows/sdd-done.md`; regenerate `_assets/`; CREATE
`tests/sdd_scripts/test_techwiki_closeout_contract.py`.

```python
# parrot/sdd/techwiki/check.py
_VALID_POLICIES = ("required", "none")

@dataclass
class DocsDecision:
    policy: str                # required | none | unset | invalid
    status: str                # ok | warning | skipped | invalid
    present: list[str]; missing: list[str]; reason_codes: list[str]

def resolve_docs_policy(spec_path: Path) -> tuple[str, list[str]]:
    """Return (policy, pages). Absent `docs` key -> ("unset", []); malformed -> ("invalid", [])
    (mirrors check_e2e_closeout.resolve_policy: split on '---', yaml.safe_load, never coerced)."""

def evaluate_docs(policy: str, pages: list[str], api_modules: list[str], root: Path) -> DocsDecision:
    """`none` -> skipped; `unset` -> skipped (docs_unset); `required` with every page present and
    non-trivial -> ok; `required` with missing pages -> warning (docs_required_missing_pages);
    a present page that is empty or has no `title`/H1 -> warning (docs_page_empty / docs_page_no_title);
    an `api_modules` entry that is not a dotted identifier -> warning (docs_api_module_syntax);
    `invalid` -> invalid. Pages must stay inside root (no '..', no absolute paths) -> invalid
    (docs_page_outside_root). (S6: the contract is stronger than path existence.)"""

# parrot/sdd/scripts/techwiki_check.py
def main(argv: Sequence[str] | None = None) -> int:
    """`--spec PATH --root PATH --json`; prints the DocsDecision JSON; exit 0 for ok/warning/skipped,
    2 for invalid or usage error. By construction there is no blocking exit code."""
```

`/sdd-done` handling of the exit code (S5): `0` → record the `Docs:` line from the JSON; `2` →
record `Docs: invalid — <reason_codes>` (malformed `docs:` block or usage error) and continue;
any other failure (command missing, traceback) → record `Docs: check failed (exit N) — see output`
and continue. Unlike Step 4.6, **no exit code of `techwiki check` aborts closeout**; the step text
says so verbatim and `test_techwiki_closeout_contract` asserts the words "never aborts" are present.

Command changes:
- `/sdd-task` §3: "**Documentation task (FEAT-801).** When the spec's `docs.policy` is
  `required`, emit exactly one task *Documentation — <pages>* that creates/updates the listed
  `wiki/` pages from `sdd/templates/techwiki-page.md`, `depends_on` every task that creates a
  symbol the pages document (last in the graph), validation command
  `parrot sdd techwiki check --spec <spec> --root .`, `parallel: true`. `none`/absent: no task."
- `/sdd-done` new `### 4.6b. Documentation Check (FEAT-801)` between 4.6 and 4.7: run
  `DOCS_JSON=$(parrot sdd techwiki check --spec "<spec-path>" --root "$WORKTREE_PATH")`, record
  `Docs: <policy> — <status>[ (missing: ...)]`, carry it into Step 5's report, the PR body
  Evidence section and Step 12's output. "Never blocks; `--force` has nothing to bypass."
  The codex twin gets the equivalent numbered step between its 4.6 and 4.7 items.

### Module 6: `techwiki.yml` sync workflow (`M6`) — depends on M3

**Files**: CREATE `.github/workflows/techwiki.yml`; CREATE
`tests/sdd_scripts/test_techwiki_workflow_contract.py` (YAML-level assertions: trigger,
permissions, concurrency, steps order, preview path on non-main).

```yaml
name: techwiki
on:
  release: { types: [published] }          # S3: the release boundary, same family of event as release.yml
  pull_request: { paths: ['wiki/**', 'docs/decisions/**', 'packages/*/src/**', 'sdd/config.json', '.github/workflows/techwiki.yml'] }
  workflow_dispatch: { inputs: { ref: { description: 'tag or branch to bundle (preview only unless a published release tag)', required: false } } }
permissions: { contents: write }
concurrency: { group: techwiki-${{ github.event_name }}-${{ github.ref }}, cancel-in-progress: false }
jobs:
  bundle:   # checkout (ref = release tag | PR head | dispatch input; fetch-depth 0, tags) → setup uv + python 3.12
            # → uv sync --package ai-parrot --extra techwiki
            # → parrot sdd techwiki bundle --out build/techwiki --release "${TAG:-$(git describe --tags --always)}" --json --strict
            #   (on pull_request: --dry-run, report only)
            # → upload-artifact build/techwiki (always)
  publish:  # needs bundle; if: github.event_name == 'release'
            # git clone https://x-access-token:${GITHUB_TOKEN}@github.com/${{ github.repository }}.wiki.git
            # rsync -a --delete --exclude .git build/techwiki/ wiki-repo/ → commit "techwiki: sync <tag> (<short-sha>)" (skip when clean) → push
```

The `pull_request` job is read-only validation (S11): it fails the PR when the bundle reports
collisions, dangling links or skipped modules. An optional `pre_pr` closeout hook
(`sdd_hooks.example.toml` gains a commented `techwiki-bundle` command example) offers the same
check locally; it is advisory and off by default.

### Module 7: Migration of technical docs into `wiki/` (`M7`) — depends on M3, M4

**Files**: CREATE `wiki/_index.yaml`, `wiki/<section>/*.md` (moved with `git mv`, translated to
English when needed, links rewritten); MODIFY `mkdocs.yml` (nav), `docs/index.md` (moved-page
notice), `CLAUDE.md`/`.agent/CONTEXT.md` only where they link a moved page; CREATE
`sdd/state/FEAT-801/migration-map.md` (the executed file → page mapping).

Classification rule (the task writes the mapping from it; the spec does not list 200 files):
- **Stays on Pages**: `docs/index.md`, `INSTALL.md`, `config.md`, `tools_quick.md`,
  `STYLE_GUIDE.md`, `chapters/**`, `guides/**`, `examples/**`, `branding/**`, `postman/**`,
  `aws/**`, `superpowers/**`, `docs/decisions/**` (ADRs, included by the bundle),
  `docs/sdd/WORKFLOW.md` and every file `@`-included by `CLAUDE.md`, roadmap/brainstorm pages.
- **Moves to `wiki/`**: every other page reachable from the mkdocs nav sections Foundations,
  LLM Clients, Bots & Agents, Memory & Knowledge, Knowledge Graph, Tools/Loaders & RAG,
  Integrations & Transport, Prompts, Orchestration & Flows, Advanced (APIs, outputs, security,
  operations, migration guides), plus `docs/sdd/**` (except WORKFLOW.md), `docs/wiki/**`,
  `docs/migration/**`, `docs/dev_loop/**` and the top-level technical pages not in the nav.
- Sections in `_index.yaml`: Architecture · Clients · Bots & Agents · Memory · Knowledge ·
  Tools & Toolkits · Flows · Skills · Stores & Loaders · MCP & A2A · Server & APIs ·
  Integrations · Outputs & A2UI · Prompts · Security · Operations · Migration · SDD Tooling ·
  LLM Wiki · Decisions · API Reference (last two are bundle-generated).
- `mkdocs build --strict` must pass after the move (AC-10); moved pages get no redirects, only a
  "Technical reference moved to the Wiki" notice on `docs/index.md`.

### Module 8: Backfill subsystem pages (`M8`) — depends on M4 (template), M7 (sections)

**Files**: CREATE `wiki/bots/agents-and-chatbots.md`, `wiki/clients/abstract-client.md`,
`wiki/tools/tools-and-toolkits.md`, `wiki/memory/conversation-memory.md`,
`wiki/flows/agentcrew-and-agentsflow.md`, `wiki/skills/skills.md`,
`wiki/stores/vector-stores-and-embeddings.md`, `wiki/stores/loaders.md`,
`wiki/mcp/mcp-server-and-client.md`, `wiki/server/handlers-and-manager.md` (ten pages, each from
`sdd/templates/techwiki-page.md`, each linking its `ref:` pages, written from the code and
existing specs; a page that already exists after M7 is extended, not duplicated).

### Module 9: Pages cut-over (`M9`) — depends on M6 having published a release green (human-observed)

**Files**: MODIFY `mkdocs.yml` (remove `mkdocstrings` plugin block and the `API Reference` nav
block), `requirements-docs.txt` (drop `mkdocstrings[python]`), `docs/index.md` ("Browse the
API" button → wiki URL; Contributing paragraph), the six chapter pages that link into
`api-reference/` (`docs/chapters/{foundations,llm-clients,bots-agents,memory-knowledge,tools-rag,integrations}.md`,
11 inbound links in total, verified by grep — rewritten to the wiki's `Reference-…` pages, S10),
`.github/workflows/docs.yml` (`paths:` loses `packages/ai-parrot/src/parrot/**` and the
editable-install step); DELETE `docs/api-reference/`. `mkdocs build --strict` turns
`validation: warn` into errors, so a missed inbound link fails the task. Old Pages URLs under
`api-reference/` break; this is accepted as a versioned change unless §8 Q-redirects decides
otherwise. The task's Completion Note must cite the green `techwiki` **release** run URL before it
is closed.

### Delegation-eligible modules

| Module | Eligible | Why / decided contracts |
|---|---|---|
| M1 | yes | models and verbs fully specified; naming rules fixed (U+2010 rule, `<Section>-<Title>`) |
| M2 | partial | rendering layout decided (one page per module, parameter tables); griffe edge cases (overloads, properties, Pydantic fields) are `FILL IN` bounded by AC-4 determinism |
| M3 | yes | collisions/dangling → exit 1 with report; Home/Sidebar from `_index.yaml` |
| M4 | yes | text edits with fixed wording; twins + `_assets --write` |
| M5 | yes | decision table fixed in §3; command text fixed |
| M6 | yes | workflow shape fixed above |
| M7 | no (judgement: classification + translation) | rule fixed; mapping is the task's artifact |
| M8 | no (content) | template fixed; content needs the thinking model |
| M9 | yes | mechanical edits, gated on a human-observed precondition |

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_techwiki_config_defaults_and_forbid_extra` | M1 | `load_techwiki_config` defaults; unknown key rejected; `SddConfig.techwiki` round-trips `sdd/config.json` |
| `test_page_name_rules` | M1 | spaces → `-`, section prefix, literal hyphen → `PageNameError`, empty title → error |
| `test_rewrite_links_relative_and_ref` | M1 | relative `.md` and `ref:` links → `[[Name]]`; unknown → collected as dangling |
| `test_generate_static_no_import` | M2 | fixture package renders without being importable (sys.modules untouched) |
| `test_generate_is_deterministic` | M2 | two runs → identical bytes |
| `test_public_filter` | M2 | `_private`, `__all__` honoured |
| `test_griffe_unavailable_exit_3` | M2 | monkeypatched import failure → exit 3 with the extra named |
| `test_generate_matches_golden` | M2 | fixture package output == `fixtures/techwiki_golden/**` byte-for-byte (S8) |
| `test_rendering_rules` | M2 | `__all__`, re-export alias, overload collapse, property, Pydantic field, nested class rows |
| `test_strict_fails_on_skipped_module` | M2 | a fixture module with a syntax error → listed in report; `--strict` exit 4 |
| `test_bundle_manifest_resolves_links` | M3 | every rewritten link's target exists in `techwiki-manifest.json` (S9) |
| `test_check_content_rules` | M5 | empty page / no title / bad `api_modules` entry → warning codes (S6) |
| `test_check_repo_relative_only` | M5 | `check` touches only `--root`-relative paths and runs with griffe absent (S12) |
| `test_bundle_collision_and_dangling_exit_1` | M3 | report lists both; exit 1; files still written |
| `test_bundle_home_sidebar_from_index` | M3 | sections in `_index.yaml` order; ADR section present; release/commit on Home |
| `test_bundle_dry_run_writes_nothing` | M3 | only the report |
| `test_resolve_docs_policy_table` | M5 | unset/none/required/invalid incl. non-dict `docs`, page outside root |
| `test_check_never_blocking` | M5 | every policy/status → exit 0 or 2; no `allowed=False` path; `main` has no `--force` |

### Integration Tests
| Test | Description |
|---|---|
| `test_feat801_doc_contract` (`tests/sdd_scripts/`) | `sdd/templates/spec.md` has `# docs:` block and `## 10. Documentation`; `sdd/templates/techwiki-page.md` exists with the six sections; all three `sdd-spec` twins mention the chapter |
| `test_techwiki_closeout_contract` (`tests/sdd_scripts/`) | both `/sdd-done` twins call `parrot sdd techwiki check`; `### 4.6b` sits between 4.6 and 4.7 in the command; codex twin step order; the word "never blocks" present; all three `sdd-task` twins carry the documentation-task rule |
| `test_techwiki_workflow_contract` (`tests/sdd_scripts/`) | `techwiki.yml` parses; `on.release.types == [published]`; `on.pull_request` present; `permissions.contents == write`; `publish` job has `if: github.event_name == 'release'`; bundle step uses `--extra techwiki` and `--strict`; PR path uses `--dry-run` |
| `test_check_asset_sync --check` (existing CI step) | `_assets/` regenerated for every changed command/template |
| `test_command_twin_parity` (existing) | `.agent/workflows/sdd-spec.md` / `sdd-task.md` stay byte-identical to the commands modulo frontmatter |
| `test_cli_techwiki_mounted` (`packages/ai-parrot/tests/sdd/`) | `parrot sdd techwiki --help` lists api/bundle/check/sidebar via `mounted_modules()` |

### Validation Contract

tests:
- packages/ai-parrot/tests/sdd/test_techwiki_config.py
- packages/ai-parrot/tests/sdd/test_techwiki_naming.py
- packages/ai-parrot/tests/sdd/test_techwiki_api.py
- packages/ai-parrot/tests/sdd/test_techwiki_bundle.py
- packages/ai-parrot/tests/sdd/test_techwiki_check.py
- packages/ai-parrot/tests/sdd/test_config.py
- tests/sdd_scripts/test_feat801_doc_contract.py
- tests/sdd_scripts/test_techwiki_closeout_contract.py
- tests/sdd_scripts/test_techwiki_workflow_contract.py
- tests/sdd_scripts/test_check_asset_sync.py
- tests/sdd_scripts/test_command_twin_parity.py
- tests/sdd_scripts/test_sdd_done_hooks_contract.py
- tests/sdd_scripts/test_e2e_closeout_contract.py
markers: none

### Test Data / Fixtures
```python
# packages/ai-parrot/tests/sdd/fixtures/techwiki_pkg/samplepkg/__init__.py  — "Sample package." ; __all__ = ["Widget", "make"]
# packages/ai-parrot/tests/sdd/fixtures/techwiki_pkg/samplepkg/core.py     — class Widget (Google docstring, 2 methods,
#   one `_private`), def make(size: int, *, name: str | None = None) -> Widget, def _helper()
# packages/ai-parrot/tests/sdd/fixtures/techwiki_repo/  — sdd/config.json with techwiki pointing at the fixture package,
#   wiki/_index.yaml (2 sections), wiki/a/one.md (ref: link + relative link), wiki/b/two.md (dangling link),
#   wiki/b/two-copy.md (collision with a generated name), docs/decisions/one.md (Context/Decision/Consequences)

@pytest.fixture
def techwiki_repo(tmp_path: Path) -> Path:
    """Copy the fixture repo into tmp_path and `git init` it (bundle reads the commit sha)."""
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] AC-1 `parrot sdd techwiki --help` lists `api`, `bundle`, `check`, `sidebar`; `mounted_modules()` includes the three new script modules.
- [ ] AC-2 `parrot sdd techwiki api` renders the public API of every distribution listed in `sdd/config.json` without importing any of them (test asserts `sys.modules` unchanged for the fixture package).
- [ ] AC-3 Without griffe installed, `api`/`bundle` exit 3 with a message naming `ai-parrot[techwiki]`; `check` and `sidebar` work without griffe and in a foreign repository that has only `sdd/config.json` (S12).
- [ ] AC-3b The `techwiki` extra declares `griffe` and `jinja2` itself; `uv sync --package ai-parrot --extra techwiki` in a clean environment makes `parrot sdd techwiki api` run (S7).
- [ ] AC-4 Two consecutive `techwiki api` runs on the same commit produce byte-identical output.
- [ ] AC-5 `techwiki bundle` rejects a title with a literal hyphen (`PageNameError`), reports page-name collisions and dangling links with both source paths, exits 1, and still writes `techwiki-report.json`.
- [ ] AC-6 The bundle contains `Home.md` (release, commit, link to the informative site), `_Sidebar.md` (sections in `_index.yaml` order, then Decisions, then API Reference per distribution), every ADR from `docs/decisions/**` read-only, and every authored page.
- [ ] AC-7 `techwiki check` implements the §3 M5 table (including the content rules `docs_page_empty`, `docs_page_no_title`, `docs_api_module_syntax`); it has no blocking exit code and no `--force` argument (test inspects `argparse` and `main`); both `/sdd-done` twins state that no exit code of the check aborts closeout.
- [ ] AC-7b `techwiki api --strict` exits 4 when any module is skipped; the bundle report and manifest list skipped modules first; the fixture package matches its golden output.
- [ ] AC-8 `sdd/templates/spec.md` carries the commented `# docs:` block and `## 10. Documentation`; `sdd/templates/techwiki-page.md` exists; all three `sdd-spec`, `sdd-task` and `sdd-done` twins carry their FEAT-801 text; `scripts/sdd/check_asset_sync.py --check` passes.
- [ ] AC-9 `/sdd-done` prints a `Docs:` line for every feature; a pre-existing spec without `docs:` reports `Docs: unset — skipped`.
- [ ] AC-10 After M7, `mkdocs build --strict` passes, the nav contains only informative entries, no moved page remains under `docs/`, and `wiki/_index.yaml` lists every section that has a page.
- [ ] AC-11 `wikitoolkit build` indexes `wiki/**/*.md` with no config change (`wikitoolkit query` finds a migrated page by title).
- [ ] AC-12 `.github/workflows/techwiki.yml` passes `test_techwiki_workflow_contract`; its first `release: published` run pushes a commit `techwiki: sync <tag> (<sha>)` to `ai-parrot.wiki.git` (human-observed, URL recorded in M9's Completion Note); a `pull_request` run is read-only and fails on collisions, dangling links or skipped modules.
- [ ] AC-13 M9 removes `mkdocstrings` from `mkdocs.yml` and `requirements-docs.txt`, deletes `docs/api-reference/`, rewrites the 11 inbound `api-reference/` links in `docs/index.md` and the six chapter pages, and `mkdocs build --strict` still passes.
- [ ] AC-14 No `requests`/`httpx`/LangChain imports; `ruff check` passes on every touched file; every new function has a Google docstring and type hints.
- [ ] AC-15 Every migrated page is in English (M7 Completion Note lists the translated files).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Verified against commit `d1b155ab1c` (dev, 2026-11-04).

### Verified Imports
```python
from parrot.sdd.cli import VERBS, _mount, mounted_modules          # verified: packages/ai-parrot/src/parrot/sdd/cli.py:237,316,311
from parrot.sdd.config import SddConfig, load_sdd_config, SddConfigError   # verified: packages/ai-parrot/src/parrot/sdd/config.py:19,106,15
from parrot.sdd.scripts.check_e2e_closeout import resolve_policy, main       # verified: .../scripts/check_e2e_closeout.py:53,201
from parrot.sdd.scripts.sdd_meta import parse, parse_taxonomy, resolve_flow  # verified: .../scripts/sdd_meta.py:15-31 (re-export)
from parrot.knowledge.wiki.ledger.sdd_meta import _read_frontmatter          # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:132
import jinja2   # 3.1.6 present in the workspace venv        # verified: python -c "import jinja2"
import yaml     # PyYAML 6.0.3                                 # verified: check_e2e_closeout.py:22
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/sdd/cli.py
VERBS: dict[str, dict[str, tuple[str, tuple[str, ...], str]]] = {...}   # line 237; nouns: worktree task ids spec brief docs tests closeout hooks
def _mount(noun: click.Group, verb: str, module: str, prefix: tuple[str, ...], help_: str) -> None:   # line 316
def mounted_modules() -> set[str]:                                        # line 311
# module bottom: `for _noun, _verbs in VERBS.items(): _group = sdd.group(name=_noun, ...)(lambda: None); ... _mount(...)`

# packages/ai-parrot/src/parrot/sdd/config.py
class SddConfig(BaseModel):                                   # line 19, model_config = ConfigDict(extra="forbid")
    base_branch: str = "dev"                                  # line 24
    projects: list[str] | None = None                         # line 35
def load_sdd_config(root: Path | None = None) -> SddConfig:   # line 106

# packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py
def resolve_policy(spec_path: Path) -> str:                   # line 53 — split('---', 2) + yaml.safe_load; absent → "optional"; malformed → "invalid"
@dataclass class GateDecision: allowed, policy, status, gate_satisfied, reason_codes   # line 43
def main(argv: Optional[Sequence[str]] = None) -> int:        # line 201 — argparse --spec --feat-id --worktree; prints JSON; 0/1

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
def _read_frontmatter(doc_path: Path) -> dict[str, Any] | None:   # line 132
def parse(doc_path: Path, *, config: SddConfig | None = None) -> FlowMeta:   # line 169
def resolve_flow(...)                                                        # line 314

# packages/ai-parrot/src/parrot/sdd/installer.py
def install_sdd_integration(root: Path, hosts: Sequence[str] = ("claude",), *, keep_edits: bool = False,
    dry_run: bool = False, portable: bool = False, base_branch: str | None = None, push_base: bool = False,
    hotfix_base: str | None = None, dangerous_guard: bool = True, sdd_coder: bool = True) -> list[str]:   # line 1064

# scripts/sdd/check_asset_sync.py
ASSET_SOURCES: tuple[tuple[str, tuple[str, ...]], ...]        # line 28 — includes ".claude/commands/sdd-*.md", ".agents/skills/sdd-*/SKILL.md",
                                                              #   ".agent/workflows/sdd-*.md", "sdd/templates/*" (new template file is covered)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `VERBS["techwiki"]` | mount loop | dict entry | `cli.py:237` / bottom loop |
| `SddConfig.techwiki` | `load_sdd_config` | new optional field | `config.py:35` |
| `resolve_docs_policy` | spec frontmatter | same parsing as `resolve_policy` | `check_e2e_closeout.py:53-92` |
| Step 4.6b | `/sdd-done` | between `### 4.6.` (line 237) and `### 4.7.` (line 290) | `.claude/commands/sdd-done.md` |
| codex twin step | `.agents/skills/sdd-done/SKILL.md` | between items `4.6.` (line 102) and `4.8.` (line 128) | verified |
| google twin | `.agent/workflows/sdd-done.md` | `### 4.6.` at line 176, `### 5.` at line 268 | verified |
| docs task rule | `/sdd-task` §3 | after "Aim for tasks completable in 1–4 hours each." | `.claude/commands/sdd-task.md:121`; codex twin item `5. Plan task decomposition:` (`.agents/skills/sdd-task/SKILL.md:69`); google twin `### 3.` (`.agent/workflows/sdd-task.md:113`) |
| chapter hint | `/sdd-spec` §5 | after the "E2E plan hint" paragraph | `.claude/commands/sdd-spec.md:566`; codex twin item `10. Write the spec:` (`.agents/skills/sdd-spec/SKILL.md:121`); google twin line 568 |
| package data | wheel | `"parrot.sdd"` list in `[tool.setuptools.package-data]` | `packages/ai-parrot/pyproject.toml:996` |
| optional extra | pip | `[project.optional-dependencies]` | `packages/ai-parrot/pyproject.toml:219` |
| Pages workflow | cut-over | `paths:` line 11, editable-install step | `.github/workflows/docs.yml` |

### Configuration References
- `sdd/config.json` — currently `base_branch`, `staging_branch`, `hotfix_base`, `issue_tracker`, `jira_host`, `reviewer`, `test_command`; `SddConfig` is `extra="forbid"`, so the `techwiki` field MUST be added to the model before the key is written.
- `.parrot/wiki.json` — `include_suffixes` includes `.md`; `decisions.adr_globs = ["docs/adr/**/*.md", "docs/adrs/**/*.md", "docs/decisions/**/*.md"]` (reason ADRs stay).
- `mkdocs.yml:54` `- mkdocstrings:` (handler paths `packages/ai-parrot/src`); `mkdocs.yml:299` `- API Reference:` nav block (10 entries); `requirements-docs.txt:3` `mkdocstrings[python]>=1.0.8`.
- GitHub: wiki enabled, repo public; `https://github.com/phenobarbital/ai-parrot.wiki.git` has `refs/heads/master`.
- PyPI 2026-11-04: `griffe 2.4.1` (`requires_python >= 3.11`).

### Does NOT Exist (Anti-Hallucination)
- ~~`wiki/`~~ at the repo root, ~~`wiki/_index.yaml`~~ — created by M7.
- ~~`.github/workflows/techwiki.yml`~~ — created by M6; no wiki-sync workflow exists.
- ~~`parrot.sdd.techwiki`~~ package, ~~`parrot/sdd/scripts/techwiki_*.py`~~, ~~`VERBS["techwiki"]`~~ — created by M1–M5.
- ~~`SddConfig.techwiki`~~ — not a field today (and `extra="forbid"` rejects the key until it is).
- ~~`griffe`~~ in any `pyproject.toml` or in the venv (`ModuleNotFoundError`); only reachable through `mkdocstrings[python]` in `requirements-docs.txt`.
- ~~`docs:` frontmatter key~~, ~~`## 10. Documentation`~~, ~~`sdd/templates/techwiki-page.md`~~ — not in the templates.
- ~~`parrot docs`~~ top-level group — the CLI has `parrot wiki` (wikitoolkit) and `parrot sdd docs` (frontmatter helpers: parse/taxonomy/resolve-flow/list/backfill/migrate-index) only.
- ~~`sdd/CONVENTIONS.md` § Project areas content~~ — empty placeholder; `projects:` vocabulary is observed usage.
- ~~`parrot.sdd.scripts.sdd_meta.read_frontmatter`~~ — the helper is private (`_read_frontmatter`) in `parrot.knowledge.wiki.ledger.sdd_meta`; M5 copies the parsing rule rather than importing a private name.

### Edit Sites (Blueprint Anchors)

Verified against: `d1b155ab1c`

| File | Action | Verbatim anchor line | Verified at | Occurrences |
|---|---|---|---|---|
| `packages/ai-parrot/src/parrot/sdd/cli.py` | MODIFY | `    "hooks": {` | `cli.py:302` | 1 |
| `packages/ai-parrot/src/parrot/sdd/config.py` | MODIFY | `    projects: list[str] \| None = None` | `config.py:35` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `wikitoolkit-server = ["ai-parrot-server"]` | `pyproject.toml:379` | 1 |
| `packages/ai-parrot/pyproject.toml` | MODIFY | `    "_assets/sdd/CODEX.md",` | `pyproject.toml:~1010` (inside `"parrot.sdd" = [`) | 1 |
| `sdd/config.json` | MODIFY | `  "test_command": null` | `sdd/config.json:8` | 1 |
| `sdd/templates/spec.md` | MODIFY | `#   scenario_ids: []` | `spec.md:23` | 1 |
| `sdd/templates/spec.md` | MODIFY | `## Revision History` | `spec.md:392` | 1 |
| `sdd/templates/techwiki-page.md` | CREATE | — | — | — |
| `.claude/commands/sdd-spec.md` | MODIFY | `**E2E plan hint (new section in spec, FEAT-581 — optional):**` | `sdd-spec.md:566` | 1 |
| `.agent/workflows/sdd-spec.md` | MODIFY | `**E2E plan hint (new section in spec, FEAT-581 — optional):**` | `sdd-spec.md:568` | 1 |
| `.agents/skills/sdd-spec/SKILL.md` | MODIFY | `10. Write the spec:` | `SKILL.md:121` | 1 |
| `.claude/commands/sdd-task.md` | MODIFY | `- Aim for tasks completable in 1–4 hours each.` | `sdd-task.md:121` | 1 |
| `.agent/workflows/sdd-task.md` | MODIFY | `- Aim for tasks completable in 1–4 hours each.` | `sdd-task.md:~117` | 1 |
| `.agents/skills/sdd-task/SKILL.md` | MODIFY | `5. Plan task decomposition:` | `SKILL.md:69` | 1 |
| `.claude/commands/sdd-done.md` | MODIFY | `### 4.7. Test Report (FEAT-695)` | `sdd-done.md:290` | 1 |
| `.agent/workflows/sdd-done.md` | MODIFY | `### 4.7. Test Report (FEAT-695)` | `sdd-done.md:~229` | 1 |
| `.agents/skills/sdd-done/SKILL.md` | MODIFY | `4.8. Closeout hooks — pre_pr (FEAT-764), after 4.7's test report and before step 6:` | `SKILL.md:128` | 1 |
| `.github/workflows/techwiki.yml` | CREATE | — | — | — |
| `mkdocs.yml` | MODIFY | `  - mkdocstrings:` | `mkdocs.yml:54` | 1 |
| `mkdocs.yml` | MODIFY | `  - API Reference:` | `mkdocs.yml:299` | 1 |
| `requirements-docs.txt` | MODIFY | `mkdocstrings[python]>=1.0.8` | `requirements-docs.txt:3` | 1 |
| `docs/index.md` | MODIFY | `[Browse the API →](api-reference/index.md){ .md-button }` | `docs/index.md:17` | 1 |
| `.github/workflows/docs.yml` | MODIFY | `      - 'packages/ai-parrot/src/parrot/**'` | `docs.yml:11` | 1 |
| `packages/ai-parrot/src/parrot/sdd/techwiki/*` | CREATE | — | — | — |
| `packages/ai-parrot/src/parrot/sdd/scripts/techwiki_{api,bundle,check}.py` | CREATE | — | — | — |
| `wiki/_index.yaml`, `wiki/**/*.md` | CREATE (M7 `git mv`, M8) | — | — | — |

Line numbers marked `~` were read from a nearby anchor; `/sdd-task` re-runs `grep -c` for every row.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror `check_e2e_closeout.py`: a pure decision function returning a dataclass, a `main()` that
  prints one JSON object, exit code as the contract, docstrings in Google style.
- Mount verbs through `VERBS` only; scripts expose `main(argv) -> int` like every
  `parrot.sdd.scripts` module (`_mount` calls `module.main([*prefix, *args])`).
- Pydantic v2 models with `extra="forbid"` for configuration; `self.logger`/module logger, never
  `print` outside CLI output.
- Jinja templates loaded via `importlib.resources` from `parrot.sdd.techwiki.templates`
  (package-data entry added in M1).
- Edit the SOURCE command files (`.claude/commands/`, `.agents/skills/`, `.agent/workflows/`),
  then `python scripts/sdd/check_asset_sync.py --write`; never edit `_assets/` by hand.
- Keep `.agent/workflows/sdd-spec.md` and `sdd-task.md` byte-identical to their commands modulo
  frontmatter (`test_command_twin_parity`).
- Tests next to the distribution (`packages/ai-parrot/tests/sdd/`) for Python modules; text
  contracts in `tests/sdd_scripts/`.

### Known Risks / Gotchas
- **GitHub page naming**: `-` in a page name is a space; a literal hyphen in a title becomes U+2010.
  `page_name` rejects hyphenated titles (AC-5). Section prefixes use the same rule.
- **`import parrot` side effects**: the CLI itself imports parrot (Navigator settings, observability
  boot). That is acceptable in CI (docs.yml already installs the core); the *generator* must stay
  static so the 30 distributions are never imported.
- **Python floor**: the brainstorm claimed a 3.10 floor from the stale `docs/STYLE_GUIDE.md`;
  `requires-python` is `>=3.11,<3.14` (`packages/ai-parrot/pyproject.toml:18`), so griffe 2.x
  fits without a marker (S7). `techwiki` stays an optional extra; `check`/`sidebar` import griffe
  lazily so a foreign repo without the extra still gets the documentation check.
- **Cython modules** (`.pyx`): griffe reads `.pyi` stubs when present, otherwise the module is
  skipped and listed in the report; not an error.
- **Page-name collisions** between authored and generated pages (`Reference-…` prefix reserved for
  generated pages; authored sections may not be named `Reference`).
- **`SddConfig` is `extra="forbid"`**: writing `techwiki` into `sdd/config.json` before M1 lands
  breaks every `parrot sdd` command in the repo. M1 adds the field and the key in one task.
- **Concurrent pushes to main**: concurrency group serialises; last run wins.
- **Pre-existing specs** have no `docs:` key → `Docs: unset — skipped`, never a warning.
- **Migration link rot**: moved pages lose their Pages URLs; `mkdocs build --strict` plus the
  bundle's dangling-link check are the two safety nets; `docs/index.md` carries the notice.
- **Translation drift**: Spanish pages (e.g. `docs/wiki/cheatsheet.md`, `guia-fireflies.md` if it
  moves) are translated at migration; the Completion Note lists them (AC-15).
- **`GITHUB_TOKEN` push to the wiki repo** requires `permissions: contents: write`; if the push is
  refused, the artifact is still uploaded and the job fails loudly.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `griffe` | `>=2.4,<3`, optional extra `techwiki` | static API loader + Google docstring parser |
| `jinja2` | `>=3.1`, declared in the `techwiki` extra (present in the venv as 3.1.6 via the `agents` extra) | page templates |
| `pyyaml` | present (6.0.3) | frontmatter / `_index.yaml` |
| GitHub Actions: `actions/checkout@v6`, `astral-sh/setup-uv`, `actions/upload-artifact@v4` | current | sync workflow |

---

## Decisions

```yaml
schema_version: 1
document_id: github-wiki-technical-reference
entries:
  - id: techwiki-generator-is-static
    statement: The technical-wiki API reference is generated by static analysis (griffe) and never by importing the documented packages.
    relation: forbids
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/cli.py]
    contradicts: []
    supersedes: []
    rationale: Importing parrot boots Navigator settings and observability and would require every optional dependency in CI; static loading needs only the source trees.
    rejected_alternatives: [pdoc with markdown templates, pydoc-markdown]
  - id: techwiki-source-of-truth-is-monorepo
    statement: The GitHub Wiki is a publish target regenerated from `wiki/` plus generated pages on every published release; it is never edited in place and reflects released code only.
    relation: constrains
    about: [sdd-tooling]
    targets: [file:.github/workflows/release.yml]
    contradicts: []
    supersedes: []
    rationale: One source of truth per topic; releases from dev lag for QA, and a hotfix merge to main ahead of its tag must not publish unreleased code either (design research S3).
    rejected_alternatives: [sync on every push to main, sync from dev, allow web edits with reverse sync]
  - id: docs-check-never-blocks
    statement: "`parrot sdd techwiki check` reports a feature's declared documentation pages as a warning and has no blocking exit code; hotfix and brief lanes are exempt."
    relation: constrains
    about: [sdd-tooling]
    targets: [file:packages/ai-parrot/src/parrot/sdd/scripts/check_e2e_closeout.py]
    contradicts: []
    supersedes: []
    rationale: The user chose warning-only so documentation discipline stays with the reviewer and in-flight features are never blocked.
    rejected_alternatives: [blocking gate with grandfathering, blocking always]
  - id: adrs-stay-in-docs-decisions
    statement: ADRs remain under `docs/decisions/**` (wikitoolkit `adr_globs`) and the wiki bundle includes them read-only; they are never moved into `wiki/`.
    relation: constrains
    about: [sdd-tooling, knowledge-wiki]
    targets: [file:packages/ai-parrot/src/parrot/knowledge/wiki/decisions/ingest.py]
    contradicts: []
    supersedes: []
    rationale: The decision plane and the consequence gate glob that path; moving the files would silently empty the plane.
    rejected_alternatives: [move ADRs and change adr_globs]
```

## Decision Waivers

## Consequences

<!-- decision-audit: input_digest=sha256:e298362cba74b8b5f3f1fc93c6c3162940e1cb814d71cbc3af5d89e532b142eb evaluation_digest=sha256:45a9135245f5a89fc1774169e79f3158f5b64674b3a693ad9f7647602815ee16 rules_version=1 status=pass -->

Audit status: `pass` (exit 0)

Findings:
- none

Diagnostics:
- none

Coverage:
- Subsystems: bots, clients, config, flows, knowledge-graphindex, knowledge-wiki, memory, sdd-tooling, skills, tools
- Unmapped tags: api-reference, docs, github-wiki, griffe, mkdocs, sdd-flow
- Targets resolved: 4/4
- Impact complete: true
- Inventory complete: true
- Omitted ids: not recorded

```json
{
  "coverage": {
    "impact_complete": true,
    "inventory_complete": true,
    "omitted_ids": [],
    "subsystems": [
      "bots",
      "clients",
      "config",
      "flows",
      "knowledge-graphindex",
      "knowledge-wiki",
      "memory",
      "sdd-tooling",
      "skills",
      "tools"
    ],
    "targets_resolved": 4,
    "targets_total": 4,
    "unmapped_tags": [
      "api-reference",
      "docs",
      "github-wiki",
      "griffe",
      "mkdocs",
      "sdd-flow"
    ]
  },
  "diagnostics": [],
  "evaluation_digest": "sha256:45a9135245f5a89fc1774169e79f3158f5b64674b3a693ad9f7647602815ee16",
  "exit_code": 0,
  "findings": [],
  "input_digest": "sha256:e298362cba74b8b5f3f1fc93c6c3162940e1cb814d71cbc3af5d89e532b142eb",
  "snapshot": {
    "approvals_digest": "6e5b5a5fb07d04ec7e7cdbf3afac1a634711ea195aa4061a8261bcf61b19992f",
    "config_digest": "sha256:a6bce9c0800713c30eaa78146ad0c06399f6ec0e9b083129e494abb6fd073343",
    "inventory": {},
    "rules_version": 1,
    "structural_revision": "sha256:ea0905fc396676a0daf141371346859e57a41268e7c10a099fb5df5d97ad7ab3",
    "taxonomy_digest": "9887c26aa37a5daa626531f2ef465c9f7ef63adf1a9d890eb248ea33c0053dbd"
  },
  "status": "pass"
}
```

## 8. Open Questions

- [x] CLI noun — *Resolved (clarification, 2026-11-04)*: `parrot sdd techwiki`.
- [x] ADRs location — *Resolved*: stay in `docs/decisions/`; bundle includes them read-only.
- [x] `docs/sdd/**` and `docs/wiki/**` — *Resolved*: move to the wiki ("SDD Tooling", "LLM Wiki" sections); `docs/sdd/WORKFLOW.md` and `@`-included files stay.
- [x] `docs/migration/**` — *Resolved*: move to the wiki ("Migration" section).
- [x] Wiki reflects which branch — *Resolved in brainstorm*: `main` only.
- [x] Organisation of authored pages — *Resolved in brainstorm*: by subsystem.
- [x] Generated pages committed? — *Resolved in brainstorm*: CI only.
- [x] Language — *Resolved in brainstorm*: English.
- [x] Backfill — *Resolved in brainstorm*: main subsystems (M8 list).
- [x] Gate strictness — *Resolved in brainstorm*: warning only; hotfix/brief exempt.
- [ ] Chapter numbering: `## 10. Documentation` appended after §9 (my call) to avoid renumbering §8/§9 cited by number in commands and tests. Accept or renumber in a follow-up? — *Owner: Jesus*
- [ ] Release label on `Home.md`: `git describe --tags --always` plus the `ai-parrot` version from `pyproject.toml` (proposed: both). — *Owner: Claude (M3)*
- [ ] Preview from `dev`: artifact-only on `workflow_dispatch` (proposed). — *Owner: Jesus*
- [ ] Q-redirects (S10, escalated): old Pages URLs under `docs/api-reference/` and the moved
  technical pages break at cut-over. Accept as a versioned change (proposed, no redirect stubs) or
  generate `meta refresh` stubs for the ten `api-reference/*.md` URLs? — *Owner: Jesus*
- [ ] Trigger changed from "push to main" (brainstorm) to "release published" after design research
  S3 (a hotfix merge ahead of its tag would otherwise publish unreleased code). Confirm. — *Owner: Jesus*
- [ ] Follow-up feature: multi-language reference (Svelte admin UI, TS client) via the wikitoolkit symbol plane. — *Owner: Jesus*

---

## 9. Design Research Cross-Check

> Independent design opinion from the `codex` seat over the **accepted exploration
> doc** (never over this spec). Model: `gpt-5.6-luna` (codex-cli 0.166.0, reasoning high) ·
> Status: completed (2026-11-04 21:29–21:33 UTC, exit 0, 12 suggestions, schema-valid) ·
> Transcript: `sdd/state/FEAT-801/design_research/`
> Every `affected_paths` entry was containment-checked and `test -e`'d: all 26 distinct paths exist.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Model techwiki in the typed SDD configuration (architecture) | CONFIRM | `SddConfig` is `extra="forbid"`; the field and the key land in the same task | §3 M1, §7 gotcha |
| S2 | Do not route docs metadata through FlowMeta (api) | CONFIRM | dedicated `resolve_docs_policy` mirrors `resolve_policy`; never imports a private name | §3 M5, §6 Does NOT Exist |
| S3 | Publish from the release boundary, not every main push (risk) | CONFIRM | `release.yml` fires on `release: created`; a hotfix merge ahead of its tag would publish unreleased code | §2 Overview, §3 M6, Decisions, §8 (confirm) |
| S4 | Source triggers must cover the whole workspace (architecture) | CONFIRM | subsumed by S3 (release event has no path filter); PR job paths cover `packages/*/src/**` | §3 M6 |
| S5 | Specify non-blocking closeout handling explicitly (risk) | CONFIRM | exit 2 and unexpected failures are recorded as `Docs:` lines; "never aborts" is asserted by test | §3 M5, AC-7 |
| S6 | Documentation contract stronger than path existence (testing) | CONFIRM | content rules (empty, no title, `api_modules` syntax) → warning codes; template AC line updated | §2 Data Models, §3 M4/M5, AC-7 |
| S7 | Make the techwiki extra self-contained (risk) | CONFIRM | `requires-python` is `>=3.11,<3.14`, the 3.10 claim was stale; jinja2 lives only in the `agents` extra | §2 interfaces, §3 M1, §7, AC-3b |
| S8 | Freeze the generated API surface with golden fixtures (testing) | CONFIRM | rendering rules fixed; golden test; `--strict` exit 4 on skipped modules | §3 M2, §4, AC-7b |
| S9 | Stable page identifiers instead of title-derived links (architecture) | CONFIRM (partial) | links already resolve by source path / `ref:` module id; a manifest makes that explicit. REJECT a separate ID layer: GitHub needs the title-derived file name anyway, and the U+2010 rule is enforced, not assumed | §2 Data Models, §3 M3, §4 |
| S10 | Plan migration compatibility and link verification (risk) | CONFIRM + ESCALATE | 11 inbound `api-reference/` links verified by grep (index + 6 chapters) → rewritten in M9 under `mkdocs build --strict`; redirect stubs vs accepted breakage escalated | §3 M9, AC-13, §8 Q-redirects |
| S11 | Run bundle validation before merge (testing) | CONFIRM | `pull_request` dry-run job + optional advisory `pre_pr` hook; SDD presence check stays warning-only | §2 Overview, §3 M6, AC-12 |
| S12 | Foreign-repository and asset-sync coverage (testing) | CONFIRM | `check` must run without griffe and only on repo-relative paths; asset sync already gated | AC-3, AC-8, §4 `test_check_repo_relative_only` |

Summary: **12** confirmed (2 partial) · **0** rejected outright · **1** escalated (S10 redirects).

---

## Worktree Strategy

- **Isolation**: one feature worktree `feat-FEAT-801-github-wiki-technical-reference`; the
  `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph** (evidence):
  - M2 → M1 (imports `TechwikiConfig`, `page_name`); M3 → M1, M2 (imports `generate`,
    `rewrite_links`); M5 → M1 (imports `load_techwiki_config`, mounts verb); M6 → M3 (runs
    `bundle`); M7 → M3 (link format), M4 (page template); M8 → M4, M7 (sections exist);
    M9 → M6 (green run on `main`, human-observed; recorded in the Completion Note).
  - M4 has no code dependency and can run concurrently with M1–M3; M5's command edits can run
    concurrently with M2/M3.
- **Shared files** (serialise their tasks): `packages/ai-parrot/pyproject.toml` (M1 only),
  `packages/ai-parrot/src/parrot/sdd/cli.py` (M1 only), `mkdocs.yml` and `docs/index.md`
  (M7 then M9), `_assets/manifest.json` (M4 and M5 both regenerate it → M5's command task
  depends on M4's task), the three `sdd-spec`/`sdd-task`/`sdd-done` twin sets (M4 touches
  sdd-spec; M5 touches sdd-task and sdd-done — disjoint files).
- **Exclusive resources** (`parallel: false`): M1 (edits `pyproject.toml`), M7 (mass `git mv`
  across `docs/` + `mkdocs.yml`), M9 (`requirements-docs.txt`, `mkdocs.yml`, workflow).
- **Cross-feature dependencies**: none to merge first. Check in-flight specs touching
  `.claude/commands/sdd-{spec,task,done}.md` or `sdd/templates/spec.md` at `/sdd-task` time
  (FEAT-799 touches the installer only).

---

## 10. Documentation

> Dogfooding the chapter this spec introduces. `docs.policy` is omitted from this spec's own
> frontmatter because the key does not exist until M4 lands; the pages below are produced by M7/M8
> and by a dedicated page for the pipeline itself.

- `wiki/sdd-tooling/techwiki-pipeline.md` — create: the `parrot sdd techwiki` verbs, `sdd/config.json`
  `techwiki` keys, page naming rules, the sync workflow, how a feature declares its pages.
- `wiki/sdd-tooling/spec-documentation-chapter.md` — create: the `docs:` frontmatter, the
  chapter, the derived task and the `/sdd-done` `Docs:` line.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-11-04 | Jesus Lara / Claude | Initial draft from the accepted brainstorm (Option B) and the clarification round |
