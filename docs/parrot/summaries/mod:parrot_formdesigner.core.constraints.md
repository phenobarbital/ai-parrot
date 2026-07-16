---
type: Wiki Summary
title: parrot_formdesigner.core.constraints
id: mod:parrot_formdesigner.core.constraints
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Field constraints and conditional visibility rules for form fields.
relates_to:
- concept: class:parrot_formdesigner.core.constraints.ConditionOperator
  rel: defines
- concept: class:parrot_formdesigner.core.constraints.DependencyOperation
  rel: defines
- concept: class:parrot_formdesigner.core.constraints.DependencyRule
  rel: defines
- concept: class:parrot_formdesigner.core.constraints.FieldCondition
  rel: defines
- concept: class:parrot_formdesigner.core.constraints.FieldConstraints
  rel: defines
- concept: class:parrot_formdesigner.core.constraints.PostDependency
  rel: defines
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.core.constraints`

Field constraints and conditional visibility rules for form fields.

This module defines the data models for field-level constraints (min/max,
patterns, file size limits) and the dependency rule system that controls
conditional visibility and behavior.

## Classes

- **`FieldConstraints(BaseModel)`** — Constraints applied to a form field for validation.
- **`ConditionOperator(str, Enum)`** — Operators for field conditions in dependency rules.
- **`FieldCondition(BaseModel)`** — A single condition referencing another field's value.
- **`DependencyRule(BaseModel)`** — Rule controlling conditional visibility/behavior of a field or section.
- **`DependencyOperation(BaseModel)`** — An operation that computes or assigns a value from referenced field values.
- **`PostDependency(BaseModel)`** — A forward dependency: how a field's answered value affects a later field.
