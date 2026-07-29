---
type: Wiki Entity
title: WorkdayToolkit
id: class:parrot_tools.workday.tool.WorkdayToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Toolkit for interacting with Workday via SOAP/WSDL with multi-service support.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# WorkdayToolkit

Defined in [`parrot_tools.workday.tool`](../summaries/mod:parrot_tools.workday.tool.md).

```python
class WorkdayToolkit(AbstractToolkit)
```

Toolkit for interacting with Workday via SOAP/WSDL with multi-service support.

This toolkit provides async tools for Workday operations across multiple services:
- Human Resources: Worker management, organization queries, employment data
- Absence Management: Time off balances, leave requests
- Time Tracking: Timesheet operations (placeholder for future implementation)
- Staffing: Position management (placeholder for future implementation)
- Financial Management: Spend categories, worktags (placeholder for future implementation)
- Recruiting: Job requisitions, candidates (placeholder for future implementation)
- Payroll: Payroll balances, results, and payment dates

Each tool delegates to a vendored ``WorkdayComposable`` (``WorkdayService``)
that self-routes its WSDL from the ``operation_type``. Composable instances are
created lazily per operation_type in ``_get_composable`` and cached for reuse.

All public async methods automatically become tools via AbstractToolkit.

## Methods

- `async def wd_start(self) -> str` — Initialize the primary SOAP client connection.
- `async def start(self) -> str` — Compatibility wrapper for toolkit lifecycle start.
- `async def wd_close(self) -> None` — Close all composable connections.
- `async def wd_get_worker(self, worker_id: str, output_format: Optional[Type[BaseModel]]=None) -> Union[WorkerModel, BaseModel]` — Get detailed information about a specific worker by ID.
- `async def wd_search_workers(self, search_text: Optional[str]=None, manager_id: Optional[str]=None, location_id: Optional[str]=None, job_profile_id: Optional[str]=None, hire_date_from: Optional[str]=None, hire_date_to: Optional[str]=None, max_results: int=100) -> List[Dict[str, Any]]` — Search for workers based on various criteria.
- `async def wd_get_worker_contact(self, worker_id: str, include_personal: bool=True, include_work: bool=True, output_format: Optional[Type[BaseModel]]=None) -> Dict[str, Any]` — Get contact information for a specific worker.
- `async def wd_get_worker_job_data(self, worker_id: str, effective_date: Optional[str]=None) -> Dict[str, Any]` — Get job-related data for a worker.
- `async def wd_get_organization(self, org_id: str, include_hierarchy: bool=False) -> Dict[str, Any]` — Get organization information by ID.
- `async def wd_get_worker_time_off_balance(self, worker_id: str, output_format: Optional[Type[BaseModel]]=None) -> Dict[str, Any]` — Get time off balance for a worker.
- `async def wd_get_time_off_balance(self, worker_id: str, time_off_plan_id: Optional[str]=None, output_format: Optional[Type[BaseModel]]=None) -> Union[Dict[str, Any], BaseModel]` — Get time off plan balances for a worker using Absence Management API.
- `async def wd_run_custom_report(self, report_name: str, report_owner: Optional[str]=None, params: Optional[Dict[str, Any]]=None, query_string_template: Optional[str]=None, flatten_list_dicts: bool=False, drop_flattened_columns: bool=False) -> List[Dict[str, Any]]` — Execute a Workday RaaS (Reports as a Service) custom report via REST.
- `async def wd_get_workers_by_organization(self, org_id: str, output_format: Optional[Type[BaseModel]]=None, include_subordinate: bool=True, exclude_inactive: bool=True, max_results: int=100) -> List[Dict[str, Any]]` — Get all workers in an organization.
- `async def wd_get_workers_by_ids(self, worker_ids: List[str], id_type: str='Employee_ID') -> List[Dict[str, Any]]` — Get multiple workers by their IDs.
- `async def wd_search_workers_by_name(self, name: str, max_results: int=100, search_type: str='Contains') -> List[Dict[str, Any]]` — Search workers by name using Field_And_Parameter_Criteria.
- `async def wd_get_workers_by_manager(self, manager_id: str, include_indirect_reports: bool=False, max_results: int=100) -> List[Dict[str, Any]]` — Get all workers reporting to a manager.
- `async def wd_get_inactive_workers(self, org_id: Optional[str]=None, termination_date_from: Optional[str]=None, termination_date_to: Optional[str]=None, max_results: int=100) -> List[Dict[str, Any]]` — Get terminated/inactive workers.
- `async def wd_get_payroll_balances(self, worker_id: str, start_date: Optional[str]=None, end_date: Optional[str]=None, pay_component_group_ids: Optional[List[str]]=None) -> Dict[str, Any]` — Get payroll balances for a worker.
- `async def wd_get_payroll_results(self, worker_id: str, start_date: Optional[str]=None, end_date: Optional[str]=None, include_details: bool=False) -> List[Dict[str, Any]]` — Get payroll results (historical/off-cycle) for a worker.
- `async def wd_get_company_payment_dates(self, start_date: str, end_date: str, pay_group_id: Optional[str]=None) -> List[Dict[str, Any]]` — Get company payment dates.
- `async def find_employee_id_by_name(self, name: str, max_results: int=50) -> List[Dict[str, Any]]` — Find Workday employee IDs and names matching a worker name.
- `async def get_current_user_info(self, worker_id: str) -> Dict[str, Any]` — Get comprehensive Workday information for a worker.
- `async def get_more_employee_data(self, worker_id: str) -> Dict[str, Any]` — Get extended employee data from Workday including benefits, roles, and documents.
- `async def get_personal_information(self, worker_id: str) -> Dict[str, Any]` — Get personal information for a Workday worker.
- `async def get_direct_reports(self, worker_id: str) -> List[Dict[str, Any]]` — Get the direct reports (subordinates) of a manager in Workday.
- `async def get_time_off_balance(self, worker_id: str, time_off_plan_id: Optional[str]=None) -> List[Dict[str, Any]]` — Get time off plan balances for a worker.
- `async def get_current_user_time_off_balance(self, worker_id: str) -> List[Dict[str, Any]]` — Get all time off plan balances for a worker (all plans).
- `async def get_current_user_time_off_history(self, worker_id: str, start_date: Optional[str]=None, end_date: Optional[str]=None) -> List[Dict[str, Any]]` — Get time off request history for a worker.
- `async def get_today_date_and_day_of_week(self) -> Dict[str, str]` — Return today's ISO date and the day of the week name.
- `async def request_my_time_off(self, worker_id: str, start_date: str, end_date: str, time_off_type: str, daily_quantity: float=8.0, comment: Optional[str]=None, dry_run: bool=True) -> Dict[str, Any]` — Submit a time-off request in Workday on behalf of a worker.
- `async def get_my_time_off_eligibility(self, worker_id: str) -> List[Dict[str, Any]]` — Get the time-off types a worker is eligible to request in Workday.
