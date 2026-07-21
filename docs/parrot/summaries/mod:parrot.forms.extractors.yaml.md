---
type: Wiki Summary
title: parrot.forms.extractors.yaml
id: mod:parrot.forms.extractors.yaml
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: YAML extractor for FormSchema generation.
relates_to:
- concept: class:parrot.forms.extractors.yaml.YamlExtractor
  rel: defines
- concept: mod:parrot
  rel: references
- concept: mod:parrot.forms.constraints
  rel: references
- concept: mod:parrot.forms.options
  rel: references
- concept: mod:parrot.forms.schema
  rel: references
- concept: mod:parrot.forms.types
  rel: references
---

# `parrot.forms.extractors.yaml`

YAML extractor for FormSchema generation.

Parses YAML form definitions into FormSchema instances. Supports both the
legacy format (used by existing form YAML files) and the new format with
full i18n, constraints, and dependency rules.

Uses yaml_rs (Rust) when available, falls back to PyYAML.

## Classes

- **`YamlExtractor`** — Parses YAML form definitions into FormSchema instances.
