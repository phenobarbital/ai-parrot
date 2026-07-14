---
type: Wiki Summary
title: parrot.autonomous.admin
id: mod:parrot.autonomous.admin
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: Admin login page for the Autonomous Orchestrator.
relates_to:
- concept: func:parrot.autonomous.admin.admin_login_page
  rel: defines
---

# `parrot.autonomous.admin`

Admin login page for the Autonomous Orchestrator.

Serves a simple HTML page at ``/autonomous/admin`` that:

1. Collects *username* + *password*.
2. POSTs to ``/api/v1/login`` with header ``X-Auth-Method: BasicAuth``.
3. On success, stores the JWT token and full user payload in **localStorage**.
4. Redirects the admin to the WhatsApp dashboard (or any protected page).

## Functions

- `async def admin_login_page(request: web.Request) -> web.Response` — Serve the admin login HTML page (no auth required).
