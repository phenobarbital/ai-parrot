---
kind: inline
jira_key: null
fetched_at: 2026-10-16
summary_oneline: /sdd-done should report a table of tests run/passed in the PR body as an approval metric
---
cada sdd-worker o sdd-coder ejecuta tests sobre el codigo para determinar si todo va bien y en algunos casos sdd-worker ejecuta todos los tests asociados al current spec para determinar que todo funciona, pero esto no se está reportando en el commit message del pull-request creado por sdd-done, considero útil que sdd-done reporte en una tabla la cantidad de tests aplicados y aprobados que este codigo tiene como una metrica visible para poder aprobar dicho spec.
