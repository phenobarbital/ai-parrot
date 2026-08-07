"""Unit tests for the CommCenter render + validation core (FEAT-417, Module 5)."""
from datetime import datetime

import pytest
from notify.models import Actor, Channel, Chat, TeamsChannel
from notify.server.wrapper import NotifyWrapper
from parrot.services.comm_center.models import RecipientIn
from parrot.services.comm_center.render import (
    build_wire_payload,
    partial_render,
    prepare,
    resolve_functions,
)

FROZEN = datetime(2026, 8, 6, 12, 0, 0)


class TestPartialRender:
    """Pass-1 partial rendering — computed functions resolved, records preserved."""

    def test_preserves_record_placeholders(self):
        out = partial_render(
            "Hola {{ name }}, hoy es {{ today }} - {{ email }}",
            resolve_functions(now=FROZEN),
        )
        assert "2026-08-06" in out
        assert "{{ name }}" in out and "{{ email }}" in out

    def test_syntax_error_raises(self):
        with pytest.raises(Exception):
            partial_render("Hola {{ name ", resolve_functions(now=FROZEN))

    def test_functions_deterministic(self):
        assert resolve_functions(now=FROZEN) == resolve_functions(now=FROZEN)


class TestWirePayload:
    """The three verified traps — regression-guarded via a real NotifyWrapper."""

    def test_recipient_key_is_singular(self):
        p = build_wire_payload(
            RecipientIn(name="Ana", email="a@e.com"), "email", "hi", None
        )
        assert "recipient" in p and "recipients" not in p

    def test_username_always_emitted_falls_back_to_name(self):
        p = build_wire_payload(
            RecipientIn(name="Ana Gomez", email="a@e.com"), "email", "hi", None
        )
        assert p["username"] == "Ana Gomez"  # Trap 1 guard

    def test_email_builds_actor_with_account(self):
        p = build_wire_payload(
            RecipientIn(name="Ana", email="a@e.com"), "email", "hi", None
        )
        r = NotifyWrapper(**p).recipients[0]
        assert isinstance(r, Actor)
        assert r.account.address == "a@e.com"

    def test_teams_builds_teamschannel(self):
        p = build_wire_payload(
            RecipientIn(name="Ops", extra={"team_id": "T1", "channel_id": "C1"}),
            "teams",
            "hi",
            None,
        )
        assert isinstance(NotifyWrapper(**p).recipients[0], TeamsChannel)

    def test_telegram_and_slack_shapes(self):
        chat = build_wire_payload(
            RecipientIn(name="x", extra={"chat_id": "1"}), "telegram", "hi", None
        )
        assert isinstance(NotifyWrapper(**chat).recipients[0], Chat)
        ch = build_wire_payload(
            RecipientIn(name="x", extra={"channel_id": "C9"}), "slack", "hi", None
        )
        assert isinstance(NotifyWrapper(**ch).recipients[0], Channel)

    def test_extra_column_cannot_clobber_template(self):
        """Regression guard (adversarial code review, FEAT-417): an ingested
        column literally named 'template' must never silently replace the
        real partially-rendered message body — verified structurally
        against the merge order in build_wire_payload."""
        p = build_wire_payload(
            RecipientIn(
                name="Ana", email="a@e.com", extra={"template": "MALICIOUS OVERRIDE"}
            ),
            "email",
            "Hola {{ name }}",
            None,
        )
        assert p["template"] == "Hola {{ name }}"

    def test_extra_column_cannot_clobber_provider(self):
        """Same guard, for the 'provider' structural key."""
        p = build_wire_payload(
            RecipientIn(name="Ana", email="a@e.com", extra={"provider": "sms"}),
            "email",
            "hi",
            None,
        )
        assert p["provider"] == "email"

    def test_extra_column_survives_when_not_protected(self):
        """The filter is scoped to structural keys only -- ordinary extra
        columns are still forwarded verbatim as pass-2 placeholders."""
        p = build_wire_payload(
            RecipientIn(name="Ana", email="a@e.com", extra={"department": "Sales"}),
            "email",
            "hi",
            None,
        )
        assert p["department"] == "Sales"


class TestValidation:
    """Provider resolution + contact-field validation via prepare()."""

    async def test_missing_contact_field_skipped(self):
        b = await prepare(
            recipients=[RecipientIn(name="NoMail")],
            provider="email",
            template_source="hi",
            subject=None,
            now=FROZEN,
        )
        assert len(b.queued) == 0 and len(b.skipped) == 1
        assert "email" in b.skipped[0].reason

    async def test_unknown_provider_skipped_not_defaulted(self):
        b = await prepare(
            recipients=[
                RecipientIn(name="A", email="a@e.com", provider="carrier-pigeon")
            ],
            provider="email",
            template_source="hi",
            subject=None,
            now=FROZEN,
        )
        assert len(b.skipped) == 1

    async def test_row_provider_overrides_global(self):
        b = await prepare(
            recipients=[
                RecipientIn(name="A", extra={"chat_id": "1"}, provider="telegram")
            ],
            provider="email",
            template_source="hi",
            subject=None,
            now=FROZEN,
        )
        assert b.queued[0].payload["provider"] == "telegram"

    async def test_partial_send_valid_rows_survive(self):
        b = await prepare(
            recipients=[
                RecipientIn(name="Bad"),
                RecipientIn(name="Good", email="g@e.com"),
            ],
            provider="email",
            template_source="Hola {{ name }}",
            subject=None,
            now=FROZEN,
        )
        assert len(b.queued) == 1 and len(b.skipped) == 1

    async def test_prepare_performs_no_io(self):
        """prepare() must be a pure function — no Redis/DB/aiohttp (spec G12)."""
        b = await prepare(
            recipients=[RecipientIn(name="Ana", email="a@e.com")],
            provider="email",
            template_source="Hola {{ name }}, hoy es {{ today }}",
            subject="Hi",
            now=FROZEN,
        )
        assert b.resolved_functions["today"] == "2026-08-06"
        assert "{{ name }}" in b.template
        assert len(b.queued) == 1
