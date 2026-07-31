---
type: Wiki Entity
title: YamlExtractor
id: class:parrot_formdesigner.extractors.yaml.YamlExtractor
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parses YAML form definitions into FormSchema instances.
---

# YamlExtractor

Defined in [`parrot_formdesigner.extractors.yaml`](../summaries/mod:parrot_formdesigner.extractors.yaml.md).

```python
class YamlExtractor
```

Parses YAML form definitions into FormSchema instances.

Supports two YAML formats:

Legacy format (backward compatible):
    - Fields use ``name`` and ``type`` keys
    - Validation rules use legacy names (min_length, max_length, etc.)
    - FieldType values use old names (choice, multichoice, toggle, textarea)
    - Section-level ``name`` and ``title`` keys

New format:
    - Fields use ``field_id`` and ``field_type`` keys
    - Constraints use the ``constraints`` block
    - Dependency rules use ``depends_on`` block
    - Labels/titles can be i18n dicts

Example:
    extractor = YamlExtractor()
    schema = extractor.extract_from_string(yaml_content)
    schema = extractor.extract_from_file("/path/to/form.yaml")

## Methods

- `def extract(self, content: str) -> FormSchema` — Parse YAML string content into a FormSchema.
- `def extract_from_string(self, content: str) -> FormSchema` — Parse YAML string content into a FormSchema.
- `def extract_from_file(self, path: str | Path) -> FormSchema` — Load and parse a YAML form definition file.
