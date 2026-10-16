# F004 — MCP / transport / remote wiring (type: grep)
Citations: ledger/operations.py:1-129; wiki/transport.py:22-32,143-147,381-404,446-447; wiki/remote.py:16-30;
           wiki/tools.py:16; packages/ai-parrot-tools/src/parrot_tools/wiki/tools.py:31,346-355
- Framework-free ops `op_ledger_{open,ready,claim,close,context}` + Pydantic `Ledger*Input` models in operations.py.
- transport.py `_SPECS` registers 5 ledger tools (mount="ledger") and dispatches by name.
- remote.py `READ_ONLY_TOOLS` includes ledger_ready, ledger_context — a new read tool must be added here to be proxied.
- Two tool adapter layers: parrot/knowledge/wiki/tools.py and parrot_tools/wiki/tools.py (class per tool, name="ledger_ready").
- Tests: tests/knowledge/wiki/test_cli_ledger.py (436 lines), tests/knowledge/wiki/test_ledger_tools.py, tests/sdd/test_ledger_lifecycle_acceptance.py.
