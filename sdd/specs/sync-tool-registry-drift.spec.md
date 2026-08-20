---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Sync `TOOL_REGISTRY` / `LOADER_REGISTRY` Drift Revealed by the AnnAssign Fix

**Feature ID**: FEAT-436
**Date**: 2026-08-20
**Author**: Jesus (filed as a follow-up from FEAT-427's Completion Note)
**Status**: approved
**Target version**: n/a (internal dev tooling / package metadata)

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-427 (`TASK-2245`, merged to `dev` in `d279f72c4`) fixed
`scripts/generate_tool_registry.py` to recognize `ast.AnnAssign`-style
registry declarations (`TOOL_REGISTRY: dict[str, str] = {...}`). Before
that fix, `read_existing_registry()` always returned `{}`, so `--check`
could never see real drift — it just unconditionally reported the entire
registry as stale.

Now that the parser reads existing entries correctly, running
`python scripts/generate_tool_registry.py --check` against current `dev`
(verified 2026-08-20, HEAD `0dfa99db9`) exits `1` and reports **real,
pre-existing drift** that had been silently accumulating because the
write mode had the same bug (it also always treated the file as `{}` and
therefore never actually wrote a change) — see FEAT-427 §7 Known Risks.

This spec's job is to **make `--check` exit `0` again** by closing that
drift — but by hand-curating the two `__init__.py` files, not by running
the generator's plain write mode unmodified (see §2 for why).

### Verified Evidence (2026-08-20, `dev` HEAD `0dfa99db9`)

```
$ python scripts/generate_tool_registry.py --check
Would update TOOL_REGISTRY (92 changes):
  + abstract_document: parrot_tools.document.AbstractDocumentTool
  ... (91 more/changed lines, see §6 Appendix A for the full list)
Would update LOADER_REGISTRY (1 changes):
  + WebScrapingLoader: parrot_loaders.webscraping.WebScrapingLoader

Registries are STALE. Run: python scripts/generate_tool_registry.py
```

Cross-referencing the 92 `TOOL_REGISTRY` "changes" against the **values**
already present in the current registry (not just keys) splits them into
three distinct categories — this distinction is the crux of the spec and
was not visible before this analysis:

1. **49 genuinely unregistered classes** — the dotted import path does
   not appear anywhere in the current `TOOL_REGISTRY.values()`. These are
   real tools/toolkits added to the source tree without ever being wired
   into the registry. **In scope: add these.**
2. **42 "alias duplicates"** — the scanned class **is already registered**
   under a different, hand-chosen key (e.g. existing key `"bestbuy"` →
   `parrot_tools.retail.bby.BestBuyToolkit`, while the generator's naming
   convention independently derives `"best_buy"` for the exact same
   class). Blindly adding these would create a second registry key
   pointing at an already-registered class — not closing drift, just
   adding ambiguous duplicate aliases. **Out of scope for this task** —
   see §1 Non-Goals and §8 Open Questions.
3. **1 renamed value, same key** — `"odoo"` currently points to
   `parrot_tools.odoo.OdooToolkit` (a re-export); the scanner finds the
   class's actual defining module, `parrot_tools.odoo.toolkit.OdooToolkit`.
   Both import paths currently resolve (verified:
   `from parrot_tools.odoo import OdooToolkit` and
   `from parrot_tools.odoo.toolkit import OdooToolkit` both succeed), so
   this is a safe, no-behavior-change canonicalization. **In scope: apply
   this rename.**

`LOADER_REGISTRY`'s one change (`WebScrapingLoader`) is category 1 (a
genuinely unregistered, real loader at
`packages/ai-parrot-loaders/src/parrot_loaders/webscraping.py`, verified
importable). **In scope: add it.**

### Goals
- `packages/ai-parrot-tools/src/parrot_tools/__init__.py`'s
  `TOOL_REGISTRY` gains the 49 genuinely-missing entries (§6 Appendix A,
  "TRUE NEW" list) and the `"odoo"` value is corrected in place.
- `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py`'s
  `LOADER_REGISTRY` gains the 1 genuinely-missing `WebScrapingLoader`
  entry.
- Both files' existing hand-authored structure — section comments
  (e.g. `# --- Toolkits (Batch 1 — simple tools) ---`,
  `# --- Web ---`) and entry ordering — is preserved exactly for every
  pre-existing line; new entries are appended under a new, clearly
  labeled trailing comment section, not interleaved in a way that
  reorders or re-groups existing entries.
- After this change, `python scripts/generate_tool_registry.py --check`
  reports **only** the 42 known alias-duplicates (§1 Open Questions) as
  remaining "changes" — i.e. drift is reduced from 93 lines to exactly
  the 42 deferred alias-duplicate lines, not eliminated to zero (that
  would require resolving the naming-convention question first).

### Non-Goals (explicitly out of scope)
- **Do NOT add any of the 42 alias-duplicate entries** listed in §6
  Appendix B. Adding a second key for an already-registered class is a
  naming-policy decision (should the registry have exactly one canonical
  key per class, and if so, which naming convention wins — the curated
  short alias or `_class_to_key()`'s derived form?), not a drift-sync
  mechanical fix. This is explicitly deferred to §8 Open Questions.
- **Do NOT run `python scripts/generate_tool_registry.py` unmodified
  (plain write mode) against either `__init__.py` file.** Verified: the
  write branch of `update_init_file()` replaces the *entire* assignment
  line range (`node.lineno` to `node.end_lineno`) with a flat
  `key: value` list built from `merged.items()`, in scan order — this
  physically deletes every `# --- ... ---` section comment currently
  inside the dict literal (comments are not part of the AST value node,
  so they fall inside the replaced line range and are not preserved) and
  reorders every existing entry. Both `__init__.py` files currently have
  such comments (verified: 14 section-comment lines across the two
  files). This task requires a hand-curated edit instead — see §3.
- No change to `scripts/generate_tool_registry.py` itself — that script
  was already fixed by FEAT-427; this spec only touches the two
  generated-but-hand-maintained `__init__.py` files.
- No change to `TOOL_BASE_CLASSES`/`LOADER_BASE_CLASSES` or the
  `_class_to_key()` naming convention.
- No audit of any other package's registry beyond these two files.

---

## 2. Architectural Design

### Overview

This is a **data-sync task, not a code-logic change**: hand-add the 49 +
1 = 50 missing entries (49 to `TOOL_REGISTRY`, 1 to `LOADER_REGISTRY`)
and correct the 1 renamed value (`odoo`), directly editing the two
`__init__.py` files with `Edit`, preserving every existing line. New
entries go in a new trailing section so the diff is purely additive for
everything except the single `odoo` line.

### Component Diagram
```
scripts/generate_tool_registry.py --check   (read-only, evidence source — NOT run in write mode)
        │
        ▼
packages/ai-parrot-tools/src/parrot_tools/__init__.py       (hand-edited: +49 entries, ~1 renamed value)
packages/ai-parrot-loaders/src/parrot_loaders/__init__.py   (hand-edited: +1 entry)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/__init__.py` | modify | append 49 entries in a new trailing section inside `TOOL_REGISTRY`; fix `"odoo"` value in place |
| `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` | modify | append 1 entry (`WebScrapingLoader`) in a new trailing section inside `LOADER_REGISTRY` |
| `scripts/generate_tool_registry.py` | verify only | run with `--check`/`--dry-run` to confirm before/after state; not modified |

### Data Models
Not applicable — no new data models; this only edits two `dict[str, str]`
literals.

### New Public Interfaces
None. No new functions/classes — this task only adds dict entries whose
values are dotted paths to classes that **already exist** in the tree
(verified importable in §6 Appendix A).

---

## 3. Module Breakdown

### Module 1: `TOOL_REGISTRY` sync
- **Path**: `packages/ai-parrot-tools/src/parrot_tools/__init__.py`
- **Responsibility**:
  1. Change line 26 (`"odoo": "parrot_tools.odoo.OdooToolkit",`) to
     `"odoo": "parrot_tools.odoo.toolkit.OdooToolkit",` — value only, key
     unchanged.
  2. Immediately before the closing `}` of `TOOL_REGISTRY` (currently
     line ~150), add a new comment `# --- Synced from drift audit
     (FEAT-436) ---` followed by the 49 entries from §6 Appendix A, TRUE
     NEW list, each as `"<key>": "<dotted.path.ClassName>",` — alphabetized
     by key for reviewability.
- **Depends on**: none.

### Module 2: `LOADER_REGISTRY` sync
- **Path**: `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py`
- **Responsibility**: Immediately before the closing `}` of
  `LOADER_REGISTRY` (currently line 43), add
  `"WebScrapingLoader": "parrot_loaders.webscraping.WebScrapingLoader",`
  under a new comment `# --- Synced from drift audit (FEAT-436) ---`.
- **Depends on**: none.

### Module 3: Verification
- **Path**: none (no new file) — run
  `python scripts/generate_tool_registry.py --check` and
  `python scripts/generate_tool_registry.py --check --tools-only` /
  `--loaders-only` as a manual verification step (not a new test file;
  FEAT-427 already added `tests/scripts/test_generate_tool_registry.py`
  covering the script's own parsing logic, which is unaffected by this
  data-only change).
- **Depends on**: Modules 1, 2.

---

## 4. Test Specification

### Unit Tests
No new unit tests — this task adds no new code, only dict entries whose
correctness is mechanically verifiable (see Acceptance Criteria).
`tests/scripts/test_generate_tool_registry.py` (from FEAT-427) already
covers the parser; it is unaffected by data-only edits to unrelated
`__init__.py` files and must continue to pass unmodified.

### Integration Tests
| Test | Description |
|---|---|
| Existing `packages/ai-parrot-tools/tests/` suite | Run the full `ai-parrot-tools` test suite to confirm no import collisions or `__all__`/registry-consumer regressions from the added entries. |
| Existing `packages/ai-parrot-loaders/tests/` suite | Same, for the loaders package. |

### Manual Verification Commands
```bash
python scripts/generate_tool_registry.py --check --tools-only
# Expect: reports exactly 42 remaining "changes" (the deferred alias-duplicates
# from §6 Appendix B) — NOT 92, NOT 0.

python scripts/generate_tool_registry.py --check --loaders-only
# Expect: exit 0, "All registries are up to date."
```

---

## 5. Acceptance Criteria

- [ ] `packages/ai-parrot-tools/src/parrot_tools/__init__.py`: the
      `"odoo"` entry's value is
      `"parrot_tools.odoo.toolkit.OdooToolkit"` (was
      `"parrot_tools.odoo.OdooToolkit"`).
- [ ] `packages/ai-parrot-tools/src/parrot_tools/__init__.py`:
      `TOOL_REGISTRY` contains all 49 keys listed in §6 Appendix A (TRUE
      NEW), each mapping to exactly the dotted path shown there.
- [ ] `packages/ai-parrot-loaders/src/parrot_loaders/__init__.py`:
      `LOADER_REGISTRY` contains
      `"WebScrapingLoader": "parrot_loaders.webscraping.WebScrapingLoader"`.
- [ ] None of the 42 keys listed in §6 Appendix B (alias-duplicates) were
      added to `TOOL_REGISTRY`.
- [ ] Every pre-existing entry and every pre-existing `# --- ... ---`
      section comment in both files is byte-for-byte unchanged (verify
      with `git diff` — the diff must be purely additive except for the
      single `odoo` value line).
- [ ] `python scripts/generate_tool_registry.py --check --tools-only`
      reports exactly the 42 deferred alias-duplicates as remaining
      changes (not 92, not 0) — confirms this task's 49 additions + 1
      rename are exactly and only what landed.
- [ ] `python scripts/generate_tool_registry.py --check --loaders-only`
      exits `0`.
- [ ] All 50 newly-registered dotted paths import successfully:
      `python -c "import importlib; [importlib.import_module(p.rsplit('.',1)[0]) and getattr(importlib.import_module(p.rsplit('.',1)[0]), p.rsplit('.',1)[1]) for p in [...]]"`
      (see §6 Appendix A for the full path list).
- [ ] `python -m pytest packages/ai-parrot-tools/tests/ -q` passes (no
      new failures vs. pre-change baseline).
- [ ] `python -m pytest packages/ai-parrot-loaders/tests/ -q` passes (no
      new failures vs. pre-change baseline).
- [ ] `ruff check packages/ai-parrot-tools/src/parrot_tools/__init__.py
      packages/ai-parrot-loaders/src/parrot_loaders/__init__.py` clean.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**

### Verified Imports
No new imports — this task edits two dict literals only. Both files'
existing `from .version import __version__, __title__, __description__`
import is unchanged.

### Existing Class/Function Signatures
```python
# packages/ai-parrot-tools/src/parrot_tools/__init__.py — lines 12-150 (verified 2026-08-20)
TOOL_REGISTRY: dict[str, str] = {
    # --- Toolkits (Batch 1 — simple tools) ---
    "zipcode": "parrot_tools.zipcode.ZipcodeAPIToolkit",
    ...
    "odoo": "parrot_tools.odoo.OdooToolkit",   # line 26 — value to change
    ...
}   # closing brace at line 150
__all__ = ["__version__", "TOOL_REGISTRY"]   # line 152
```

```python
# packages/ai-parrot-loaders/src/parrot_loaders/__init__.py — lines 9-43 (verified 2026-08-20)
LOADER_REGISTRY: dict[str, str] = {
    # --- Text / Document loaders ---
    "TextLoader": "parrot_loaders.txt.TextLoader",
    ...
    "LOADER_MAPPING": "parrot_loaders.factory.LOADER_MAPPING",
}   # closing brace at line 43
__all__ = ["__version__", "LOADER_REGISTRY"]   # line 45
```

### Appendix A — TRUE NEW entries to add (49 tools + 1 loader, verified importable 2026-08-20)

`TOOL_REGISTRY` additions:
```
"abstract_document": "parrot_tools.document.AbstractDocumentTool",
"abstract_schema_manager": "parrot_tools.database.abstract.AbstractSchemaManagerTool",
"create_draft_message": "parrot_tools.o365.mail.CreateDraftMessageTool",
"create_event": "parrot_tools.o365.events.CreateEventTool",
"data_analysis_think": "parrot_tools.think.DataAnalysisThinkTool",
"data_frame_to_csv": "parrot_tools.csv_export.DataFrameToCSVTool",
"data_frame_to_excel": "parrot_tools.excel.DataFrameToExcelTool",
"download_attachment": "parrot_tools.o365.mail.DownloadAttachmentTool",
"download_one_drive_file": "parrot_tools.o365.onedrive.DownloadOneDriveFileTool",
"download_share_point_file": "parrot_tools.o365.sharepoint.DownloadSharePointFileTool",
"dynamic_rest": "parrot_tools.resttool.DynamicRESTTool",
"file_operations": "parrot_tools.codeinterpreter.internals.FileOperationsTool",
"get_event": "parrot_tools.o365.events.GetEventTool",
"get_message": "parrot_tools.o365.mail.GetMessageTool",
"gig_smart": "parrot_tools.gigsmart.toolkit.GigSmartToolkit",
"google_base": "parrot_tools.google.base.GoogleBaseTool",
"google_business": "parrot_tools.google.places.GoogleBusinessTool",
"google_places_base": "parrot_tools.google.tools.GooglePlacesBaseTool",
"google_reviews": "parrot_tools.google.tools.GoogleReviewsTool",
"google_traffic": "parrot_tools.google.tools.GoogleTrafficTool",
"graph_index": "parrot_tools.graphindex.toolkit.GraphIndexToolkit",
"inspector": "parrot_tools.aws.inspector.InspectorToolkit",
"list_events": "parrot_tools.o365.events.ListEventsTool",
"list_messages": "parrot_tools.o365.mail.ListMessagesTool",
"list_one_drive_files": "parrot_tools.o365.onedrive.ListOneDriveFilesTool",
"list_share_point_files": "parrot_tools.o365.sharepoint.ListSharePointFilesTool",
"multi_store_search": "parrot_tools.multistoresearch.toolkit.MultiStoreSearchToolkit",
"o365": "parrot_tools.o365.base.O365Tool",
"office365": "parrot_tools.o365.oauth_toolkit.Office365Toolkit",
"office365_file_management": "parrot_tools.o365.bundle.Office365FileManagementToolkit",
"one_drive": "parrot_tools.o365.bundle.OneDriveToolkit",
"prices": "parrot_tools.pricestool.PricesTool",
"python_execution": "parrot_tools.codeinterpreter.internals.PythonExecutionTool",
"query_plan": "parrot_tools.think.QueryPlanTool",
"rag_retrieval_think": "parrot_tools.think.RAGRetrievalThinkTool",
"sandbox_pandas": "parrot_tools.sandboxtool.SandboxPandasTool",
"scraping_plan": "parrot_tools.think.ScrapingPlanTool",
"search_email": "parrot_tools.o365.mail.SearchEmailTool",
"search_one_drive_files": "parrot_tools.o365.onedrive.SearchOneDriveFilesTool",
"search_share_point_files": "parrot_tools.o365.sharepoint.SearchSharePointFilesTool",
"security_report": "parrot_tools.security.report_toolkit.SecurityReportToolkit",
"send_email": "parrot_tools.o365.mail.SendEmailTool",
"share_point": "parrot_tools.o365.bundle.SharePointToolkit",
"simple_rest": "parrot_tools.resttool.SimpleRESTTool",
"soc2_advisory": "parrot_tools.security.soc2_advisory.SOC2AdvisoryToolkit",
"static_analysis": "parrot_tools.codeinterpreter.internals.StaticAnalysisTool",
"update_event": "parrot_tools.o365.events.UpdateEventTool",
"upload_one_drive_file": "parrot_tools.o365.onedrive.UploadOneDriveFileTool",
"upload_share_point_file": "parrot_tools.o365.sharepoint.UploadSharePointFileTool",
```

`LOADER_REGISTRY` addition:
```
"WebScrapingLoader": "parrot_loaders.webscraping.WebScrapingLoader",
```

All 50 dotted paths above were verified importable via
`importlib.import_module(...)` + `getattr(...)` on 2026-08-20 against
`dev` HEAD `0dfa99db9` — 0 failures.

### Appendix B — Alias-duplicates to LEAVE UNADDED (42; deferred, see §8)
```
arango_db_search      → parrot_tools.arangodbsearch.ArangoDBSearchTool       (existing key: "arango_search" or similar — verify at implementation time)
best_buy               → parrot_tools.retail.bby.BestBuyToolkit               (existing key: "bestbuy")
break_even_analysis     → parrot_tools.breakeven.BreakEvenAnalysisTool
cloud_sploit            → parrot_tools.cloudsploit.toolkit.CloudSploitToolkit
cloud_watch             → parrot_tools.aws.cloudwatch.CloudWatchToolkit
df_to_html              → parrot_tools.dftohtml.DfToHtmlTool
document_converter       → parrot_tools.doc_converter.DocumentConverterTool
document_db              → parrot_tools.aws.documentdb.DocumentDBToolkit
duck_duck_go             → parrot_tools.ddgo.DuckDuckGoToolkit             (existing key: "ddgo")
ec2                     → parrot_tools.aws.ec2.EC2Toolkit
ecr                     → parrot_tools.aws.ecr.ECRToolkit
ecs                     → parrot_tools.aws.ecs.ECSToolkit
eks                     → parrot_tools.aws.eks.EKSToolkit
guard_duty               → parrot_tools.aws.guardduty.GuardDutyToolkit
iam                     → parrot_tools.aws.iam.IAMToolkit
ibis_world               → parrot_tools.ibisworld.tool.IBISWorldTool
lambda                  → parrot_tools.aws.lambda_func.LambdaToolkit
lead_iq                 → parrot_tools.leadiq.tool.LeadIQToolkit          (existing key: "leadiq")
monte_carlo_simulation    → parrot_tools.montecarlo.MonteCarloSimulationTool
ms_teams                → parrot_tools.msteams.MSTeamsToolkit             (existing key: "msteams")
ms_word                 → parrot_tools.msword.MSWordTool
network_ninja            → parrot_tools.networkninja.NetworkNinjaTool
open_weather             → parrot_tools.openweather.OpenWeatherTool
power_bi_query           → parrot_tools.powerbi.PowerBIQueryTool
power_bi_table_info       → parrot_tools.powerbi.PowerBITableInfoTool
power_point              → parrot_tools.powerpoint.PowerPointTool
q_source                → parrot_tools.qsource.QSourceTool
rds                     → parrot_tools.aws.rds.RDSToolkit
rest                    → parrot_tools.resttool.RESTTool
route53                 → parrot_tools.aws.route53.Route53Toolkit
s3                      → parrot_tools.aws.s3.S3Toolkit
secrets_ia_c             → parrot_tools.security.secrets_iac_toolkit.SecretsIaCToolkit
security_hub             → parrot_tools.aws.securityhub.SecurityHubToolkit
serp_api_search          → parrot_tools.serpapi.SerpApiSearchTool
site_search              → parrot_tools.sitesearch.toolkit.SiteSearchToolkit
text_file                → parrot_tools.textfile.TextFileTool
troc_operations          → parrot_tools.troc.tool.TROCOperationsToolkit   (existing key: "troc")
what_if                 → parrot_tools.whatif_toolkit.WhatIfToolkit
whats_app                → parrot_tools.messaging.whatsapp.WhatsAppTool
y_finance                → parrot_tools.yfinance.YFinanceTool
zipcode_api              → parrot_tools.zipcode.ZipcodeAPIToolkit         (existing key: "zipcode")
zoom_us                 → parrot_tools.zoomtoolkit.ZoomUsToolkit          (existing key: "zoom")
```
(Determined by: value already present in `TOOL_REGISTRY.values()` under a
different key, cross-referenced 2026-08-20 against `dev` HEAD `0dfa99db9`.
The implementer MUST NOT add any of these 42 keys — re-verify this list
against the then-current `--check --tools-only` output at implementation
time in case unrelated commits shifted the registry in the interim; the
categorization rule (value already in `.values()`) is what matters, not
this frozen list, if the two have drifted.)

### Does NOT Exist (Anti-Hallucination)
- ~~A "canonical alias" resolution mechanism~~ — does not exist in
  `scripts/generate_tool_registry.py` or `TOOL_REGISTRY`'s consumers; the
  registry has no built-in concept of "primary key vs. alias" today. This
  is exactly why §1 Non-Goals defers the 42 alias-duplicates — adding
  them would be the *first* precedent of dual-keying, not a neutral sync.
- ~~A test file for this task~~ — none is created; see §4 Test
  Specification (existing suites cover this by import + drift-check, no
  new test file needed for a pure-data change).
- ~~Any change to `scripts/generate_tool_registry.py`~~ — already fixed by
  FEAT-427; not touched again here.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Use `Edit` (not the generator script) on both `__init__.py` files.
- Alphabetize the 49 (or 1) new entries within their new trailing
  section for reviewability — the existing sections are NOT
  alphabetical (they're grouped by rollout batch), so do not attempt to
  re-sort or merge new entries into the old sections; a new, clearly
  separate section keeps the diff purely additive and the review
  tractable.
- Match the existing quoting/formatting style exactly:
  `    "<key>": "<dotted.path.ClassName>",` (4-space indent, trailing
  comma, double quotes).

### Known Risks / Gotchas
- **Do not trust `--check`'s raw diff count as "safe to auto-apply."**
  As this spec demonstrates, 42 of the 92 reported "changes" are
  same-class alias duplicates, not real gaps — always cross-reference
  against `.values()`, not just against the raw generator diff, before
  adding anything to a registry.
- The `"lambda"` key (existing, alias-duplicate, NOT added by this task)
  is a Python keyword as a *string* dict key, which is syntactically
  fine (`"lambda"` is a str literal, not an identifier) — no escaping
  concerns, just noting it for the implementer's sanity check when
  scanning the diff.
- `arango_db_search`'s existing alias key was not pinned down precisely
  during spec authoring (only confirmed the value collision, not the
  exact existing key string) — the implementer should verify the exact
  existing key via `grep -n "arangodbsearch" packages/ai-parrot-tools/src/parrot_tools/__init__.py`
  before writing the Completion Note, but this does not change the
  Non-Goal (still must not add `arango_db_search` as a new key).

### External Dependencies
None.

---

## 8. Open Questions

- [ ] **Registry key-naming policy**: should `TOOL_REGISTRY` converge on
      exactly one canonical key per class (deciding, for each of the 42
      alias-duplicates, whether the short hand-curated alias or
      `_class_to_key()`'s derived form wins), or is intentional
      dual-keying (both `"bestbuy"` and `"best_buy"` resolving to the
      same class) acceptable/desirable for discoverability? — *Owner:
      repo maintainer* — explicitly deferred; this spec only closes the
      unambiguous 49+1 true-gap entries.
- [ ] Once the naming-policy question above is resolved, should
      `_class_to_key()` itself be changed to match the curated
      convention (so future scans stop proposing a second key for
      already-registered classes), or should the 42 existing short
      aliases be renamed to match `_class_to_key()`'s output instead? —
      *Owner: repo maintainer* — out of scope here; likely its own
      follow-up spec once decided.

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-20 | Jesus | Initial draft — filed as a follow-up from FEAT-427's Completion Note recommendation |
