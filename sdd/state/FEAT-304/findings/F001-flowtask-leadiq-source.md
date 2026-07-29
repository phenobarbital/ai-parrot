---
id: F001
query_id: Q001
type: read
intent: Read the flowtask LeadIQ source component to port
executed_at: 2026-07-13T00:00:00Z
duration_ms: 0
parent_id: null
depth: 0
---

# F001 — flowtask LeadIQ component (source to port)

## Summary

The source is a `FlowComponent`/`HTTPService` subclass driving the LeadIQ
**GraphQL** API at `https://api.leadiq.com/graphql`. It supports three
`type` searches — `company`, `employees`, `flat` — via three hardcoded
GraphQL query constants, executes them with `self.session(method="post",
url, data=json.dumps(payload), headers)`, then flattens each response into a
pandas DataFrame. Auth is `Authorization: Basic {LEADIQ_API_KEY}` plus
`apollo-require-preflight: true`. It is DataFrame-in / DataFrame-out (flowtask
pipeline semantics), which must be adapted to tool semantics on port.

## Citations

- path: `flowtask/components/LeadIQ.py`
  lines: 51-53
  symbol: `base_url`
  excerpt: |
    accept = "application/json"
    base_url = "https://api.leadiq.com"

- path: `flowtask/components/LeadIQ.py`
  lines: 56-300
  symbol: `COMPANY_SEARCH_QUERY / EMPLOYEE_SEARCH_QUERY / FLAT_SEARCH_QUERY`
  excerpt: |
    COMPANY_SEARCH_QUERY = "query SearchCompany($input: SearchCompanyInput!) {...}"
    EMPLOYEE_SEARCH_QUERY = "query GroupedAdvancedSearch($input: GroupedSearchInput!) {...}"
    FLAT_SEARCH_QUERY = "query FlatAdvancedSearch($input: FlatSearchInput!) {...}"

- path: `flowtask/components/LeadIQ.py`
  lines: 324-350
  symbol: `start`
  excerpt: |
    if not LEADIQ_API_KEY:
        raise ComponentError("LEADIQ_API_KEY not configured")
    self.headers = {'Authorization': f'Basic {LEADIQ_API_KEY}',
        'Content-Type': 'application/json', 'apollo-require-preflight': 'true'}

- path: `flowtask/components/LeadIQ.py`
  lines: 434-453
  symbol: `_execute_query`
  excerpt: |
    url = self.get_leadiq_url("graphql")
    args = {"method": "post", "url": url, "data": json.dumps(payload), "headers": self.headers}
    result, error = await self.session(**args)

- path: `flowtask/components/LeadIQ.py`
  lines: 455-617
  symbol: `_process_company_response / _process_employee_response / _process_flat_response`
  excerpt: |
    # company -> single flattened dict per company (search_term, found, name, domain,
    #   industry, naics_code, technologies[], employee_count, founded_year, location...)
    # employees/flat -> one row per person, company info merged in

## Notes

Reusable verbatim on port: the three GraphQL query strings and the three
`_process_*_response` transforms. The pandas DataFrame assembly (`run`) and
the FlowComponent input plumbing (`self.previous`, `self.input`, DataFrame
column extraction) are flowtask-specific and should be dropped.
