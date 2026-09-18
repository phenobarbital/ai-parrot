---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
projects: [sdd-tooling, ai-parrot]
tags: [sdd, templates, taxonomy, frontmatter]
---

# Feature Specification: SDD Document Taxonomy — `projects` and `tags` frontmatter

**Feature ID**: FEAT-576
**Date**: 2026-09-19
**Author**: Jesus Lara
**Status**: draft
**Target version**: next minor of `ai-parrot` (the parser lives in core)

---

## 1. Motivation & Business Requirements

### Problem Statement

SDD brainstorm, proposal and spec documents don't say **which project or part
of the codebase** they concern (e.g. `parrot-formdesigner`, core `ai-parrot`,
`ai-parrot-server`, the admin UI, the SDD tooling itself). They also carry no
**tags** to organize and categorize the growing set of specifications (several
hundred under `sdd/specs/` and `sdd/proposals/`). Today the only way to find
"every spec touching formdesigner" or "every memory/compaction spec" is to grep
bodies or rely on slug naming conventions. `/sdd-status`, `/sdd-next`, the wiki
ledger and `/sdd-tojira` have nothing to filter or label on.

### Goals
- G1. Each of the three templates (`sdd/templates/spec.md`, `brainstorm.md`,
  `proposal.md`) declares two new frontmatter keys: `projects` (list) and
  `tags` (list).
- G2. `projects` values come from a **known vocabulary**: the `packages/*`
  distribution directory names plus a small allowlist of non-package areas. An
  unknown value is **accepted with a logged warning** (same soft pattern as
  `KNOWN_BRANCHES`), never rejected. Common aliases (`parrot-core`,
  `formdesigner`) normalize to canonical names.
- G3. `tags` are free-form and normalized (lowercase kebab-case, deduplicated,
  order preserved).
- G4. A single parser (`parse_taxonomy`) reads both keys. Docs without them
  parse to empty lists, so every existing document keeps working unchanged.
- G5. Authoring commands (`/sdd-brainstorm`, `/sdd-proposal`, `/sdd-fromjira`,
  `/sdd-spec`, and the dev-loop `sdd-ideation` agent) fill both keys, and
  `/sdd-spec` **carries them forward** from the brainstorm/proposal.
- G6. `/sdd-status` and `/sdd-next` accept `--project <p>` / `--tag <t>` filters.
- G7. The wiki ledger ingest (`SDDGraphIngest`) surfaces projects/tags in the
  spec page summary, so `wikitoolkit query "<tag>"` finds specs by tag.
- G8. `/sdd-tojira` maps `projects ∪ tags` to Jira **labels**.
- G9. An **optional, dry-run-by-default** backfill script infers `projects` for
  existing docs from the code paths they mention. It changes files only with
  `--apply`.

### Non-Goals (explicitly out of scope)
- **Caching projects/tags in the per-spec task index header** (`sdd/tasks/index/*.json`).
  The user decided against it. Filters resolve taxonomy from the spec file
  through the index header's existing `spec` path (see §8).
- Validating or rejecting unknown `projects` (strict vocabulary was not chosen).
- Inferring **tags** automatically during backfill. Tag inference is guesswork,
  so the script only infers `projects`.
- Committing a backfill of all existing documents inside this feature. The
  script ships, and running it is a separate, reviewed operator action.
- Changing `FlowMeta` or the `parse()` contract (see §7).
- Jira component mapping. Components stay `Nav-AI`.

---

## 2. Architectural Design

### Overview

A small taxonomy layer sits next to the existing flow-metadata parser in
`parrot.knowledge.wiki.ledger.sdd_meta`. It lives there because the wiki CLI
must import it outside the repo (see the shim docstring in
`scripts/sdd/sdd_meta.py:1-8`). It adds:

- `KNOWN_PROJECTS: frozenset[str]`: canonical project names.
- `PROJECT_ALIASES: dict[str, str]`: alias → canonical (e.g. `parrot-core` →
  `ai-parrot`, `formdesigner` → `parrot-formdesigner`).
- `DocTaxonomy(BaseModel)`: `projects: list[str]`, `tags: list[str]`, with
  `field_validator`s that coerce a bare scalar to a one-item list, normalize,
  deduplicate, and warn on unknown projects.
- `parse_taxonomy(doc_path) -> DocTaxonomy`: the same forgiving frontmatter
  read as `parse()`. No frontmatter, no keys, or a non-dict block gives an
  empty taxonomy.

`FlowMeta` and `parse()` are **not** modified. `FlowMeta` already ignores unknown
keys (Pydantic default `extra="ignore"`, `sdd_meta.py:42-46`), so adding
`projects`/`tags` to frontmatter cannot break `parse()`, `resolve_flow()`,
`ensure_worktree` or `/sdd-task`.

The canonical frontmatter shape, the same in all three templates:

```yaml
---
type: feature
base_branch: dev
# projects: parts of the codebase this doc concerns. Use `packages/*` dir names
#   (ai-parrot, ai-parrot-server, parrot-formdesigner, …) or an area
#   (sdd-tooling, dev-loop, admin-ui, docs, ci). Unknown values warn, not fail.
projects: []
# tags: free-form kebab-case keywords for organizing specs (e.g. memory, mcp).
tags: []
---
```

On top of the parser:

1. **Authoring commands** fill the keys. If the author gives no projects,
   the command infers a proposal from the Code Context / Localization paths and
   states it. It never leaves `projects: []` silently when code paths are known.
2. **`/sdd-spec` carry-forward**: a new row in the §2a mapping table routes
   brainstorm/proposal `projects`/`tags` to the spec frontmatter. Explicit
   answers in the current run win over the carried values; otherwise the
   carried values are copied as-is and extended only when §4 codebase research
   finds another touched distribution.
3. **`scripts/sdd/doc_taxonomy.py`** CLI: lists docs matching
   `--project`/`--tag` filters (AND across flags, OR within a repeated flag), or
   prints a vocabulary summary. `/sdd-status` and `/sdd-next` call it to get the
   set of matching spec paths, then keep only indexes whose header `spec` is in
   that set.
4. **Wiki ingest** puts `projects: …; tags: …` into the spec page summary.
5. **`/sdd-tojira`** sends `labels = projects ∪ tags`.
6. **`scripts/sdd/backfill_taxonomy.py`** runs as a dry run by default and
   prints `<path>: projects += [...]`. With `--apply` it inserts or extends
   frontmatter keys **by text insertion** (never a YAML re-dump, which would
   drop comments), and it never overwrites existing non-empty `projects`/`tags`.

### Component Diagram
```
sdd/templates/{spec,brainstorm,proposal}.md ── frontmatter: projects, tags
            │
authoring commands (/sdd-brainstorm, /sdd-proposal, /sdd-fromjira,
            │        sdd-ideation agent, /sdd-spec carry-forward)
            ▼
   sdd/specs/*.spec.md, sdd/proposals/*.md
            │
            ▼
parrot.knowledge.wiki.ledger.sdd_meta
   ├─ FlowMeta / parse()           (unchanged)
   └─ DocTaxonomy / parse_taxonomy()  ◄── NEW (KNOWN_PROJECTS, PROJECT_ALIASES)
            │
   ┌────────┼──────────────────┬───────────────────────────┐
   ▼        ▼                  ▼                           ▼
doc_taxonomy CLI      SDDGraphIngest summary     /sdd-tojira labels
   │
   ▼
/sdd-status --project/--tag, /sdd-next --project/--tag

backfill_taxonomy.py ──(dry-run | --apply)──► existing docs' frontmatter
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `parrot.knowledge.wiki.ledger.sdd_meta` | extends | new model, constants and function beside `FlowMeta`/`parse` |
| `scripts/sdd/sdd_meta.py` (shim) | modifies | re-export the new names |
| `SDDGraphIngest._process_spec_file` | modifies | summary string gains taxonomy |
| `sdd/templates/{spec,brainstorm,proposal}.md` | modifies | frontmatter keys + comments |
| `.claude/commands/sdd-{spec,brainstorm,proposal,fromjira,status,next,tojira}.md` + `.agent/workflows/` + `.agents/skills/` twins | modifies | fill / carry / filter / label steps |
| `.claude/agents/sdd-ideation.md` + `parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` | modifies | fill keys when writing a brainstorm/proposal |
| `sdd/WORKFLOW.md` | modifies | new "Document Taxonomy" section |

### Data Models
```python
class DocTaxonomy(BaseModel):
    projects: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
```

### New Public Interfaces
```python
KNOWN_PROJECTS: frozenset[str]
PROJECT_ALIASES: dict[str, str]
def parse_taxonomy(doc_path: Path) -> DocTaxonomy: ...
def normalize_tag(raw: str) -> str: ...
def normalize_project(raw: str) -> str: ...
```
CLIs: `python -m scripts.sdd.doc_taxonomy`, `python -m scripts.sdd.backfill_taxonomy`.

---

## 3. Module Breakdown

#### Delegation-eligible modules

| Module | Eligible? | Decided patterns / exact contracts | Why not (if no) |
|---|---|---|---|
| M1: taxonomy parser | yes | skeleton below; regex, alias map, warn-not-fail fixed | — |
| M2: templates | yes | exact YAML block in §2 Overview | — |
| M3: authoring commands + ideation agent | no | — | prose edits across 3 mirrors + packaged twin; carry-forward wording needs judgment |
| M4: `doc_taxonomy` CLI | yes | flags + exit codes below | — |
| M5: status/next filters | yes | calls M4 with `--kind spec --paths-only`, intersects on index `spec` | — |
| M6: wiki ingest summary | yes | exact summary format below | — |
| M7: `/sdd-tojira` labels | yes | `labels = projects ∪ tags` (sorted, deduped) | — |
| M8: backfill script | no | — | path→project inference heuristics and text-insertion edge cases need judgment |
| M9: docs | yes | new `sdd/WORKFLOW.md` section | — |

### Module 1: Taxonomy parser
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py` (+ re-export in `scripts/sdd/sdd_meta.py`)
- **Responsibility**: constants, normalization, `DocTaxonomy`, `parse_taxonomy`. Shares the frontmatter-splitting logic with `parse()` by extracting a private `_read_frontmatter(doc_path) -> dict` helper that both call. `parse()`'s behavior and return values stay unchanged.
- **Depends on**: existing `sdd_meta`
- **Interface Skeleton**:
  ```python
  # packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py  (modifies; FlowMeta at :42, parse at :55)
  #: Canonical `projects` values: every `packages/<dist>` directory name plus
  #: non-package areas. Soft vocabulary — unknown values warn, never fail.
  KNOWN_PROJECTS: frozenset[str] = frozenset({
      # packages/* (drift-guarded by a test that lists the directory)
      "ai-parrot", "ai-parrot-advisors", "ai-parrot-embeddings", "ai-parrot-integrations",
      "ai-parrot-loaders", "ai-parrot-pipelines", "ai-parrot-server", "ai-parrot-tools",
      "ai-parrot-visualizations", "ai-parrot-openlit-bridge", "parrot-formdesigner", "navrules",
      # every ai-parrot-client-* directory, listed explicitly
      # non-package areas
      "sdd-tooling", "dev-loop", "admin-ui", "docs", "ci",
  })

  #: alias -> canonical project name (applied after lowercasing).
  PROJECT_ALIASES: dict[str, str] = {
      "parrot-core": "ai-parrot", "core": "ai-parrot", "parrot": "ai-parrot",
      "formdesigner": "parrot-formdesigner", "server": "ai-parrot-server",
      "tools": "ai-parrot-tools", "parrot-tools": "ai-parrot-tools",
      "sdd": "sdd-tooling", "ui": "admin-ui",
  }

  _TAG_RE: re.Pattern[str]  # ^[a-z0-9][a-z0-9-]{0,39}$

  def normalize_tag(raw: str) -> str:
      """Lowercase, strip, map runs of whitespace/underscores to '-', collapse '--'.

      Raises:
          ValueError: when the normalized value does not match ``_TAG_RE``.
      """

  def normalize_project(raw: str) -> str:
      """Normalize like a tag, then apply ``PROJECT_ALIASES``.

      Logs ``logger.warning`` (never raises) when the result is not in
      ``KNOWN_PROJECTS``. Raises ValueError only on a malformed value (same
      regex as tags).
      """

  class DocTaxonomy(BaseModel):
      """Organizational metadata of an SDD doc: projects it concerns + tags."""

      projects: list[str] = Field(default_factory=list)
      tags: list[str] = Field(default_factory=list)

      # field_validator(mode="before") on both: None -> [], str -> [str],
      # then normalize each, dedupe preserving first occurrence.

  def _read_frontmatter(doc_path: Path) -> dict[str, Any]:
      """Return the leading YAML frontmatter as a dict ({} when absent/non-dict)."""

  def parse_taxonomy(doc_path: Path) -> DocTaxonomy:
      """Parse ``projects``/``tags`` from a brainstorm/proposal/spec frontmatter.

      Returns an empty ``DocTaxonomy`` when no frontmatter or no keys exist.

      Raises:
          pydantic.ValidationError: when a tag/project is malformed (e.g. ``tags: [Foo Bar!]``).
      """
  ```

### Module 2: Templates
- **Path**: `sdd/templates/spec.md`, `sdd/templates/brainstorm.md`, `sdd/templates/proposal.md`
- **Responsibility**: add the commented `projects: []` / `tags: []` keys shown in §2 Overview to each frontmatter block (in `proposal.md`, after `base_branch:`). No duplicate "**Projects**:" body lines: frontmatter is the single source.
- **Depends on**: none (M1 only for the tests that parse the templates)

### Module 3: Authoring commands + ideation agent
- **Paths** (each edit mirrored to all copies):
  - `.claude/commands/sdd-{brainstorm,proposal,fromjira,spec}.md`
  - `.agent/workflows/sdd-{brainstorm,proposal,fromjira,spec}.md`: **`sdd-spec` must stay byte-identical** to its `.claude` original except for the one documented substitution (`tests/sdd_scripts/test_command_twin_parity.py:20-33`)
  - `.agents/skills/sdd-{brainstorm,proposal,fromjira,spec}/SKILL.md`
  - `.claude/agents/sdd-ideation.md` and `packages/ai-parrot/src/parrot/flows/dev_flow/_subagent_data/sdd-ideation.md` (byte-parity: `packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py:260`)
- **Responsibility**:
  - brainstorm/proposal/fromjira/ideation: a step "Fill `projects` and `tags`". Derive `projects` from the Code Context / Localization paths (`packages/<dist>/…` → `<dist>`, `parrot_tools` → `ai-parrot-tools`, `ui/` under server → `admin-ui`, `scripts/sdd`/`.claude/commands` → `sdd-tooling`, `flows/dev_loop` → `dev-loop`). Propose 2–6 tags. State both in the output summary.
  - `/sdd-spec`: add a row to the §2a table: *Frontmatter `projects`/`tags` → spec frontmatter `projects`/`tags` (verbatim; extend `projects` only with distributions found in §4 research)*. Add an item to §5 "Scaffold the Spec" to fill both keys. In the §5 sanity check, confirm the carried values are present.
- **Depends on**: M1 (the vocabulary) and M2

### Module 4: `doc_taxonomy` CLI
- **Path**: `scripts/sdd/doc_taxonomy.py` (new)
- **Responsibility**: query docs by taxonomy for the commands.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # scripts/sdd/doc_taxonomy.py  (new)
  """List SDD docs by `projects`/`tags` frontmatter (FEAT-576)."""

  DocKind = Literal["spec", "brainstorm", "proposal", "all"]

  class TaxonomyRow(BaseModel):
      path: str            # repo-relative
      kind: DocKind
      projects: list[str]
      tags: list[str]

  def collect(root: Path, kind: DocKind = "all") -> list[TaxonomyRow]:
      """Scan sdd/specs/*.spec.md and sdd/proposals/*.{brainstorm,proposal}.md.

      A doc whose frontmatter fails validation is skipped with a logged
      warning (never aborts the scan).
      """

  def filter_rows(rows: list[TaxonomyRow], projects: list[str], tags: list[str]) -> list[TaxonomyRow]:
      """AND across the two flags, OR within each; filter values normalized
      with normalize_project/normalize_tag before matching."""

  def main(argv: list[str] | None = None) -> int:
      """CLI: --project P (repeatable) --tag T (repeatable) --kind K
      [--paths-only | --json | --summary]. --summary prints project and tag
      frequency tables. Exit 0 always on a successful scan (empty result is
      not an error); exit 2 on bad arguments."""
  ```

### Module 5: `/sdd-status` and `/sdd-next` filters
- **Paths**: `.claude/commands/sdd-{status,next}.md` + `.agent/workflows/` + `.agents/skills/` twins
- **Responsibility**: document `--project <p>` / `--tag <t>` (repeatable). When given, run
  `python -m scripts.sdd.doc_taxonomy --kind spec --paths-only --project … --tag …`
  and keep only indexes whose header `spec` is in the output. `_orphans.json` is
  always excluded under a taxonomy filter, since it has no spec. `/sdd-status`
  prints the spec's projects/tags on each feature panel header line.
- **Depends on**: M4

### Module 6: Wiki ingest summary
- **Path**: `packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py` (modifies `_process_spec_file`, `:111-150`)
- **Responsibility**: call `parse_taxonomy(spec_path)`. On a `ValidationError`, log a warning and use an empty taxonomy. The spec page must still be ingested. Summary format:
  `SDD specification for <slug> (type: <t>, base: <b>; projects: a, b; tags: x, y)`.
  The `; projects: …` and `; tags: …` segments are omitted when that list is empty, so existing summaries for untagged specs stay byte-identical.
- **Depends on**: M1

### Module 7: `/sdd-tojira` labels
- **Paths**: `.claude/commands/sdd-tojira.md` + twins
- **Responsibility**: add a row to the §2 extraction table (*Frontmatter `projects`/`tags` → Jira `labels`*), add `"labels": [...]` to both the MCP and curl create examples, and on update merge labels with the ticket's existing labels (never remove human-added labels).
- **Depends on**: M1

### Module 8: Backfill script
- **Path**: `scripts/sdd/backfill_taxonomy.py` (new)
- **Responsibility**: infer `projects` for docs that lack them.
- **Depends on**: M1
- **Interface Skeleton**:
  ```python
  # scripts/sdd/backfill_taxonomy.py  (new)
  """Infer `projects` frontmatter for existing SDD docs (FEAT-576). Dry-run by default."""

  def infer_projects(text: str) -> list[str]:
      """Map code paths mentioned in the doc to canonical projects.

      `packages/<dist>/` -> <dist>; `parrot_tools`/`parrot_loaders`/
      `parrot_pipelines` -> their dist; `packages/ai-parrot-server/ui/` ->
      admin-ui; `scripts/sdd/`, `.claude/commands/`, `sdd/templates/` ->
      sdd-tooling; `flows/dev_loop` -> dev-loop; bare `parrot/<x>` (no
      packages/ prefix) -> ai-parrot. Only values in KNOWN_PROJECTS; ordered by
      first mention.
      """

  def plan_edit(doc_path: Path) -> str | None:
      """Return the new file text, or None when no change is needed (projects
      already non-empty, or nothing inferred). Inserts `projects: [...]` (and
      `tags: []` if absent) as TEXT lines before the closing `---`; creates a
      `type: feature` / `base_branch: dev` block only when the doc has no
      frontmatter at all (equal to parse()'s defaults, so flow resolution is
      unchanged). Never rewrites any other byte."""

  def main(argv: list[str] | None = None) -> int:
      """--apply to write (default dry-run prints `<path>: projects = [...]`),
      --kind spec|brainstorm|proposal|all, --limit N. Never commits."""
  ```

### Module 9: Documentation
- **Path**: `sdd/WORKFLOW.md` (new section "Document Taxonomy (FEAT-576)" after "Flow Types"). It covers the keys, the vocabulary and aliases, the warn-not-fail rule, the filters, and the backfill command.
- **Depends on**: M1, M4, M8

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_parse_taxonomy_absent_returns_empty` | M1 | no frontmatter / no keys → `DocTaxonomy(projects=[], tags=[])` |
| `test_parse_taxonomy_scalar_coerced` | M1 | `tags: memory` → `["memory"]` |
| `test_normalize_tag` | M1 | `"Tool Output_Pruning"` → `"tool-output-pruning"`; `"!!"` raises |
| `test_project_alias` | M1 | `parrot-core` → `ai-parrot`, `formdesigner` → `parrot-formdesigner` |
| `test_unknown_project_warns_not_fails` | M1 | `caplog` has a warning, value kept |
| `test_dedupe_preserves_order` | M1 | `[b, a, b]` → `[b, a]` |
| `test_parse_unchanged_with_taxonomy_keys` | M1 | `parse()` on a doc with projects/tags still returns the same `FlowMeta` |
| `test_known_projects_covers_packages_dir` | M1 | every `packages/*/pyproject.toml` dir name ∈ `KNOWN_PROJECTS` |
| `test_templates_declare_taxonomy_keys` | M2 | each of the 3 templates parses to an empty taxonomy and has both keys in the frontmatter text |
| `test_filter_and_or_semantics` | M4 | AND across flags, OR within a flag |
| `test_collect_skips_invalid_doc` | M4 | a malformed tag logs a warning, other docs are still returned |
| `test_cli_paths_only` | M4 | `main([...,"--paths-only"])` prints repo-relative paths |
| `test_ingest_summary_with_taxonomy` | M6 | summary contains `; projects: a; tags: x` |
| `test_ingest_summary_untagged_unchanged` | M6 | byte-identical to today's format |
| `test_ingest_invalid_taxonomy_still_ingests` | M6 | page produced, warning logged |
| `test_infer_projects` | M8 | path-mapping table |
| `test_plan_edit_preserves_bytes` | M8 | only inserted lines differ; comments kept |
| `test_plan_edit_never_overwrites` | M8 | non-empty `projects` → `None` |
| `test_backfill_dry_run_writes_nothing` | M8 | mtime/content unchanged without `--apply` |

Existing suites that must stay green: `tests/sdd_scripts/` (notably
`test_sdd_meta.py`, `test_command_twin_parity.py`, `test_command_contracts.py`),
`tests/knowledge/wiki/test_ledger_sdd_ingest.py`, and the dev-flow subagent
parity test for `sdd-ideation` (`packages/ai-parrot/tests/flows/dev_flow/test_subagent_defs.py::test_prompt_parity_with_repo_twin`, line 260).

### Integration Tests
| Test | Description |
|---|---|
| `test_doc_taxonomy_on_repo` | `collect(repo_root)` over the real `sdd/` tree completes with no exception |

### Test Data / Fixtures
```python
@pytest.fixture
def tagged_spec(tmp_path: Path) -> Path:
    p = tmp_path / "x.spec.md"
    p.write_text("---\ntype: feature\nbase_branch: dev\nprojects: [parrot-core, formdesigner]\n"
                 "tags: [Memory, mcp, memory]\n---\n# X\n", encoding="utf-8")
    return p
```

---

## 5. Acceptance Criteria

- [ ] AC1: All three templates contain `projects: []` and `tags: []` in their frontmatter, with the explanatory comments.
- [ ] AC2: `parse_taxonomy()` returns empty lists for every existing doc that lacks the keys. `python -m scripts.sdd.doc_taxonomy --summary` runs clean over the real repo.
- [ ] AC3: An unknown project is **kept and warned**, never rejected. A malformed tag/project raises `ValidationError` from `parse_taxonomy` only; scanners (M4, M6) skip or degrade with a warning.
- [ ] AC4: `parse()` / `FlowMeta` behavior is unchanged (existing `test_sdd_meta.py` and `test_sdd_meta_resolve_flow.py` pass unmodified).
- [ ] AC5: `KNOWN_PROJECTS` ⊇ every `packages/*` directory that has a `pyproject.toml` (drift test).
- [ ] AC6: `/sdd-brainstorm`, `/sdd-proposal`, `/sdd-fromjira`, `/sdd-spec` and `sdd-ideation` instruct filling both keys, in **all** mirrors. `test_command_twin_parity.py` and the subagent parity test pass.
- [ ] AC7: `/sdd-spec` §2a mapping table has the `projects`/`tags` carry-forward row, and its §5 sanity check verifies it.
- [ ] AC8: `/sdd-status --project X` / `--tag Y` and the same flags on `/sdd-next` are documented and use `doc_taxonomy --paths-only`. No task-index schema change.
- [ ] AC9: The wiki spec page summary includes projects/tags when present and is byte-identical when absent.
- [ ] AC10: `/sdd-tojira` sends `labels` from `projects ∪ tags` and never removes existing ticket labels on update.
- [ ] AC11: `backfill_taxonomy` is a dry run by default, only changes files with `--apply`, never overwrites non-empty `projects`, preserves every other byte, and never commits.
- [ ] AC12: `sdd/WORKFLOW.md` documents the taxonomy.
- [ ] AC13: `ruff check` clean on new/changed Python. All listed tests pass (`pytest tests/sdd_scripts/ tests/knowledge/wiki/test_ledger_sdd_ingest.py -v`).

---

## 6. Codebase Contract

### Verified Imports
```python
from parrot.knowledge.wiki.ledger.sdd_meta import FlowMeta, parse, emit, resolve_flow, KNOWN_BRANCHES  # verified: packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py:30,42,55,88,105
from scripts.sdd.sdd_meta import FlowMeta, parse, KNOWN_BRANCHES  # verified: scripts/sdd/sdd_meta.py:10-20 (re-export shim)
from parrot.knowledge.wiki.ledger.sdd_meta import parse as parse_spec_meta  # verified: sdd_ingest.py:18
from parrot.knowledge.wiki.store import WikiPageRecord  # verified: sdd_ingest.py:19; class at store.py:409
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_meta.py
KNOWN_BRANCHES: frozenset[str] = frozenset({"main", "staging", "dev"})  # line 30 — soft-warning precedent
class FlowMeta(BaseModel):                                               # line 42 — no model_config ⇒ extra="ignore"
    type: Literal["feature", "hotfix"]                                   # line 45
    base_branch: str                                                     # line 46
def parse(doc_path: Path) -> FlowMeta:                                   # line 55 — text.split("---", 2); yaml.safe_load
def emit(meta: FlowMeta) -> str:                                         # line 88
def resolve_flow(kind=None, doc_path=None, type_override=None, base_branch_override=None)  # line 105

# packages/ai-parrot/src/parrot/knowledge/wiki/ledger/sdd_ingest.py
class SDDGraphIngest:                                                    # line 27
    def _process_spec_file(self, spec_path: Path) -> tuple[WikiPageRecord, list[tuple]] | None:  # line 111
        # summary=f"SDD specification for {spec_filename} (type: {meta.type}, base: {meta.base_branch})"  # line 134
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `parse_taxonomy` | frontmatter split | shared `_read_frontmatter` extracted from `parse()` | `sdd_meta.py:76-85` |
| taxonomy re-export | `scripts/sdd/sdd_meta.py` | import list | `scripts/sdd/sdd_meta.py:10-20` |
| ingest summary | `_process_spec_file` | `parse_taxonomy(spec_path)` | `sdd_ingest.py:124,134` |
| status/next filter | index header `spec` field | `jq` + `doc_taxonomy --paths-only` | `.claude/commands/sdd-status.md:25-35`, `.claude/commands/sdd-next.md:19-26` |
| tojira labels | create payloads | `labels` field | `.claude/commands/sdd-tojira.md:132-140,187-212` |
| twin parity | `.agent/workflows/sdd-spec.md` | byte-parity test | `tests/sdd_scripts/test_command_twin_parity.py:20-33` |

### Does NOT Exist (Anti-Hallucination)
- ~~`projects` / `tags` / `components` keys in any current template or spec frontmatter~~: none exist today (a grep of `sdd/specs`, `sdd/proposals` and `sdd/templates` finds none)
- ~~`FlowMeta.tags` / `FlowMeta.projects`~~: FlowMeta stays two-field
- ~~`KNOWN_PROJECTS`, `parse_taxonomy`, `DocTaxonomy`~~: created by M1
- ~~`scripts/sdd/doc_taxonomy.py`, `scripts/sdd/backfill_taxonomy.py`~~: created by M4/M8
- ~~`tags` in `sdd/tasks/index/*.json` headers~~: deliberately NOT added (Non-Goal)
- ~~a generator that syncs `.claude/commands` → `.agent/workflows` → `.agents/skills`~~: the mirrors are hand-maintained. `.agents/skills/*/SKILL.md` bodies differ substantially from `.claude/commands` (not byte twins), so edit each one by hand.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Follow the soft-vocabulary precedent `KNOWN_BRANCHES` (`sdd_meta.py:27-30`): warn, don't reject.
- Keep `parse()`'s forgiving semantics (BOM or leading text → no frontmatter).
- Pydantic v2 `field_validator(mode="before")` for coercion. Use `self.logger`/module `logger`, never `print` (the CLIs write their results to stdout via `sys.stdout.write`, which is output, not logging).
- Any file-scanning code in async paths (ingest) stays inside the existing `asyncio.to_thread` collection (`sdd_ingest.py:73`).

### Known Risks / Gotchas
- **Twin parity**: `.agent/workflows/sdd-spec.md` must be byte-identical to `.claude/commands/sdd-spec.md` except for one line. Apply every sdd-spec edit to both identically, or `test_command_twin_parity.py` fails.
- **Packaged subagent twin**: `sdd-ideation.md` exists in `.claude/agents/` and `parrot/flows/dev_flow/_subagent_data/`, under a parity test. Edit both.
- **YAML re-dump in backfill** would strip the comment lines the templates carry. Insert text instead.
- **Bare `parrot/` paths are ambiguous** (core vs. a PEP 420 satellite such as `parrot/stores/pgvector.py`). The backfill maps them to `ai-parrot`, which can under-attribute satellites. That's acceptable because the output is a dry-run proposal for human review.
- **`KNOWN_PROJECTS` drift** when a new `packages/*` dist is added: the drift test fails loudly, which is intended.
- **Tag sprawl** (`memory` vs `memories`): `doc_taxonomy --summary` makes near-duplicates visible. No synonym merging in v1.
- The frontmatter comment lines in the templates must survive `parse()` (YAML comments are fine).

### External Dependencies
None new. `pyyaml` and `pydantic` are already imported by `sdd_meta`.

---

## Worktree Strategy

- **Isolation**: ONE feature worktree `feat-FEAT-576-sdd-spec-changes` from `origin/dev`. The `sdd-coder` engine gives each task its own sub-worktree.
- **Module dependency graph**:
  - M4 → M1 (imports `parse_taxonomy`, `normalize_*`)
  - M6 → M1 (imports `parse_taxonomy`)
  - M8 → M1 (imports `KNOWN_PROJECTS`, `normalize_project`)
  - M5 → M4 (commands invoke the CLI)
  - M3 → M1 + M2 (prose cites the vocabulary and the template block)
  - M7 → M1 (vocabulary only; soft)
  - M9 → M1, M4, M8 (documents them)
  - M2 has no code dependency and can run concurrently with M1.
- **Shared files**: `.claude/commands/sdd-spec.md` + its `.agent/workflows` twin (only M3). The `.agents/skills/*` files are touched by M3, M5 and M7, but each module edits different command files, so there's no overlap. `sdd_meta.py` is M1 only.
- **Exclusive resources**: none (no lockfile, migration or extension rebuild).
- **Cross-feature dependencies**: none. FEAT-575/574 are in flight but don't touch these files.

---

## 8. Open Questions

- [x] How to reconcile diverged `dev` before scaffolding. *Resolved by the user*: rebase local onto origin (`git pull --rebase`).
- [x] Shape of the project field. *Resolved by the user*: a list (`projects`) with a known vocabulary (`packages/*` dirs + area allowlist). Unknown values warn and are accepted.
- [x] Which consumers read the fields. *Resolved by the user*: `/sdd-status` filtering, wiki ledger ingest, carry-forward rules (`/sdd-spec` + `/sdd-tojira` labels). **Not** task-index header caching, so filters read the spec through the index's `spec` path.
- [x] Existing documents. *Resolved by the user*: an optional dry-run-by-default backfill script; running it is not part of this feature.
- [ ] Is the area allowlist (`sdd-tooling`, `dev-loop`, `admin-ui`, `docs`, `ci`) the right set, or should it include others (e.g. `wikitoolkit`, `voice`, `querysource`)? — *Owner: Jesus Lara*
- [ ] Should `/sdd-tojira` prefix project labels (e.g. `project:ai-parrot`) to separate them from topic tags in Jira? The v1 default is no prefix. — *Owner: Jesus Lara*

---

## 9. Design Research Cross-Check

> Model: — · Status: skipped (no accepted exploration document; the spec was scaffolded directly from the user request) · Transcript: —

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|

Summary: **0** confirmed · **0** rejected · **0** escalated.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-09-19 | Jesus Lara (via Claude) | Initial draft |
