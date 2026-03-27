# TASK-442 — Odoo Interface Unit Tests

**Feature**: FEAT-054 — odoo-interface
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-376

---

## Objective

Write comprehensive unit tests for `OdooInterface` using mocked aiohttp responses. No live Odoo instance required.

## File(s) to Create

- `tests/test_odoo_interface.py`

## Implementation Details

Use `pytest` + `pytest-asyncio` + `aioresponses` (or `unittest.mock.AsyncMock` patching `aiohttp.ClientSession.post`).

### Test Categories

#### Authentication Tests
- `test_authenticate_success` — mock `/jsonrpc` returning uid=2, verify `odoo.uid == 2`.
- `test_authenticate_invalid_credentials` — mock returning `False`, verify `OdooAuthenticationError`.
- `test_authenticate_rpc_error` — mock returning `{"error": {...}}`, verify `OdooRPCError`.
- `test_authenticate_network_error` — mock connection error, verify `OdooConnectionError`.

#### execute_kw Tests
- `test_execute_kw_payload_structure` — capture posted JSON, verify JSON-RPC 2.0 structure with correct service/method/args.
- `test_execute_kw_auto_authenticates` — call execute_kw without prior auth, verify auth called first.
- `test_execute_kw_rpc_error` — verify `OdooRPCError` raised with error details.

#### CRUD Method Tests
- `test_search` — verify correct args/kwargs delegation.
- `test_search_read_with_fields` — verify fields passed in kwargs.
- `test_search_read_with_domain` — verify domain passed in args.
- `test_read_by_ids` — verify ids passed correctly.
- `test_create_single_record` — verify single dict, returns int.
- `test_create_multiple_records` — verify list of dicts, returns list[int].
- `test_write_records` — verify ids + values.
- `test_unlink_records` — verify ids forwarded.
- `test_search_count` — verify domain forwarded, returns int.
- `test_fields_get` — verify attributes forwarded, returns dict.

#### Context Manager Tests
- `test_async_context_manager` — verify session created on enter, closed on exit.
- `test_close_explicit` — verify explicit close works.

#### Security Tests
- `test_invalid_model_name_rejected` — names with special chars raise ValueError.
- `test_password_not_logged` — verify password not present in log output (use `caplog`).

#### Config Tests
- `test_config_from_kwargs` — explicit kwargs used.
- `test_config_from_env_vars` — fallback to `parrot.conf` values.

## Acceptance Criteria

- [ ] All tests pass with `pytest tests/test_odoo_interface.py`.
- [ ] No live Odoo instance required (fully mocked).
- [ ] Coverage of auth, CRUD, errors, context manager, and security.
- [ ] Tests follow project conventions (pytest-asyncio, Google-style).

## Tests

This IS the test task. Target: 20+ test cases, >90% coverage of `odoointerface.py`.
