---
type: Wiki Summary
title: parrot_formdesigner.services.org_graph
id: mod:parrot_formdesigner.services.org_graph
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: OrgGraphService — árbol multi-jerarquía read-only sobre auth.* + geografía.
relates_to:
- concept: class:parrot_formdesigner.services.org_graph.OrgGraph
  rel: defines
- concept: class:parrot_formdesigner.services.org_graph.OrgGraphService
  rel: defines
- concept: class:parrot_formdesigner.services.org_graph.OrgNode
  rel: defines
---

# `parrot_formdesigner.services.org_graph`

OrgGraphService — árbol multi-jerarquía read-only sobre auth.* + geografía.

Lee tablas de solo-lectura:
- ``auth.organizations``, ``auth.organization_clients``, ``auth.clients``,
  ``auth.programs``, ``auth.program_clients``
- Geografía per-client: ``networkninja.markets``, ``networkninja.districts``,
  ``networkninja.regions``
- Proyectos propios: ``fieldsync.projects``

Principios de diseño (§8 spec):
- **Hard tenant isolation**: todo query filtra ``org_id`` / ``client_id``
  explícitamente; sin leakage cross-tenant.
- **SQL 100% parametrizado**: valores siempre vía ``$1``/``$2`` etc.;
  nombres de schema/tabla fijados como constantes (no interpolados desde
  input de usuario).
- **Múltiples jerarquías**: un "company" super-node agrupa todas las
  sub-jerarquías del tenant (por si un cliente tiene >1 organización).
- **Read-only**: no hay ningún INSERT/UPDATE/DELETE en este servicio.
- **Pool inyectado**: acepta pool o fake-pool para testabilidad completa.

Uso::

    svc = OrgGraphService(pool)
    graph = await svc.get_graph(org_id=7, tenant="myco")
    node  = await svc.get_node("client", "42", tenant="myco")

## Classes

- **`OrgNode(BaseModel)`** — A single node in the organizational hierarchy.
- **`OrgGraph(BaseModel)`** — Full organizational graph for a tenant.
- **`OrgGraphService`** — Build in-memory org-graph trees from navigator-auth + networkninja.
