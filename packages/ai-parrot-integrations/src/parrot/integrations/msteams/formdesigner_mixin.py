"""Teams FormDesigner mixin for serving Adaptive Card forms."""

from __future__ import annotations

import copy
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, ClassVar, Literal

import aiohttp
from botbuilder.core import CardFactory, TurnContext
from botbuilder.schema import Activity, ActivityTypes

from .formdesigner_cards import (
    PICKER_ACTION_KEY,
    append_render_warnings,
    build_empty_forms_card,
    build_error_card,
    build_form_not_found_card,
    build_login_required_card,
    build_picker_card,
)
from .formdesigner_client import FormDescriptor, FormDesignerClient, FormDesignerError, parse_form_ref
from .formdesigner_identity import LocalFormAuthorizer, TeamsSessionStoreLike, TenantUnresolved, resolve_bearer, resolve_form_tenant
from .formdesigner_local import LocalFormReader
from .formdesigner_submit import RecentActivityCache
from .formdesigner_turn import FormDesignerTurn, active_turn, bind_turn
from .formdesigner_wizard import WizardState, WizardStore
from .tools.formdesigner import FormDesignerToolkit

__all__ = ["PICKER_ACTION_KEY", "TeamsFormDesignerMixin"]


class TeamsFormDesignerMixin:
    """Adds FormDesigner form serving to a Teams-exposed agent."""

    formdesigner_serving: ClassVar[bool] = True
    formdesigner_mode: Literal["remote", "local"] = "remote"

    def __init__(
        self,
        *args: Any,
        formdesigner_mode: Literal["remote", "local"] | None = None,
        formdesigner_base_url: str | None = None,
        formdesigner_api_base_path: str | None = None,
        formdesigner_public_url: str | None = None,
        formdesigner_signing_secret: str | None = None,
        formdesigner_tenant: str | None = None,
        formdesigner_registry: Any | None = None,
        formdesigner_authorizer: LocalFormAuthorizer | None = None,
        formdesigner_session_store: TeamsSessionStoreLike | None = None,
        formdesigner_client: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize FormDesigner collaborators before the agent builds tools."""
        self._fd_mode_explicit = formdesigner_mode is not None
        self.formdesigner_mode = formdesigner_mode or type(self).formdesigner_mode
        self._fd_base_url = formdesigner_base_url
        self._fd_api_base_path = formdesigner_api_base_path or "/api/v1"
        self._fd_api_base_path_explicit = formdesigner_api_base_path is not None
        self._fd_public_url = formdesigner_public_url
        self._fd_signing_secret = formdesigner_signing_secret
        self._fd_tenant = formdesigner_tenant
        self._fd_registry = formdesigner_registry
        self._fd_authorizer = formdesigner_authorizer
        self._fd_store: TeamsSessionStoreLike | None = formdesigner_session_store
        self._fd_client = formdesigner_client
        self._fd_tenant_map: dict[str, str] = {}
        self._fd_allowed_hosts: list[str] = []
        self._fd_render_timeout = 15.0
        self._fd_submit_timeout = 15.0
        self._fd_http: aiohttp.ClientSession | None = None
        self._fd_wizards = WizardStore()
        self._fd_recent = RecentActivityCache()
        self._fd_logger = logging.getLogger(__name__)
        super().__init__(*args, **kwargs)

    def apply_teams_config(self, config: Any) -> None:
        """Fill unset configuration from an ``MSTeamsAgentConfig`` instance."""
        if self._fd_base_url is None:
            self._fd_base_url = getattr(config, "formdesigner_base_url", None)
        if self._fd_tenant is None:
            self._fd_tenant = getattr(config, "formdesigner_tenant", None)
        if self._fd_public_url is None:
            self._fd_public_url = getattr(config, "formdesigner_public_url", None)
        if self._fd_signing_secret is None:
            self._fd_signing_secret = getattr(config, "formdesigner_submit_secret", None)
        if not self._fd_api_base_path_explicit:
            self._fd_api_base_path = getattr(config, "formdesigner_api_base_path", None) or "/api/v1"
        if not self._fd_mode_explicit:
            mode = getattr(config, "formdesigner_mode", None)
            if mode in ("remote", "local"):
                self.formdesigner_mode = mode
        self._fd_render_timeout = float(getattr(config, "formdesigner_render_timeout", self._fd_render_timeout))
        self._fd_submit_timeout = float(getattr(config, "formdesigner_submit_timeout", self._fd_submit_timeout))
        self._fd_allowed_hosts = [str(host).lower() for host in (getattr(config, "formdesigner_allowed_hosts", None) or [])]
        self._fd_tenant_map = dict(getattr(config, "formdesigner_tenant_map", None) or {})

    def bind_teams_identity(self, store: TeamsSessionStoreLike) -> None:
        """Receive the wrapper-owned Teams session store."""
        self._fd_store = store

    def teams_commands(self) -> dict[str, Callable[[TurnContext], Awaitable[None]]]:
        """Return commands that need the Bot Framework turn context."""
        return {"getform": self.handle_getform, "listforms": self.handle_listforms}

    def _fd_enabled(self) -> bool:
        if self.formdesigner_mode == "local":
            return self._fd_registry is not None
        return bool(self._fd_base_url) or self._fd_client is not None

    @staticmethod
    def _fd_asserted_tenant(activity: Activity) -> str | None:
        """Extract the asserted tenant GUID from dict or SDK channel data."""
        channel_data = getattr(activity, "channel_data", None)
        tenant = channel_data.get("tenant") if isinstance(channel_data, dict) else getattr(channel_data, "tenant", None)
        return tenant.get("id") if isinstance(tenant, dict) else getattr(tenant, "id", None)

    async def _fd_identity(self, turn_context: TurnContext) -> FormDesignerTurn:
        """Resolve read-only identity for one FormDesigner turn."""
        activity = turn_context.activity
        turn = FormDesignerTurn(conversation_id=activity.conversation.id)
        if getattr(activity.conversation, "conversation_type", None) in ("channel", "groupChat"):
            turn.error = "Forms are only available in 1:1 chats."
            return turn
        if self._fd_store is None:
            turn.login_required = True
            return turn
        session = await self._fd_store.get_or_create(turn_context)
        turn.bearer = resolve_bearer(session, expired=self._fd_store.is_expired(session))
        if not turn.bearer:
            turn.login_required = True
            return turn
        turn.user_id = getattr(session, "nav_user_id", None)
        try:
            resolution = resolve_form_tenant(
                asserted_tenant_id=self._fd_asserted_tenant(activity),
                session_tenant_id=getattr(session, "tenant_id", None),
                tenant_map=self._fd_tenant_map,
                config_tenant=self._fd_tenant,
            )
        except TenantUnresolved:
            turn.error = "No forms workspace is configured for your organization."
            return turn
        turn.tenant, turn.tenant_source = resolution.tenant, resolution.source
        self._fd_logger.info("formdesigner: tenant %s via %s", resolution.tenant, resolution.source)
        return turn

    def _fd_reader(self, turn: FormDesignerTurn | None) -> Any:
        """Return the remote client or a turn-specific local reader."""
        if self.formdesigner_mode == "local":
            return LocalFormReader(
                self._fd_registry,
                authorizer=self._fd_authorizer,
                user_id_resolver=lambda: turn.user_id if turn is not None else None,
                public_base_url=self._fd_public_url,
                signing_secret=self._fd_signing_secret,
                api_base_path=self._fd_api_base_path,
            )
        if self._fd_client is None:
            if not self._fd_base_url:
                raise FormDesignerError("FormDesigner is not configured", status=500)
            self._fd_client = FormDesignerClient(
                self._fd_base_url, api_base_path=self._fd_api_base_path, timeout=self._fd_render_timeout
            )
        return self._fd_client

    async def _fd_send_card(self, card: dict[str, Any], turn_context: TurnContext) -> None:
        """Send an Adaptive Card through the current Bot Framework turn."""
        attachment = CardFactory.adaptive_card(card)
        await turn_context.send_activity(Activity(type=ActivityTypes.message, attachments=[attachment]))

    async def _fd_send_turn_problem(self, turn: FormDesignerTurn, turn_context: TurnContext) -> bool:
        """Send a login or error card when the turn cannot serve forms."""
        if turn.login_required:
            await self._fd_send_card(build_login_required_card(), turn_context)
            return True
        if turn.error or not turn.tenant:
            await self._fd_send_card(build_error_card(turn.error or "Forms are unavailable."), turn_context)
            return True
        return False

    async def handle_getform(self, turn_context: TurnContext) -> None:
        """Serve ``/getform [slug-or-uid]``, or show the picker without an argument."""
        tokens = (getattr(turn_context.activity, "text", "") or "").split()
        try:
            index = next(index for index, token in enumerate(tokens) if token.lower() == "/getform")
        except StopIteration:
            await self.handle_listforms(turn_context)
            return
        if index + 1 >= len(tokens):
            await self.handle_listforms(turn_context)
            return
        await self.serve_form(turn_context, form_ref=tokens[index + 1])

    async def handle_listforms(self, turn_context: TurnContext) -> None:
        """Send a tenant-scoped form picker or an empty-state card."""
        turn = await self._fd_identity(turn_context)
        if await self._fd_send_turn_problem(turn, turn_context):
            return
        if not self._fd_enabled():
            await self._fd_send_card(build_error_card("Forms are not configured for this bot."), turn_context)
            return
        try:
            forms = await self._fd_reader(turn).list_forms(tenant=turn.tenant, bearer_token=turn.bearer)
            card = build_picker_card(forms, tenant=turn.tenant) if forms else build_empty_forms_card(tenant=turn.tenant)
            await self._fd_send_card(card, turn_context)
        except FormDesignerError as exc:
            self._fd_logger.warning("formdesigner: list_forms failed status=%s", exc.status)
            message = "You don't have access to these forms." if exc.status == 403 else "Forms are unavailable."
            await self._fd_send_card(build_error_card(message), turn_context)

    async def serve_form(
        self, turn_context: TurnContext, *, form_ref: str | uuid.UUID, turn: FormDesignerTurn | None = None
    ) -> None:
        """Resolve, render and send a form card without raising into Teams."""
        turn = turn or await self._fd_identity(turn_context)
        if await self._fd_send_turn_problem(turn, turn_context):
            return
        if not self._fd_enabled():
            await self._fd_send_card(build_error_card("Forms are not configured for this bot."), turn_context)
            return
        if self.formdesigner_mode == "local" and (not self._fd_signing_secret or not self._fd_public_url):
            await self._fd_send_card(build_error_card("Forms are not configured for this bot."), turn_context)
            return
        try:
            reader = self._fd_reader(turn)
            ref = parse_form_ref(form_ref)
            if isinstance(ref, uuid.UUID):
                form_uid = ref
            else:
                descriptor = await reader.get_form_by_slug(tenant=turn.tenant, slug=ref, bearer_token=turn.bearer)
                if descriptor is None:
                    await self._fd_send_card(build_form_not_found_card(str(form_ref)), turn_context)
                    return
                form_uid = descriptor.form_uid
            form = await reader.get_form(tenant=turn.tenant, form_uid=form_uid, bearer_token=turn.bearer)
            if len(form.sections) > 1:
                state = self._fd_wizards.start(
                    conversation_id=turn.conversation_id,
                    form_uid=form.form_uid,
                    tenant=turn.tenant,
                    total_sections=len(form.sections),
                    owner_user_id=turn.user_id or "",
                    form_version=form.published_version or form.version,
                )
                rendered = await reader.render_teams(
                    tenant=turn.tenant, form_uid=form.form_uid, bearer_token=turn.bearer, section_index=0
                )
                if rendered.metadata.get("total_sections") != len(form.sections):
                    raise FormDesignerError("section rendering mismatch", status=200)
                card = self._fd_decorate_wizard(rendered.content, state)
            else:
                rendered = await reader.render_teams(tenant=turn.tenant, form_uid=form.form_uid, bearer_token=turn.bearer)
                card = rendered.content
            await self._fd_send_card(append_render_warnings(card, rendered.warnings), turn_context)
        except FormDesignerError as exc:
            self._fd_logger.warning("formdesigner: serve_form failed status=%s", exc.status)
            if exc.status == 404:
                card = build_form_not_found_card(str(form_ref))
            elif exc.status == 403:
                card = build_error_card("You don't have access to this form.")
            elif exc.status == 500 and self.formdesigner_mode == "local":
                card = build_error_card("Forms are not configured for this bot.")
            else:
                card = build_error_card("Forms are unavailable.")
            await self._fd_send_card(card, turn_context)

    def _fd_decorate_wizard(self, card: dict[str, Any], state: WizardState) -> dict[str, Any]:
        """Add wizard controls to every terminal/navigation ``Action.Submit``."""
        decorated = copy.deepcopy(card)
        for action in decorated.get("actions", []):
            data = action.get("data") if action.get("type") == "Action.Submit" else None
            if isinstance(data, dict) and data.get("_action") in ("next", "cancel", "submit"):
                data[PICKER_ACTION_KEY] = {
                    "kind": "wizard",
                    "action": data["_action"],
                    "form_uid": str(state.form_uid),
                    "wizard_id": str(state.wizard_id),
                    "section_index": state.section_index,
                }
        return decorated

    def agent_tools(self) -> list[Any]:
        """Return parent tools plus FormDesigner request-local tools."""
        toolkit = FormDesignerToolkit(
            _TurnReaderProxy(self),
            tenant_resolver=lambda: (turn.tenant if (turn := active_turn()) else None),
            bearer_resolver=lambda: (turn.bearer if (turn := active_turn()) else None),
            enqueue_card=lambda uid: (turn.enqueue(uid) if (turn := active_turn()) else False),
        )
        return [*super().agent_tools(), *toolkit.get_tools()]

    @asynccontextmanager
    async def formdesigner_turn(self, turn_context: TurnContext) -> AsyncIterator[None]:
        """Bind a fresh request-local identity and pending-card queue."""
        turn = await self._fd_identity(turn_context)
        async with bind_turn(turn):
            yield None

    async def flush_formdesigner_cards(self, turn_context: TurnContext) -> None:
        """Drain distinct queued UIDs through fresh identity checks."""
        turn = active_turn()
        if turn is None:
            return
        for form_uid in turn.drain():
            await self.serve_form(turn_context, form_ref=form_uid)

    async def _fd_get_http(self) -> aiohttp.ClientSession:
        """Lazily create the submission HTTP session."""
        if self._fd_http is None or self._fd_http.closed:
            self._fd_http = aiohttp.ClientSession()
        return self._fd_http

    async def aclose(self) -> None:
        """Close FormDesigner client and submission session resources."""
        client = self._fd_client
        if client is not None and callable(getattr(client, "close", None)):
            await client.close()
        self._fd_client = None
        if self._fd_http is not None and not self._fd_http.closed:
            await self._fd_http.close()
        self._fd_http = None


class _TurnReaderProxy:
    """Resolve the form reader from the request-local active turn."""

    def __init__(self, owner: TeamsFormDesignerMixin) -> None:
        self._owner = owner

    def _reader(self) -> Any:
        turn = active_turn()
        if turn is None:
            raise FormDesignerError("no active turn", status=403)
        return self._owner._fd_reader(turn)

    async def list_forms(self, **kwargs: Any) -> list[FormDescriptor]:
        """Delegate list calls to the turn-specific reader."""
        return await self._reader().list_forms(**kwargs)

    async def get_form(self, **kwargs: Any) -> Any:
        """Delegate schema reads to the turn-specific reader."""
        return await self._reader().get_form(**kwargs)

    async def get_form_by_slug(self, **kwargs: Any) -> FormDescriptor | None:
        """Delegate slug resolution to the turn-specific reader."""
        return await self._reader().get_form_by_slug(**kwargs)
