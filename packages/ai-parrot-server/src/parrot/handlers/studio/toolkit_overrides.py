"""Per-user toolkit override endpoints (FEAT-593): /agents/{name}/toolkits/{slug}/me."""
from __future__ import annotations

import copy
from typing import Any

from navigator_auth.decorators import is_authenticated, user_session

from parrot.security.vault_utils import (
    delete_vault_credential,
    retrieve_vault_credential,
    store_vault_credential,
)
from parrot.tools.config_schema import secret_paths
from parrot.tools.spec import SECRET_MASK

from ..toolkit_persistence import ToolkitConfigService, UserToolkitOverride
from ._base import StudioBaseView
from .agents import _StudioAgentsMixin
from .models import StudioError
from .tooling_store import AgentToolingStore


def _pop_dotted(target: dict[str, Any], dotted: str) -> tuple[bool, Any]:
    """Remove a dotted dict value, returning whether it existed and its value."""
    current: Any = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        if isinstance(current, list):
            if not part.isdigit() or int(part) >= len(current):
                return False, None
            current = current[int(part)]
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return False, None
    final = parts[-1]
    if isinstance(current, list) and final.isdigit() and int(final) < len(current):
        return True, current.pop(int(final))
    if isinstance(current, dict) and final in current:
        return True, current.pop(final)
    return False, None


def _set_dotted(target: dict[str, Any], dotted: str, value: Any) -> None:
    """Set a dotted dict value, creating only the needed intermediate dictionaries."""
    current: Any = target
    parts = dotted.split(".")
    for index, part in enumerate(parts[:-1]):
        next_is_index = parts[index + 1].isdigit()
        if isinstance(current, list):
            if not part.isdigit():
                return
            position = int(part)
            if position >= len(current):
                return
            current = current[position]
            continue
        child = current.get(part)
        expected_type = list if next_is_index else dict
        if not isinstance(child, expected_type):
            child = expected_type()
            current[part] = child
        current = child
    final = parts[-1]
    if isinstance(current, list):
        if final.isdigit() and int(final) < len(current):
            current[int(final)] = value
        return
    current[final] = value


@is_authenticated()
@user_session()
class StudioUserToolkitOverrideHandler(_StudioAgentsMixin, StudioBaseView):
    """GET/PUT/DELETE the caller's override. No owner check; PBAC ``astudio:toolkits:override``."""

    def _error(self, message: str, *, status: int, code: str | None = None, details: dict | None = None):
        """Build a Studio API error response."""
        return self.json_response(StudioError(message=message, code=code, details=details).model_dump(), status=status)

    async def _spec(self, name: str, slug: str):
        """Load the persisted agent toolkit spec and its schema."""
        store = AgentToolingStore(self)
        state = await store.load(name)
        spec = next((item for item in state.tooling.toolkits if item.slug.lower() == slug.lower()), None)
        if spec is None:
            raise LookupError(slug)
        _, schema = store.schema_for(slug)
        return spec, schema

    async def get(self):
        """Return the caller's masked override and current overridable parameters."""
        if (denied := await self._pbac_gate("toolkits", "astudio:toolkits:override")) is not None:
            return denied
        name = self.request.match_info.get("name")
        slug = self.request.match_info.get("slug")
        if not name or not slug:
            return self._error("Agent name and toolkit slug are required.", status=400, code="missing_resource")
        try:
            spec, _ = await self._spec(name, slug)
        except LookupError:
            return self._error("Requested toolkit was not found.", status=404, code="not_found")
        user = await self._get_user()
        override = next(
            (item for item in await ToolkitConfigService().load(user.user_id, name) if item.slug.lower() == slug.lower()),
            None,
        )
        params = copy.deepcopy(override.params) if override is not None else {}
        if override is not None:
            for path in override.secret_refs:
                _set_dotted(params, path, SECRET_MASK)
        return self.json_response(
            {
                "slug": slug,
                "overridable": spec.user_overridable,
                "params": params,
                "configured": override is not None,
            }
        )

    async def put(self):
        """Save the caller's overridable parameters and vault their secret values."""
        if (denied := await self._pbac_gate("toolkits", "astudio:toolkits:override")) is not None:
            return denied
        name = self.request.match_info.get("name")
        slug = self.request.match_info.get("slug")
        if not name or not slug:
            return self._error("Agent name and toolkit slug are required.", status=400, code="missing_resource")
        try:
            payload = await self.request.json()
        except Exception:
            return self._error("Invalid JSON body.", status=400, code="invalid_json")
        params = (payload or {}).get("params", {})
        if not isinstance(params, dict):
            return self._error("params must be an object.", status=400, code="invalid_request")
        try:
            spec, schema = await self._spec(name, slug)
        except LookupError:
            return self._error("Requested toolkit was not found.", status=404, code="not_found")
        offending = sorted(set(params) - set(spec.user_overridable))
        if offending:
            return self._error(
                "One or more parameters are not user-overridable.",
                status=422,
                code="not_overridable",
                details={"params": offending},
            )
        user = await self._get_user()
        service = ToolkitConfigService()
        previous = next(
            (item for item in await service.load(user.user_id, name) if item.slug.lower() == slug.lower()),
            None,
        )
        clean = copy.deepcopy(params)
        refs = dict(previous.secret_refs) if previous is not None else {}
        secrets: dict[str, Any] = {}
        for path in secret_paths(schema, params):
            found, value = _pop_dotted(clean, path)
            if not found:
                continue
            if value == SECRET_MASK:
                continue
            secrets[path] = value
        vault_name = f"toolkit_{slug}_{name}_user"
        if secrets:
            try:
                try:
                    current = await retrieve_vault_credential(user.user_id, vault_name)
                except KeyError:
                    current = {}
                current.update(secrets)
                await store_vault_credential(user.user_id, vault_name, current)
            except RuntimeError:
                return self._error("Vault service unavailable.", status=503, code="vault_unavailable")
            refs.update({path: vault_name for path in secrets})
        await service.save(
            UserToolkitOverride(user_id=user.user_id, agent_id=name, slug=slug, params=clean, secret_refs=refs)
        )
        session = await self._resolve_session()
        session.pop(f"{name}_toolkit_overrides_rev", None)
        return self.json_response({"agent": name, "slug": slug, "persisted": True})

    async def delete(self):
        """Remove the caller's override and its user-scoped vault credential."""
        if (denied := await self._pbac_gate("toolkits", "astudio:toolkits:override")) is not None:
            return denied
        name = self.request.match_info.get("name")
        slug = self.request.match_info.get("slug")
        if not name or not slug:
            return self._error("Agent name and toolkit slug are required.", status=400, code="missing_resource")
        user = await self._get_user()
        try:
            await ToolkitConfigService().remove(user.user_id, name, slug)
            await delete_vault_credential(user.user_id, f"toolkit_{slug}_{name}_user")
        except RuntimeError:
            return self._error("Vault service unavailable.", status=503, code="vault_unavailable")
        session = await self._resolve_session()
        session.pop(f"{name}_toolkit_overrides_rev", None)
        return self.json_response({"agent": name, "slug": slug, "deleted": True})
