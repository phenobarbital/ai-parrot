---
type: Concept
title: parse_custom_punch_field_report_data()
id: func:parrot_tools.interfaces.workday.parsers.custom_punch_field_report_parsers.parse_custom_punch_field_report_data
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Parse the raw Custom Punch - Field Report data from SOAP response.
---

# parse_custom_punch_field_report_data

```python
def parse_custom_punch_field_report_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]
```

Parse the raw Custom Punch - Field Report data from SOAP response.

Args:
    raw_data: List of Report_Entry dictionaries from the SOAP response

Returns:
    List of parsed custom punch field report entry dictionaries
