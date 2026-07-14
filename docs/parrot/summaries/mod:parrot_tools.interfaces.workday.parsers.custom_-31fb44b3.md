---
type: Wiki Summary
title: parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers
id: mod:parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parsers for Workday Custom Punch - Field Report.
relates_to:
- concept: func:parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers.parse_custom_punch_field_report_data
  rel: defines
---

# `parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers`

Parsers for Workday Custom Punch - Field Report.

This module provides parsing functions to extract all fields from the SOAP response.

## Functions

- `def parse_custom_punch_field_report_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]` — Parse the raw Custom Punch - Field Report data from SOAP response.
