---
type: Wiki Summary
title: parrot.forms.constraints
id: mod:parrot.forms.constraints
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Field constraints and conditional visibility rules for form fields.
relates_to:
- concept: class:parrot.forms.constraints.ConditionOperator
  rel: defines
- concept: class:parrot.forms.constraints.DependencyRule
  rel: defines
- concept: class:parrot.forms.constraints.FieldCondition
  rel: defines
- concept: class:parrot.forms.constraints.FieldConstraints
  rel: defines
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.constraints`

Field constraints and conditional visibility rules for form fields.

This module defines the data models for field-level constraints (min/max,
patterns, file size limits) and the dependency rule system that controls
conditional visibility and behavior.

## Classes

- **`FieldConstraints(BaseModel)`** — Constraints applied to a form field for validation.
- **`ConditionOperator(str, Enum)`** — Operators for field conditions in dependency rules.
- **`FieldCondition(BaseModel)`** — A single condition referencing another field's value.
- **`DependencyRule(BaseModel)`** — Rule controlling conditional visibility/behavior of a field or section.
