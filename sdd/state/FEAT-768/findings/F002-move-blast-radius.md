# F002 — Blast radius of the move: exactly two live references, and a pin test that asserts on the example's source text

**Merged from**: FC-002, FC-006

<!-- merged from FC-002 -->
**Query**: Q007 · **Type**: read · **Depth**: 0

## Summary
`packages/ai-parrot-semantic/tests/test_example_agent.py` does NOT import the example as a module:
it builds an absolute path from the test file's own location and loads it with
`importlib.util.spec_from_file_location`. `Path(__file__).resolve().parents[3]` resolves to the repo
root (tests → ai-parrot-semantic → packages → root), so the only edit a move requires is
`_EXAMPLE_PATH` at line 21 (`"examples" / "semantic"` → `"examples" / "agents" / "semantic"`).
Nothing else in the file hardcodes the path — but note line 82 reads the example's **source text**
(`_EXAMPLE_PATH.read_text()`) and asserts the string `"_pbac.available"` is absent, i.e. the test
polices how the example is *written*, not just what it does. The test also reaches into private
state (`facade._manager`, `facade._authorizers`, `semantic._pbac`, `semantic._models`) and
monkeypatches `parrot.semantic.handoff.datetime`, so any new example that wants the same regression
coverage will need equally white-box tests. `pytest.importorskip("duckdb")` at line 19 gates the
whole module.

## Citations
- `packages/ai-parrot-semantic/tests/test_example_agent.py:21` — `_EXAMPLE_PATH = Path(__file__).resolve().parents[3] / "examples" / "semantic" / "agent_semantic_example.py"` — **the single line a move breaks**
- `packages/ai-parrot-semantic/tests/test_example_agent.py:26-37` — `example()` module-scoped fixture — `importlib.util.spec_from_file_location("semantic_agent_example", _EXAMPLE_PATH)`, registers and pops `sys.modules[spec.name]`
- `packages/ai-parrot-semantic/tests/test_example_agent.py:19` — `pytest.importorskip("duckdb")`
- `packages/ai-parrot-semantic/tests/test_example_agent.py:77-83` — `test_pbac_is_wired_through_a_real_guard` — asserts `semantic._pbac.available is True`, the guard class name, and that the literal `"_pbac.available"` does not appear in the example's source
- `packages/ai-parrot-semantic/tests/test_example_agent.py:61-74` — `test_agent_has_semantic_and_guarded_facade_tools` — pins the tool names `sl_query_metrics`, `sl_save_result_as_dataset`, `guarded_dataset_query_dataset`, the absence of `guarded_dataset_publish` and of any `dataset_*` tool, and that `GovernedSinkRegistry().register(facade)` raises
- `packages/ai-parrot-semantic/tests/test_example_agent.py:40-44, 85-92` — `warehouse_env` fixture + `test_build_toolkits_does_not_mutate_environment` — depend on the module-level `CONNECTION_ENV` and `connection_env()` names staying exported
- `packages/ai-parrot-semantic/tests/test_example_agent.py:199-215` — `test_run_demo_succeeds_and_denial_can_fail` — monkeypatches `GuardedDatasetFacade._read` and asserts `run_demo` raises `RuntimeError("…unexpectedly read…")`
- `sdd/tasks/completed/TASK-4702-semantic-agent-example.md:29-31` — the task that created the three files, listing `examples/semantic/agent_semantic_example.py`, `examples/semantic/README.md`, `packages/ai-parrot-semantic/tests/test_example_agent.py`

## Notes
- The test module name `test_example_agent.py` is singular. If the proposal adds a second pinned
  example, decide whether to extend this file or add a sibling — the module-scoped `example` fixture
  makes extension awkward (it would need parametrising or a second fixture).
- `[cross-lane: type=git_log, intent=confirm whether examples/semantic/ was ever at another path, i.e. whether this is the first move]`

---

<!-- merged from FC-006 -->
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
