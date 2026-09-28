---
id: F014
query_id: Q014
type: read
intent: Can "multi-graduates" (jsonb_array_length>1) and count-by-course (jsonb unnest) be expressed in slug payloads?
executed_at: 2026-09-28T20:30:00Z
parent_id: null
depth: 0
---
# F014 — Multi-graduates: yes, via a raw aggregate in `fields`; count-by-course: not via the flat slug payload — needs a second slug (lateral unnest) or a v3 multi-query `tExplode`+`GroupBy` pipeline
## Summary
`filter` cannot carry `jsonb_array_length(...)` (keys must be plain identifiers, F013) and no `where`/raw-SQL escape hatch exists in the payload; JSONB containment cannot express "≥2 elements" (array containment ignores duplicates). However `fields` is interpolated verbatim (F012), so `{"fields": ["count(*) FILTER (WHERE jsonb_array_length(graduation_details) > 1) AS multi_graduates"]}` (or `sum(CASE WHEN ... THEN 1 ELSE 0 END)`) yields the KPI in one row. Count-by-course needs `jsonb_array_elements(graduation_details)->>'course'` grouped; Postgres rejects set-returning functions in GROUP BY, and `fields`/`group_by` cannot change the FROM clause, so it is not expressible against the base slug. Options: (a) a dedicated slug whose `query_raw` is e.g. `SELECT {fields} FROM <tbl> t CROSS JOIN LATERAL jsonb_array_elements(t.graduation_details) AS gd {filter}` with payload `{"fields":["gd->>'course' AS course","count(*) AS graduates"],"group_by":["gd->>'course'"]}`; (b) the multi-query endpoint `/api/v3/queries` with the `tExplode` transformation (pandas explode + json_normalize) followed by the `GroupBy` operator — pulls all ~17.5k rows into pandas per refresh.
## Citations
- path: `../querysource/querysource/parsers/sql.pyx`
  lines: 345-347
  symbol: `SQLParser.process_fields`
  excerpt: |
    sql = sql.replace(' * FROM', ' {fields} FROM')
    fields = ', '.join(self.fields)
    sql = sql.format_map(SafeDict(fields=fields))
- path: `../querysource/rust/src/sql_parser.rs`
  lines: 476-506
  symbol: `process_fields`
  excerpt: |
    let mut result = sql.replace(" * FROM", " {fields} FROM");
    let field_str = fields.join(", ");
- path: `../querysource/querysource/queries/multi/transformations/tExplode.catalog.yaml`
  lines: 13-15
  symbol: `tExplode`
  excerpt: |
    description: >-
      Explode a column of lists or dicts into multiple rows, optionally normalising
      dict values into columns (pandas explode + json_normalize).
- path: `venv:querysource/queries/multi/operators/GroupBy.py`
  lines: 32
  symbol: `GroupBy`
  excerpt: |
    class GroupBy(AbstractOperator):
## Implications
- The multi-graduates KPI works with the single base slug — but only because `fields` is unvalidated raw SQL (an injection surface the example should not advertise as a pattern for user-supplied input; the payload is fixed in the surface).
- The pie chart needs either an extra slug definition shipped with the example (see F016 for registration) or a v3 multi-query pipeline; lane A should check whether FEAT-598 `LinkedDataSource` supports `is_multiquery` refresh from the browser.
- No grep hit for `unnest`/`jsonb_array_elements`/`jsonb_array_length` support anywhere in querysource parsers (`grep -rn` over `querysource/` + `rust/`) — there is no first-class JSONB-unnest feature.
