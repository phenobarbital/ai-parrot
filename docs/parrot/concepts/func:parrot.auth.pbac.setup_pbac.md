---
type: Concept
title: setup_pbac()
id: func:parrot.auth.pbac.setup_pbac
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Initialize the PBAC engine and register it with the aiohttp application.
---

# setup_pbac

```python
def setup_pbac(app: web.Application, policy_dir: str='policies', cache_ttl: int=30, default_effect: Optional[object]=None) -> 'tuple[Optional[PDP], Optional[PolicyEvaluator], Optional[Guardian]]'
```

Initialize the PBAC engine and register it with the aiohttp application.

Performs the following steps:
1. Validates that the policy directory exists.
2. Creates a ``YAMLStorage`` pointing at that directory.
3. Creates ``PolicyEvaluator`` with short TTL cache (default 30s) for
   time-dependent policy freshness.
4. Loads YAML policies via ``PolicyLoader.load_from_directory()``.
5. Creates ``PDP(storage=yaml_storage)`` and attaches the evaluator.
6. Calls ``PDP.setup(app)`` which registers:
   - ``app['security']`` → ``Guardian`` instance
   - ``app['abac']`` → ``PDP`` instance
   - ABAC middleware
   - ``POST /api/v1/abac/check`` (and other ABAC endpoints)

Graceful degradation: if *policy_dir* does not exist or the imports
fail (navigator-auth not installed), the function logs a warning and
returns ``(None, None, None)``.  The application continues running
with the existing default resolver (fail-open).

Args:
    app: The aiohttp ``web.Application`` to register PBAC into.
    policy_dir: Path to directory containing ``*.yaml`` policy files.
        Defaults to ``"policies"`` (relative to the working directory).
    cache_ttl: Seconds before a cached policy decision expires.
        Use 30s (default) to support time-sensitive policies like
        business-hours restrictions.
    default_effect: Default ``PolicyEffect`` when no policy matches.
        Defaults to ``PolicyEffect.DENY`` (deny-by-default security model).

Returns:
    A tuple ``(pdp, evaluator, guardian)`` where all three are not None
    when PBAC was successfully initialized.  Returns ``(None, None, None)``
    if the policy directory is missing, empty, or imports fail.

Example::

    pdp, evaluator, guardian = setup_pbac(
        app,
        policy_dir="/etc/parrot/policies",
        cache_ttl=30,
    )
