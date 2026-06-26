# F003 — Parrot-owned OAuth2 callback web surface (EXISTS)

**Query**: Q011 (grep `oauth2_routes.py`)
**Verdict**: VERIFIED EXISTS — brainstorm §8 "parrot-owned authenticated web surface" partially built.

- `auth/oauth2_routes.py`: `setup_oauth2_routes(app, provider_id, callback_path)` (l.202), `make_oauth2_callback(provider_id)` (l.151), `_handle_web_callback(...)` (l.74).
- Callback delegates token exchange to `manager.handle_callback(code, state)` (l.170), then `_handle_web_callback` (l.182).
- Origin allowlist enforced (l.97); `state_payload` must carry `user_id` (l.111).
- Route is **excluded from auth middleware** — "it IS the auth callback" (l.216).
- Jira-specific callback at `/api/auth/jira/callback` noted as still present (l.14).

**Implication**: OAuth authorization-code redirect+callback already lands in parrot and persists to vault. New for A2A: the **resume trigger** must fan back to a *suspended A2A task* (current callback resumes the web/chat session, not an A2A task). Brainstorm correct that OAuth-callback-as-resume-trigger is new for this surface.
