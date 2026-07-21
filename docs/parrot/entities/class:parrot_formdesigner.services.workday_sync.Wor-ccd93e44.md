---
type: Wiki Entity
title: WorkdayIdentitySyncAdapter
id: class:parrot_formdesigner.services.workday_sync.WorkdayIdentitySyncAdapter
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Stub de sincronización de identidades hacia Workday.
---

# WorkdayIdentitySyncAdapter

Defined in [`parrot_formdesigner.services.workday_sync`](../summaries/mod:parrot_formdesigner.services.workday_sync.md).

```python
class WorkdayIdentitySyncAdapter
```

Stub de sincronización de identidades hacia Workday.

Interfaz estable para upgrade drop-in cuando FEAT-026/027 estén
disponibles. Actualmente: loggea la operación y devuelve un dict
de aceptación con ``stub=True``; **cero llamadas HTTP**.

Args:
    base_url: URL base del endpoint Workday (ignorada en stub mode).
        Cuando ``None``, el adapter opera siempre en stub mode.
    api_key: API key para autenticación Workday (ignorada en stub mode).
        Cuando ``None``, no se intenta autenticación.

Note:
    ``WORKDAY_SYNC_BASE_URL`` no existe como variable de entorno definida
    porque el endpoint upstream no está disponible (§8). No leer esa
    variable hasta que el spec de guardrails Workday esté aprobado.

## Methods

- `async def sync_user(self, user_id: str, *, action: Literal['provision', 'deprovision'], org_id: int) -> dict[str, Any]` — Stub: loggea la operación y devuelve aceptación sin llamada HTTP.
