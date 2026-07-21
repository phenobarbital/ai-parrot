---
type: Wiki Summary
title: parrot_tools.zipcode
id: mod:parrot_tools.zipcode
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: ZipcodeAPI Toolkit - A unified toolkit for zipcode operations.
relates_to:
- concept: class:parrot_tools.zipcode.BasicZipcodeInput
  rel: defines
- concept: class:parrot_tools.zipcode.CityToZipcodesInput
  rel: defines
- concept: class:parrot_tools.zipcode.ZipcodeAPIToolkit
  rel: defines
- concept: class:parrot_tools.zipcode.ZipcodeDistanceInput
  rel: defines
- concept: class:parrot_tools.zipcode.ZipcodeRadiusInput
  rel: defines
- concept: mod:parrot_tools.decorators
  rel: references
- concept: mod:parrot_tools.toolkit
  rel: references
---

# `parrot_tools.zipcode`

ZipcodeAPI Toolkit - A unified toolkit for zipcode operations.

## Classes

- **`BasicZipcodeInput(BaseModel)`** — Basic input schema for zipcode operations.
- **`ZipcodeDistanceInput(BaseModel)`** — Input schema for zipcode distance calculation.
- **`ZipcodeRadiusInput(BaseModel)`** — Input schema for zipcode radius search.
- **`CityToZipcodesInput(BaseModel)`** — Input schema for city to zipcodes lookup.
- **`ZipcodeAPIToolkit(AbstractToolkit)`** — Toolkit for interacting with ZipcodeAPI service.
