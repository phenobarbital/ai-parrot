---
type: Wiki Entity
title: EmployeeHierarchyManager
id: class:parrot.interfaces.hierarchy.EmployeeHierarchyManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Hierarchy Manager using ArangoDB to store employees and their reporting structure.
relates_to:
- concept: class:parrot.memory.cache.CacheMixin
  rel: extends
---

# EmployeeHierarchyManager

Defined in [`parrot.interfaces.hierarchy`](../summaries/mod:parrot.interfaces.hierarchy.md).

```python
class EmployeeHierarchyManager(CacheMixin)
```

Hierarchy Manager using ArangoDB to store employees and their reporting structure.
It supports importing from PostgreSQL, inserting individual employees,
and performing hierarchical queries like finding superiors, subordinates, and colleagues.

Attributes:
    arango_host (str): Hostname for ArangoDB server.
    arango_port (int): Port for ArangoDB server.
    db_name (str): Name of the ArangoDB database to use.
    username (str): Username for ArangoDB authentication.
    password (str): Password for ArangoDB authentication.
    employees_collection (str): Name of the collection for employee vertices.

## Methods

- `async def connection(self)` — Async context manager for ArangoDB connection
- `async def drop_all_indexes(self)` — Drop all user-defined indexes from the employees collection.
- `async def import_from_postgres(self)` — Import employees from PostgreSQL
- `async def truncate_hierarchy(self) -> None` — Truncate employees and reports_to collections.
- `async def insert_employee(self, employee: Employee) -> str` — Insert an individual employee
- `async def does_report_to(self, employee_oid: str, boss_oid: str, limit: int=1) -> bool` — Check if employee_oid reports directly or indirectly to boss_oid.
- `async def get_all_superiors(self, employee_oid: str) -> List[Dict]` — Return all superiors of an employee up to the CEO.
- `async def get_direct_reports(self, boss_oid: str) -> List[Dict]` — Return direct reports of a boss
- `async def get_all_subordinates(self, boss_oid: str, max_depth: int=10) -> List[Dict]` — Return all subordinates (direct and indirect) of a boss
- `async def get_org_chart(self, root_oid: Optional[str]=None) -> Dict` — Build the complete org chart as a hierarchical tree
- `async def get_colleagues(self, employee_oid: str) -> List[Dict[str, Any]]` — Return colleagues (employees who share the same boss)
- `async def get_employee_info(self, employee_oid: str) -> Optional[Dict]` — Get detailed information about an employee.
- `async def get_department_context(self, employee_oid: str) -> Dict` — Get a summary of the employee's department context, including
- `async def are_in_same_department(self, employee1: str, employee2: str) -> bool` — Check if two employees are in the same department (broader than colleagues).
- `async def get_team_members(self, manager_id: str, include_all_levels: bool=False) -> List[Dict[str, Any]]` — Get all team members under a manager.
- `async def are_colleagues(self, employee1: str, employee2: str) -> bool` — Check if two employees are colleagues (same boss, same level).
- `async def is_manager(self, employee_oid: str) -> bool` — Check if the given employee is a manager (has direct reports).
- `async def get_closest_common_boss(self, employee1: str, employee2: str) -> Optional[Dict]` — Find the closest common boss between two employees.
- `async def is_boss_of(self, employee_oid: str, boss_oid: str, direct_only: bool=False) -> Dict[str, Any]` — Check if boss_oid is a boss (direct or indirect) of employee_oid.
- `async def is_subordinate(self, employee_oid: str, manager_oid: str, direct_only: bool=False) -> Dict[str, Any]` — Check if employee_oid is a subordinate of manager_oid.
- `async def get_relationship(self, employee1: str, employee2: str) -> Dict[str, Any]` — Get the complete relationship between two employees.
- `async def check_management_chain(self, employee_id: str, target_manager_id: str) -> Dict[str, Any]` — Check if target_manager_id is anywhere in employee's management chain.
