---
id: F009
query_id: Q009
type: read
intent: test conventions for the Odoo toolkit
executed_at: 2026-09-30T23:58:00Z
duration_ms: 0
parent_id: None
depth: 0
---

# F009 — Test conventions: AsyncMock transport, tests under packages/ai-parrot/tests

## Summary

Odoo toolkit tests live in `packages/ai-parrot/tests/test_odoo_*.py` (not in `ai-parrot-tools/tests`, except `test_odoo_shell.py`). `test_odoo_toolkit.py` stubs `parrot.utils` (:19-30), builds `_fake_transport()` with `AsyncMock` `execute_kw/authenticate/version` (:57-80) and `_make_toolkit(transport)` (:83); each test asserts the `execute_kw` call tuple and the returned envelope class. `test_odoo_json2_transport.py` patches the aiohttp session and asserts the JSON-2 URL + body.

## Citations

- path: `packages/ai-parrot/tests/test_odoo_toolkit.py`
  lines: 1-8
  excerpt: |
    The transport is replaced with an AsyncMock so tests are deterministic and
    network-free. Each test asserts both: (a) execute_kw is called with the right
    model/method/args/kwargs, and (b) the returned envelope/entity is the correct Pydantic class
- path: `packages/ai-parrot/tests/test_odoo_toolkit.py`
  lines: 57-90
  symbol: `_fake_transport`, `_make_toolkit`
- path: `packages/ai-parrot/tests/test_odoo_json2_transport.py`
  lines: 27-40
  symbol: `_config`
- path: `packages/ai-parrot-tools/tests/test_odoo_shell.py`

## Notes

—
