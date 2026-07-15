---
type: Wiki Entity
title: EmployeesTool
id: class:parrot_tools.employees.EmployeesTool
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Employee Hierarchy Tool for querying organizational structure.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# EmployeesTool

Defined in [`parrot_tools.employees`](../summaries/mod:parrot_tools.employees.md).

```python
class EmployeesTool(AbstractTool)
```

Employee Hierarchy Tool for querying organizational structure.

This tool provides unified access to employee hierarchy operations through
the EmployeeHierarchyManager interface. It supports various queries including:
- Reporting relationships (managers, subordinates)
- Peer relationships (colleagues)
- Department and organizational context
- Hierarchical comparisons

Example Usage:
    ```python
    # Initialize the tool
    hierarchy_manager = EmployeeHierarchyManager(...)
    employees_tool = EmployeesTool(hierarchy_manager=hierarchy_manager)

    # Register with an agent
    agent.add_tool(employees_tool)

    # Query examples:
    # "Who is John's manager?"
    # "Get all employees reporting to Mary"
    # "Are Alice and Bob colleagues?"
    # "Show me the department context for employee E12345"
    ```

Args:
    hierarchy_manager: Instance of EmployeeHierarchyManager
    name: Tool name (default: "employees_hierarchy")
    description: Tool description
    **kwargs: Additional arguments passed to AbstractTool
