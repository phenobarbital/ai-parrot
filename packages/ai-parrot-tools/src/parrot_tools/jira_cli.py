"""Jira toolkit CLI — local 3LO auth, status, logout and KB sync (FEAT-696 M5)."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
import re
import secrets
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp
import click

from parrot.auth.jira_oauth import (
    DEFAULT_SCOPES,
    JiraTokenSet,
    build_authorization_url,
    exchange_code,
    fetch_accessible_resources,
    fetch_myself,
)
from parrot_tools.jira_kb import IssueTypeEntry, JiraKnowledgeBase, PrioritiesEntry, ProjectEntry
from parrot_tools.jira_local_auth import FileTokenCredentialResolver, LocalJiraTokenStore

logger = logging.getLogger(__name__)

DEFAULT_KB_FILENAME = "jira_kb.yaml"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60)
_ENV_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_./:@+,=-]+$")
_ENV_LINE = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_pasted_redirect(text: str) -> Tuple[str, Optional[str]]:
    """Extract (code, state|None) from a pasted redirect URL or bare code.

    Args:
        text: The pasted redirect URL, or a bare authorization code.

    Returns:
        A tuple of the authorization code and the ``state`` parameter (None for a bare code
        or a URL without ``state``).

    Raises:
        click.ClickException: If the redirect carries ``error=`` or no ``code``.
    """
    text = text.strip()
    if text.startswith("http"):
        parsed = urlparse(text)
        qs = parse_qs(parsed.query)
        if "error" in qs:
            raise click.ClickException(f"Authorization denied: {qs['error'][0]}")
        code = qs.get("code", [None])[0]
        if not code:
            raise click.ClickException("No 'code' parameter in the pasted URL.")
        state = qs.get("state", [None])[0]
        return code, state
    return text, None


def _format_env_value(value: str) -> str:
    """Render a value for a dotenv line, quoting it when it is not a plain token."""
    if value and _ENV_SAFE_VALUE.match(value):
        return value
    if "'" not in value and "\n" not in value and "\r" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _atomic_write_text(path: Path, content: str) -> None:
    """Write text via a temp file and ``os.replace``; keeps an existing file's mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def upsert_env(path: Path, values: Mapping[str, str]) -> None:
    """Replace-or-append env vars in a .env file, atomically.

    Existing assignments of the given keys are replaced in place (keeping any ``export``
    prefix); missing keys are appended. Unrelated lines, comments and ordering are kept.

    Args:
        path: The .env file to update; created if missing.
        values: Mapping of variable name to value.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []
    written: set[str] = set()
    out: list[str] = []
    for line in lines:
        match = _ENV_LINE.match(line)
        key = match.group(2) if match else None
        if key is not None and key in values:
            if key in written:
                continue  # drop duplicate assignments of a key we own
            out.append(f"{match.group(1)}{key}={_format_env_value(values[key])}\n")
            written.add(key)
        else:
            out.append(line)
    for key, value in values.items():
        if key in written:
            continue
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.append(f"{key}={_format_env_value(value)}\n")
        written.add(key)
    _atomic_write_text(path, "".join(out))


def _prompt_value(value: Optional[str], env_name: str, prompt_text: str, hide: bool = False) -> str:
    """Return a flag value, else the environment variable, else an interactive prompt."""
    if value:
        return value
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    return click.prompt(prompt_text, hide_input=hide)


def _new_state() -> str:
    """Return a fresh CSRF ``state`` nonce for one login attempt."""
    return secrets.token_urlsafe(24)


def _looks_like_url(text: str) -> bool:
    return text.strip().startswith("http")


def _same_site(a: str, b: str) -> bool:
    return a.rstrip("/").lower() == b.rstrip("/").lower()


def _choose_site(resources: list[dict[str, Any]], site: Optional[str]) -> dict[str, Any]:
    """Pick the accessible site: ``--site`` decides, otherwise the user chooses when several exist."""
    if not resources:
        raise click.ClickException("The token grants access to no Jira sites.")
    if site:
        matches = [r for r in resources if _same_site(str(r.get("url", "")), site)]
        if not matches:
            known = ", ".join(str(r.get("url", "")) for r in resources)
            raise click.ClickException(f"--site {site} is not accessible with this grant. Available: {known}")
        return matches[0]
    if len(resources) == 1:
        return resources[0]
    click.echo("Multiple Jira sites are accessible:")
    for index, resource in enumerate(resources, start=1):
        click.echo(f"  {index}. {resource.get('url', '')} ({resource.get('name', '')})")
    choice = click.prompt("Select a site", type=click.IntRange(1, len(resources)))
    return resources[choice - 1]


def _expiry_text(epoch: float) -> str:
    stamp = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"{stamp} ({'expired' if time.time() >= epoch else 'valid'})"


def _session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)


async def _exchange_and_list(
    client_id: str, client_secret: str, code: str, redirect_uri: str
) -> Tuple[dict[str, Any], list[dict[str, Any]]]:
    """Exchange the authorization code and list the accessible Atlassian sites."""
    async with _session() as session:
        token_data = await exchange_code(
            session, client_id=client_id, client_secret=client_secret, code=code, redirect_uri=redirect_uri
        )
        resources = await fetch_accessible_resources(session, token_data["access_token"])
    return token_data, resources


async def _myself(access_token: str, cloud_id: str) -> dict[str, Any]:
    """Call ``/myself`` on the chosen site."""
    async with _session() as session:
        return await fetch_myself(session, access_token, cloud_id)


async def _jira_get(session: aiohttp.ClientSession, token: JiraTokenSet, path: str) -> Any:
    """GET a Jira REST path with the bearer token; never echoes the token."""
    headers = {"Authorization": f"Bearer {token.access_token}", "Accept": "application/json"}
    async with session.get(f"{token.api_base_url}{path}", headers=headers) as response:
        if response.status != 200:
            raise click.ClickException(f"Jira GET {path} failed with HTTP {response.status}.")
        return await response.json()


async def _fetch_structure(token: JiraTokenSet, project_keys: Optional[list[str]]) -> dict[str, Any]:
    """Query live Jira for the structural sections of the KB."""
    async with _session() as session:
        if project_keys is None:
            projects = await _jira_get(session, token, "/rest/api/3/project")
            project_keys = [str(p["key"]) for p in projects]
        project_entries: dict[str, ProjectEntry] = {}
        components: set[str] = set()
        for key in project_keys:
            detail = await _jira_get(session, token, f"/rest/api/3/project/{key}")
            issue_types = {
                str(it["name"]): IssueTypeEntry(
                    id=str(it["id"]),
                    subtask=bool(it.get("subtask", False)),
                    level=int(it.get("hierarchyLevel") or 0),
                )
                for it in detail.get("issueTypes", [])
            }
            project_entries[key] = ProjectEntry(name=str(detail.get("name", key)), issue_types=issue_types)
            for component in await _jira_get(session, token, f"/rest/api/3/project/{key}/components"):
                components.add(str(component["name"]))
        priorities = await _jira_get(session, token, "/rest/api/3/priority")
        fields = await _jira_get(session, token, "/rest/api/3/field")
    return {
        "projects": project_entries,
        "components": sorted(components),
        "priority_scale": [str(p["name"]) for p in priorities],
        "live_field_ids": {str(f["id"]) for f in fields},
    }


def _load_fresh_token(site: Optional[str] = None) -> JiraTokenSet:
    """Return the stored token, refreshing it through the local resolver when expired."""
    store = LocalJiraTokenStore()
    try:
        token = store.get(site)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if token is None:
        raise click.ClickException("No stored Jira credentials. Run `parrot jiratoolkit auth` first.")
    if not token.is_expired:
        return token
    resolver = FileTokenCredentialResolver.from_env()
    try:
        refreshed = asyncio.run(resolver.resolve("cli", "local"))
    except ValueError as exc:
        raise click.ClickException(f"Token refresh failed; run `parrot jiratoolkit auth` again. ({exc})") from exc
    if refreshed is None:
        raise click.ClickException("No stored Jira credentials. Run `parrot jiratoolkit auth` first.")
    return refreshed


@click.group(name="jiratoolkit")
def cli() -> None:
    """Jira toolkit utilities."""


# The lazy loader resolves the command by attribute name ("jiratoolkit").
jiratoolkit = cli


@cli.command()
@click.option("--site", default=None, help="Jira site URL")
@click.option("--scopes", default=None, help="Comma-separated scopes")
@click.option("--env-file", default=".env", type=click.Path(), help="Path to .env file")
@click.option("--client-id", default=None, help="OAuth client ID")
@click.option("--client-secret", default=None, help="OAuth client secret")
@click.option("--redirect-uri", default=None, help="OAuth redirect URI")
@click.option(
    "--allow-bare-code",
    is_flag=True,
    default=False,
    help="Accept a bare authorization code (no CSRF state check). Default: require the full redirected URL.",
)
def auth(site, scopes, env_file, client_id, client_secret, redirect_uri, allow_bare_code) -> None:
    """Authenticate with Jira using OAuth 2.0 (3LO) — manual paste flow."""
    if client_secret:
        click.secho(
            "Warning: --client-secret exposes the secret in your shell history and process list; "
            "prefer JIRA_CLIENT_SECRET or the hidden prompt.",
            fg="yellow",
            err=True,
        )
    client_id = _prompt_value(client_id, "JIRA_CLIENT_ID", "Jira OAuth client ID")
    client_secret = _prompt_value(client_secret, "JIRA_CLIENT_SECRET", "Jira OAuth client secret", hide=True)
    redirect_uri = _prompt_value(redirect_uri, "JIRA_REDIRECT_URI", "Redirect URI registered on the Jira app")
    scope_list = [s.strip() for s in scopes.split(",") if s.strip()] if scopes else list(DEFAULT_SCOPES)

    state = _new_state()
    authorize_url = build_authorization_url(client_id, redirect_uri, state, scope_list)
    click.echo("Open this URL in your browser, authorize access, then paste the redirected URL here:\n")
    click.echo(authorize_url + "\n")
    pasted = click.prompt("Redirected URL or code")

    code, returned_state = parse_pasted_redirect(pasted)
    if _looks_like_url(pasted):
        if returned_state is None or not hmac.compare_digest(returned_state, state):
            raise click.ClickException("State mismatch: the pasted URL is not from this login. Aborting.")
    elif not allow_bare_code:
        raise click.ClickException(
            "Paste the full redirected URL so the login state can be verified "
            "(or pass --allow-bare-code to skip the CSRF check)."
        )
    else:
        click.secho("Warning: bare code accepted without a state check.", fg="yellow", err=True)

    token_data, resources = asyncio.run(_exchange_and_list(client_id, client_secret, code, redirect_uri))
    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        raise click.ClickException("The token response carried no refresh token; check the offline_access scope.")
    chosen = _choose_site(resources, site)
    myself = asyncio.run(_myself(token_data["access_token"], str(chosen["id"])))

    now = time.time()
    granted_scopes = str(token_data.get("scope", "")).split() or scope_list
    token = JiraTokenSet(
        access_token=token_data["access_token"],
        refresh_token=refresh_token,
        expires_at=now + float(token_data.get("expires_in", 3600)),
        cloud_id=str(chosen["id"]),
        site_url=str(chosen["url"]),
        account_id=str(myself.get("accountId", "")),
        display_name=str(myself.get("displayName", "")),
        email=myself.get("emailAddress"),
        scopes=granted_scopes,
        granted_at=now,
        last_refreshed_at=now,
        available_sites=resources,
    )
    LocalJiraTokenStore().save(token)
    upsert_env(
        Path(env_file),
        {
            "JIRA_CLIENT_ID": client_id,
            "JIRA_CLIENT_SECRET": client_secret,
            "JIRA_REDIRECT_URI": redirect_uri,
            "JIRA_AUTH_TYPE": "oauth2_local",
        },
    )
    click.echo(f"Site:    {token.site_url}")
    click.echo(f"Account: {token.display_name} ({token.account_id})")
    click.echo(f"Expires: {_expiry_text(token.expires_at)}")
    click.echo(f"Credentials saved; client settings written to {env_file}.")


@cli.command()
@click.option("--site", default=None, help="Jira site URL")
def status(site) -> None:
    """Show current Jira authentication status."""
    try:
        token = LocalJiraTokenStore().get(site)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    if token is None:
        raise click.ClickException("Not authenticated. Run `parrot jiratoolkit auth`.")
    click.echo(f"Site:     {token.site_url}")
    click.echo(f"Cloud ID: {token.cloud_id}")
    click.echo(f"Account:  {token.display_name} ({token.account_id})")
    if token.email:
        click.echo(f"Email:    {token.email}")
    click.echo(f"Scopes:   {' '.join(token.scopes)}")
    click.echo(f"Expires:  {_expiry_text(token.expires_at)}")

    async def _probe() -> dict[str, Any]:
        return await _myself(token.access_token, token.cloud_id)

    try:
        asyncio.run(_probe())
        click.echo("Probe /myself: ok")
    except ValueError as exc:
        click.echo(f"Probe /myself: failed ({exc})")


@cli.command()
@click.option("--site", default=None, help="Jira site URL to remove")
def logout(site) -> None:
    """Remove stored Jira credentials for a site."""
    if LocalJiraTokenStore().delete(site):
        click.echo("Stored Jira credentials removed. The .env file was not modified.")
    else:
        click.echo("No stored Jira credentials matched; nothing removed.")


@cli.command(name="sync-kb")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output YAML path")
@click.option("--projects", default=None, help="Comma-separated project keys")
def sync_kb(output, projects) -> None:
    """Generate or update a Jira knowledge base YAML file."""
    out_path = Path(output or os.environ.get("JIRA_KB_PATH") or DEFAULT_KB_FILENAME)
    project_keys = [p.strip() for p in projects.split(",") if p.strip()] if projects else None
    token = _load_fresh_token()

    existing: Optional[JiraKnowledgeBase] = None
    if out_path.exists():
        try:
            existing = JiraKnowledgeBase.load(out_path)
        except (ValueError, OSError) as exc:
            raise click.ClickException(f"Existing KB {out_path} is unreadable; fix or remove it. ({exc})") from exc

    live = asyncio.run(_fetch_structure(token, project_keys))
    # Hand-edited field aliases are kept only while their ids still exist in Jira.
    kept_fields = {}
    if existing is not None:
        kept_fields = {alias: fid for alias, fid in existing.fields.items() if fid in live["live_field_ids"]}
    generated = JiraKnowledgeBase(
        site=token.site_url,
        cloud_id=token.cloud_id,
        verified=datetime.now(tz=timezone.utc).date().isoformat(),
        projects=live["projects"],
        priorities=PrioritiesEntry(scale=live["priority_scale"]),
        fields=kept_fields,
        components=live["components"],
    )
    merged = existing.merge_generated(generated) if existing is not None else generated
    merged.save(out_path)
    issue_type_count = sum(len(p.issue_types) for p in merged.projects.values())
    click.echo(
        f"KB written to {out_path}: {len(merged.projects)} project(s), {issue_type_count} issue type(s), "
        f"{len(merged.components)} component(s)."
    )
