---
type: Wiki Entity
title: BusinessHours
id: class:parrot.human.models.BusinessHours
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Defines a business-hours window for an escalation tier.
---

# BusinessHours

Defined in [`parrot.human.models`](../summaries/mod:parrot.human.models.md).

```python
class BusinessHours(BaseModel)
```

Defines a business-hours window for an escalation tier.

When ``EscalationTier.business_hours`` is set, the manager will only
dispatch that tier if the *current time* (in the given timezone) falls
within the window.  Tiers whose window is currently closed are skipped.

Attributes:
    tz: IANA timezone name, e.g. ``"Europe/Madrid"``.
    days: Day range or list, e.g. ``"mon-fri"`` or ``"mon,wed,fri"``.
    hours: 24-hour window, e.g. ``"09:00-18:00"``.

Example::

    bh = BusinessHours(tz="Europe/Madrid", days="mon-fri", hours="09:00-18:00")
    bh.contains(datetime.now(pytz.timezone("Europe/Madrid")))

## Methods

- `def contains(self, now: datetime) -> bool` — Return True if *now* falls within this business-hours window.
