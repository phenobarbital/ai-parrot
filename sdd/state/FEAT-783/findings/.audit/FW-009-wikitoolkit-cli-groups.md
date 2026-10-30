---
id: FW-009
query_id: Q009
type: wiki_query
intent: "Orient: wikitoolkit CLI command group structure, to place a new 'usage' group."
executed_at: 2026-10-30T22:40:30Z
duration_ms: 0
parent_id: null
depth: 1
---

# FW-009 — `wikitoolkit` groups are symbols / ns / ledger / sync / adr, registered in `knowledge/wiki/cli.py`; `ledger` is the worked template for a new `usage` group

## Summary

A prior proposal's finding enumerates the CLI groups: "wikitoolkit CLI has groups symbols, ns,
ledger, sync (and adr); `schema` is unused" (`sdd/state/FEAT-600/findings/F021-cli-groups.md`,
score=0.58). The `ledger` group is the direct precedent — TASK-3236 created it, and later tasks
(TASK-3392 `plan-fix`/`unclaim`/`close --resolved-by`, TASK-4400 `list`/`show`, TASK-4604
`retract-feedback`) each added subcommands to it, so the incremental pattern is established.
The paired CLI+MCP pattern is also established: TASK-4020 shipped "`wikitoolkit lint` CLI command
+ `wiki_lint` MCP tool" in one task, which is the shape a `wikitoolkit usage …` + `wiki_usage`
pair would take.

## Citations

- path: `packages/ai-parrot/src/parrot/knowledge/wiki/cli.py`
  lines: 1-1
  symbol: CLI group registration site
  excerpt: |
    # groups: symbols, ns, ledger, sync, adr  (schema registered but unused)
    # per sdd/state/FEAT-600/findings/F021-cli-groups.md

- path: `sdd/state/wiki-ledger-show/findings/F001-cli-ledger-group.md`
  lines: 1-1
  symbol: prior finding (score=1.00)
  excerpt: |
    F001 — `wikitoolkit ledger` command group
           (type: grep+read, wiki: sym:...cli.py#ledger_unclaim)

- path: `sdd/tasks/completed/TASK-3236-ledger-cli-group.md`
  lines: 1-1
  symbol: group creation precedent
  excerpt: |
    TASK-3236: wikitoolkit ledger command group

- path: `sdd/tasks/completed/TASK-4020-lint-cli-mcp.md`
  lines: 1-1
  symbol: CLI+MCP pairing precedent
  excerpt: |
    TASK-4020: `wikitoolkit lint` CLI command + `wiki_lint` MCP tool

- path: `sdd/tasks/completed/TASK-3392-cli-plan-fix-unclaim-resolved-by.md`
  lines: 1-1
  symbol: incremental subcommand precedent

## Notes

Performance constraint on any new subcommand: `issue:f0a40d0853f2` — "wikitoolkit hook warm start
misses AC23b: p50 ~415-425ms vs 300ms target". A `usage bind` subcommand shelled out from a Claude
Code `SubagentStop` hook (the source's design) would pay that ~420 ms per sub-agent stop, against
the source's own S2 pass criterion of "< 150 ms". **This is a falsifying measurement against the
source's hook design as written.**

[cross-lane: type=grep, intent=Confirm the CLI group registration lines in knowledge/wiki/cli.py and whether a lazy-import warm path exists]
