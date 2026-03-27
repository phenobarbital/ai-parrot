# TASK-438 — Odoo Config Variables

**Feature**: FEAT-054 — odoo-interface
**Status**: pending
**Priority**: high
**Effort**: S
**Depends on**: —

---

## Objective

Add Odoo connection configuration variables to `parrot/conf.py` so the OdooInterface can read them from environment variables.

## File(s) to Modify

- `parrot/conf.py`

## Implementation Details

1. Add the following configuration variables using the same pattern as existing config vars (e.g., `REDIS_SERVICES_URL`):
   - `ODOO_URL`: Odoo instance base URL (e.g., `https://myodoo.com`). Default: `None`.
   - `ODOO_DATABASE`: Odoo database name. Default: `None`.
   - `ODOO_USERNAME`: Odoo login username. Default: `None`.
   - `ODOO_PASSWORD`: Odoo login password or API key. Default: `None`.
   - `ODOO_TIMEOUT`: Request timeout in seconds. Default: `30`.
   - `ODOO_VERIFY_SSL`: Whether to verify SSL certificates. Default: `True`.

2. Follow the existing pattern in `conf.py` for reading env vars (likely via `navconfig` or `os.environ.get`).

## Acceptance Criteria

- [ ] All six `ODOO_*` variables are defined in `parrot/conf.py`.
- [ ] Variables read from environment with sensible defaults.
- [ ] No new imports beyond what `conf.py` already uses.

## Tests

- Verify variables are importable: `from parrot.conf import ODOO_URL, ODOO_DATABASE, ...`
