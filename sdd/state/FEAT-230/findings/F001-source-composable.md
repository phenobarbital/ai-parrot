# F001 — Source composable: flowtask WorkdayService interface
**Type:** read/tree  **Confidence:** high
## Summary
Source at `/home/jesuslara/proyectos/parallel/flowtask/flowtask/interfaces/workday/` is a mature, SDD-built composable (FEAT-027, TASK-101..105). 60 files, ~16.6k LOC.
- `service.py:111` `class WorkdayService(SOAPClient)` — public API: `fetch(op,**p)->pd.DataFrame`, `fetch_models()->list[Model]`, `get_custom_report()`, `call_operation()`, `start()/close()`.
- Eager handler registry (service.py:218-243) maps ~23 operation_types → handler instances.
- Subdirs: `handlers/` (per-entity, WorkdayTypeBase.execute), `models/` (Pydantic), `parsers/` (SOAP→model), `config.py` (WorkdayConfig + get_wsdl_path), `utils/`.
## Citations
- service.py:33 `from flowtask.interfaces.SOAPClient import SOAPClient`
- service.py:30 `import pandas as pd` (fetch returns DataFrame)
- service.py:218-243 handler registry
## Notes
External deps beyond workday pkg: `pandas`, `zeep.helpers`, `flowtask.interfaces.SOAPClient`, `flowtask.conf`.
