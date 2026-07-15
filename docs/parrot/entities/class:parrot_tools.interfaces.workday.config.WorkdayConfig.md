---
type: Wiki Entity
title: WorkdayConfig
id: class:parrot_tools.interfaces.workday.config.WorkdayConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Explicit Workday credentials / tenant; each optional field falls back
---

# WorkdayConfig

Defined in [`parrot_tools.interfaces.workday.config`](../summaries/mod:parrot_tools.interfaces.workday.config.md).

```python
class WorkdayConfig(BaseModel)
```

Explicit Workday credentials / tenant; each optional field falls back
to the matching ``WORKDAY_*`` in ``parrot.conf`` when left ``None``.

Usage::

    # All-defaults — picks up credentials from the environment / conf.
    cfg = WorkdayConfig()

    # Explicit override — useful for multi-tenant scenarios or tests.
    cfg = WorkdayConfig(client_id="my-id", client_secret="my-secret")

Resolved values are exposed via the ``resolved_*`` computed properties so
that callers always get a definite value regardless of whether an explicit
override was provided.

## Methods

- `def resolved_client_id(self) -> str | None` — Return the explicit ``client_id`` or fall back to ``WORKDAY_CLIENT_ID``.
- `def resolved_client_secret(self) -> str | None` — Return the explicit ``client_secret`` or fall back to ``WORKDAY_CLIENT_SECRET``.
- `def resolved_token_url(self) -> str | None` — Return the explicit ``token_url`` or fall back to ``WORKDAY_TOKEN_URL``.
- `def resolved_refresh_token(self) -> str | None` — Return the explicit ``refresh_token`` or fall back to ``WORKDAY_REFRESH_TOKEN``.
- `def resolved_report_username(self) -> str | None` — Return the explicit ``report_username`` or fall back to ``WORKDAY_REPORT_USERNAME``.
- `def resolved_report_password(self) -> str | None` — Return the explicit ``report_password`` or fall back to ``WORKDAY_REPORT_PASSWORD``.
- `def resolved_tenant(self) -> str | None` — Return the explicit ``tenant`` or fall back to ``WORKDAY_DEFAULT_TENANT``.
- `def resolved_report_owner(self) -> str | None` — Return the explicit ``report_owner`` or fall back to ``WORKDAY_REPORT_OWNER``.
- `def resolved_workday_url(self) -> str | None` — Return the explicit ``workday_url`` or fall back to ``WORKDAY_URL``.
