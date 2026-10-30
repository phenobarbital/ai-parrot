---
id: F002
query_id: Q003
type: read
intent: "verify e2e-ui-tester's DevTools-MCP attach + screenshot-on-anomaly contract"
executed_at: 2026-10-27T19:10:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F002 — `e2e-ui-tester` attaches via an optional DevTools MCP tool; today it only captures a one-off PNG

## Summary

`.claude/agents/e2e-ui-tester.md` declares tools `Read, Bash, Glob, Grep,
Write` only — no browser-automation/Playwright tool of its own. Its
protocol explicitly makes DevTools-MCP attachment optional/best-effort: if
unavailable, it falls back to a `curl` HTTP-only check and must mark the
report as reduced coverage. Its only visual evidence instruction is
"Capture a screenshot on any unexpected finding" — a single PNG, not a
continuous recording — referenced under `observations[].evidence_refs` in
`e2e-exploration.json`.

## Citations

- path: `.claude/agents/e2e-ui-tester.md`
  lines: 27-29
  symbol: frontmatter `tools:`
  excerpt: |
    model: sonnet
    color: magenta
    tools: Read, Bash, Glob, Grep, Write

- path: `.claude/agents/e2e-ui-tester.md`
  lines: 48-60
  symbol: "Preconditions — verify before dispatch", item 2
  excerpt: |
    A dedicated browser-automation MCP tool (e.g. `chrome-devtools-mcp`, ...)
    is NOT guaranteed present. ... If none is available, you may still
    verify HTTP-level `ui` readiness with `curl`, but you MUST record that
    as reduced, non-browser evidence

- path: `.claude/agents/e2e-ui-tester.md`
  lines: 111-120
  symbol: "Exploration process", steps 2-3
  excerpt: |
    watching for unexpected console errors or 5xx network responses ...
    Capture a screenshot on any unexpected finding.
    3. If no such tool is available, fall back to `curl` ...

- path: `.claude/agents/e2e-ui-tester.md`
  lines: 124-162
  symbol: "Report contract — `e2e-exploration.json`"
  excerpt: |
    "observations": [{"target_id": "browser", "summary": "...",
      "evidence_refs": ["artifacts/logs/e2e/browser-explore/screenshot.png"]}]
    ... no `passed`/`status`/`gate_satisfied` field of any kind

## Notes

The example `evidence_refs` path in this spec
(`artifacts/logs/e2e/browser-explore/screenshot.png`) already matches the
real per-run log directory convention confirmed independently in F005/F006
(`<worktree>/artifacts/logs/e2e/<run_id>/...`) — a sibling `.webm` would sit
naturally in the same directory.
