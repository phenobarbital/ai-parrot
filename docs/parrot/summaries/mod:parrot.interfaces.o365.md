---
type: Wiki Summary
title: parrot.interfaces.o365
id: mod:parrot.interfaces.o365
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.interfaces.o365
relates_to:
- concept: class:parrot.interfaces.o365.MSALCacheTokenCredential
  rel: defines
- concept: class:parrot.interfaces.o365.MSALTokenCredential
  rel: defines
- concept: class:parrot.interfaces.o365.O365Client
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.credentials
  rel: references
---

# `parrot.interfaces.o365`

## Classes

- **`MSALTokenCredential(TokenCredential)`** — Custom TokenCredential that uses MSAL tokens for azure-identity compatibility.
- **`MSALCacheTokenCredential(TokenCredential)`** — TokenCredential that uses an MSAL client application with a serialized cache.
- **`O365Client(CredentialsInterface)`** — O365Client - Migrated to Microsoft Graph SDK
