# F003 — Current WorkdayToolkit (in-line SOAP)
**Type:** read  **Confidence:** high
## Summary
`packages/ai-parrot-tools/src/parrot_tools/workday/tool.py` (1775 L) + `models.py` (1389 L).
- `WorkdaySOAPClient(SOAPClient)` (tool.py:350) builds references/criteria in-line (`_build_worker_reference`, `_build_request_criteria`, `_parse_worker_response`).
- `WorkdayToolkit(AbstractToolkit)` (tool.py:472) — lazy multi-WSDL client routing via METHOD_TO_SERVICE_MAP (tool.py:111).
- ~16 `wd_*` public async methods (wd_get_worker, wd_search_workers_by_name, wd_get_workers_by_manager, wd_get_time_off_balance, wd_run_custom_report, wd_get_payroll_*...). Each wraps SOAP build+call+parse IN-LINE — this is the per-method code the proposal wants to replace with the composable.
- Uses `@tool_schema(InputModel)` decorators (tool.py:707+).
## Citations
- tool.py:350,472,600-619 (lifecycle), 708-1600 (wd_* methods)
