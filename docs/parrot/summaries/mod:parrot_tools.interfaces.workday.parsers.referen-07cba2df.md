---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.reference_parsers
id: mod:parrot_tools.interfaces.workday.parsers.reference_parsers
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parsers for Workday Get_References (Integrations service) responses.
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.reference_parsers.parse_reference_data
  rel: defines
- concept: mod:parrot_tools.interfaces.workday.utils
  rel: references
---

# `parrot_tools.interfaces.workday.parsers.reference_parsers`

Parsers for Workday Get_References (Integrations service) responses.

## Functions

- `def parse_reference_data(reference: Dict[str, Any]) -> Dict[str, Any]` — Parse one ``Reference_ID`` element from a Get_References response.
