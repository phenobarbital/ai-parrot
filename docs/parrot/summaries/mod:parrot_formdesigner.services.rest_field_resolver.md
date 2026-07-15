---
type: Wiki Summary
title: parrot_formdesigner.services.rest_field_resolver
id: mod:parrot_formdesigner.services.rest_field_resolver
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: RestFieldResolver service for FieldType.REST form fields.
relates_to:
- concept: class:parrot_formdesigner.services.rest_field_resolver.AdditionalArg
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.CallbackRestFieldSpec
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.ConfigurationError
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.InternalRestFieldSpec
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.RemoteRestFieldSpec
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.RestCallbackInput
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.RestCallbackOutput
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.RestFieldResolver
  rel: defines
- concept: class:parrot_formdesigner.services.rest_field_resolver.RestFieldResult
  rel: defines
- concept: mod:parrot_formdesigner.services.auth_context
  rel: references
- concept: mod:parrot_formdesigner.services.callback_registry
  rel: references
---

# `parrot_formdesigner.services.rest_field_resolver`

RestFieldResolver service for FieldType.REST form fields.

Implements the three REST dispatch modes (remote / internal / callback),
JSONPath response extraction, Jinja2 display-template rendering, and
informational response-schema validation. **Never raises** — all errors
flow into ``RestFieldResult``.

Mirrors — does NOT subclass — ``RemoteResponseResolver`` (FEAT-167).

See spec §2 Architectural Design, §7 Patterns to Follow, and §8 Q2/Q3/Q5
for detailed design decisions and resolution order rules.

## Classes

- **`ConfigurationError(Exception)`** — Raised when resolver cannot determine the internal base URL.
- **`AdditionalArg(BaseModel)`** — Extra argument forwarded alongside the uploaded content.
- **`RemoteRestFieldSpec(_RestFieldSpecBase)`** — Spec for mode='remote': calls an absolute external URL.
- **`InternalRestFieldSpec(_RestFieldSpecBase)`** — Spec for mode='internal': calls a relative path on the running server.
- **`CallbackRestFieldSpec(_RestFieldSpecBase)`** — Spec for mode='callback': invokes a pre-registered Python coroutine.
- **`RestCallbackInput(BaseModel)`** — Payload delivered to a registered callback coroutine.
- **`RestCallbackOutput(BaseModel)`** — Return value from a registered callback coroutine.
- **`RestFieldResult(BaseModel)`** — Output of ``RestFieldResolver.resolve()``.
- **`RestFieldResolver`** — Dispatch FieldType.REST field uploads by mode.
