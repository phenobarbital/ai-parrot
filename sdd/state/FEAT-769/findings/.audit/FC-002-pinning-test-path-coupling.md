# FC-002 — The pinning test loads the example by filesystem path (`parents[3]`), so a move needs exactly one line changed — but it also asserts on the example's *source text*

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
