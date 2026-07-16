---
type: Wiki Summary
title: parrot_formdesigner.services.csrf
id: mod:parrot_formdesigner.services.csrf
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: CSRF token utilities for the remote events endpoint — FEAT-188.
relates_to:
- concept: func:parrot_formdesigner.services.csrf.issue_form_csrf_token
  rel: defines
- concept: func:parrot_formdesigner.services.csrf.validate_form_csrf_token
  rel: defines
---

# `parrot_formdesigner.services.csrf`

CSRF token utilities for the remote events endpoint — FEAT-188.

Issues and validates per-session per-form CSRF tokens using an in-process
store with a soft TTL of 1 hour.

MVP limitations:
- In-process dictionary store — tokens are NOT shared across multiple worker
  processes (e.g., gunicorn with multiple workers).  For production deployments
  with multi-process servers, replace ``_STORE`` with a shared backend such as
  Redis.  This is intentional for the MVP; production hardening is a follow-up
  tracked in the spec §3 Module 6 notes.

## Functions

- `def issue_form_csrf_token(session_id: str, form_id: str) -> str` — Issue a CSRF token for the given session / form pair.
- `def validate_form_csrf_token(session_id: str, form_id: str, token: str) -> bool` — Validate a CSRF token against the in-process store.
