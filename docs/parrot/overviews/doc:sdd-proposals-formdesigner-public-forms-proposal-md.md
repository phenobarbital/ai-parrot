---
type: Wiki Overview
title: 'FEAT-241 — Public forms: register/revoke auth-exempt paths in navigator-auth''s
  runtime exclude list'
id: doc:sdd-proposals-formdesigner-public-forms-proposal-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The original request, preserved verbatim. Full source at
---

---
id: FEAT-241
title: Public forms — register/revoke auth-exempt paths in navigator-auth's runtime exclude list
slug: formdesigner-public-forms
type: feature
mode: enrichment
status: review
source:
  kind: inline
  jira_key: null
  jira_url: null
  fetched_at: 2026-06-16
  summary_oneline: Public forms (is_public=True) register auth-exempt paths in navigator-auth's runtime exclude list; revoke on is_public=False.
overall_confidence: medium
base_branch: dev
research_state: sdd/state/FEAT-241/
created: 2026-06-16
updated: 2026-06-16
---

# FEAT-241 — Public forms: register/revoke auth-exempt paths in navigator-auth's runtime exclude list

> **Mode**: enrichment
> **Confidence**: medium
> **Source**: `inline`
> **Audit**: [`sdd/state/FEAT-241/`](../state/FEAT-241/)

---

## 0. Origin

The original request, preserved verbatim. Full source at
`sdd/state/FEAT-241/source.md`.

> Hay que permitir crear forms en parrot-formdesigner que si una propiedad
> "is_public" es TRUE, las URLs para acceder al form en sus distintas versiones
> (JSON schema, etc) y la URL para publicar resultados, debe ser registradas en
> el exclude list de navigator-auth, el problema radica en que las tablas de
> rutas son "frozen" (de hecho, son un frozenset) cuando termina de iniciar el
> servidor, hay que permitir que el middleware de navigator-auth (../navigator-auth)
> invoque una función que evalua de una lista de paths registrados para ser
> excluidos del middleware de auth, entonces FormDesigner puede simplemente
> agregar los paths relativos al Form a esa lista con un método de edición, y
> retirar de dicha lista si el usuario edita el formulario y apaga la propiedad
> (is_public=False).

**Initial signals** (extracted, not interpreted):
- Verbs: "permitir crear", "registradas", "invoque una función", "agregar", "retirar" → enrichment (new capability + edit flows)
- Named entities: `is_public`, `frozenset`, exclude list, navigator-auth middleware, FormDesigner, JSON schema, "publicar resultados"
- Components: parrot-formdesigner + navigator-auth (cross-repo)
- Acceptance criteria provided: no (intent + proposed mechanism only)

---

## 1. Synthesis Summary

The request asks parrot-formdesigner to expose a form's read/representation URLs
(get, JSON schema, rendered formats) and its result-submission/validation URLs
**without authentication** when a new `FormSchema.is_public` flag is `True`, and
to revoke that exemption when it flips to `False`. The source's premise — that
navigator-auth's exclude routes are a `frozenset` frozen at boot — is **outdated
for the per-app list**: `AuthHandler.setup` already seeds `app["auth_exclude_list"]`
as a mutable list, evaluated at *request time* by all three middlewares via
`fnmatch`, with an existing `add_exclude_list(path)` method. The genuine work is
therefore *smaller* on the middleware side (add symmetric remove + bulk + a
startup provider hook) but hides a *hard blocker* on the formdesigner side: every
form route is individually wrapped with `is_authenticated`, a handler-level
decorator that ignores the exclude list and 401s anonymous callers regardless. The
recommendation (confirmed with the requester) is to make navigator-auth the
general home — `is_authenticated` honors the exclude list, a provider-callback
re-hydrates paths on startup, and a bulk add/remove API — while formdesigner adds
`is_public`, computes the public paths, and registers a provider callback.

---

## 2. Codebase Findings

> All entries are grounded in `sdd/state/FEAT-241/findings/`. No fabricated
> paths or symbols.

### 2.1 Localization

| # | Path | Symbol | Lines | Role | Evidence |
|---|------|--------|-------|------|----------|
| 1 | `../navigator-auth/navigator_auth/auth.py` | `AuthHandler.setup` / `add_exclude_list` / `verify_exceptions` | 534-537, 666-677 | seeds, mutates, and request-time-evaluates the per-app exclude list | F003 |
| 2 | `../navigator-auth/navigator_auth/middlewares/abstract.py` | `base_middleware.excluding_routes` / `valid_routes` | 46-71 | per-middleware (frozen tuple) exemption matcher via `fnmatch` | F001 |
| 3 | `../navigator-auth/navigator_auth/conf.py` | `AUTH_EXCLUDE_LIST_KEY` / `exclude_list` | 44-58 | app key + default seed for the exclude list | F002 |
| 4 | `../navigator-auth/navigator_auth/decorators.py` | `is_authenticated` / `allow_anonymous` | 42-72, 126-176 | handler-level auth gate that **ignores** the exclude list (hard blocker) | F004 |
| 5 | `../navigator-auth/navigator_auth/abac/middleware.py` | abac exclude check | 33-36 | second middleware reading the same app exclude list | F003 |
| 6 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/routes.py` | `setup_form_api` / `_wrap_auth` | 67-89, 200-241 | mounts form routes, blanket-wraps each with `is_authenticated` | F005 |
| 7 | `packages/parrot-formdesigner/src/parrot_formdesigner/core/schema.py` | `FormSchema` | 300-315 | canonical form model; **lacks `is_public`** | F006 |
| 8 | `packages/parrot-formdesigner/src/parrot_formdesigner/api/handlers.py` | `create_form` / `update_form` / `patch_form` / `publish_form` | 741, 915, 963, 1437 | lifecycle hook points that persist via `registry.register` | F007 |

### 2.2 Constraints Discovered

- **The exclude list is already runtime-mutable, not a frozenset.**
  `app["auth_exclude_list"]` is a plain `list`, read at request time by the
  basic/jwt `auth_middleware` (`verify_exceptions`), `abac/middleware`, and
  `backends/abstract` via `fnmatch`. A `frozenset` exists nowhere in
  `navigator_auth` (grep → 0).
  *Implication*: target the per-app list (via `app["auth"].add_exclude_list`),
  **not** the per-middleware `exclude_routes` tuple, which is genuinely frozen at
  init and is the wrong hook.
  *Evidence*: F002, F003

- **`is_authenticated` is a second auth layer the exclude list does not cover.**
  It checks only `request["authenticated"]`, attempts every backend, and raises
  `HTTPUnauthorized` otherwise — never consulting `auth_exclude_list` or
  `allow_anonymous`. Exempting a path at the middleware level is necessary but
  **not sufficient** while the handler is wrapped with `is_authenticated`.
  *Implication*: navigator-auth's `is_authenticated` must learn to honor the
  exclude list / `allow_anonymous` (chosen approach, see §3 / U2).
  *Evidence*: F004, F005

- **The exclude list is in-memory and re-seeded every boot.**
  `AuthHandler.setup` unconditionally does `app[KEY] = list(exclude_list)`.
  Runtime-registered public-form paths are lost on restart.
  *Implication*: a startup re-hydration mechanism is mandatory (chosen: a
  navigator-auth exclude-provider callback, see §3 / U3).
  *Evidence*: F002, F003

- **Only `add_exclude_list` exists; there is no removal.**
  *Implication*: a symmetric (idempotent) `remove_exclude_list` plus bulk
  register/unregister are required for clean `is_public` on/off toggling.
  *Evidence*: F003

- **All mutating form handlers funnel through `registry.register(form, overwrite=True)`**
  and `registry.get` returns the prior form.
  *Implication*: centralize the add/remove toggle (e.g. in `FormRegistry` or a
  small gateway) and diff old-vs-new `is_public` instead of duplicating across
  four handlers.
  *Evidence*: F007

- **`fnmatch` patterns are globs.** The render endpoint's `{format}` collapses to
  one pattern `/api/v1/forms/<id>/render/*`; other public paths are exact.
  *Evidence*: F001, F003

### 2.3 Recent History (Relevant)

| Commit | When | Author | Message | Touched |
|--------|------|--------|---------|---------|
| `27b478b` | 2026-04-02 | Jesus Lara | wip: new pbac implementation — introduced the mutable per-app exclude list ("avoids global mutation") | `navigator_auth/auth.py` |

> This commit is *why* the "frozenset" premise is outdated: it replaced an earlier
> frozen/global structure with the current per-app mutable list.

---

## 3. Probable Scope  *(mode = enrichment)*

### What's New

- **`FormSchema.is_public: bool = False`** — platform-agnostic visibility flag
  (`core/schema.py`).  *Evidence*: F006
- **`AuthHandler.remove_exclude_list(path)`** + idempotent `add_exclude_list` +
  bulk `register_exclusions(paths)` / `unregister_exclusions(paths)` in
  navigator-auth.  *Evidence*: F003  *(U4)*
- **navigator-auth exclude-provider callback API** (e.g.
  `add_exclude_provider(async_fn)`), invoked for all providers on `on_startup`, so
  the in-memory list is re-hydrated after every restart.  *(U3)*
- **`is_authenticated` honors the exclude list / `allow_anonymous`** — short-circuit
  before attempting backends when the path is exempt.  *Evidence*: F004  *(U2)*
- **A formdesigner public-path helper** — `(form_id, base_path) → list[str]` of
  exempt glob patterns.  *Evidence*: F005
- **A formdesigner exclude-provider** registered with navigator-auth, yielding the
  public paths of all persisted `is_public=True` forms (the restart re-hydration
  source of truth lives in the forms store).  *Evidence*: F007  *(U3)*

### What Changes

- **`navigator_auth/decorators.py::is_authenticated`** — add exclude-list /
  `allow_anonymous` short-circuit.  *Evidence*: F004  *(U2)*
- **`parrot_formdesigner/api/handlers.py`** (`create_form`/`update_form`/
  `patch_form`/`publish_form`/`delete_form`) **or** `FormRegistry.register` /
  `FormRegistry.delete` — on an `is_public` transition (and on deletion of a
  public form) call bulk register/unregister against `request.app["auth"]`.
  Deleting a public form **must** unregister its exempt paths so its URLs do not
  remain anonymous.  *Evidence*: F007
- **`parrot_formdesigner` startup** — register the exclude-provider callback so
  public paths survive restarts.  *Evidence*: F007  *(U3)*

### Public URL set (confirmed — U1)

For a form `{id}` under `base_path` `/api/v1`, when `is_public=True`:
- `GET  /api/v1/forms/{id}`              (get_form)
- `GET  /api/v1/forms/{id}/schema`       (JSON schema)
- `GET  /api/v1/forms/{id}/render/*`     (rendered representations — glob)
- `POST /api/v1/forms/{id}/data`         (submit results)
- `POST /api/v1/forms/{id}/validate`     (pre-submit validation)

### What's Untouched (Non-Goals)

- The per-middleware `exclude_routes` *tuple* mechanism (frozen by design; wrong hook).
- RBAC / tenant authorization — "public" means anonymous-readable, orthogonal to RBAC.
- The Telegram / UI surface (`setup_form_ui`) — only the JSON REST surface is in scope.

### Patterns to Follow

- Existing `add_exclude_list` and the per-app `app[AUTH_EXCLUDE_LIST_KEY]` list —
  mirror its idiom for `remove`/bulk.  *Evidence*: F003
- `FormRegistry.on_startup` already hooks aiohttp `on_startup` — natural home for
  registering the exclude-provider.  *Evidence*: F007

### Integration Risks

- **Two-repo change, ordered rollout.** navigator-auth must ship the
  `is_authenticated` change + provider API *before* formdesigner relies on it
  (formdesigner already hard-imports navigator-auth — F005). Pin a minimum
  navigator-auth version.  *Evidence*: F004, F005
- **Path/`base_path` drift.** The helper must derive paths from the same
  `base_path` used by `setup_form_api`, or exemptions silently won't match.
  *Evidence*: F005
- **Stale exemptions.** Deleting a public form must also unregister its paths,
  else a deleted form's URLs stay anonymous. (Add `delete_form` to the toggle set.)
  *Evidence*: F007

---

## 4. Confidence Map

| ID | Claim | Evidence | Confidence | Reasoning |
|----|-------|----------|------------|-----------|
| C1 | navigator-auth's per-app exclude list is a runtime-mutable list evaluated at request time, not a frozenset | F002, F003 | high | direct read of `setup` + `verify_exceptions`; grep `frozenset` → 0 |
| C2 | `add_exclude_list` exists; no removal method does | F003 | high | direct read + grep `remove/discard` → 0 |
| C3 | `is_authenticated` 401s anonymous callers even on exclude-listed paths | F004 | high | decorator body checks only `request["authenticated"]`, never the exclude list |
| C4 | `FormSchema` has no `is_public` field today | F006 | high | direct read + package-wide grep → 0 |
| C5 | The public URL set is get/schema/render-*/data/validate | F005 | medium | route table + source intent + user confirmation (U1) |
| C6 | Runtime-registered exempt paths are lost on restart and need re-hydration | F002, F003 | high | `setup` unconditionally re-seeds the list each boot |
| C7 | The toggle should be centralized (registry/gateway), not duplicated across handlers | F007 | medium | all handlers funnel through `register`; design recommendation |

Distribution: **5** high, **2** medium, **0** low.

---

## 5. Open Questions

### Resolved (during proposal phase)

- [x] **Which form URLs become anonymous when `is_public=True`?** — *Resolved*:
  `GET /forms/{id}`, `GET /forms/{id}/schema`, `GET /forms/{id}/render/*`,
  `POST /forms/{id}/data`, `POST /forms/{id}/validate`.  *Resolves*: C5
- [x] **How to bypass handler-level `is_authenticated`?** — *Resolved*: enhance
  navigator-auth so `is_authenticated` short-circuits when the path is in
  `app["auth_exclude_list"]` or `allow_anonymous` is set (global fix).  *Resolves*: C3
- [x] **Who re-hydrates the in-memory exclude list on restart?** — *Resolved*:
  navigator-auth exposes an exclude-provider callback API invoked on `on_startup`;
  parrot-formdesigner supplies a provider yielding persisted `is_public` form
  paths.  *Resolves*: C6
- [x] **What navigator-auth API to add?** — *Resolved*: idempotent
  `add_exclude_list` + `remove_exclude_list` + bulk
  `register_exclusions`/`unregister_exclusions`.  *Resolves*: C2
- [x] **Should `delete_form` also unregister exempt paths?** — *Resolved*: yes —
  deleting a public form must unregister its exempt paths so the form's URLs do
  not remain anonymous. `delete_form` / `FormRegistry.delete` joins the toggle
  set.  *Resolves*: C7

### Unresolved (defer to spec / implementation)

- [ ] **Minimum navigator-auth version / release ordering for the two-repo rollout.**
  — *Owner*: tbd.

---

## 6. Recommended Next Step

**`/sdd-spec FEAT-241`** — *Rationale*: localization is high-confidence (C1–C4, C6),
the change is bounded across two known files per repo, and all four architectural
decisions are now resolved (U1–U4). The spec can pin the residual delete-form and
release-ordering questions as acceptance criteria.

### Alternatives

- **`/sdd-brainstorm FEAT-241`** — only if the navigator-auth `is_authenticated`
  behavior change (U2) proves contentious in review and you want to weigh the
  formdesigner-local wrapper alternative.
- **Manual review** — not needed; research was complete (not truncated).

---

## 7. Research Audit

| Artifact | Path |
|----------|------|
| State checkpoints | `sdd/state/FEAT-241/state.json` |
| Source (raw) | `sdd/state/FEAT-241/source.md` |
| Research plan | `sdd/state/FEAT-241/research_plan.json` |
| Findings (digests) | `sdd/state/FEAT-241/findings/F001…F007` |
| Synthesis (JSON) | `sdd/state/FEAT-241/synthesis.json` |

**Budget consumed**:
- Files read: 8 / 40
- Grep calls: 13 / 25
- Git calls: 2 / 10
- Depth: 2 / 2
- Truncated: **no**

**Mode determination**: `auto` → resolved to `enrichment` (new capability +
edit/lifecycle flows; no failure/negation in source).

---

## 8. Provenance

| Field | Value |
|-------|-------|
| Generated by | `/sdd-proposal v1.0` |
| Synthesis prompt | `sdd/templates/synthesis.prompt.md v1.0` |
| Plan prompt | `sdd/templates/research_plan.prompt.md v1.0` |
| Schema versions | state=1.0, synthesis=1.0, research_plan=1.0 |
| Operator | Claude (Opus 4.8) for Jesus Lara |
