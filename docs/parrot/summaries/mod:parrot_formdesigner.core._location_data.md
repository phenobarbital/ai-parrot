---
type: Wiki Summary
title: parrot_formdesigner.core._location_data
id: mod:parrot_formdesigner.core._location_data
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Offline country reference data via pycountry.
relates_to:
- concept: func:parrot_formdesigner.core._location_data.get_country_info
  rel: defines
- concept: func:parrot_formdesigner.core._location_data.is_valid_iso_country_code
  rel: defines
- concept: func:parrot_formdesigner.core._location_data.list_country_options
  rel: defines
- concept: mod:parrot_formdesigner.core.options
  rel: references
---

# `parrot_formdesigner.core._location_data`

Offline country reference data via pycountry.

Wraps pycountry to provide helpers used by the LOCATION field type
validator and JSON Schema extractor. No network calls — all data is
bundled with the pycountry package.

If pycountry is not installed, functions degrade gracefully:
- `is_valid_iso_country_code` returns True (validation skipped).
- `get_country_info` returns None.
- `list_country_options` returns an empty list.

## Functions

- `def is_valid_iso_country_code(code: str) -> bool` — Return True if code is a valid ISO 3166-1 alpha-2 country code.
- `def get_country_info(code: str) -> dict | None` — Return name, flag emoji, and dial code for a country code.
- `def list_country_options() -> list[FieldOption]` — Return all countries as a FieldOption list sorted by name.
