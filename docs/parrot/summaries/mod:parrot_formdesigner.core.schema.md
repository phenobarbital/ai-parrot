---
type: Wiki Summary
title: parrot_formdesigner.core.schema
id: mod:parrot_formdesigner.core.schema
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Core form schema data models.
relates_to:
- concept: class:parrot_formdesigner.core.schema.FormField
  rel: defines
- concept: class:parrot_formdesigner.core.schema.FormMetadataField
  rel: defines
- concept: class:parrot_formdesigner.core.schema.FormSchema
  rel: defines
- concept: class:parrot_formdesigner.core.schema.FormSection
  rel: defines
- concept: class:parrot_formdesigner.core.schema.FormSubsection
  rel: defines
- concept: class:parrot_formdesigner.core.schema.FormType
  rel: defines
- concept: class:parrot_formdesigner.core.schema.RenderWarning
  rel: defines
- concept: class:parrot_formdesigner.core.schema.RenderedForm
  rel: defines
- concept: class:parrot_formdesigner.core.schema.SubmitAction
  rel: defines
- concept: mod:parrot_formdesigner.core.auth
  rel: references
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.events
  rel: references
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
- concept: mod:parrot_formdesigner.services._identifiers
  rel: references
---

# `parrot_formdesigner.core.schema`

Core form schema data models.

This module defines the canonical Pydantic models for form structure:
FormField, FormSubsection, FormSection, SubmitAction, FormSchema, and
RenderedForm.  These models are the foundation of the entire forms
abstraction layer.

## Classes

- **`FormType(str, Enum)`** — Discriminator for the form's structural type.
- **`FormField(BaseModel)`** — A single field within a form section.
- **`FormSubsection(BaseModel)`** — A visual sub-grouping of fields within a section.
- **`FormSection(BaseModel)`** — A logical grouping of fields within a form.
- **`SubmitAction(BaseModel)`** — Defines what happens when a form is submitted.
- **`FormMetadataField(BaseModel)`** — Declared contextual metadata captured on every form submission.
- **`FormSchema(BaseModel)`** — The canonical representation of a complete form.
- **`RenderWarning(BaseModel)`** — Warning emitted when a renderer uses degraded fallback for a field type.
- **`RenderedForm(BaseModel)`** — Output of a form renderer.
