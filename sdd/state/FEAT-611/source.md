---
kind: inline
jira_key: null
fetched_at: 2026-09-28T20:05:00Z
summary_oneline: Parallel A2UI linked-surfaces E2E examples reusing FEAT-610 infrastructure to exercise other FEAT-598 capabilities/datasets
---

# A2UI Linked surfaces End 2 End test (parallel track)

Contexto (chat con Jesús Lara, 2026-09-28):

> estoy creando un sample test end-2-end que dije
> FEAT-598 está en DEV pero no lo he probado
> si quieres hacer una prueba e2e alternativa te lo agradezco
> así dos personas prueban mejor que una

Jesús creó FEAT-610 (`sdd/proposals/a2ui-linked-e2e-test.proposal.md`): ejemplo E2E
sobre `polestar_graduates_directory` (KPIs, bar/pie charts, grid.js, refresh por widget
vía `/api/v3/queries/{slug}`, BasicAuth, `examples/a2ui/{server,client}.py`).

Petición (Javier León): una prueba E2E **paralela** e independiente que tome lo que
FEAT-610 construye (servidor aiohttp + QuerySource + AuthHandler, renderer, helper de
dashboard multi-widget) como base para construir **otros ejemplos** de linked surfaces,
de modo que dos personas validen FEAT-598 desde ángulos distintos. FEAT-610 es contexto,
no algo a re-ejecutar.
