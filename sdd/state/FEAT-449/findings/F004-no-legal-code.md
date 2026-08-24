---
id: F004
query_id: Q004
type: grep
intent: Locate any existing legal-domain code (BOE/CENDOJ/ECLI/EUR-Lex) so the proposal reports greenfield vs extension accurately
executed_at: 2026-08-23T00:21:02Z
depth: 0
parent_id: null
---

# F004 — Zero legal-domain code exists; the "new tooling for legal resources" commit added only the design doc

## Summary

A case-insensitive grep for `cendoj|eurlex|eur-lex|celex|BOE-A-|ECLI:` across every `.py` file
in `packages/` returns **0 matches**. The recent commit `db9b32dff` whose message reads "new
tooling for legal resources" touched exactly one file — the design document that is this
proposal's own source — and added no code. The entire legal domain (toolkits, id parsing,
ingestion, contracts) is greenfield.

## Citations

- path: `packages/`
  excerpt: |
    $ grep -rniE "cendoj|eurlex|eur-lex|celex|BOE-A-|ECLI:" --include=*.py . | wc -l
    0

- path: `sdd/proposals/claude_legal-wiki-design.md`
  excerpt: |
    commit db9b32dff "new tooling for legal resources"
     sdd/proposals/claude_legal-wiki-design.md | 289 ++++++++++++++++++++++++++++++
     1 file changed, 289 insertions(+)

## Notes

Confirms the source's own "Does NOT exist (to be created)" line. No partial head start to
reconcile against.
