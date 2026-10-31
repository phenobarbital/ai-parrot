"""Deprecated Jira commands backed by the generic connection flow."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import aiohttp
import click

from parrot.auth.jira_oauth import JiraTokenSet, fetch_accessible_resources
from parrot.auth.oauth2.local_cache import RemoteConnectionResolver, open_connection_cache
from parrot.auth.oauth2.paste import parse_pasted_redirect  # noqa: F401
from parrot.auth.oauth2.remote_client import NotLoggedIn, ServerConnectionsClient
from parrot.cli.login import LoginStore
from parrot_tools.jira_kb import IssueTypeEntry, JiraKnowledgeBase, PrioritiesEntry, ProjectEntry

DEFAULT_KB_FILENAME = "jira_kb.yaml"
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=60)


def _scope_list(scopes: Optional[str]) -> Optional[list[str]]:
    """Parse the legacy comma-separated scopes option."""
    return [scope.strip() for scope in scopes.split(",") if scope.strip()] if scopes else None


def _require_login(store: LoginStore) -> Any:
    """Return the current login record or exit with the standard hint."""
    record = store.load_optional()
    if record is None:
        click.echo("Not logged in — run `parrot login`", err=True)
        sys.exit(2)
    return record


def _choose_site(resources: list[dict[str, Any]], site: Optional[str]) -> dict[str, Any]:
    """Choose the requested Jira site or the first accessible site."""
    if not resources:
        raise click.ClickException("The token grants access to no Jira sites.")
    if site:
        for resource in resources:
            if str(resource.get("url", "")).rstrip("/").lower() == site.rstrip("/").lower():
                return resource
        known = ", ".join(str(resource.get("url", "")) for resource in resources)
        raise click.ClickException(f"--site {site} is not accessible with this grant. Available: {known}")
    return resources[0]


def _session() -> aiohttp.ClientSession:
    """Create the short-lived session used to discover Jira resources."""
    return aiohttp.ClientSession(timeout=_HTTP_TIMEOUT)


async def _jira_get(session: aiohttp.ClientSession, token: JiraTokenSet, path: str) -> Any:
    """GET a Jira REST path with the broker-resolved bearer token."""
    headers = {"Authorization": f"Bearer {token.access_token}", "Accept": "application/json"}
    async with session.get(f"{token.api_base_url}{path}", headers=headers) as response:
        if response.status != 200:
            raise click.ClickException(f"Jira GET {path} failed with HTTP {response.status}.")
        return await response.json()


async def _fetch_structure(token: JiraTokenSet, project_keys: Optional[list[str]]) -> dict[str, Any]:
    """Query live Jira for the structural sections of the knowledge base."""
    async with _session() as session:
        if project_keys is None:
            project_keys = [str(project["key"]) for project in await _jira_get(session, token, "/rest/api/3/project")]
        projects: dict[str, ProjectEntry] = {}
        components: set[str] = set()
        for key in project_keys:
            detail = await _jira_get(session, token, f"/rest/api/3/project/{key}")
            projects[key] = ProjectEntry(
                name=str(detail.get("name", key)),
                issue_types={
                    str(issue_type["name"]): IssueTypeEntry(
                        id=str(issue_type["id"]),
                        subtask=bool(issue_type.get("subtask", False)),
                        level=int(issue_type.get("hierarchyLevel") or 0),
                    )
                    for issue_type in detail.get("issueTypes", [])
                },
            )
            components.update(
                str(component["name"])
                for component in await _jira_get(session, token, f"/rest/api/3/project/{key}/components")
            )
        priorities = await _jira_get(session, token, "/rest/api/3/priority")
        fields = await _jira_get(session, token, "/rest/api/3/field")
    return {
        "projects": projects,
        "components": sorted(components),
        "priority_scale": [str(priority["name"]) for priority in priorities],
        "live_field_ids": {str(field["id"]) for field in fields},
    }


def _load_fresh_token(site: Optional[str] = None) -> JiraTokenSet:
    """Resolve a cached or remote Jira access token without a local refresh token."""
    store = LoginStore()
    login = _require_login(store)

    async def _resolve() -> JiraTokenSet:
        async with ServerConnectionsClient(store) as client:
            cache = open_connection_cache(store)
            access_token = await RemoteConnectionResolver("jira", cache=cache, client=client).resolve("cli", login.user_id)
            if access_token is None:
                raise click.ClickException("Jira is not connected — run `parrot connect jira`")
            async with _session() as session:
                resources = await fetch_accessible_resources(session, access_token)
        chosen = _choose_site(resources, site)
        cloud_id = str(chosen.get("id", ""))
        site_url = str(chosen.get("url", ""))
        if not cloud_id or not site_url:
            raise click.ClickException("Accessible Jira resource is missing id or URL.")
        return JiraTokenSet(access_token=access_token, cloud_id=cloud_id, site_url=site_url, available_sites=resources)

    try:
        return asyncio.run(_resolve())
    except NotLoggedIn:
        raise click.ClickException("Not logged in — run `parrot login`") from None


@click.group(name="jiratoolkit")
def cli() -> None:
    """Jira toolkit utilities."""


jiratoolkit = cli


@cli.command()
@click.option("--site", default=None, help="Ignored legacy option")
@click.option("--scopes", default=None, help="Comma-separated scopes")
@click.option("--env-file", default=".env", type=click.Path(), help="Ignored legacy option")
@click.option("--client-id", default=None, help="Ignored legacy option")
@click.option("--client-secret", default=None, help="Ignored legacy option")
@click.option("--redirect-uri", default=None, help="Ignored legacy option")
@click.option("--allow-bare-code", is_flag=True, default=False, help="Ignored legacy option")
def auth(site, scopes, env_file, client_id, client_secret, redirect_uri, allow_bare_code) -> None:
    """Deprecated alias of `parrot connect jira` (FEAT-774)."""
    del site, env_file, client_id, client_secret, redirect_uri, allow_bare_code
    click.echo("`parrot jiratoolkit auth` is deprecated — use `parrot connect jira`.", err=True)
    store = LoginStore()
    _require_login(store)
    from parrot.cli.connect import ConnectFailed, run_connect

    async def _connect() -> dict[str, Any]:
        async with ServerConnectionsClient(store) as client:
            return await run_connect(
                client, open_connection_cache(store), "jira", scopes=_scope_list(scopes), open_browser=True, paste=True,
                device=False, prompt=lambda text: click.prompt(text, err=True), echo=lambda text: click.echo(text, err=True),
            )

    try:
        asyncio.run(_connect())
    except NotLoggedIn:
        click.echo("Not logged in — run `parrot login`", err=True)
        sys.exit(2)
    except ConnectFailed as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)


@cli.command()
@click.option("--site", default=None, help="Ignored legacy option")
def status(site: Optional[str]) -> None:
    """Show the current Jira connection status."""
    del site
    store = LoginStore()
    _require_login(store)

    async def _status() -> list[dict[str, Any]]:
        async with ServerConnectionsClient(store) as client:
            return [row for row in await client.list() if row.get("provider") == "jira"]

    rows = asyncio.run(_status())
    if not rows:
        click.echo("Jira is not connected — run `parrot connect jira`", err=True)
        return
    row = rows[0]
    click.echo("Provider\tStatus\tAccount\tScopes\tExpires")
    click.echo("\t".join(["jira", str(row.get("status") or "-"), str(row.get("account_id") or "-"),
                            ", ".join(row.get("scopes_granted") or []) or "-", str(row.get("expires_at") or "-")]))


@cli.command()
@click.option("--site", default=None, help="Ignored legacy option")
def logout(site: Optional[str]) -> None:
    """Disconnect Jira and remove its cached access token."""
    del site
    store = LoginStore()
    _require_login(store)

    async def _logout() -> None:
        async with ServerConnectionsClient(store) as client:
            await client.disconnect("jira")
        await open_connection_cache(store).delete("jira")

    asyncio.run(_logout())
    click.echo("Disconnected jira", err=True)


@cli.command(name="sync-kb")
@click.option("--output", "-o", default=None, type=click.Path(), help="Output YAML path")
@click.option("--projects", default=None, help="Comma-separated project keys")
def sync_kb(output: Optional[str], projects: Optional[str]) -> None:
    """Generate or update a Jira knowledge base YAML file."""
    out_path = Path(output or os.environ.get("JIRA_KB_PATH") or DEFAULT_KB_FILENAME)
    project_keys = [project.strip() for project in projects.split(",") if project.strip()] if projects else None
    token = _load_fresh_token()
    existing: Optional[JiraKnowledgeBase] = None
    if out_path.exists():
        try:
            existing = JiraKnowledgeBase.load(out_path)
        except (ValueError, OSError) as exc:
            raise click.ClickException(f"Existing KB {out_path} is unreadable; fix or remove it. ({exc})") from exc
    live = asyncio.run(_fetch_structure(token, project_keys))
    generated = JiraKnowledgeBase(
        site=token.site_url, cloud_id=token.cloud_id, verified=datetime.now(tz=timezone.utc).date().isoformat(),
        projects=live["projects"], priorities=PrioritiesEntry(scale=live["priority_scale"]),
        fields={} if existing is None else {key: value for key, value in existing.fields.items() if value in live["live_field_ids"]},
        components=live["components"],
    )
    if existing is not None:
        generated.status_map = existing.status_map
        generated.limits = existing.limits
        generated.priorities.legacy = existing.priorities.legacy
        generated.priorities.default = existing.priorities.default
    generated.save(out_path)
    click.echo(f"Wrote Jira knowledge base to {out_path}")
