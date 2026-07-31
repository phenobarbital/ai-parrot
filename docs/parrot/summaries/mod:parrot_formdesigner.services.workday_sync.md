---
type: Wiki Summary
title: parrot_formdesigner.services.workday_sync
id: mod:parrot_formdesigner.services.workday_sync
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: WorkdayIdentitySyncAdapter — stub de sincronización de identidades con Workday.
relates_to:
- concept: class:parrot_formdesigner.services.workday_sync.WorkdayIdentitySyncAdapter
  rel: defines
---

# `parrot_formdesigner.services.workday_sync`

WorkdayIdentitySyncAdapter — stub de sincronización de identidades con Workday.

FEAT-302 Module 4 — STUB ONLY (§8 RESUELTO).

Por qué solo stub:
- FEAT-026 / FEAT-027 (Workday Identity Sync en ai-parrot) **no existen**.
- Su construcción está bloqueada por un spec prerequisito de guardrails
  ABAC/PBAC para la API de Workday y el Toolkit de Workday.
- Hasta que ese spec esté aprobado e implementado, cualquier llamada HTTP
  real a la API de Workday es prematura e insegura.

Contrato de upgrade:
- La interfaz pública (``sync_user()``) es estable; un upgrade drop-in
  a cliente real requiere únicamente:
  1. Poner ``base_url`` y ``api_key`` reales.
  2. Implementar el cuerpo HTTP en ``sync_user()`` según el contrato del
     spec de guardrails Workday.
  3. Eliminar la bandera ``stub=True`` del retorno.
- El adapter NO modifica permisos; para revocar acceso completo combinar
  con ``RBACService.revoke_all()``.

Uso::

    adapter = WorkdayIdentitySyncAdapter()  # stub
    result = await adapter.sync_user(
        "user-abc",
        action="provision",
        org_id=7,
    )
    # → {"status": "accepted", "stub": True, "action": "provision",
    #    "user_id": "user-abc", "org_id": 7}

## Classes

- **`WorkdayIdentitySyncAdapter`** — Stub de sincronización de identidades hacia Workday.
