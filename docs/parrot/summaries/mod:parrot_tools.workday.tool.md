---
type: Wiki Summary
title: parrot_tools.workday.tool
id: mod:parrot_tools.workday.tool
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Workday Toolkit - A unified toolkit for Workday SOAP operations with multi-service
  support.
relates_to:
- concept: class:parrot_tools.workday.tool.CustomReportInput
  rel: defines
- concept: class:parrot_tools.workday.tool.FindEmployeeByNameInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetCompanyPaymentDatesInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetOrganizationInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetPayrollBalancesInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetPayrollResultsInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetTimeOffBalanceInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetTimeOffBalanceInput2
  rel: defines
- concept: class:parrot_tools.workday.tool.GetTimeOffHistoryInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetWorkerContactInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetWorkerInfoInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetWorkerInput
  rel: defines
- concept: class:parrot_tools.workday.tool.GetWorkerJobDataInput
  rel: defines
- concept: class:parrot_tools.workday.tool.RequestTimeOffInput
  rel: defines
- concept: class:parrot_tools.workday.tool.SearchWorkersInput
  rel: defines
- concept: class:parrot_tools.workday.tool.WorkdayToolkit
  rel: defines
- concept: class:parrot_tools.workday.tool.WorkdayToolkitInput
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.http
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.interfaces.workday.config
  rel: references
- concept: mod:parrot_tools.interfaces.workday.service
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
- concept: mod:parrot_tools.workday.models
  rel: references
---

# `parrot_tools.workday.tool`

Workday Toolkit - A unified toolkit for Workday SOAP operations with multi-service support.

This toolkit wraps common Workday operations across multiple services (Human Resources,
Absence Management, Time Tracking, Staffing, Financial Management, and Recruiting) as
async tools, extending AbstractToolkit and using SOAPClient for SOAP/WSDL handling.

Features:
    - Multi-service WSDL support with automatic client routing
    - OAuth2 authentication with refresh_token grant
    - Redis token caching for performance
    - Automatic tool generation from public async methods
    - Lazy client initialization for optimal resource usage

Dependencies:
    - zeep
    - httpx
    - redis
    - pydantic

Example usage:
    # Single service (Human Resources only)
    toolkit = WorkdayToolkit(
        credentials={
            "client_id": "your-client-id",
            "client_secret": "your-client-secret",
            "token_url": "https://wd2-impl.workday.com/ccx/oauth2/token",
            "wsdl_path": "https://wd2-impl.workday.com/ccx/service/tenant/Human_Resources/v44.2?wsdl",
            "refresh_token": "your-refresh-token"
        },
        tenant_name="your_tenant"
    )

    # Multiple services with explicit WSDL paths
    toolkit = WorkdayToolkit(
        credentials={
            "client_id": "your-client-id",
            "client_secret": "your-client-secret",
            "token_url": "https://wd2-impl.workday.com/ccx/oauth2/token",
            "refresh_token": "your-refresh-token"
        },
        tenant_name="your_tenant",
        wsdl_paths={
            "human_resources": "https://wd2-impl.workday.com/ccx/service/tenant/Human_Resources/v44.2?wsdl",
            "absence_management": "https://wd2-impl.workday.com/ccx/service/tenant/Absence_Management/v45?wsdl",
            "time_tracking": "https://wd2-impl.workday.com/ccx/service/tenant/Time_Tracking/v44.2?wsdl",
            "staffing": "https://wd2-impl.workday.com/ccx/service/tenant/Staffing/v44.2?wsdl",
            "financial_management": "https://wd2-impl.workday.com/ccx/service/tenant/Financial_Management/v45?wsdl",
            "recruiting": "https://wd2-impl.workday.com/ccx/service/tenant/Recruiting/v44.2?wsdl"
        }
    )

    # Initialize the connection
    await toolkit.wd_start()

    # Use methods - appropriate client is selected automatically
    worker = await toolkit.wd_get_worker(worker_id="12345")
    time_off = await toolkit.wd_get_time_off_balance(worker_id="12345")

## Classes

- **`WorkdayToolkitInput(BaseModel)`** — Default configuration for Workday toolkit operations.
- **`GetWorkerInput(BaseModel)`** — Input for retrieving a single worker by ID.
- **`SearchWorkersInput(BaseModel)`** — Input for searching workers with filters.
- **`GetWorkerContactInput(BaseModel)`** — Input for retrieving worker contact information.
- **`GetOrganizationInput(BaseModel)`** — Input for retrieving organization information.
- **`GetWorkerJobDataInput(BaseModel)`** — Input for retrieving worker's job-related data.
- **`GetTimeOffBalanceInput(BaseModel)`** — Input for retrieving time off balance information.
- **`CustomReportInput(BaseModel)`** — Input for executing a Workday RaaS custom report.
- **`GetPayrollBalancesInput(BaseModel)`** — Input for retrieving payroll balances.
- **`GetPayrollResultsInput(BaseModel)`** — Input for retrieving payroll results (historical/off-cycle).
- **`GetCompanyPaymentDatesInput(BaseModel)`** — Input for retrieving company payment dates.
- **`FindEmployeeByNameInput(BaseModel)`** — Input for finding a worker by name.
- **`GetWorkerInfoInput(BaseModel)`** — Input for retrieving worker information by ID.
- **`GetTimeOffHistoryInput(BaseModel)`** — Input for retrieving a worker's time-off request history.
- **`GetTimeOffBalanceInput2(BaseModel)`** — Input for retrieving time off plan balances.
- **`RequestTimeOffInput(BaseModel)`** — Input for submitting a time-off request.
- **`WorkdayToolkit(AbstractToolkit)`** — Toolkit for interacting with Workday via SOAP/WSDL with multi-service support.
