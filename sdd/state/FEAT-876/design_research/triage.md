# Design Research Triage — bookstore-notebooks-shared-pageindex (FEAT-876)

Model: `gpt-5.6-luna` (codex-cli 0.167.0, reasoning high) · Status: completed
Run: 2026-11-10T21:06:42Z → 21:11:14Z, exit 0 (first attempt failed at brief rendering on a literal
`{{repo_root}}` in the brainstorm text; brief inputs neutralised to `<repo_root>` and the run repeated).
Every `affected_paths` entry passed `parrot sdd spec check-path` (containment) and `test -e`.

| # | Suggestion (kind) | Disposition | Reason | Landed in |
|---|---|---|---|---|
| S1 | Separate notebook catalog model, or every caller filters `kind='book'` (architecture) | CONFIRM (filtering) / REJECT (separate table) | One table keeps `tree_name UNIQUE` and slug allocation as the collision guard; notebook rows fill the NOT NULL source columns; every card-enumerating path filters `kind` | §2 Overview, §5 AC |
| S2 | Lazy registration leaves `<book>_notes` a free tree until read (risk) | CONFIRM | Facade classifies by name + catalog, independent of the row | §2 Overview, M3 `_resolve`, §4 |
| S3 | Centralize authorization at `_mutate`; cover `index_segments`; completeness test (architecture) | CONFIRM | `_mutate` verified at `toolkit.py:459`; direct-lock paths listed | §2, M2, §4 |
| S4 | Authorize both endpoints of `rename_tree` (risk) | CONFIRM | signature `(src, dst, *, overwrite)` at `toolkit.py:800` | §2, M3, §4, §5 |
| S5 | Plain template bypass; ownership guard or narrow the claim (risk) | ESCALATE | Claim narrowed already; generic ownership marker is a product decision | §8 Q2 |
| S6 | Keep `list_trees` as `list[str]`; separate annotated listing (api) | CONFIRM | `toolkit.py:741` returns `list[str]` | §2, M2/M3, §5 |
| S7 | Test no-LLM filtering; `_NullAdapter` makes default LLM walk fail (testing) | CONFIRM | `_NullAdapter()` at `library.py:336`; `search` checks only `is not None` (`toolkit.py:1768`); `search_book` passes `has_llm` (`:661`) | §2, M3, §4 |
| S8 | Stage import, validate, publish atomically, hash the logical snapshot (risk) | CONFIRM | per-piece store ops only; `--staging-` marker + sweep exist (`library.py:73`) | §2 Import, §4, §5 |
| S9 | Collision-safe anchor remapping (risk) | CONFIRM | `SegmentStore.list_revisions` (`segment_store.py:106`) retains old revisions → content matching | §2, M4, §4 |
| S10 | Preserve manual relations on re-index (risk) | CONFIRM | `_invalidate_graph` (`library.py:1960`) → `delete_relations(book_id=...)` with no origin filter (`:1969`) | §2, M4, §4/§5 |
| S11 | `(scope, book_id)` identity at read boundaries (api) | CONFIRM | project-first masking in `merged_cards` / `resolve_book` | §2, §4 |
| S12 | Concurrency / generation-consistency tests (testing) | CONFIRM | FEAT-831 protects single trees only | §4 Integration |

Summary: 11 confirmed (S1 partially) · 0 rejected outright · 1 escalated.
