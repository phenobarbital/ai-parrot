# `parrot login` and connections

This guide is for operators deploying CLI authentication, users connecting
provider accounts, and integrators running local MCP toolkits.

## Deployment prerequisites

Complete these navigator-auth changes before giving users the CLI:

1. Add `navigator_auth.backends.oauth2.Oauth2Provider` to
   `AUTHENTICATION_BACKENDS`.
2. Register a static OAuth client named `parrot-cli` with
   `client_type="public"`, `allowed_grant_types` containing `device_code` and
   `refresh_token`, and `default_scopes` containing `openid`, `profile`, and
   `email`. Public clients must use PKCE.
3. Configure the authorization server settings below. The values shown are the
   shipped defaults except for `OAUTH_DEVICE_VERIFICATION_URI`, which must be
   the public verification page for the deployment.

```text
OAUTH_ACCESS_TOKEN_TTL=3600
OAUTH_REFRESH_TOKEN_TTL=2592000
OAUTH_REFRESH_ROTATION=True
OAUTH_REQUIRE_PKCE_PUBLIC=True
OAUTH_DEVICE_CODE_TTL=600
OAUTH_DEVICE_POLL_INTERVAL=5
OAUTH_DEVICE_SLOW_DOWN_INCREMENT=5
OAUTH_DEVICE_VERIFICATION_URI=https://auth.example.com/device
```

Provider descriptors in `OAUTH2_PROVIDERS_FILE` may also set
`device_authorization_url`. Microsoft uses
`https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode` and Google
uses `https://oauth2.googleapis.com/device/code`. Atlassian does not offer this
grant and therefore uses browser polling or pasted completion instead.

If authorization-server discovery has no device endpoint, `parrot login`
prints an error telling the operator to enable `Oauth2Provider`. If the static
client is missing or is not allowed to use device login, it reports that the
`parrot-cli` public client is not authorized. Both prerequisite failures exit
with status 2 and do not create a login file.

## Logging in

Log in to the AI-Parrot server, then inspect the resolved Navigator identity:

```bash
parrot login --server https://parrot.example.com
parrot whoami
```

The default client is `parrot-cli` and the default scopes are `openid profile
email`. Override them only when the deployment registered matching values:

```bash
parrot login --server https://parrot.example.com \
  --client-id parrot-cli --scopes "openid profile email" --no-browser
```

`--no-browser` prints the verification URL and user code without opening a
browser, which is useful over SSH. `parrot logout` revokes the login on a
best-effort basis and removes both the login file and local connection cache.

## Connecting a provider

A login is required before connection commands can run:

```bash
parrot connect jira
parrot connections
parrot disconnect jira
```

By default, `parrot connect PROVIDER` opens the provider consent URL and polls
until the browser callback completes. If polling expires or cannot observe the
callback, it prompts for the redirected URL. Use `--paste` to prompt
immediately, or `--no-browser` when working over SSH. Optional provider scopes
can be supplied with `--scopes`.

For a provider descriptor with an RFC 8628 endpoint, use the device flow:

```bash
parrot connect microsoft --device --no-browser
parrot connect google --device
```

Microsoft and Google support device authorization. Atlassian does not, so Jira
connections use browser polling or `--paste` rather than `--device`.

## Where credentials live

The default login is `~/.parrot/login.json`; `PARROT_LOGIN_FILE` can select a
different path. It is an owner-only `0600` file containing the CLI access and
refresh tokens, the Navigator identity, and a random `cache_key`. Never copy it
into a repository or pass its token values in MCP host configuration.

Provider access tokens are cached in the adjacent
`~/.parrot/connections.cache`. The cache is `0600` and AES-GCM encrypted using
the login's `cache_key`. It contains access tokens only: provider refresh
tokens remain on the server, where the Identity Vault is the durable owner.
The cache can be rebuilt by reconnecting or pulling tokens again.

## Local MCP toolkits

`parrot mcp-local NAME` resolves the login once, when the stdio server process
starts. It uses `~/.parrot/login.json` by default; select another file with
`--login-file PATH` or `PARROT_LOGIN_FILE`. Managed Claude Code and Codex host
entries pass `PARROT_LOGIN_FILE` through when it is set during toolkit
installation. Restart the MCP process after changing login identity.

When no usable login exists, startup and tools that do not require delegated
credentials retain their previous behavior. A tool that needs an unconnected
provider returns an MCP error result rather than writing guidance outside the
JSON-RPC stream. The result contains `isError`, a text item, and the complete
`AuthRequiredPayload` in `structuredContent`; see
[Credentials and identity](../mcp-local-toolkits.md#credentials-and-identity)
for an example.

## agentd

Run agentd as a per-user daemon. For a Unix-domain-socket peer, it reads only
that OS user's `~/.parrot/login.json` and accepts the file only when it is a
regular, non-symlink file owned by the peer uid with mode `0600`. A valid login
produces the Navigator principal with `identity_source="login_file"`.

The login file is writable by its owner, so agentd trusts nothing in it except
the bearer token. Login-file resolution is **off** until the operator sets
`AGENTD_LOGIN_FILE_SERVER_URL` to the Navigator server agentd should trust:

- the principal is always requested from that server, never from the
  `server_url` written in the file;
- a login file that names any other server is ignored;
- agentd reads the file read-only: it never refreshes an expired login, never
  rewrites the file and never creates a lock or temporary file in the peer's
  directory. An expired or rejected login falls back like any other failure; the
  user runs `parrot login` again.

An absent or unsafe file, an invalid or expired login, an untrusted server, or a
failed principal lookup falls back to the existing peer-credential or configured
service identity. Set `AGENTD_LOGIN_FILE_LOOKUP=0` to disable login-file
resolution even when a trusted server is configured. A shared daemon
running as a service user and reading other users' home directories is not a
supported deployment model.

## Migrating from `parrot jiratoolkit auth`

Use the generic connection commands for Jira:

```bash
parrot login --server https://parrot.example.com
parrot connect jira --paste
parrot connections
parrot disconnect jira
```

`parrot jiratoolkit auth` is a deprecated alias that currently delegates to
the generic Jira connection flow. Migrate scripts to `parrot connect jira`.
The former `oauth2_local` Jira authentication mode and its local refresh-token
store have been removed; do not configure them as a current authentication
path.
