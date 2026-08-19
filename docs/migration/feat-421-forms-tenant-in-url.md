# Migration — FEAT-421: Client-declared tenant in the forms URL

**Feature**: FEAT-421 (URL shape amended by FEAT-429 before release)
**Jira**: NAV-9372 (create), NAV-9370 (edit/save)
**Status**: breaking change, hard cut — `parrot-formdesigner` 0.9.0
**Affects**: `navigator-svelte`, `fieldsync`, and any other consumer of the
`parrot-formdesigner` forms REST/UI/Telegram/audio surface.

> **Note (FEAT-429):** The original FEAT-421 design used a `/t/{tenant}/`
> marker segment for router disambiguation. This was simplified to
> `/{tenant}/` before 0.9.0 shipped — aiohttp's literal-first route
> matching makes the marker unnecessary. Neither `navigator-svelte` nor
> `fieldsync` had shipped the `/t/{tenant}/` shape to production, so this
> guide describes only the final, `/t/`-free URL shape — one migration,
> not two.

## Why this change exists

`parrot-formdesigner` used to **infer** which tenant a forms request was
about — through a fallback chain that preferred the first programme in the
caller's session (`session["session"]["programs"][0]`), then a hardcoded
`"navigator"` default. A user who belongs to eleven programmes belongs to
all eleven; `programs[0]` is an arbitrarily-ordered value, never a statement
of which programme a given request concerns. The observed consequence:
AI-created and AI-edited forms were written under `navigator` instead of the
programme the caller was actually browsing, then 404'd on load/save
(NAV-9372, NAV-9370).

As of 0.9.0, the client **declares** which tenant a forms request is about,
as an explicit `/{tenant}/` segment in the URL. The backend validates and
authorizes that declaration; it never guesses. This is a **hard cut** — the
old, unqualified forms URLs are not registered at all, and requests to them
return a router-level 404. There is no deprecation window, because a
fallback window would keep the exact inference that caused NAV-9370/9372
alive.

## Coordinated deploy checklist

Because this is a hard cut, `navigator-svelte`, `fieldsync`, and the
`parrot-formdesigner` wheel **must ship together**:

- [ ] Update every forms URL your client builds (see the table below) to
      include the `/{tenant}/` segment.
- [ ] Ensure the tenant your client declares is one the caller is actually a
      member of (`session["session"]["programs"]`) — a non-member
      declaration is rejected with 403 (superusers are exempt).
- [ ] Do **not** send the tenant as a query parameter (`?program_slug=` or
      similar) — it is not read from the query string on any route.
- [ ] If your client also submits `tenant` in a POST/PUT/PATCH body, ensure
      it matches the URL tenant exactly, or drop it — a mismatch is a hard
      400.
- [ ] Confirm you did **not** also prefix any `/org/*` URL — see below.
- [ ] Confirm no tenant/programme is named `org`, `form-controls`, or
      `api` (FEAT-429 reserved-segment guard — see below).
- [ ] Deploy `parrot-formdesigner>=0.9.0`, then the client changes, in the
      same release window (or the client changes first, since the URLs they
      call would 404 against `<0.9.0` too — coordinate the exact order with
      your release process).

## `/org/*` URLs are UNCHANGED

**This is the single most likely migration error.** The forms namespace
(`/{tenant}/forms/...`) and the `/org/*` namespace sit under the same
`base_path` (`/api/v1` by default), which invites the assumption that both
got the tenant prefix. **They did not.** Organizations are the layer that
*defines* tenants; scoping them *by* a tenant would invert the dependency.
All nine `/org/*` routes keep their exact 0.8.x paths, unprefixed, with no
tenant declaration or validation applied to them at all:

```
GET  /api/v1/org/graph
POST /api/v1/org/projects
POST /api/v1/org/cost-centers/{project_id}/workday-map
POST /api/v1/org/users/{user_id}/assign
POST /api/v1/org/sync/workday
GET  /api/v1/org/stores/{store_id}/sites
POST /api/v1/org/stores/{store_id}/sites
GET  /api/v1/org/sites/{site_id}/locations
POST /api/v1/org/sites/{site_id}/locations
GET  /api/v1/org/locations/{location_id}
```

If you prefix one of these with `/{tenant}/`, it will 404 — that is the
router telling you the route does not exist at that path, not a bug in this
migration.

`/api/v1/form-controls` (the static field-type catalog) is also **unchanged
and unprefixed** — it carries no per-tenant data.

## Reserved tenant segments (FEAT-429)

Removing the `/t/` marker put the dynamic `{tenant}` segment at the same
URL tree level as literal segments like `org` and `form-controls` (and
`api`, on the HTML/Telegram surface's root). A tenant slug that exactly
matches one of these literals — e.g. a programme actually named `"org"` —
is rejected by `requires_tenant()` with a plain **404** on every forms
route, and the server logs a boot-time `WARNING` if a provisioned tenant
collides with a reserved segment. This set is derived automatically from
the routes the package registers, not a fixed list, so it grows if a
future release adds another top-level literal route. **Do not name a
tenant/programme `org`, `form-controls`, or `api`.**

## Old → new URL table

Every table below was generated from the **live router** (`setup_form_api` /
`setup_form_ui`), not transcribed from the spec — it is exhaustive as of
0.9.0.

### JSON REST API (`base_path` default: `/api/v1`)

| Old (0.8.x) | New (0.9.0) |
|---|---|
| `GET/POST /api/v1/forms` | `GET/POST /api/v1/{tenant}/forms` |
| `POST /api/v1/forms/from-db` | `POST /api/v1/{tenant}/forms/from-db` |
| `POST /api/v1/forms/blank` | `POST /api/v1/{tenant}/forms/blank` |
| `GET/PUT/PATCH/DELETE /api/v1/forms/{form_uid}` | `GET/PUT/PATCH/DELETE /api/v1/{tenant}/forms/{form_uid}` |
| `POST /api/v1/forms/{form_uid}/edit` | `POST /api/v1/{tenant}/forms/{form_uid}/edit` |
| `POST /api/v1/forms/{form_uid}/clone` | `POST /api/v1/{tenant}/forms/{form_uid}/clone` |
| `GET /api/v1/forms/{form_uid}/schema` | `GET /api/v1/{tenant}/forms/{form_uid}/schema` |
| `GET /api/v1/forms/{form_uid}/style` | `GET /api/v1/{tenant}/forms/{form_uid}/style` |
| `GET /api/v1/forms/{form_uid}/render/{format}` | `GET /api/v1/{tenant}/forms/{form_uid}/render/{format}` |
| `POST /api/v1/forms/{form_uid}/validate` | `POST /api/v1/{tenant}/forms/{form_uid}/validate` |
| `POST /api/v1/forms/{form_uid}/data` | `POST /api/v1/{tenant}/forms/{form_uid}/data` |
| `PATCH /api/v1/forms/{form_uid}/operations` | `PATCH /api/v1/{tenant}/forms/{form_uid}/operations` |
| `POST /api/v1/forms/{form_uid}/fields/{field_uid}/upload` | `POST /api/v1/{tenant}/forms/{form_uid}/fields/{field_uid}/upload` |
| `POST/GET/DELETE /api/v1/forms/{form_uid}/partial` | `POST/GET/DELETE /api/v1/{tenant}/forms/{form_uid}/partial` |
| `POST /api/v1/forms/{form_uid}/events/{event_name}` | `POST /api/v1/{tenant}/forms/{form_uid}/events/{event_name}` |
| `GET /api/v1/forms/{form_uid}/audio/ws` (WebSocket) | `GET /api/v1/{tenant}/forms/{form_uid}/audio/ws` |
| `POST /api/v1/forms/{form_uid}/publish` | `POST /api/v1/{tenant}/forms/{form_uid}/publish` |
| `GET/POST /api/v1/fields` | `GET/POST /api/v1/{tenant}/fields` |
| `GET /api/v1/forms/{form_uid}/versions` | `GET /api/v1/{tenant}/forms/{form_uid}/versions` |
| `GET /api/v1/forms/{form_uid}/versions/{version}` | `GET /api/v1/{tenant}/forms/{form_uid}/versions/{version}` |
| `GET /api/v1/forms/{form_uid}/import-report` | `GET /api/v1/{tenant}/forms/{form_uid}/import-report` |
| `GET /api/v1/form-controls` | **unchanged** — `GET /api/v1/form-controls` |

### HTML pages + Telegram (`ui/routes.py`, `base_path` default: `""`)

| Old (0.8.x) | New (0.9.0) |
|---|---|
| `GET /` | `GET /{tenant}/` |
| `GET /gallery` | `GET /{tenant}/gallery` |
| `GET /forms/{form_uid}` | `GET /{tenant}/forms/{form_uid}` |
| `POST /forms/{form_uid}` | `POST /{tenant}/forms/{form_uid}` |
| `GET /forms/{form_uid}/schema` | `GET /{tenant}/forms/{form_uid}/schema` |
| `GET /forms/{form_uid}/telegram` | `GET /{tenant}/forms/{form_uid}/telegram` |
| `POST /api/v1/forms/{form_uid}/telegram-submit` | `POST /api/v1/{tenant}/forms/{form_uid}/telegram-submit` |

## The new error contract

Every rejection carries a machine-readable `error` slug so frontends can
branch on one vocabulary, whether the underlying transport is HTTP or a
WebSocket close.

### 400 — `tenant_not_declared`

The URL carried no tenant segment (or it was empty, e.g. `//forms`).

```json
{
  "error": "tenant_not_declared",
  "message": "This endpoint requires an explicit tenant.",
  "expected": "/api/v1/{tenant}/forms/{form_uid}"
}
```

### 403 — `tenant_forbidden`

The declared tenant is not one the caller is a member of
(`session["session"]["programs"]`), and the caller is not a superuser.

```json
{
  "error": "tenant_forbidden",
  "message": "You are not authorized for the declared tenant.",
  "expected": "/api/v1/{tenant}/forms/{form_uid}"
}
```

### 400 — `tenant_conflict`

A POST/PUT/PATCH body declared a `tenant` that differs from the URL
segment. The URL is authoritative on every verb; a matching or absent body
`tenant` is fine.

```json
{
  "error": "tenant_conflict",
  "message": "The body tenant does not match the URL tenant.",
  "expected": "/api/v1/{tenant}/forms/{form_uid}"
}
```

### 404 — cross-tenant form access (no dedicated slug)

Requesting a `form_uid` that belongs to a *different* tenant than the one
declared returns a plain 404 (the same shape as "form not found"), **never**
403 — a 403 would confirm the form exists under some other tenant, which is
an existence oracle:

```json
{"error": "form_not_found"}
```

### Audio WebSocket — same vocabulary, WS close instead of HTTP status

The audio WS route cannot return an HTTP status once the connection is
upgraded, so tenant rejections are reported as a WebSocket **close code
1008** (policy violation), preceded by a JSON error message using the same
`error` slugs (`TENANT_NOT_DECLARED`, `TENANT_MISMATCH` as the `code`
field, matching the HTTP body's `error` slug in spirit).

## The POST-body rule

**The URL is authoritative on every verb, including POST.** A request body
*may* additionally carry `"tenant"`; when present, it is a cross-check
against the URL segment — matching or absent, it is accepted; a mismatch is
400 `tenant_conflict`. The body value is never trusted as an override or a
substitute for the URL.

```
POST /api/v1/flexroc/forms
{"title": "New Form", "tenant": "flexroc"}   → 200 OK (matches)

POST /api/v1/flexroc/forms
{"title": "New Form"}                         → 200 OK (no body tenant — fine)

POST /api/v1/flexroc/forms
{"title": "New Form", "tenant": "navigator"}  → 400 tenant_conflict
```

## What did NOT change

- `/org/*` route paths and behaviour — see the dedicated section above.
- `/api/v1/form-controls` — unchanged, unprefixed.
- `FormRegistry.default_tenant` as a constructor parameter — it still
  exists for non-HTTP entry points (`load_from_directory`, boot hydration)
  where no request exists to declare a tenant. Only the forms **HTTP
  boundary** stopped using it as a fallback.
- `require_tenant` — unrelated to this change (see the spec's Known Risks
  section for why it was never the cause of NAV-9370/9372).
- Query-string parameters in general — the tenant specifically never
  travels in the query string, on any verb.

## Zero host wiring required

Installing `parrot-formdesigner>=0.9.0` is sufficient. Unlike an earlier,
rejected design (`forms_tenant_context_middleware` in this repository's own
`app.py`, which was never installed by the wheel and therefore reached no
consumer), the tenant declaration + authorization is a decorator shipped
inside the package itself, composed at route-registration time. Neither
`fieldsync` nor `navigator` needs to edit an `app.py`, register a
middleware, or otherwise wire anything — only the URL update described
above.
