"""Database model for stored Jinja2 notification templates.

Templates are persisted in ``navigator.notification_templates`` so a
non-developer can author, version, and edit a Jinja2 template body without
touching files under ``TEMPLATE_DIR``. Templates are **global** (no
``user_id``) — see spec ``commcenter-notify.spec.md`` §8, resolved in
brainstorm.
"""
# ruff: noqa: UP045 -- `datamodel`/`asyncdb.models.Model` field validation does
# not understand PEP 604 `X | None` unions (raises `TypeError: Expected type,
# got types.UnionType` at construction time); `typing.Optional[X]` is required
# here, verified live against this repo's installed `datamodel` package.
import uuid
from datetime import datetime
from typing import Optional

from asyncdb.models import Model
from datamodel import Field
from parrot.conf import PARROT_SCHEMA


class NotificationTemplate(Model):
    """A stored Jinja2 template used by the CommCenter bulk sender.

    ``template_string`` is rendered once per batch (partial render — see
    ``CommCenterService.partial_render``) and again per-recipient by
    ``NotifyWorker``. ``provider`` is only a *default*: it can be
    overridden per request or per recipient row.
    """

    template_id: uuid.UUID = Field(
        primary_key=True,
        required=False,
        default_factory=uuid.uuid4,
    )
    name: str = Field(required=True)
    template_string: str = Field(required=True)
    subject: Optional[str] = Field(required=False, default=None)
    provider: Optional[str] = Field(required=False, default=None)
    description: Optional[str] = Field(required=False, default=None)
    tags: list = Field(required=False, default_factory=list)
    is_active: bool = Field(required=False, default=True)
    created_at: datetime = Field(required=False, default=datetime.now)
    created_by: Optional[int] = Field(required=False, default=None)
    updated_at: datetime = Field(required=False, default=datetime.now)
    updated_by: Optional[int] = Field(required=False, default=None)

    class Meta:
        """Meta NotificationTemplate."""

        driver = "pg"
        name = "notification_templates"
        schema = PARROT_SCHEMA
        strict = True
        frozen = False
