---
type: Wiki Overview
title: JiraToolkit — Remove Silent Default Auth
id: doc:docs-superpowers-specs-2026-07-06-jiratoolkit-remove-default-auth-design-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Now that the toolkit supports per-user OAuth 2.0 (3LO) authentication, the
relates_to:
- concept: mod:parrot.bots.jira_specialist
  rel: mentions
- concept: mod:parrot_tools.jiratoolkit
  rel: mentions
---

# JiraToolkit — Remove Silent Default Auth

**Date**: 2026-07-06
**Status**: Approved
**Area**: `parrot_tools.jiratoolkit`, `parrot.bots.jira_specialist`

## Problem

Now that the toolkit supports per-user OAuth 2.0 (3LO) authentication, the
legacy "default auth" is a liability. When no credentials are passed, the
toolkit silently:

1. **Guesses `auth_type`** from the server URL
   (`atlassian.net` → `basic_auth`, else `token_auth`).
2. **Falls back to env-var credentials** (`JIRA_USERNAME` / `JIRA_PASSWORD` /
   `JIRA_API_TOKEN`), building a working *shared service-account* client.

A tool that is meant to authenticate per-user therefore silently acts as a
single shared identity when misconfigured — a correctness and security
problem. The `JiraSpecialist` compounds this with its own default
(`effective = auth_type or "basic_auth"`).

## Goal

Remove the silent default. When authentication cannot be established from
**explicit** configuration, surface an explicit, actionable error to the LLM
at tool-call time instead of quietly using a shared account.

## Decisions

- **Scope**: Keep env-var service accounts working when a static `auth_type`
  is *explicitly* selected (arg or `JIRA_AUTH_TYPE`). Only the *implicit*
  default is removed.
- **Error surface**: Call-time `AuthorizationRequired` envelope to the LLM
  (converted by `ToolManager.execute_tool` into an
  `authorization_required` `ToolResult`). Not a constructor crash — a
  `ValueError` in `__init__` never reaches the model and would leave the
  agent with no Jira tools registered at all.

## Design

### 1. `JiraToolkit.__init__` (`jiratoolkit.py`)

- **Remove the URL-guessing heuristic.** `auth_type` comes only from the
  constructor arg or `JIRA_AUTH_TYPE`. If neither is set, `auth_type` stays
  `None`.
- **No silent client for the unconfigured case.** Add a deferred
  `self._auth_error: Optional[str]`. When `auth_type is None` and no
  `credential_resolver` is supplied, do **not** build a client; record a
  clear `_auth_error` and return. Env credentials are still *read* but never
  used to fabricate a default client.
- **Explicit static modes unchanged for the happy path.** When `auth_type`
  is explicitly `basic_auth` / `token_auth` / `oauth`, `server_url` is still
  required and the client is built from arg-or-env credentials. If the
  required credentials are entirely missing, the `ValueError` from
  `_init_jira_client` is caught and stored as `_auth_error` (so tools stay
  registered and the error reaches the LLM rather than crashing
  construction).
- `oauth2_3lo` path is unchanged (still requires `credential_resolver`).

### 2. `JiraToolkit._pre_execute` (`jiratoolkit.py`)

At the top, for non-`oauth2_3lo` modes: if `self._auth_error is not None`,
raise `AuthorizationRequired(tool_name=..., message=self._auth_error,
provider="jira")`. Otherwise the existing no-op behavior stands.

### 3. `JiraSpecialist.post_configure` (`jira_specialist.py`)

Drop `effective = auth_type or "basic_auth"`. When there is no OAuth manager
**and** no explicit `JIRA_AUTH_TYPE`, build the toolkit without an
`auth_type` (unauthenticated state) rather than fabricating a `basic_auth`
service account. Credentials are passed only for an explicitly configured
static mode.

## Testing

- No `auth_type` + no `credential_resolver` → construction succeeds, tools
  registered, any tool call raises `AuthorizationRequired` (`provider="jira"`).
- Explicit `basic_auth` + env creds → client built, no `_auth_error`,
  `_pre_execute` is a no-op (regression: service accounts still work).
- Explicit `basic_auth` with missing creds → construction succeeds,
  tool call raises `AuthorizationRequired`.
- URL heuristic removed: `JiraToolkit(server_url="https://x.atlassian.net")`
  with no creds no longer becomes a working `basic_auth` client.
- `oauth2_3lo` behavior unchanged.
- `JiraSpecialist.post_configure` with no auth type + no oauth manager builds
  an unauthenticated toolkit (no silent basic_auth).

## Out of scope

- Full removal of env-var credential reading.
- Changes to the `oauth2_3lo` per-user flow.
- `jira_reconfigure_auth` semantics.

---

## Follow-up: `GitToolkit` (GitHub) — same treatment

The GitHub toolkit had the same silent env-var credential fallback. It
differs from Jira in two ways that made the change smaller:

- It **already** surfaces an explicit error to the LLM at tool-call time
  (`GitToolkitError`, e.g. "personal access token required") via the lazy
  `_default_token` / `_resolve_connection` / `_RepoConnection.token` paths.
  No new error mechanism was needed.
- It has **no per-user mode** (only `pat` / `github_app`), and its sole
  production consumer (`GitHubReviewer._build_git_toolkit`) already reads
  `GITHUB_*` from config at the wiring layer and passes credentials
  explicitly (disabling itself when they are absent).

### Change

Removed the silent `os.getenv` credential fallbacks from
`GitToolkit.__init__`:

- `github_token` (PAT) — no `GITHUB_TOKEN` fallback.
- `app_id` / `installation_id` — no `GITHUB_APP_ID` /
  `GITHUB_APP_INSTALLATION_ID` fallback.
- `private_key` / `private_key_path` — no `GITHUB_APP_PRIVATE_KEY` /
  `GITHUB_APP_PRIVATE_KEY_PATH` fallback.

Credentials must now be passed explicitly. Non-credential env reads
(`GIT_DEFAULT_REPOSITORY` / `GITHUB_REPOSITORY`, `GIT_DEFAULT_BRANCH`) are
retained — they are not auth. Removed the now-dead `_coerce_int` helper and
updated the call-time error messages (and the `repositories` field
docstring) to state there is no env fallback.

### Divergence from the Jira decision

For Jira we *kept* env-var service accounts when a static `auth_type` was
explicitly selected, because `auth_type` was the explicit-intent signal.
GitToolkit has no such signal (`auth_type` defaults to `pat`), and its
wiring layer already passes credentials explicitly, so credential env reads
are removed entirely rather than gated. This is the faithful analog of
"remove the default fallback auth" for a toolkit with no per-user mode.

### Testing

`TestNoDefaultAuthFallback` in `test_gittoolkit_github_app.py`: env
`GITHUB_TOKEN` / `GITHUB_APP_*` are ignored; explicit PAT still works and
ignores env; ad-hoc connections require an explicit token; app mode requires
explicit `app_id` / `private_key`. All existing GitToolkit + reviewer tests
pass unchanged.
