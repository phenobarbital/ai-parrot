---
id: FW-009
query_id: Q001
type: wiki_query
intent: "Depth-2 follow-up from Q001/cli lazy-command map: FEAT-696 `parrot jiratoolkit` — a CLI-side 3LO login already exists; how is it keyed and consumed?"
executed_at: 2026-10-30T15:24:00Z
duration_ms: 3000
parent_id: FW-001
depth: 2
---

# FW-009 — FEAT-696 `parrot jiratoolkit auth`: a working CLI 3LO login (manual-paste flow, local file token store) consumed by `JiraToolkit` under a FIXED identity `local:cli`

## Summary

The lazy command map registers `"jiratoolkit": "parrot_tools.jira_cli"` (FEAT-696, ai-parrot-tools). `jira_cli.py` implements `auth` (L283-351): builds the Atlassian authorize URL with `build_authorization_url(client_id, redirect_uri, state, scopes)` from `parrot.auth.jira_oauth`, prints it, asks the user to **paste the redirected URL** (CSRF `state` verified with `hmac.compare_digest`; `--allow-bare-code` bypass), exchanges the code with `exchange_code`, lists accessible sites (`fetch_accessible_resources`), calls `/myself`, and stores the token in a `LocalJiraTokenStore` (`parrot_tools.jira_local_auth`) — plus `status`, `logout`, `sync-kb`. Consumption: `JiraToolkit(auth_type="oauth2_local")` normalizes to `oauth2_3lo` with `_local_single_user=True` and a `FileTokenCredentialResolver`; `_pre_execute` (jiratoolkit.py L1316-1409) then resolves with `channel="cli"`, `user_id="local"`, `user_key="local:cli"` and, if a `PermissionContext` IS present, requires its channel in `credential_resolver.allowed_channels` (TASK-4421 identity guard). So the CLI 3LO precedent exists end to end but (a) needs no server (client secret lives in the user's env/.env), (b) is single-user with no principal, (c) has its own token file store outside the Identity Vault, (d) is Jira-specific. S-4 is essentially "generalize this to any descriptor provider, key it by principal, and store via the S-1 `CredentialStore`".

## Citations

- path: `packages/ai-parrot/src/parrot/cli/__init__.py`
  lines: 130-131
  symbol: `cli._lazy_commands`
  excerpt: |
    # FEAT-696 — Jira toolkit CLI (local 3LO auth, KB sync), ships in ai-parrot-tools.
    "jiratoolkit": "parrot_tools.jira_cli",

- path: `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py`
  lines: 1-35
  symbol: imports
  excerpt: |
    from parrot.auth.jira_oauth import DEFAULT_SCOPES, JiraTokenSet, build_authorization_url, exchange_code,
        fetch_accessible_resources, fetch_myself
    from parrot_tools.jira_local_auth import FileTokenCredentialResolver, LocalJiraTokenStore

- path: `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py`
  symbol: `parse_pasted_redirect`
  excerpt: |
    def parse_pasted_redirect(text): Extract (code, state|None) from a pasted redirect URL or bare code.

- path: `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py`
  lines: 283-351
  symbol: `auth`
  excerpt: |
    state = _new_state()
    authorize_url = build_authorization_url(client_id, redirect_uri, state, scope_list)
    click.echo("Open this URL in your browser, authorize access, then paste the redirected URL here:\n")
    pasted = click.prompt("Redirected URL or code")
    code, returned_state = parse_pasted_redirect(pasted)
    if ... not hmac.compare_digest(returned_state, state): raise click.ClickException("State mismatch ...")
    token_data, resources = asyncio.run(_exchange_and_list(client_id, client_secret, code, redirect_uri))

- path: `packages/ai-parrot-tools/src/parrot_tools/jira_cli.py`
  symbol: `status` / `logout` / `_load_fresh_token`
  excerpt: |
    def status(site) / def logout(site) / def _load_fresh_token(site): stored token, refreshed through the local resolver when expired

- path: `packages/ai-parrot-tools/src/parrot_tools/jiratoolkit.py`
  lines: 1316-1409
  symbol: `JiraToolkit._pre_execute`
  excerpt: |
    perm_ctx = kwargs.get("_permission_context")
    if self._local_single_user:
        if perm_ctx is not None and channel not in self.credential_resolver.allowed_channels: raise AuthorizationRequired(...)
        channel = "cli"; user_id = "local"; user_key = "local:cli"
        token_set = await self.credential_resolver.resolve(channel, user_id)
    else:
        if perm_ctx is None: raise AuthorizationRequired("Permission context is required for Jira OAuth 2.0 (3LO) tools ...")

## Notes

Wiki: `sym:...tests/unit/test_oauth2_local_wiring.py#TestOAuth2LocalMode` (1.00; "Verify the local OAuth mode uses a fixed local identity"), `sdd/specs/jiratoolkit-upgrades.spec.md` (0.95), `sym:JiraToolkit._pre_execute` (0.83), `TASK-4421` (0.62), `TASK-4422` Jira CLI (0.33), `sym:jira_cli.py#auth` (0.12), `file:jira_cli.py` (0.01). The flow is **manual paste** — no loopback listener, no server callback — which sidesteps the redirect-URI problem entirely and is browser-agnostic (works over SSH). S-1 M7 rewrites `JiraOAuthManager` on the generic engine; `parrot.auth.jira_oauth` helpers (`build_authorization_url`, `exchange_code`) that `jira_cli.py` imports may move or change — S-4 must re-verify them after FEAT-773 merges.
[cross-lane: type=read, intent=parrot_tools/jira_local_auth.py — LocalJiraTokenStore file location/permissions and FileTokenCredentialResolver.allowed_channels]
[cross-lane: type=grep, intent=does FEAT-773 S-1 spec M7 keep build_authorization_url/exchange_code in parrot.auth.jira_oauth (edit sites)]
