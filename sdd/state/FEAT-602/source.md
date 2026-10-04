---
kind: inline
jira_key: null
fetched_at: 2026-09-25T00:00:00Z
summary_oneline: "HoobaToolkit — OpenAPI (api.hooba.com) + Playwright hybrid toolkit: draft invoices, draft expenses/purchases, BBVA bank Excel → expense drafts for Spanish autónomos"
---

# hooba toolkit

## Configuracion

Hooba (https://app.hooba.com/) es un software contable de gestión exigido por un convenio "Red.es", posee un API openAPI:
url: https://api.hooba.com/api/doc

Con las siguientes propiedades (hay que registrarlas en .env como HOOBA_ACCOUNT_ID, HOOBA_MEMBER_ID, HOOBA_USER_ID y HOOBA_SUBSCRIPTION_ID)
accountId: HOOBA_ACCOUNT_ID
memberId: HOOBA_MEMBER_ID
userId: HOOBA_USER_ID
subscriptionId: HOOBA_SUBSCRIPTION_ID

con URLs como:
https://api.hooba.com/accounts/{accountId}/member

Que usan las siguientes headers (cookie de sesión redactada — el valor `sid` es un secreto y no se persiste):
```
:authority: api.hooba.com
:method: GET
:path: /accounts/{accountId}/member
accept: application/json, text/plain, */*
accept-encoding: gzip, deflate, br, zstd
accept-language: es-ES,es;q=0.9
cookie: sid=<REDACTED>; _ga_...=<REDACTED>; _ga=<REDACTED>
ngsw-bypass: true
origin: https://app.hooba.com
x-hooba-language: es
```

Se obtiene un JSON como este (valores personales elididos):
```
{
  "member": {
    "id": <memberId>, "externalId": "", "code": "",
    "firstName": "...", "firstSurname": "...", "secondSurname": "...",
    "gender": "male", "birthdate": "...",
    "tin": , "iban": , "socialSecurityNumber": ,
    "email": "...", "phone": {"countryCode": "ES", "prefix": 34, "number": "..."},
    "address": "...", "postcode": "...", "city": "...", "region": "...",
    "createdAt": "2025-12-18T15:02:04+00:00", "enabled": true, "notificationsEnabled": true,
    "avatar": null, "userJoinedAt": "2025-12-18T15:12:37+00:00", "countryId": "ES",
    "absencePolicyId": ..., "timeTrackingPolicyId": ..., "locationId": ..., "userId": <userId>
  },
  "memberGroupIds": [...], "roleIds": [1], "applicationIds": [1, 3, 2, 4, 9, 12, 7, 13, 10],
  "user": {"id": <userId>, "firstName": "...", "firstSurname": "...", "secondSurname": "...",
           "timeZone": "Europe/Madrid", "phone": {...}, "email": "...", "newEmail": ""},
  "invitation": null, "openedTimeTrackingRecord": null, "attributes": [], "disabledNotificationIds": []
}
```

Para authentication, existe:

path: /auth/login

POST
```
{
  "username": "string",
  "password": "string"
}
```

con:
HOOBA_USERNAME
HOOBA_PASSWORD

# Task

Construir una interfaz HTTP openAPI para interactuar con Hooba tanto via http (API REST openAPI) como vía web con playwright (operativa disponible previamente), construir una HoobaToolkit que combine ambas operativas (usar la API cuando se deba, via web para automatizar operaciones disponibles vía web).
El Toolkit le debe permitir a un agente de ai-parrot:
- crear facturas en modo borrador
- declarar gastos y compras en modo borrador
- subir un excel de relación de gastos del banco (BBVA) para convertirlos en declaraciones de gastos, según la normativa vigente del Reino de España para autónomos
