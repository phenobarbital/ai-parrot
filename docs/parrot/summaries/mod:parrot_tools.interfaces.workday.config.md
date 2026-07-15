---
type: Wiki Summary
title: parrot_tools.interfaces.workday.config
id: mod:parrot_tools.interfaces.workday.config
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: WorkdayConfig — credential + tenant configuration for WorkdayService.
relates_to:
- concept: class:parrot_tools.interfaces.workday.config.WorkdayConfig
  rel: defines
- concept: func:parrot_tools.interfaces.workday.config.get_wsdl_path
  rel: defines
- concept: mod:parrot.conf
  rel: references
---

# `parrot_tools.interfaces.workday.config`

WorkdayConfig — credential + tenant configuration for WorkdayService.

Each optional credential field falls back to the matching ``WORKDAY_*``
setting from ``parrot.conf`` when left ``None`` (G3/C6).

WSDL routing helper
-------------------
``get_wsdl_path(operation_type)`` maps a Workday operation key to the
correct WSDL file path.  The mapping is lifted verbatim from the two
``wsdl_mapping`` blocks in ``workday.py`` (original source)
(lines 339-360 and 500-517) and unified into a single canonical dict.

Known discrepancy between the two original blocks
--------------------------------------------------
``get_organization``:
  - ``__init__``     (line 345): ``WORKDAY_WSDL_HUMAN_RESOURCES``   ← used here
  - helper method   (line 506): ``WORKDAY_WSDL_PATH``               ← superseded
The ``__init__`` block is the authoritative runtime path (executed on
every component instantiation), so this module uses
``WORKDAY_WSDL_HUMAN_RESOURCES`` for ``get_organization``.

## Classes

- **`WorkdayConfig(BaseModel)`** — Explicit Workday credentials / tenant; each optional field falls back

## Functions

- `def get_wsdl_path(operation_type: str) -> Any` — Return the WSDL path for a given Workday operation type.
