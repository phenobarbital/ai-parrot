---
type: Wiki Overview
title: 'TASK-1154: pycountry Dependency + LOCATION Reference Data'
id: doc:sdd-tasks-completed-task-1154-pycountry-location-reference-data-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Phase 2, Module 16. Adds `pycountry>=23.0` to the package dependencies and
---

# TASK-1154: pycountry Dependency + LOCATION Reference Data

**Feature**: FEAT-167 — FormDesigner New Field Types
**Spec**: `sdd/specs/formdesigner-new-fields.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1147
**Assigned-to**: unassigned

---

## Context

Phase 2, Module 16. Adds `pycountry>=23.0` to the package dependencies and
creates a thin wrapper module `core/_location_data.py` that exposes country
lookup helpers used by the LOCATION validator (TASK-1150) and JSON Schema
extractor (TASK-1152).

---

## Scope

- Add `pycountry>=23.0` to `packages/parrot-formdesigner/pyproject.toml`
- Create `core/_location_data.py` with functions:
  - `is_valid_iso_country_code(code: str) -> bool`
  - `get_country_info(code: str) -> dict | None` — returns `{name, flag, dial_code}`
  - `list_country_options() -> list[FieldOption]` — returns all countries as `FieldOption` list

**NOT in scope**: pycountry is used only for reference; no network calls.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/parrot-formdesigner/pyproject.toml` | MODIFY | Add `pycountry>=23.0` to dependencies |
| `packages/parrot-formdesigner/src/parrot_formdesigner/core/_location_data.py` | CREATE | Country lookup wrapper |
| `packages/parrot-formdesigner/tests/unit/test_core_models.py` | MODIFY | Add pycountry tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# core/options.py:12 (verified):
from parrot_formdesigner.core.options import FieldOption

# FieldOption model (verified):
class FieldOption(BaseModel):
    value: str
    label: LocalizedString
    description: LocalizedString | None = None
    disabled: bool = False
    icon: str | None = None
```

### Does NOT Exist
- ~~`pycountry` as a dep~~ — THIS task adds it to pyproject.toml
- ~~`core/_location_data.py`~~ — THIS task creates it
- ~~Any network-based country lookup~~ — use pycountry offline only

---

## Implementation Notes

### pyproject.toml Change
Find the `[project.dependencies]` or `[tool.poetry.dependencies]` section and
add `"pycountry>=23.0"`. Read the file first to understand its format.

### _location_data.py
```python
"""Offline country reference data via pycountry.

Wraps pycountry to provide helpers used by the LOCATION field type
validator and JSON Schema extractor. No network calls — all data is
bundled with the pycountry package.
"""
from __future__ import annotations

import logging

try:
    import pycountry
    _HAS_PYCOUNTRY = True
except ImportError:
    _HAS_PYCOUNTRY = False

from .options import FieldOption

logger = logging.getLogger(__name__)

# ISO 3166-1 alpha-2 dial code lookup (subset — most common countries)
# pycountry does not include dial codes, so we maintain a small lookup.
_DIAL_CODES: dict[str, str] = {
    "US": "+1", "CA": "+1", "GB": "+44", "ES": "+34", "FR": "+33",
    "DE": "+49", "MX": "+52", "VE": "+58", "CO": "+57", "AR": "+54",
    "BR": "+55", "CL": "+56", "PE": "+51", "EC": "+593",
    # Add more as needed — this is not exhaustive
}


def is_valid_iso_country_code(code: str) -> bool:
    """Return True if code is a valid ISO 3166-1 alpha-2 country code.

    Args:
        code: Two-letter country code (case-insensitive).

    Returns:
        True if valid, False otherwise. Returns True if pycountry is not installed.
    """
    if not _HAS_PYCOUNTRY:
        logger.warning("pycountry not installed — LOCATION validation skipped")
        return True
    return pycountry.countries.get(alpha_2=code.upper()) is not None


def get_country_info(code: str) -> dict | None:
    """Return name, flag emoji, and dial code for a country code.

    Args:
        code: ISO 3166-1 alpha-2 country code.

    Returns:
        Dict with keys 'name', 'flag', 'dial_code', or None if not found.
    """
    if not _HAS_PYCOUNTRY:
        return None
    country = pycountry.countries.get(alpha_2=code.upper())
    if country is None:
        return None
    # Build flag emoji from regional indicator symbols
    flag = "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in code.upper())
    return {
        "name": country.name,
        "flag": flag,
        "dial_code": _DIAL_CODES.get(code.upper(), ""),
    }


def list_country_options() -> list[FieldOption]:
    """Return all countries as FieldOption list sorted by name.

    Returns:
        List of FieldOption with value=alpha_2, label=name, icon=flag.
    """
    if not _HAS_PYCOUNTRY:
        return []
    options = []
    for country in sorted(pycountry.countries, key=lambda c: c.name):
        flag = "".join(chr(0x1F1E6 + ord(c) - ord('A')) for c in country.alpha_2)
        options.append(FieldOption(
            value=country.alpha_2,
            label=country.name,
            icon=flag,
        ))
    return options
```

---

## Acceptance Criteria

- [ ] `pycountry>=23.0` in `packages/parrot-formdesigner/pyproject.toml`
- [ ] `core/_location_data.py` exists and is importable
- [ ] `is_valid_iso_country_code("ES")` returns `True`
- [ ] `is_valid_iso_country_code("XX")` returns `False`
- [ ] `get_country_info("ES")` returns `{"name": "Spain", "flag": "🇪🇸", "dial_code": "+34"}`
- [ ] `list_country_options()` returns `>= 200` entries
- [ ] `test_pycountry_dependency_resolves_es` passes
- [ ] `ruff check packages/parrot-formdesigner/` passes

---

## Test Specification

```python
# packages/parrot-formdesigner/tests/unit/test_core_models.py
# Add:

def test_pycountry_dependency_resolves_es():
    """Wrapper returns ISO-2 ES → name Spain, flag 🇪🇸, dial code +34."""
    from parrot_formdesigner.core._location_data import get_country_info, is_valid_iso_country_code
    info = get_country_info("ES")
    assert info is not None
    assert info["name"] == "Spain"
    assert info["flag"] == "🇪🇸"
    assert info["dial_code"] == "+34"
    assert is_valid_iso_country_code("ES") is True


def test_location_rejects_unknown_code():
    """is_valid_iso_country_code('XX') returns False."""
    from parrot_formdesigner.core._location_data import is_valid_iso_country_code
    assert is_valid_iso_country_code("XX") is False


def test_list_country_options_has_entries():
    """list_country_options returns a non-empty list of FieldOption."""
    from parrot_formdesigner.core._location_data import list_country_options
    options = list_country_options()
    assert len(options) >= 200
    values = {o.value for o in options}
    assert "ES" in values
    assert "US" in values
    assert "VE" in values
```

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
