<!--
  sdd/templates/design_research.prompt.md — neutral design-research brief (FEAT-545).
  Rendered by /sdd-spec section 3b and piped to `codex exec ... --output-schema
  design_research.schema.json`.
  FORBIDDEN INPUTS: never paste the spec draft, the spec author's reasoning, a preferred
  conclusion, or any text written by the model that will author the spec. The brief carries
  ONLY the accepted exploration document (brainstorm/proposal) and verified code anchors.
  Placeholders (double-curly-brace tokens, deliberately NOT written with literal braces in
  this comment — a renderer that does a naive whole-document string replace must not also
  rewrite this sentence): problem_statement, constraints_and_goals,
  recommended_option_or_scope, code_context_paths, open_questions, question.
-->
# Independent design review — read-only

You are an independent design reviewer for **ai-parrot**, an async-first Python
framework for AI agents (aiohttp, Pydantic v2, `uv` workspace under `packages/`).
You have read-only access to the repository in your working directory.

## Rules
1. Read the code you cite. Every `affected_paths` entry must be a repo-relative
   path you actually opened; suggestions with unverifiable paths are discarded.
2. Judge the design intent below against what exists in the repository: what is
   missing, what is risky, what would be simpler, what the codebase already
   provides that the intent re-invents.
3. Do not restate the intent, do not praise it, do not write code. Propose at
   most 12 concrete, falsifiable suggestions, each tagged with a kind
   (`architecture` | `api` | `testing` | `risk` | `alternative`), a risk level and
   your confidence.
4. Output exactly ONE JSON object conforming to the schema you were given — no
   markdown fences, no prose before or after.

## Accepted design intent (verbatim from the exploration document)

### Problem statement
navigator-auth ≥ 0.28.x ships a complete passkey (WebAuthn / FIDO2) backend —
`PasskeyAuth`, merged in
[phenobarbital/navigator-auth#607](https://github.com/phenobarbital/navigator-auth/pull/607)
(FEAT-101, merged 2026-10-02). It exposes a public sign-in ceremony
(`POST /api/v1/auth/passkey/login/options` + `POST /api/v1/login` with
`X-Auth-Method: PasskeyAuth`), session-bound enrollment
(`register/options`, `register/verify`) and credential management
(`GET/PATCH/DELETE /api/v1/auth/passkey/credentials`). The installed
`navigator-auth 0.28.9` already contains all of it.

ai-parrot cannot use any of it today:

- The Admin UI login page (`packages/ai-parrot-server/ui/src/pages/Login.svelte`)
  only knows the `BasicAuth` username/password form. Non-external backends
  discovered through `/api/v1/auth/methods` render as a **disabled** button
  ("Not yet supported in this Admin UI"), so even with `PasskeyAuth` enabled a
  user sees a dead button.
- There is no user-level account/security page anywhere in the SPA, so nobody
  can **enroll** a first passkey or manage existing ones.
- `ai-parrot-server` declares no `navigator-auth[passkey]` extra: the shared
  venv has `fido2` but **not** `webauthn` (py_webauthn), so `PasskeyAuth`
  refuses to start (`ConfigError`) on a stock install.
- The inline admin login page (`parrot/autonomous/admin.py`, served at
  `/autonomous/admin`) is BasicAuth-only as well.

**Who is affected**: every operator who wants phishing-resistant, passwordless
login for the agent workspace and admin pages (end users and admins alike);
ops teams who want ABAC policies keyed on `auth_method == "passkey"` /
`mfa == true` (the backend already emits those session keys).

**Why now**: the backend work is done and released; the only missing piece is
the client side that drives the browser ceremonies.

### Constraints and goals
- **Scope (Round 1/2 decisions)**: sign-in **and** enrollment **and**
  credential management in the Admin UI; server-side wiring in ai-parrot
  (optional extra + operator docs + example settings); passkey **sign-in only**
  in the inline `/autonomous/admin` page. `parrot-formdesigner` has no login
  form (it redirects to `/admin` when `ai_parrot_token` is missing), so it
  needs no change.
- **Sign-in UX**: explicit "Sign in with a passkey" button (username-first when
  a username is typed, usernameless otherwise) **plus** conditional UI /
  autofill (`autocomplete="username webauthn"` + `mediation: "conditional"`),
  mirroring navigator-auth's own OAuth2 login page.
- **Visibility**: no new build flag. Show passkey UI only when the browser has
  `window.PublicKeyCredential` and the public `login/options` endpoint answers;
  the **same** usernameless `login/options` call is reused as the conditional-UI
  challenge (one request per login-page load).
- **Session model unchanged**: the SPA keeps authenticating with
  `Authorization: Bearer <token>` from `ai_parrot_token`; a passkey login must
  produce the same login envelope (`data.token` + user payload) and store it
  through the existing `AuthStore` so `handle401()`, `logout()`, the Topbar
  identity and `parrot-formdesigner`/`admin.py` interop keep working.
- **Enrollment auth**: Bearer-authenticated requests skip navigator-auth's CSRF
  double-submit check, so the SPA's enrollment/management calls go through the
  existing `apiClient` with no CSRF plumbing. (The inline admin page also uses
  a Bearer token and needs none either.)
- **Relying-party origin**: the backend resolves the RP **only** from the
  browser `Origin` header against `PASSKEY_RELYING_PARTIES` (exact match). The
  SPA is same-origin in production; during `pnpm dev` the Vite origin
  (`http://localhost:5173`) must be listed as an RP or ceremonies 4xx. Docs
  must say so.
- **Browser compatibility**: use the native
  `PublicKeyCredential.parseRequestOptionsFromJSON` /
  `parseCreationOptionsFromJSON` / `credential.toJSON()` when available
  (Chrome 129+, Safari 18+, Firefox 119+) and a hand-written base64url fallback
  otherwise. **No new npm dependency.**
- **Routing**: new user-level section `/account/security`. A new first path
  segment means updating `config.appSections` **and** `SPA_SECTIONS` in
  `parrot/server/ui/serving.py` (and its tests) in lockstep, or the SPA shell
  will 404 / be auth-blocked on a hard reload.
- **Security**: never show a different error for "unknown user" vs "bad
  assertion" (the backend returns a uniform 401; the UI must not undo that);
  treat `NotAllowedError` / `AbortError` as a dismissed prompt, not an error;
  an explicit click must abort a pending conditional-UI request before starting
  a modal one (two concurrent `credentials.get` calls reject).
- **Conventions**: Svelte 5 runes only, `$lib` imports, vendored shadcn
  primitives (`button`, `card`, `input`, `label`, `dialog`, `badge`,
  `skeleton` exist — there is **no** `dropdown-menu`), vitest +
  `@testing-library/svelte` next to the code; Python side `aiohttp` only.
- **Tests**: vitest with a mocked `navigator.credentials` (jsdom has none) and
  mocked `apiClient`/`axios`; pytest for `serving.py` section changes and the
  admin inline page.

---

### Recommended option / probable scope
**Option A** is recommended because:

- It is the only option that delivers the full agreed scope (sign-in **plus**
  enrollment **plus** management) without changing the SPA's Bearer-token auth
  contract or adding a runtime dependency. Options C and D either replace the
  login architecture or trade typing/testability for a small code-sharing win,
  and neither removes the need for the Svelte security page.
- The hand-written helper is the known cost: ~60 lines of base64url fallback
  already battle-tested upstream, plus native-API-first paths that most current
  browsers take. That is cheaper to own than a library whose autofill/abort
  model fights the agreed "one call = probe + conditional UI, click aborts it"
  behaviour (Option B).
- Duplicating the ceremony into `admin.py`'s inline page is accepted: that page
  is a self-contained HTML string by design (no bundler), it only needs
  sign-in, and the duplicated block is the same vanilla JS navigator-auth
  already maintains — the brainstorm records this as a known duplication rather
  than inventing a shared-asset mechanism (Option D).

What we trade off: a second WebAuthn code path (TypeScript module vs inline
vanilla JS) that must stay behaviourally aligned, and one more place
(`/account`) where `config.appSections` and `SPA_SECTIONS` must match.

---

A small typed WebAuthn helper module in the SPA (JSON ⇄ ArrayBuffer
conversion with native-API-first, hand-written fallback; capability detection;
`AbortController` handling), a `passkey` API module wrapping the six backend
endpoints, an `AuthStore.loginWithPasskey()` method that reuses the Basic
login's token-storage path, a `PasskeySignIn` component dropped into
`Login.svelte` (button + conditional UI; replaces the disabled
`ProviderButtons` entry for the passkey backend), and a new
`pages/account/Security.svelte` page (list / add / rename / delete passkeys)
registered as route `/account/security`, linked from the Sidebar "Workspace"
section (and/or a Topbar link). Server side: `ai-parrot-server[passkey]` extra
(`navigator-auth[passkey]`), `SPA_SECTIONS += "/account"`, operator docs in
`docs/admin-ui.md`, example `AUTHENTICATION_BACKENDS` /
`PASSKEY_RELYING_PARTIES` settings, and the same vanilla-JS passkey block
navigator-auth ships in its OAuth2 login page added to `_ADMIN_LOGIN_HTML`
(sign-in only).

✅ **Pros:**
- Zero new runtime dependencies; the fallback is ~60 lines and already proven
  in navigator-auth's `templates/oauth/login.html`.
- Fully typed and unit-testable with the existing vitest setup (mock
  `navigator.credentials`, `PublicKeyCredential`).
- Reuses every existing seam: `AuthStore` token storage, `apiClient` 401
  interceptor, `router` + `App.svelte` route table, `nav.ts` registry,
  `SPA_SECTIONS`.
- Keeps the SPA's Bearer session model; enrollment needs no CSRF work.
- Gives users a real home for passkeys (`/account/security`) that later account
  features (API keys, sessions) can extend.

❌ **Cons:**
- More hand-written code than a library (`webauthn.ts` helper + its tests).
- A new top-level section touches both the UI config and the Python serving
  module — two places to keep in sync (already the documented rule, but a
  footgun).
- The inline admin page gets a second copy of the vanilla JS (inline HTML
  string, no bundler); it can't share the SPA's TypeScript module.

📊 **Effort:** Medium–High (≈ 8–10 tasks: helper, API module, store method,
sign-in component, security page, routing/nav, serving.py + tests, server
extra + docs/settings, admin.py inline page, docs).

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `navigator-auth[passkey]` (≥ 0.28.9) | `PasskeyAuth` backend + `webauthn>=2,<3` (py_webauthn) | New optional extra on `ai-parrot-server`; Redis ≥ 6.2 (GETDEL) |
| Browser WebAuthn Level 3 API | `PublicKeyCredential.parseRequestOptionsFromJSON` / `parseCreationOptionsFromJSON`, `credential.toJSON()`, `isConditionalMediationAvailable()` | Native in Chrome 129+, Safari 18+, Firefox 119+; fallback for older |
| `vitest` ^4 + `@testing-library/svelte` | Unit tests with mocked `navigator.credentials` | Already in `ui/package.json` |
| `pytest` + `aiohttp` test client | `serving.py` section/exclusion tests, admin inline page smoke test | Existing `tests/test_admin_ui_serving.py` |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-server/ui/src/pages/Login.svelte` — host for the passkey button + `autocomplete="username webauthn"` on the username input.
- `packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts` — `login()` token/user persistence path to factor into a shared "store login envelope" step used by `loginWithPasskey()`.
- `packages/ai-parrot-server/ui/src/lib/api/http.ts` — `apiClient` (Bearer + 401 interceptor) for enrollment/management; `extractServerMessage()` for `{reason}` error bodies.
- `packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte` — exclude the passkey backend the same way `isBasicAuth()` excludes BasicAuth.
- `packages/ai-parrot-server/ui/src/App.svelte` route table, `lib/nav.ts` registry, `lib/router.svelte.ts` `isInAppPath()`.
- `packages/ai-parrot-server/src/parrot/server/ui/serving.py` — `SPA_SECTIONS`, `_spa_paths()`, `_auth_exclusion_patterns()`.
- `packages/ai-parrot-server/src/parrot/autonomous/admin.py` — `_ADMIN_LOGIN_HTML` + `saveSession(data)` helper.
- navigator-auth `templates/oauth/login.html` (upstream, not vendored) — reference vanilla-JS ceremony to port into `admin.py`.

---

### Verified code anchors (paths only — open them yourself)
packages/ai-parrot-server/ui/src/pages/Login.svelte
packages/ai-parrot-server/ui/src/pages/Login.test.ts
packages/ai-parrot-server/ui/src/lib/stores/auth.svelte.ts
packages/ai-parrot-server/ui/src/lib/config.ts
packages/ai-parrot-server/ui/src/lib/router.svelte.ts
packages/ai-parrot-server/ui/src/App.svelte
packages/ai-parrot-server/ui/src/lib/nav.ts
packages/ai-parrot-server/ui/src/lib/components/Sidebar.svelte
packages/ai-parrot-server/ui/src/lib/components/Topbar.svelte
packages/ai-parrot-server/ui/src/lib/components/ProviderButtons.svelte
packages/ai-parrot-server/ui/src/lib/api/http.ts
packages/ai-parrot-server/ui/src/lib/api/auth-headers.ts
packages/ai-parrot-server/ui/vite.config.ts
packages/ai-parrot-server/ui/vitest-setup.ts
packages/ai-parrot-server/src/parrot/server/ui/serving.py
packages/ai-parrot-server/tests/test_admin_ui_serving.py
packages/ai-parrot-server/src/parrot/autonomous/admin.py
packages/ai-parrot-server/src/parrot/autonomous/orchestrator.py
packages/ai-parrot-server/pyproject.toml
packages/ai-parrot/pyproject.toml
app.py
docs/admin-ui.md
packages/parrot-formdesigner/src/parrot_formdesigner/ui/templates.py
.venv/lib/python3.12/site-packages/navigator_auth/backends/passkey.py
.venv/lib/python3.12/site-packages/navigator_auth/backends/abstract.py
.venv/lib/python3.12/site-packages/navigator_auth/backends/__init__.py
.venv/lib/python3.12/site-packages/navigator_auth/conf.py
.venv/lib/python3.12/site-packages/navigator_auth/passkey/rp.py
.venv/lib/python3.12/site-packages/navigator_auth/passkey/types.py

### Questions still open in the exploration document
none

## Question
Given this accepted design intent and these verified code anchors, how would you build it? What is missing, risky, or better done another way?
