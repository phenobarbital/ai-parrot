# §4d citation probe — results (HEAD 7e6741f13)

57 checks across 2 probe agents + 1 inline re-check. **No fabricated path or symbol.**

| Status | Count | Notes |
|---|---|---|
| verified | 54 | exact line numbers recorded below |
| stale (signature refined) | 1 | c23 `handle_owner` |
| inconclusive → re-verified inline | 1 | c40 `pytest.ini testpaths` |
| ambiguous (broad anchor by design) | 6 | c4, c29, c30, c36, c41, c49 — multi-hit substrings; the cited lines are all present in the hit list, so the underlying claims stand |

## Stale
- **c23** → F008. Finding cited `handle_owner(handle) -> tuple[str, str, str, str]`.
  Actual: `handoff.py:46` — `def handle_owner(handle: ResultHandle) -> tuple[str, str, str, str]:`
  (parameter is annotated). Claim otherwise correct.

## Inconclusive, resolved inline
- **c40** → F007. The probe's fixed command was `grep -rnw 'testpaths' pytest.ini --include=*.py`,
  whose `--include=*.py` filter excludes `pytest.ini` itself — the empty result was an artifact,
  not evidence. Re-checked inline: `pytest.ini` (19 lines) contains no `testpaths`, no
  `norecursedirs`; `grep -nE 'testpaths|norecursedirs|collect_ignore' pytest.ini conftest.py`
  exits 1. **Claim VERIFIED**: `examples/` is pytest-collected.

## Key verified anchors (line numbers confirmed at HEAD)
toolkit.py: `tool_prefix = "sl"`:41 · `__init__(self, **kwargs: Any)`:44 · `allow_raw_sql`:63,69,70,97,104,469 ·
`static_subject_forbidden`:67 · `guard_required`:79 · list_models:123 · list_metrics:138 · get_dimensions:147 ·
get_dimension_values:158 · search_data_model:165 · list_saved_queries:183 · compile_query:195 · query_metrics:200 ·
run_sql:451 · save_result_as_dataset:546
context.py: SemanticRequestIdentity:18 · current_pctx:44 · require_identity:62 · bind_semantic_context:86
models.py: SemanticQuery:102 · `ConfigDict(extra="forbid")`:105 · SemanticQueryResult:217
handoff.py: GovernedDatasetSink(Protocol):34 · handle_owner:46 · GovernedSinkRegistry:74 · build_read_authorizer:159
bootstrap.py: StaticSubject:23 · LocalSemanticLayerToolkit:60 · results.py ResultHandle:23
__init__.py:7 — `__all__ = ["__version__", "SemanticQuery", "SemanticQueryResult", "SemanticLayerToolkit"]`
handlers/semantic.py: SemanticLayerHandler(BaseView):18
test_example_agent.py: importorskip:19 · _EXAMPLE_PATH:21 · spec_from_file_location:29
examples/semantic/README.md:3 · examples/semantic/agent_semantic_example.py CONNECTION_ENV:29, GuardedDatasetFacade:35, connection_env:268, build_toolkits:285, build_agent:314
ruff.toml:68 line-length=120 · ruff.toml:152 examples per-file-ignores
ci.yml:535 `uv sync --all-packages --extra duckdb` · ci.yml:536 `uv run pytest packages/ai-parrot-semantic/tests -q --tb=short`
pytest.ini:3 asyncio_mode=auto · docs/tools/semantic-layer.md:123 · test_mcp_local.py:26 `_DOC_PATH`
hooba_agent.py: Usage:::3 · --smoke:5,44,64 · asyncio.run(main()):78
**ABSENT (confirmed)**: `examples/agents/semantic` does not exist.
