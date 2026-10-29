# FC-006 — Only three live references to `examples/semantic/` exist; exactly two must change on a move (plus historical SDD/ledger records that must NOT be rewritten)

**Query**: Q011 · **Type**: grep · **Depth**: 0

## Summary
A repo-wide grep for `examples/semantic`, `examples/agents/semantic` and `agent_semantic_example`
(excluding `.git/` and `__pycache__`) returns eight files. Only two are *live code/docs that break*:
the pinning test's `_EXAMPLE_PATH` and the README's run command. The third live reference is the
example's own `__main__`-less path independence — it uses `tempfile`, not a sibling fixture dir, so it
is path-agnostic. The remaining five are immutable history: a completed task file, two ledger
snapshots (`sdd/ledger/issues.jsonl`, `sdd/ledger/events.jsonl` — 2 hits), and this proposal's own
state files. **There is no reference in any `pyproject.toml`, `ruff.toml`, `.github/workflows/*.yml`,
`pytest.ini`, `conftest.py`, `MANIFEST`, `.gitignore` or `mkdocs` nav** — nothing packages or ships
the examples tree. `docs/tools/semantic-layer.md` never names the example path either.

## Citations
- `packages/ai-parrot-semantic/tests/test_example_agent.py:21` — **must change**: `_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "semantic" / "agent_semantic_example.py"`
- `examples/semantic/README.md:3` — **must change**: ``Run `python examples/semantic/agent_semantic_example.py` with the DuckDB extra.``
- `sdd/tasks/completed/TASK-4702-semantic-agent-example.md:29-30, 109, 113, 145, 200, 205, 251-252` — historical record of the original CREATE; leave as-is
- `sdd/ledger/issues.jsonl:484` — `issue:f0da823294fb` whose `about` is `["examples/semantic/agent_semantic_example.py", "packages/ai-parrot-semantic/tests/test_example_agent.py"]`; status **closed**. Moving the file orphans this `about` path, but the issue is closed so no `plan-fix` lane is affected
- `sdd/ledger/events.jsonl` — 2 matching event records (append-only log; never rewritten)

## Notes
- `examples/` is not referenced by any workflow or packaging config, so the move has **zero** CI
  surface beyond the one test line. Verified by grepping `.github/workflows/` for `examples` (no hits)
  and `packages/ai-parrot-semantic/pyproject.toml` (no hits).
- `[cross-lane: type=git_log, intent=confirm no open PR/branch touches examples/semantic/ concurrently — a move conflicts badly with an in-flight edit]`
