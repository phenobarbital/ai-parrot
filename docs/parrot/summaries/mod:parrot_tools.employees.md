---
type: Wiki Summary
title: parrot_tools.employees
id: mod:parrot_tools.employees
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Employee Hierarchy Tool for AI-Parrot.
relates_to:
- concept: class:parrot_tools.employees.EmployeeAction
  rel: defines
- concept: class:parrot_tools.employees.EmployeesTool
  rel: defines
- concept: class:parrot_tools.employees.EmployeesToolArgsSchema
  rel: defines
- concept: mod:parrot.interfaces.hierarchy
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot_tools.employees`

Employee Hierarchy Tool for AI-Parrot.

Provides employee hierarchy operations as a unified tool interface
for AI agents and chatbots.

## Classes

- **`EmployeeAction(str, Enum)`** — Available employee hierarchy actions.
- **`EmployeesToolArgsSchema(AbstractToolArgsSchema)`** — Arguments schema for EmployeesTool.
- **`EmployeesTool(AbstractTool)`** — Employee Hierarchy Tool for querying organizational structure.
