---
id: FC-018
query_id: Q026
type: read
intent: "E2E harness the user runs per config_name."
executed_at: 2026-11-06T16:11:10Z
duration_ms: 600
parent_id: null
depth: 0
---

# FC-018 — Two e2e paths: a manifest-driven pytest suite and a per-config runner that reads the row from the ENV database

## Summary

`examples/planogram/e2e/README.md` documents a live pytest suite gated by `PARROT_TEST_REAL_LLM=1` and `PLANOGRAM_E2E_MANIFEST` (manifest + config file + ground truth). Separately, `examples/planogram/e2e/main.py <config_name>` reads the active row of `troc.planograms_configurations` through `querysource.conf.default_dsn` of the active `ENV`, runs every photo in `examples/planogram/images/<config_name>/`, and looks for references in `images/<config_name>/references/`. Coverage of the two EcoTank end caps is therefore manual: the per-config runner against whichever database `ENV` selects, with the photos of FC-004; nothing asserts expected outcomes for them.

## Citations

- path: `examples/planogram/e2e/README.md`
  lines: 187-204
  symbol: `(Running the Tests)`
  excerpt: |
    PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=/path/to/your/manifest.json pytest examples/planogram/e2e -q
    PARROT_TEST_REAL_LLM=1 PLANOGRAM_E2E_MANIFEST=/path/to/your/manifest.json pytest examples/planogram/e2e -q -k shelves
- path: `examples/planogram/e2e/main.py`
  lines: 3-17
  symbol: `(module docstring)`
  excerpt: |
    Reads one active row of ``troc.planograms_configurations`` by ``config_name``, builds the same
    per photo found in ``examples/planogram/images/<config_name>/`` — every photo is a different
    ``examples/planogram/images/<config_name>/references/``, by file name or by stem.
    The DSN is ``querysource.conf.default_dsn`` of the active ``ENV``; it is never logged. Photos,
- path: `examples/planogram/e2e/main.py`
  lines: 57-57
  symbol: `_ROW_SQL`
  excerpt: |
    _ROW_SQL = "SELECT * FROM troc.planograms_configurations WHERE config_name = $1 AND is_active = TRUE LIMIT 1"
- path: `examples/planogram/e2e/main.py`
  lines: 476-493
  symbol: `main`
  excerpt: |
    parser.add_argument("planogram", help="config_name of the row, which is also the folder under images/")
    parser.add_argument("--image-dir", type=Path, default=None, help="photo folder (default: images/<planogram>)")
    parser.add_argument("--output-dir", type=Path, default=None, help="results folder (default: results/<planogram>)")
    parser.add_argument("--backend", default=None, help='"provider:model" override of the row\'s llm_backend')
    parser.add_argument("--no-cache", action="store_true", help="disable the vision response cache")

## Notes

Only headings and matching lines of the README (265 lines) and `main.py` (515 lines) were read. The README headings are: Purpose, Privacy, Prerequisites, Manifest Format, Config File Format, Ground Truth Format, Running the Tests, Skip vs. Fail, Outputs, Cost and Cache, Signoff.
