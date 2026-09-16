# F006 — Confirmed stale tests: schema-version + removed-symbol drift (not packaging)

**Query**: ad hoc, surfaced while triaging `test-wiki-extras`/`test-core` failures
**Confidence**: high (each individually confirmed), scope not fully enumerated

## F006a — `tests/knowledge/wiki/test_store_migration_v2.py`

- `packages/ai-parrot/src/parrot/knowledge/wiki/store.py:50`:
  `SCHEMA_VERSION = "3"` today.
- `git log --oneline -- .../wiki/store.py` top commits are the FEAT-557
  "wikitoolkit-sqlite-optimizations" series; `SCHEMA_VERSION` was bumped
  2 → 3 as part of that work.
- The test (docstring: *"Opens the committed `fixtures/wiki_v1.db` (a
  `SCHEMA_VERSION == "1"` fixture) ..."*) hardcodes the **target** version:
  `assert row[0] == SCHEMA_VERSION == "2"` (line 75,
  `test_open_v1_db_migrates_to_v2`). CI: `AssertionError: assert '3' == '2'`
  — confirmed in both `test-wiki-extras` and `test-core` runs.
- This is a genuine test-staleness bug from FEAT-557, unrelated to
  packaging/extras. Fix: assert against the live `SCHEMA_VERSION` import
  (already imported at the top of the file) instead of the hardcoded
  literal `"2"`, and/or add explicit coverage for the 2→3 step introduced by
  FEAT-557 so the migration chain (1→2→3) is actually exercised end to end,
  not just relabeled.

## F006b — `tests/test_infographic_html.py` (`BASE_CSS`)

- `packages/ai-parrot-visualizations/src/parrot/outputs/formats/
  infographic_html.py` docstrings (lines 320-321, 419-420) explicitly
  describe `BASE_CSS` as **"legacy"**, replaced by
  `DesignSystem.stylesheet(theme_cfg, layout_name)` with a `"report"`
  layout reproducing the old look via `layout-report.css` (FEAT-493
  TASK-2712).
- `tests/test_infographic_html.py:54`: `from
  parrot.outputs.formats.infographic_html import BASE_CSS,
  InfographicHTMLRenderer` — the symbol no longer exists. CI:
  `ImportError: cannot import name 'BASE_CSS'`.
- The test file has dozens of assertions directly probing `BASE_CSS`
  content (CSS variable names, `@media print` block, `!important` rules) —
  this needs a real rewrite to assert against the new
  `DesignSystem.stylesheet(..., layout="report")` output, not a one-line
  patch. Deliberately **not** designed in this proposal; flagged for its
  own task at spec time.

## F006c — Other confirmed-real (not extras-related) import errors seen in the same sweep, not yet root-caused

`ImportError: cannot import name 'DatabaseAgentToolkit' from
'parrot.bots.database.toolkits'`, `'DatabaseAgent' from
'parrot.bots.database.agent'`, `'flows' from 'parrot.bots'`, `'FAISSStore'
from 'parrot.stores.faiss_store'`. Each is a genuine "symbol renamed/moved,
test never updated" pattern (same shape as F006a/b), confirmed present in
the log but not individually traced to a root commit in this pass — listed
here so `/sdd-spec` scopes a task to triage each one specifically rather
than they get silently re-swept under "continue-on-collection-errors".
