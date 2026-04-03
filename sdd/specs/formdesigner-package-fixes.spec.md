# Spec: formdesigner-package-fixes

**Feature ID**: FEAT-080
**Status**: approved
**Author**: Jesus Lara
**Date**: 2026-04-03

## Problem Statement

Code review of FEAT-079 (parrot-formdesigner package extraction) identified 31 issues across 7 severity levels. These range from critical security vulnerabilities (XSS, missing auth) and phantom APIs (AI hallucinations) to important reliability issues (wrong Redis library, race conditions, ReDoS) and maintainability improvements.

## Goals

1. Fix all 7 critical issues before production deployment
2. Fix all 12 important issues that affect reliability
3. Address high-priority suggestions that improve robustness
4. Ensure zero phantom APIs / AI hallucinations remain in the codebase

## Non-Goals

- Adding new features to formdesigner
- Refactoring the overall package architecture
- Adding comprehensive integration tests (separate effort)

## Task Breakdown

### TASK-556: Fix cache layer — Redis library, race condition, datetime deprecation
- Replace `aioredis` with `redis.asyncio` (C1)
- Add asyncio.Lock to `_get_redis()` (I1)
- Replace all `datetime.utcnow()` with `datetime.now(tz=timezone.utc)` (I3)
- Log Redis close errors at DEBUG level instead of bare `pass`
- Fire callbacks in `invalidate_all()` or document the omission

### TASK-557: Fix phantom attributes and dead code
- Remove or implement `trigger_phrases` on FormSchema (C2)
- Fix `from .extractors.yaml` → `from ..extractors.yaml` in registry (C3)
- Fix `rendered.output` → `rendered.content` in api.py (I7)
- Add `ValidationResult` to `parrot.formdesigner.__all__` (I12)
- Remove dead `if TYPE_CHECKING: pass` block and legacy comments

### TASK-558: Fix XSS vulnerabilities in renderer and templates
- Apply `html.escape()` to all user-controlled values in html5.py (C4)
- Escape `locale` in `page_shell()` template (C6)
- Rename `html` variable shadow in html5.py render() (I11)
- Document XSS trust boundary for `gallery_page`/`form_page` raw HTML injection

### TASK-559: Add API authentication to handler endpoints
- Implement auth middleware or `_is_authorized()` check on all 8 API routes (C5)
- Add rate limiting consideration for LLM-calling endpoints
- Return 401/403 with clear error messages

### TASK-560: Fix tool layer issues
- Fix DSN import to use env var fallback with clear error (C7)
- Replace `_validator._detect_circular_dependencies()` with public method (I4)
- Replace `"json_str" in dir()` with pre-initialized variables (I5)
- Accept injected `AsyncDB` / connection pool instead of per-request creation (I6)
- Fix `PydanticUndefinedType` → `PydanticUndefined` comparison (I10)
- Replace bare `ImportError` fallback with actionable error message (S1)
- Move tool construction to handler `__init__`, not per-request (I9)

### TASK-561: Fix handler robustness and service hardening
- Add `.get()` guards on `result.metadata` and `result.result` access (I8)
- Add type annotation for `client` parameter in routes.py and api.py (S7)
- Fix inconsistent 404 response in `submit_form` (use styled HTML)
- Use `list_forms()` instead of N+1 `get()` calls in gallery (S3)
- Add ReDoS protection: validate regex at `FieldConstraints` construction (I2)
- Add `Field(ge=0)` constraints on min/max length/items (S5)
- Use `model_dump_json()` instead of `json.dumps(model_dump())` in storage (S8)

## Dependencies

- All tasks are independent and can be worked in parallel
- TASK-558 (XSS) and TASK-559 (auth) are highest priority for security
- TASK-556 (cache) and TASK-557 (phantom attrs) are highest priority for correctness

## Risks

- TASK-559 (auth) may need architectural discussion on which auth strategy to use
- TASK-560 (DSN fallback) changes the tool constructor API — check consumer examples
