---
type: Wiki Summary
title: parrot_formdesigner.services.rbac
id: mod:parrot_formdesigner.services.rbac
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RBACService — policies ABAC/PBAC (nav-auth format) + RBACContext.
relates_to:
- concept: class:parrot_formdesigner.services.rbac.PermissionRecord
  rel: defines
- concept: class:parrot_formdesigner.services.rbac.Policy
  rel: defines
- concept: class:parrot_formdesigner.services.rbac.RBACContext
  rel: defines
- concept: class:parrot_formdesigner.services.rbac.RBACScope
  rel: defines
- concept: class:parrot_formdesigner.services.rbac.RBACService
  rel: defines
---

# `parrot_formdesigner.services.rbac`

RBACService — policies ABAC/PBAC (nav-auth format) + RBACContext.

Implementa Module 3 de FEAT-302 (C4 RESUELTO §8):

- **NO** motor RBAC paralelo.
- **NO** columna ``scope`` en ``auth.permissions``.
- **NUNCA** escribe en ``auth.user_permissions``.

Las policies son declarativas, compatibles con el formato YAML del engine
ABAC/PBAC de nav-auth, persistidas como JSONB en ``fieldsync.auth_policies``.
El enforcement autoritativo lo ejecuta nav-auth; este módulo gestiona la
emisión, almacenamiento y compilación de policies, y proyecta el
``RBACContext`` a los handlers para shadow-mode gate-keeping.

``RBACScope`` es vocabulario de alto nivel que se **compila** a una ``Policy``
ABAC antes de persistir:

- ``own``    → subjects.users = [user_id]
- ``team``   → subjects.groups = [team/<program_id>]
- ``client`` → conditions.resource.client_id = (computed)
- ``global`` → sin restricción de subjects/conditions

Ejemplo de policy referencia (§8)::

    Policy(
        name="eng_agents_biz_hours",
        effect="allow",
        description="Engineering agents during business hours",
        resources=["agent:*"],
        actions=["agent:chat"],
        subjects={"groups": ["engineering", "developers"]},
        conditions={"environment": {"is_business_hours": True}},
        priority=20,
        enforcing=False,
    )

Uso::

    svc = RBACService(pool)
    record = await svc.assign_role(
        "user-abc",
        program_id=7,
        codename="edit_form",
        scope=RBACScope.OWN,
        tenant="acme",
    )
    ctx = await svc.resolve("user-abc", program_id=7, tenant="acme")
    ctx.has_permission("edit_form", scope=RBACScope.OWN)   # → True

## Classes

- **`RBACScope(str, Enum)`** — Vocabulary of RBAC scopes that compile to ABAC policies.
- **`Policy(BaseModel)`** — Declarative ABAC/PBAC policy — mirrors the nav-auth YAML format.
- **`PermissionRecord(BaseModel)`** — A compiled permission entry (result of assign_role).
- **`RBACContext(BaseModel)`** — Runtime RBAC context projected for a user in a program.
- **`RBACService`** — Manage ABAC/PBAC policies in ``fieldsync.auth_policies`` + project context.
