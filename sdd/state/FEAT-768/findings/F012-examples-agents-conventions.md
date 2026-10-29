# F012 — examples/agents/ conventions: domain-foldered, feature-burst maintained, feat(<slug>): TASK-<NNN> commits

**Merged from**: FG-004

<!-- merged from FG-004 -->
**Query**: Q013 · **Type**: git_log · **Depth**: 0

## Summary
`examples/agents/` is not a flat directory: tracked content sits in **domain
sub-folders** — `a2ui/` (with a nested `linked_e2e/` and `linked_e2e/policies/`),
`aws/`, `finance/`, `oauth/`, `webbrowser/`. Adding `examples/agents/semantic/` therefore
matches the established layout exactly. Maintenance is bursty rather than continuous: in
the last 90 days the directory saw ~30 commits, all clustered in two feature pushes —
FEAT-611 `a2ui-linked-e2e` (2026-09-28 → 2026-10-02, ~15 commits, which added a whole
example server + agent + policies tree under `examples/agents/a2ui/linked_e2e/`) and the
`hooba` toolkit example (`663cab07d`, 2026-09-26, `examples/agents/finance/hooba_agent.py`
with a `--smoke` mode), then nothing since 2026-10-02. Commit-message convention is the
standard SDD one, `feat(<feature-slug>): TASK-<NNN> — <title>` / `fix(<slug>): <title>`,
with `style(<slug>): TASK-<NNN> — engine lint autofix` follow-ups; the semantic-layer
commits use the same `<slug>` = `semantic-layer`. Two reusable precedents stand out: the
`--smoke` offline-run flag on `hooba_agent.py`, and FEAT-611's pattern of registering the
example agent in the `AgentRegistry` so the admin UI can see it (`1016eb844`).

## Citations
- `git ls-files examples/agents` → sub-folders `a2ui/`, `a2ui/linked_e2e/`, `a2ui/linked_e2e/policies/`, `aws/`, `finance/`, `oauth/`, `webbrowser/` (no `semantic/`)
- `examples/agents/finance/hooba_agent.py` — commit `663cab07` (2026-09-26) `feat(hooba): TASK-3747 — examples/agents/finance/hooba_agent.py with --smoke mode`
- `examples/agents/a2ui/linked_e2e/` — commit `7a12a75c` (2026-09-29) `feat(a2ui-linked-e2e-parallel): TASK-3839 — linked E2E example server, Epson agent, HTTP runner`
- `examples/agents/a2ui/linked_e2e/` — commit `1016eb84` (2026-09-29) `fix(a2ui-linked-e2e-parallel): FEAT-611 — register epson_linked in the AgentRegistry so the admin UI …`
- `examples/agents/a2ui/linked_e2e/policies/` — commit `a283d4f6` (2026-09-29) `fix(a2ui-linked-e2e): FEAT-611 example policies for navigator-auth 0.28.3 URI enforcement`
- Most recent `examples/agents/` commit: `5f409012` (2026-10-02) — directory untouched for ~4 weeks

## Notes
The existing semantic example lives at `examples/semantic/`, *outside* `examples/agents/`.
The feature request asks for `examples/agents/semantic/`, so FEAT-768 either relocates or
duplicates-and-diverges — and `packages/ai-parrot-semantic/tests/test_example_agent.py`
pins the current path, so a move breaks that test.
[cross-lane: type=read, intent=check whether `test_example_agent.py` hardcodes `examples/semantic/agent_semantic_example.py` as a path, which decides move-vs-add]
