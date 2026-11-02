# FC-005 — `examples/agents/` house style: module docstring with a `Usage::` block, top-level helper functions, `if __name__ == "__main__": asyncio.run(main())`, per-subdir README

**Query**: Q010 · **Type**: tree+read · **Depth**: 0

## Summary
`examples/agents/` holds loose top-level scripts plus seven themed subdirectories
(`a2ui/`, `aws/`, `finance/`, `oauth/`, `webbrowser/`, `a2ui/linked_e2e/`) — there is no `semantic/`.
The dominant modern style (FEAT-era files: `finance/hooba_agent.py`, `webbrowser/webbrowsing_agent.py`,
`aws/agent_*.py`) is: a long module docstring opening with a one-line purpose and a `Usage::` block
naming the exact `python examples/agents/<dir>/<file>.py …` command and the env vars needed; a
module-level `SYSTEM_PROMPT` triple-quoted constant; small top-level `build_*` factory functions;
`async def main()` with `argparse` when there are modes; `if __name__ == "__main__": asyncio.run(main())`.
**No shebang** on any of them. Agent construction is `Agent(name=..., system_prompt=..., tools=toolkit.get_tools())`
followed by `await agent.configure()` then `await agent.ask(prompt)`. Themed subdirectories carry
their own `README.md` (`aws/README.md` 390 lines, `a2ui/README.md` 180 lines) — so
`examples/agents/semantic/README.md` is the expected home for the moved README.
Crucially, the newer, reviewed examples (`hooba_agent.py`) offer a deterministic **`--smoke` mode
that runs without an LLM**, which is the house precedent for the current semantic example's
scripted path. Older files (`examples/db_tool_usage.py`, `examples/basic_agent.py`) use bare
`print()` and no type hints; they are NOT the bar to copy — `.claude/rules/codebase-conventions.md`
forbids `print` and the semantic example already uses `logging`.

## Citations
- `examples/agents/finance/hooba_agent.py:1-7` — module docstring with `Usage::` and both a `--smoke` and a prompt invocation
- `examples/agents/finance/hooba_agent.py:20-32` — `logger = logging.getLogger(__name__)`, `SYSTEM_PROMPT` constant, `build_toolkit(settings=None) -> HoobaToolkit`
- `examples/agents/finance/hooba_agent.py:35-39` — `async def smoke(toolkit) -> Dict[str, Any]` — the deterministic no-LLM path
- `examples/agents/finance/hooba_agent.py:42-78` — `argparse` `main()` + `Agent(name=..., system_prompt=..., tools=toolkit.get_tools())` + `await agent.configure()` + `await agent.ask(...)` + `asyncio.run(main())`
- `examples/agents/webbrowser/webbrowsing_agent.py:1-36` — same shape; note `DEFAULT_CATALOG = Path(__file__).parents[2] / "webbrowsing" / "catalog"` — the precedent for an example referencing sibling fixture data by `Path(__file__)`
- `examples/agents/aws/agent_nova_pro.py:1-41` — docstring with `Usage:`, `Environment Variables:`, model facts, and a pointer to the subdir README; `from parrot.tools import tool` + `@tool`-decorated functions
- `examples/agents/finance/` , `examples/agents/aws/` , `examples/agents/webbrowser/` , `examples/agents/oauth/` , `examples/agents/a2ui/` — the five themed subdirectories; `aws/README.md` and `a2ui/README.md` are the per-subdir README precedent
- `examples/basic_agent.py:1-16` and `examples/db_tool_usage.py:1-132` — the older `print()`-based style, cited as the pattern NOT to follow

## Notes
- `examples/agents/` contains five files literally named `test_*.py` (`test_map.py`, `test_mcp.py`,
  `test_mcp_client.py`, `test_mcp_server.py`, `test_stdio.py`) with a live `__pycache__` of
  pytest-compiled `.pyc`s — pytest **has** collected this tree. See FC-008: do not name any new
  example file `test_*.py`.
- `examples/agents/a2ui/__pycache__` and `examples/agents/__pycache__` are untracked build residue, not a convention.
