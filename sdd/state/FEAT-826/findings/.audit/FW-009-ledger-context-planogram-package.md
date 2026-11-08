---
id: FW-009
query_id: Q009
type: wiki_query
intent: "Prior SDD decisions on planogram config rows (appearance rule, refactor, new pipeline)."
executed_at: 2026-11-06T16:11:08Z
duration_ms: 0
parent_id: FW-004
depth: 1
---

# FW-009 — Work ledger: one open low-severity tech-debt issue on the planogram package, unrelated to these two rows

## Summary

`wikitoolkit ledger context` over `plan.py`, `migration.py` and `comparison/rules.py` returns a single open
issue: `issue:cc0725ca11e4` (tech_debt, low, discovered from `spec:FEAT-683`) — in `_rule_appearance` the
"ambiguous zone match" reason is lost when no attribute is assessed, and the scalar-or-list normalisation of
expected values is duplicated in `comparison/definition.py` `validate_bindings`. Nothing in the ledger concerns
the Office Depot EcoTank rows, the migration, or FlowTask.

## Citations

- path: `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/comparison/rules.py`
  lines: 441-501
  symbol: `_rule_appearance`
  wiki: ledger `issue:cc0725ca11e4` (`wikitoolkit ledger context` + `wikitoolkit ledger show`, read-only)
  excerpt: |
    [low] issue:cc0725ca11e4 appearance rule: ambiguous-zone reason lost and expected-normalisation duplicated (open)
    kind: tech_debt · severity: low · discovered_from: spec:FEAT-683
    about: .../planogram/comparison/rules.py, .../planogram/comparison/definition.py
    (1) when no attribute is assessed the detail always says "appearance not observed"; _rule_illumination/
    _rule_zone_present distinguish "ambiguous zone match" via any(status == "ambiguous"). Reuse that check.
    2026-10-15T17:04:54 agent:mcp issue.opened

## Notes

- The issue body quotes `_rule_appearance` at "~L429-481"; the symbol outline now places it at L441-501, i.e. the
  file moved since the issue was opened.
- If a row for 23/24 uses a mandatory `appearance` binding, an ambiguous zone match will read as "appearance not
  observed" in the rule detail (item 1 of the issue) — cosmetic, but it obscures diagnosis.
