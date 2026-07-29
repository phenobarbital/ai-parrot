---
type: Wiki Summary
title: parrot.interfaces.images.plugins.classify
id: mod:parrot.interfaces.images.plugins.classify
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Module parrot.interfaces.images.plugins.classify
relates_to:
- concept: class:parrot.interfaces.images.plugins.classify.ClassificationPlugin
  rel: defines
- concept: class:parrot.interfaces.images.plugins.classify.ImageCategory
  rel: defines
- concept: class:parrot.interfaces.images.plugins.classify.ImageClassification
  rel: defines
- concept: mod:parrot.clients.google
  rel: references
- concept: mod:parrot.interfaces.images.plugins.abstract
  rel: references
---

# `parrot.interfaces.images.plugins.classify`

## Classes

- **`ImageCategory(str, Enum)`** — Enumeration for retail image categories.
- **`ImageClassification(BaseModel)`** — Schema for classifying a retail image.
- **`ClassificationPlugin(ImagePlugin)`** — ClassificationPlugin is a plugin for performing image classification.

## Functions

- `def is_model_class(cls) -> bool`
- `def is_enum_class(cls) -> bool`
