---
type: Wiki Summary
title: parrot_formdesigner.extractors.yaml
id: mod:parrot_formdesigner.extractors.yaml
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: YAML extractor for FormSchema generation.
relates_to:
- concept: class:parrot_formdesigner.extractors.yaml.YamlExtractor
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot_formdesigner.core.constraints
  rel: references
- concept: mod:parrot_formdesigner.core.options
  rel: references
- concept: mod:parrot_formdesigner.core.schema
  rel: references
- concept: mod:parrot_formdesigner.core.types
  rel: references
---

# `parrot_formdesigner.extractors.yaml`

YAML extractor for FormSchema generation.

Parses YAML form definitions into FormSchema instances. Supports both the
legacy format (used by existing form YAML files) and the new format with
full i18n, constraints, and dependency rules.

Uses yaml_rs (Rust) when available, falls back to PyYAML.

## Classes

- **`YamlExtractor`** — Parses YAML form definitions into FormSchema instances.
