# TASK-3370: Five packaged templates + `requires_dist` header metadata

**Feature**: FEAT-570 — `parrot toolkits` on-demand local-MCP toolkit installation
**Spec**: `sdd/specs/expose-local-mcp-tools.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3369
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. This task ships the templates that make the feature visible:
the two database toolkits the owner asked for (`querysource`, `database-query`)
plus the three that stop being implicit when TASK-3368 deletes `BUILTIN_TOOLKITS`
(`scraping`, `browsing`, `memory`).

It also adds one new template header key, `# parrot:requires_dist:` — design
research **S6** (CONFIRM): a template installs fine while its distribution is
missing, and `QuerysourceToolkit` defers its ImportError all the way to `_open`.
`parrot toolkits list` must be able to say "installed but `querysource` is not
importable" *without importing the toolkit class*, which the existing header
metadata (`summary:`, `requires_llm:` only) cannot express.

**Credential posture (owner decision, spec §8):** templates ship `env: {}`. The
installer never prompts for, captures or writes a DSN. `ToolkitSection.env` values
are copied **verbatim** into the host config (`google/assets.py:99`) and
`.mcp.json` is git-tracked, so a secret placed there would be committed. The DSN
resolves from the environment the spawned `parrot mcp-local` process inherits.

---

## Scope

- Create five templates in `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/`.
- Extend the `# parrot:` header parser in `load_template` to read `requires_dist:`
  and add the field to `ToolkitTemplate`.
- Write tests that every packaged template parses, declares a resolvable
  `class:`, and carries an empty `env:`.

**NOT in scope**: the `dist_available()` probe that *consumes* `requires_dist`
(TASK-3375), the CLI (TASK-3376), any change to toolkit classes themselves.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/querysource.yaml` | CREATE | QuerysourceToolkit template |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/database-query.yaml` | CREATE | DatabaseQueryToolkit template |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/scraping.yaml` | CREATE | Migrated from `BUILTIN_TOOLKITS["scraping"]` |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/browsing.yaml` | CREATE | Migrated from `BUILTIN_TOOLKITS["browsing"]` |
| `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/memory.yaml` | CREATE | Migrated from `BUILTIN_TOOLKITS["memory"]` |
| `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` | MODIFY | `requires_dist` header key + `ToolkitTemplate` field |
| `tests/mcp/test_toolkit_templates.py` | CREATE | Every packaged template parses and is well-formed |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.mcp.toolkit_seed import ToolkitTemplate, available_templates, load_template  # verified: toolkit_seed.py:26,47,61
from parrot.mcp.toolkit_config import load_toolkits_config  # verified: toolkit_config.py:105
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/mcp/toolkit_seed.py
_META_PREFIX: str = "# parrot:"                 # line 20
REPO_ROOT_PLACEHOLDER: str = "{{repo_root}}"    # line 19
class ToolkitTemplate(BaseModel):               # line 26
    name: str
    body: str
    requires_llm: bool = False
    summary: str = ""
def load_template(name: str) -> ToolkitTemplate:  # line 61
    # lines 83-89: the header loop — currently recognises ONLY:
    #   meta_content.startswith("summary:")       -> summary = meta_content[8:].strip()
    #   meta_content.startswith("requires_llm:")  -> requires_llm = (... == "true")

# packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py
class QuerysourceToolkit(AbstractToolkit):                      # line 56
    tool_prefix = "qs"                                          # line 59
    confirming_tools = frozenset({"save_multiquery"})           # line 61
    auto_open = True                                            # line 62
    def __init__(self, programs=None, allow_write=False, allow_raw_sql=False,
                 allow_external_sources=True, include_sql=True, max_rows=200,
                 forced_conditions=None, dsn=None, multiquery_timeout=600.0, **kwargs)  # line 64

# packages/ai-parrot-tools/src/parrot_tools/querysource/_qs.py
def default_dsn() -> str: ...   # line 63 — returns querysource.conf.asyncpg_url (env-driven)

# packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py
class DatabaseQueryToolkit(AbstractToolkit):     # line 115
    tool_prefix = "dq"                           # line 147
    def __init__(self, **kwargs) -> None:        # line 154
        # ONLY `output_dir` and `static_dir` are popped (lines 166-167); everything
        # else forwards to AbstractToolkit. save_result is excluded unless
        # output_dir is set (lines 174-176).

# Existing template format (the pattern to copy):
# packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml
#   # parrot:summary: <one line>
#   # parrot:requires_llm: false
#     bounded-source:
#       class: parrot_tools.tool_optimizations.reader.BoundedSourceToolkit
#       kwargs:
#         repo_root: {{repo_root}}
```

### Does NOT Exist
- ~~`DatabaseQueryToolkit(allow_write=…)`~~ / ~~`(allow_raw_sql=…)`~~ / ~~`(dsn=…)`~~
  / ~~`(credentials=…)`~~ — **none are constructor parameters.** Only `output_dir`
  and `static_dir`. Its DDL/DML guard is unconditional and `credentials` is a
  per-CALL tool argument.
- ~~`DatabaseQueryToolkit.validate_database_query()`~~ — does not exist; the method
  is `validate_query` (`toolkit.py:265`) ⇒ tool `dq_validate_query`. Two suites in
  `packages/ai-parrot/tests/tools/databasequery/` assert the wrong name; they are a
  pre-existing defect (spec §7) — **do not "fix" this template to match them.**
- ~~`QuerysourceToolkit.allow_ddl`~~ — not a parameter.
- ~~`ToolkitSection.requires_dist`~~ — `requires_dist` is **template header
  metadata**, not a config-section field. Do not add it to `ToolkitSection`.
- ~~`# parrot:requires_db:`~~ / ~~`# parrot:extras:`~~ — invented names; the key
  this task adds is exactly `requires_dist:`.
- ~~`${VAR}` interpolation in `env:`~~ — parrot performs no expansion; values are
  copied verbatim.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/querysource.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/database-query.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/scraping.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/browsing.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/mcp/_toolkit_templates/memory.yaml", "action": "CREATE"},
    {"path": "packages/ai-parrot/src/parrot/mcp/toolkit_seed.py", "action": "MODIFY"},
    {"path": "tests/mcp/test_toolkit_templates.py", "action": "CREATE"}
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#ToolkitTemplate",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#load_template",
    "sym:packages/ai-parrot/src/parrot/mcp/toolkit_seed.py#available_templates",
    "sym:packages/ai-parrot-tools/src/parrot_tools/querysource/toolkit.py#QuerysourceToolkit",
    "sym:packages/ai-parrot/src/parrot/tools/databasequery/toolkit.py#DatabaseQueryToolkit"
  ]
}
```

---

## Implementation Notes

### Key Constraints
- Section bodies are indented **two spaces** (they are spliced under a
  `toolkits:` root key), exactly like `bounded-source.yaml`.
- Header lines must precede the body with no blank line between them — the parser
  stops at the first line that does not start with `# parrot:`.
- `requires_dist` is a **comma-separated** list; an empty value means "core only".
- Every template ships `env: {}` — this is a hard acceptance criterion (AC6), not
  a stylistic choice.

### References in Codebase
- `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/bounded-source.yaml` — minimal example
- `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/sdd-coder.yaml` — heavily commented example

---

## Implementation Blueprint

### Steps (in order)
1. Add `requires_dist` to `ToolkitTemplate` and the header loop — *why*: the
   templates written in step 2 declare it, so the parser must accept it first or
   every template test fails.
2. Write the two database templates — *why*: they are the feature's headline and
   their comments are the only place the credential posture is explained to the
   operator.
3. Write the three migrated templates, copying kwargs verbatim from the deleted
   `BUILTIN_TOOLKITS` — *why*: any drift here silently changes behavior for every
   repo that reinstalls them after the hard cut.
4. Write the template test module — *why*: five hand-written YAML files need a
   machine check that they all parse and none leaks an `env:` value.

### `packages/ai-parrot/src/parrot/mcp/toolkit_seed.py` (MODIFY)
```python
# occurrences: 1 (verified: grep -cF '    requires_llm: bool = False' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# AFTER — insert below `    requires_llm: bool = False` (verified: toolkit_seed.py:31)
    requires_dist: tuple[str, ...] = ()

# occurrences: 1 (verified: grep -cF '        elif meta_content.startswith("requires_llm:"):' packages/ai-parrot/src/parrot/mcp/toolkit_seed.py)
# AFTER — insert a sibling branch below the `requires_llm:` branch
# (verified: toolkit_seed.py:87-89), inside the same header loop:
        elif meta_content.startswith("requires_dist:"):
            raw = meta_content[len("requires_dist:"):].strip()
            requires_dist = tuple(part.strip() for part in raw.split(",") if part.strip())

# Initialise `requires_dist: tuple[str, ...] = ()` beside the existing
# `summary = ""` / `requires_llm = False` locals (verified: toolkit_seed.py:79-81),
# and pass it to the ToolkitTemplate(...) constructor at the end of load_template.
```
**Why**: the parser is a simple prefix match over `# parrot:` lines, so a new key
is one `elif` plus one local. Declaring the field as a `tuple` (not `list`) keeps
`ToolkitTemplate` hashable-ish and matches how TASK-3375's `dist_available()`
consumes it. Do not rename the key or change the comma separator — TASK-3375 and
the template files both depend on this exact spelling.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/querysource.yaml` (CREATE)
```yaml
# parrot:summary: Tenant-scoped QuerySource query-slugs and MultiQuery pipelines.
# parrot:requires_llm: false
# parrot:requires_dist: parrot_tools,querysource
  querysource:
    class: parrot_tools.querysource.toolkit.QuerysourceToolkit
    # CREDENTIALS ARE NEVER WRITTEN HERE. The DSN resolves from the environment
    # this MCP server inherits, via querysource.conf.asyncpg_url. Set `dsn:` only
    # to override it, and never commit a secret — `env:` values below are copied
    # verbatim into .mcp.json / config.toml, which are tracked by git.
    kwargs:
      allow_write: true       # exposes qs_save_multiquery (requires confirmation)
      allow_raw_sql: true
      # programs: [<tenant-slug>, ...]   # omit for unrestricted tenant access
      # max_rows: 200
      # multiquery_timeout: 600.0
    env: {}
```
**Why this shape**: `allow_write` and `allow_raw_sql` are `true` per the owner's
"permissive, operator narrows it" decision (spec §8) — `qs_save_multiquery` is in
`confirming_tools` (`toolkit.py:61`) so it still gets an injected `confirm` flag,
and the host's own permission prompt is the human gate. `programs` and `max_rows`
stay commented because their defaults are correct for a first install. The
credential comment is load-bearing: it is the only place an operator is told why
there is no `dsn:` line.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/database-query.yaml` (CREATE)
```yaml
# parrot:summary: Multi-driver schema discovery and validated read-only queries.
# parrot:requires_llm: false
# parrot:requires_dist:
  database-query:
    class: parrot.tools.databasequery.toolkit.DatabaseQueryToolkit
    # This toolkit has NO allow_write / allow_raw_sql / dsn options — its
    # constructor accepts only output_dir and static_dir, its DDL/DML guard is
    # unconditional, and connection credentials are a per-call tool argument.
    # Setting output_dir below is what exposes dq_save_result.
    kwargs:
      output_dir: {{repo_root}}/.parrot/db_results
    env: {}
```
**Why this shape**: `requires_dist:` is deliberately **empty** — this toolkit
lives in core (`parrot.tools.databasequery`), so it is always importable. The
comment exists because "permissive defaults" is not expressible here, and without
it an implementer will try to add `allow_write: true` and get a
`TypeError`/silent kwarg passthrough. `output_dir` under `{{repo_root}}/.parrot/`
keeps results inside the already-gitignored directory.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/scraping.yaml` (CREATE)
```yaml
# parrot:summary: Structured web scraping and crawling with plan caching.
# parrot:requires_llm: false
# parrot:requires_dist: parrot_tools
  scraping:
    class: parrot_tools.scraping.toolkit.WebScrapingToolkit
    kwargs:
      headless: true
      plans_dir: .parrot/scraping_plans
    env: {}
```
**Why**: `class` and `kwargs` are copied **verbatim** from the deleted
`BUILTIN_TOOLKITS["scraping"]` (`toolkit_config.py:91-93`) so a repo reinstalling
after the hard cut gets byte-identical behavior. Do not "improve" the kwargs here.

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/browsing.yaml` (CREATE)
```yaml
# parrot:summary: Deterministic site automation with recorded actions and profiles.
# parrot:requires_llm: false
# parrot:requires_dist: parrot_tools
  browsing:
    class: parrot_tools.browsing.toolkit.WebBrowsingToolkit
    kwargs:
      catalog_dir: .parrot/browsing_catalog
      headless: true
    env: {}
```
**Why**: verbatim from `BUILTIN_TOOLKITS["browsing"]` (`toolkit_config.py:95-97`).

### `packages/ai-parrot/src/parrot/mcp/_toolkit_templates/memory.yaml` (CREATE)
```yaml
# parrot:summary: DataFrame/result scratchpad for parking large intermediate results.
# parrot:requires_llm: false
# parrot:requires_dist:
  memory:
    class: parrot.tools.working_memory.tool.WorkingMemoryToolkit
    kwargs: {}
    env: {}
```
**Why**: verbatim from `BUILTIN_TOOLKITS["memory"]` (`toolkit_config.py:99-101`).
`requires_dist:` is empty — `WorkingMemoryToolkit` is core.

### `tests/mcp/test_toolkit_templates.py` (CREATE)
```python
"""Every packaged toolkit template is well-formed (FEAT-570, TASK-3370)."""
from __future__ import annotations

import importlib
import pytest
import yaml

from parrot.mcp.toolkit_seed import available_templates, load_template  # verified: toolkit_seed.py:47,61

EXPECTED = {"bounded-source", "targeted-writer", "sdd-coder",
            "querysource", "database-query", "scraping", "browsing", "memory"}


def test_all_expected_templates_ship():
    assert EXPECTED <= set(available_templates())


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_template_parses_and_declares_class(name):
    """Body splices under `toolkits:` and names an importable dotted path."""
    tpl = load_template(name)
    parsed = yaml.safe_load("toolkits:\n" + tpl.body.replace("{{repo_root}}", "/tmp/x"))
    section = parsed["toolkits"][name]
    assert section["class"].count(".") >= 2
    # FILL IN: assert the module half of `class` is importable ONLY when
    # tpl.requires_dist is empty — a template for an optional distribution must
    # not fail this suite on a bare install; bounded by AC3.


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_template_ships_no_secret(name):
    """AC6: no template carries a populated env: block."""
    tpl = load_template(name)
    parsed = yaml.safe_load("toolkits:\n" + tpl.body.replace("{{repo_root}}", "/tmp/x"))
    assert parsed["toolkits"][name].get("env", {}) == {}
```
**Why**: parametrizing over `EXPECTED` rather than `available_templates()` means
a template that fails to ship at all is caught, not silently skipped. The
`requires_dist` guard in the import check is what keeps this suite green on a
bare `ai-parrot` install where `parrot_tools` and `querysource` are absent.

### FILL IN checklist
- [ ] `toolkit_seed.py::load_template` — initialise the `requires_dist` local and pass it to `ToolkitTemplate`; bounded by AC3
- [ ] `test_toolkit_templates.py::test_template_parses_and_declares_class` — conditional importability assertion; bounded by AC3

---

## Acceptance Criteria

- [ ] `available_templates()` returns all eight names (three existing + five new)
- [ ] Every template parses when spliced under a `toolkits:` root key
- [ ] `load_template("querysource").requires_dist == ("parrot_tools", "querysource")`
- [ ] `load_template("memory").requires_dist == ()`
- [ ] Every packaged template has `env: {}` (AC6)
- [ ] `scraping` / `browsing` / `memory` `class` + `kwargs` match the deleted
      `BUILTIN_TOOLKITS` entries byte-for-byte in meaning
- [ ] `database-query` template contains no `allow_write` / `allow_raw_sql` / `dsn` key
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/mcp/toolkit_seed.py`

---

## Validation Commands

- `pytest tests/mcp/test_toolkit_templates.py -q`
- `pytest tests/mcp/test_toolkit_seed.py -q`

---

## Test Specification

See the CREATE block above — `tests/mcp/test_toolkit_templates.py` is the full
scaffold. Add a case asserting `requires_dist` parses as a tuple for a
multi-value header, and one asserting an absent `requires_dist:` header yields `()`.

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (§3 Module 5, §8 credential and safety decisions).
2. **Check dependencies** — TASK-3369 must be in `sdd/tasks/completed/`.
3. **Verify the Codebase Contract** — re-read `QuerysourceToolkit.__init__`
   (`querysource/toolkit.py:64`) and `DatabaseQueryToolkit.__init__`
   (`databasequery/toolkit.py:154`) before writing kwargs into a template.
4. **Update status** in `sdd/tasks/index/expose-local-mcp-tools.json` → `"in-progress"`.
5. **Implement** from the Implementation Blueprint; complete every `# FILL IN:`.
6. **Verify** all acceptance criteria.
7. **Move this file** to `sdd/tasks/completed/TASK-3370-toolkit-templates.md`.
8. **Update index** → `"done"`.
9. **Fill in the Completion Note** below.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
