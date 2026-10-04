---
kind: inline
jira_key: null
fetched_at: 2026-09-28T20:15:00Z
summary_oneline: Self-contained E2E example — agent-built A2UI linked-surface dashboard (KPIs, charts, grid) over one query-slug, refreshable via QuerySource
---

# A2UI Linked surfaces End 2 End test

Ahora que FEAT-598 — A2UI Linked Surfaces ha aterrizado en dev, necesitamos crear un ejemplo End to End encapsulado (sin dependencias externas a ai-parrot) dónde a partir de 1 query-slug aportados, vamos a crear una surface A2UI de dashboard con widgets (Hero Cards con KPIs), unas charts y finalizando con una grilla "filtrable" mostrando uno de los query-slugs como una tabla tipo grilla.
La finalidad es una prueba inicial de que una surface A2UI de linked surfaces crea objetos conectados a query-slugs que son refrescables.

## Query

Query-slug: polestar_graduates_directory

### Columnas en el query-slug (fila de ejemplo)

```json
{
  "student_uid": "71d6c31f-d807-4965-9870-6f56aaccbf59",
  "first_name": "Xinyue", "last_name": "Yang", "full_name": "Yang Xin Yue",
  "email_address": "2218335612@qq.com", "phone": "13011265900.0",
  "city": null, "state": null, "country": "China", "postal_code": null,
  "street_address": null, "birth_date": null, "pronouns": null,
  "donotcall": null, "emailoptout": null, "website": null,
  "instagramusername": null, "facebookusername": null, "linkedinusername": null,
  "twitterusername": null, "longbio": null, "bio": null, "shortbio": null,
  "licensee": "Asia", "educator": null, "student": null,
  "services_especialities": null, "credentials": null,
  "last_requal_date": null, "last_diploma_date": "2025-09-19",
  "is_requalified": true,
  "graduation_details": [
    {"course": "Pilates Studio", "category": "Comprehensive",
     "course_date": "2025-09-19", "diploma_number": "POL15058"}
  ]
}
```

### Secciones a definir

#### Hero-card: KPIs
- conteo total de filas (número real: 17572) → `{ "fields": ["count(*)"] }`
- Pilates Studio graduates → `{ "fields": ["count(*)"], "filter": {"graduation_details": {"@>": [{"course": "Pilates Studio"}]}} }`
- Pilates Mat graduates → `{ "fields": ["count(*)"], "filter": {"graduation_details": {"@>": [{"course": "Pilates Mat"}]}} }`
- verificar que podemos crear un KPI de conteo de multi-graduandos (len(graduation_details) > 1).

#### Bar Chart
- Graduates per-country: `{ "fields": ["country", "count(*) as graduates"], "group_by": ["country"] }`
- Graduates by licensee: `{ "fields": ["licensee", "count(*) as graduates"], "group_by": ["licensee"] }`
- Pie Chart del count by graduation_details.course

#### Grilla
- Grilla general mostrando los 17 mil registros

## Renderer

Renderer HTML5 con echarts (charts) y grid.js (grilla) que consuma la Surface A2UI, cree el dashboard, los widgets e invoque la actualización de datos como FEAT-598 prevé; cada objeto HTML tiene un botón "refresh" que invoca la API de query-slug para refrescar la data sin que la IA intervenga (modo determinista).

### Como funciona
- client-server de ejemplo en `examples/a2ui/{server,client}.py`: server = servidor parrot/aiohttp que sirve la surface A2UI generada por un agente de ai-parrot, opcionalmente con un agente expuesto (posiblemente vía ai-parrot-server); la app aiohttp levanta QuerySource como servicio y AuthHandler.
- cliente: inicia sesión, guarda el bearer token en localStorage, consume la URL de la surface A2UI, invoca el renderer, renderiza dashboard y widgets, y puede invocar refresh/repintado de widgets vía querysource.
