---
type: Wiki Entity
title: CallbackRestFieldSpec
id: class:parrot_formdesigner.services.rest_field_resolver.CallbackRestFieldSpec
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Spec for mode=''callback'': invokes a pre-registered Python coroutine.'
---

# CallbackRestFieldSpec

Defined in [`parrot_formdesigner.services.rest_field_resolver`](../summaries/mod:parrot_formdesigner.services.rest_field_resolver.md).

```python
class CallbackRestFieldSpec(_RestFieldSpecBase)
```

Spec for mode='callback': invokes a pre-registered Python coroutine.

Attributes:
    mode: Literal discriminator — always ``"callback"``.
    callback_ref: Key in the callback registry (see ``callback_registry``).
