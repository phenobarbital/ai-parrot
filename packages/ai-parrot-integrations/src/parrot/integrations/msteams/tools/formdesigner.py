"""FormDesigner toolkit (FEAT-734 M6): list and resolve forms; the channel sends the card."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable, Iterable

from parrot.tools.toolkit import AbstractToolkit

from ..formdesigner_client import FormDesignerError, FormReader, parse_form_ref


def _localized(value: Any) -> str | None:
    """Collapse a LocalizedString (str or {lang: text}) into plain text."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("en", "default"):
            if isinstance(value.get(key), str):
                return value[key]
        for item in value.values():
            if isinstance(item, str):
                return item
        return None
    return str(value)


def _count_leaf_fields(items: Iterable[Any]) -> int:
    """Count leaf fields, recursing through subsections (items with ``fields``)."""
    total = 0
    for item in items or ():
        nested = getattr(item, "fields", None)
        if isinstance(nested, list):
            total += _count_leaf_fields(nested)
        else:
            total += 1
    return total


class FormDesignerToolkit(AbstractToolkit):
    """Lists and resolves FormDesigner forms for the current tenant."""

    def __init__(
        self,
        client: FormReader,
        *,
        tenant_resolver: Callable[[], str | None],
        bearer_resolver: Callable[[], str | None],
        enqueue_card: Callable[[uuid.UUID], bool | None],
        **kwargs: Any,
    ) -> None:
        """Resolvers and enqueue read M4's request-local turn context; no context -> fail closed."""
        super().__init__(**kwargs)
        self._reader = client
        self._tenant_resolver = tenant_resolver
        self._bearer_resolver = bearer_resolver
        self._enqueue_card = enqueue_card
        self._fd_logger = logging.getLogger(__name__)

    def _context(self) -> tuple[str, str] | dict[str, Any]:
        bearer = self._bearer_resolver()
        if not bearer:
            return {"status": "unavailable", "reason": "login_required"}
        tenant = self._tenant_resolver()
        if not tenant:
            return {"status": "unavailable", "reason": "tenant_unresolved"}
        return tenant, bearer

    async def formdesigner_list_forms(self) -> dict[str, Any]:
        """List the forms available in the caller's tenant.

        Returns {"tenant": str, "forms": [{"form_uid", "form_id", "title",
        "description"}]}. Use it to find a form before asking for it by slug.
        """
        ctx = self._context()
        if isinstance(ctx, dict):
            return ctx
        tenant, bearer = ctx
        try:
            rows = await self._reader.list_forms(tenant=tenant, bearer_token=bearer)
        except FormDesignerError as exc:
            self._fd_logger.warning("formdesigner list_forms failed (status=%s)", exc.status)
            return {"status": "error", "reason": "forms_unavailable"}
        return {
            "tenant": tenant,
            "forms": [
                {
                    "form_uid": str(row.form_uid),
                    "form_id": row.form_id,
                    "title": row.title,
                    "description": row.description,
                }
                for row in rows
            ],
        }

    async def formdesigner_get_form(self, form: str) -> dict[str, Any]:
        """Resolve ONE form by slug or form_uid and queue its card for sending.

        `form` is a slug (e.g. "store-visit") or a form_uid. Returns
        {"form_uid", "form_id", "title", "sections", "field_count",
        "card_pending": true}; the Adaptive Card is sent by the channel, so do
        not describe the form's fields back to the user.
        """
        ctx = self._context()
        if isinstance(ctx, dict):
            return ctx
        tenant, bearer = ctx
        ref = parse_form_ref(form)
        try:
            descriptor = None
            if isinstance(ref, uuid.UUID):
                uid = ref
            else:
                descriptor = await self._reader.get_form_by_slug(tenant=tenant, slug=ref, bearer_token=bearer)
                if descriptor is None:
                    return {"status": "not_found", "form": form}
                uid = descriptor.form_uid
            schema = await self._reader.get_form(tenant=tenant, form_uid=uid, bearer_token=bearer)
        except FormDesignerError as exc:
            if exc.status == 404:
                return {"status": "not_found", "form": form}
            self._fd_logger.warning("formdesigner get_form failed (status=%s)", exc.status)
            return {"status": "error", "reason": "form_unavailable"}

        sections = list(getattr(schema, "sections", None) or [])
        field_count = sum(_count_leaf_fields(getattr(sec, "fields", None) or []) for sec in sections)
        title = descriptor.title if descriptor is not None else _localized(getattr(schema, "title", None))
        form_id = descriptor.form_id if descriptor is not None else getattr(schema, "form_id", None)

        if self._enqueue_card(uid) is False:
            return {"status": "unavailable", "reason": "turn_closed"}
        return {
            "form_uid": str(uid),
            "form_id": form_id,
            "title": title,
            "sections": len(sections),
            "field_count": field_count,
            "card_pending": True,
        }
