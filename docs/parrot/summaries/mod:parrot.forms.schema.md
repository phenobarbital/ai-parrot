---
type: Wiki Summary
title: parrot.forms.schema
id: mod:parrot.forms.schema
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Core form schema data models.
relates_to:
- concept: class:parrot.forms.schema.FormField
  rel: defines
- concept: class:parrot.forms.schema.FormSchema
  rel: defines
- concept: class:parrot.forms.schema.FormSection
  rel: defines
- concept: class:parrot.forms.schema.FormSubsection
  rel: defines
- concept: class:parrot.forms.schema.RenderedForm
  rel: defines
- concept: class:parrot.forms.schema.SubmitAction
  rel: defines
- concept: mod:parrot.forms.constraints
  rel: references
- concept: mod:parrot.forms.options
  rel: references
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.schema`

Core form schema data models.

This module defines the canonical Pydantic models for form structure:
FormField, FormSubsection, FormSection, SubmitAction, FormSchema, and
RenderedForm.  These models are the foundation of the entire forms
abstraction layer.

## Classes

- **`FormField(BaseModel)`** — A single field within a form section.
- **`FormSubsection(BaseModel)`** — A visual sub-grouping of fields within a section.
- **`FormSection(BaseModel)`** — A logical grouping of fields within a form.
- **`SubmitAction(BaseModel)`** — Defines what happens when a form is submitted.
- **`FormSchema(BaseModel)`** — The canonical representation of a complete form.
- **`RenderedForm(BaseModel)`** — Output of a form renderer.
