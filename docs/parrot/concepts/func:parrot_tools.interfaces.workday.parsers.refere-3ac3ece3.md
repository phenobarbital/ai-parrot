---
type: Concept
title: parse_reference_data()
id: func:parrot_tools.interfaces.workday.parsers.reference_parsers.parse_reference_data
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Parse one ``Reference_ID`` element from a Get_References response.
---

# parse_reference_data

```python
def parse_reference_data(reference: Dict[str, Any]) -> Dict[str, Any]
```

Parse one ``Reference_ID`` element from a Get_References response.

The Workday payload looks like::

    <wd:Reference_ID wd:Descriptor="Time Calculation Tag">
      <wd:Reference_ID_Reference>
        <wd:ID wd:type="WID">…</wd:ID>
        <wd:ID wd:type="Time_Calculation_Tag_ID">CAN_Statutory_Holiday</wd:ID>
      </wd:Reference_ID_Reference>
      <wd:Reference_ID_Data>
        <wd:ID>CAN_Statutory_Holiday</wd:ID>
        <wd:Reference_ID_Type>Time_Calculation_Tag_ID</wd:Reference_ID_Type>
        <wd:Referenced_Object_Descriptor>CAN Statutory Holiday</wd:Referenced_Object_Descriptor>
      </wd:Reference_ID_Data>
    </wd:Reference_ID>
