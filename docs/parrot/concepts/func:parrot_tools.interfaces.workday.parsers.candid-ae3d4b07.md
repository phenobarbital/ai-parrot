---
type: Concept
title: parse_candidate_applications()
id: func:parrot_tools.interfaces.workday.parsers.candidate_parsers.parse_candidate_applications
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Devuelve todas las postulaciones del candidato como una lista en 'applications'.
---

# parse_candidate_applications

```python
def parse_candidate_applications(candidate_data: Dict[str, Any]) -> Dict[str, Any]
```

Devuelve todas las postulaciones del candidato como una lista en 'applications'.
- Soporta Candidate_Job_Applied_To_Data y Job_Applied_To_Data.
- Conserva timestamps completos (no truncados) tal como vienen del SOAP.
- Incluye WIDs e IDs de Job Application y Job Requisition.
- Expone Disposition, Workflow Step, Source y descriptores cuando existan.
