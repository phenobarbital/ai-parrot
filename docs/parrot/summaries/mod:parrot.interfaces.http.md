---
type: Wiki Summary
title: parrot.interfaces.http
id: mod:parrot.interfaces.http
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Module parrot.interfaces.http
relates_to:
- concept: class:parrot.interfaces.http.ComponentError
  rel: defines
- concept: class:parrot.interfaces.http.HTTPService
  rel: defines
- concept: func:parrot.interfaces.http.bad_gateway_exception
  rel: defines
- concept: mod:parrot.conf
  rel: references
- concept: mod:parrot.interfaces.credentials
  rel: references
- concept: mod:parrot.interfaces.dataframes
  rel: references
- concept: mod:parrot.utils
  rel: references
---

# `parrot.interfaces.http`

## Classes

- **`ComponentError(Exception)`** — Base class for component errors.
- **`HTTPService(CredentialsInterface, PandasDataframe)`** — HTTPService.

## Functions

- `def bad_gateway_exception(exc)` — Check if the exception is a 502 Bad Gateway error.
