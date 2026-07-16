---
type: Wiki Summary
title: parrot.interfaces.hierarchy
id: mod:parrot.interfaces.hierarchy
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Utilities for managing the employee hierarchy stored in ArangoDB.
relates_to:
- concept: class:parrot.interfaces.hierarchy.Employee
  rel: defines
- concept: class:parrot.interfaces.hierarchy.EmployeeHierarchyManager
  rel: defines
- concept: mod:parrot._imports
  rel: references
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.memory.cache
  rel: references
---

# `parrot.interfaces.hierarchy`

Utilities for managing the employee hierarchy stored in ArangoDB.

## Classes

- **`Employee`** — Employee Information
- **`EmployeeHierarchyManager(CacheMixin)`** — Hierarchy Manager using ArangoDB to store employees and their reporting structure.
