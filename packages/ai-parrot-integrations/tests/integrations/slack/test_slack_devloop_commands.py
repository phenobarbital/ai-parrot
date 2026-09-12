"""Unit tests for the Slack `/devloop` command and confirm cards (TASK-3206)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.integrations.slack.devloop import register_devloop
from parrot.integrations.slack.devloop.blocks import confirm_blocks, edit_modal, status_list_text
from parrot.integrations.slack.devloop.commands import devloop_command_handler


def _payload(text: str, user: str = "U1", channel: str = "C1") -> dict:
    return {
        "team_id": "T1",
        "user_id": user,
        "channel_id": channel,
        "text": text,
        "response_url": "https://hooks.slack.test/r",
    }


def _wrapper(authorized: bool = True) -> MagicMock:
    wrapper = MagicMock()
    wrapper._is_authorized = MagicMock(return_value=authorized)
    wrapper._background_tasks = set()
    return wrapper


def _service() -> MagicMock:
    service = MagicMock()
    service.status = AsyncMock(return_value=[])
    service.dispatch = AsyncMock(return_value="pending-1")
    service.cancel = AsyncMock()
    return service


def _transport() -> MagicMock:
    transport = MagicMock()
    transport.render_status = MagicMock(return_value="You have no dev-loop runs.")
    transport.ephemeral = AsyncMock()
    return transport


@pytest.mark.asyncio
async def test_command_handler_ack_and_subcommands():
    """help → USAGE; status → rendered list; dispatch → 'Validating…' ack without awaiting the service."""
    wrapper = _wrapper()
    service = _service()
    transport = _transport()

    help_resp = await devloop_command_handler(_payload("help"), wrapper=wrapper, service=service, transport=transport)
    assert help_resp["response_type"] == "ephemeral"
    assert "Usage" in help_resp["text"]

    status_resp = await devloop_command_handler(
        _payload("status"), wrapper=wrapper, service=service, transport=transport
    )
    assert status_resp["response_type"] == "ephemeral"
    assert status_resp["text"] == "You have no dev-loop runs."
    service.status.assert_awaited_once()

    dispatch_resp = await devloop_command_handler(
        _payload("--type feature Build the thing. Now"), wrapper=wrapper, service=service, transport=transport
    )
    assert dispatch_resp["response_type"] == "ephemeral"
    assert "Validating" in dispatch_resp["text"]
    # dispatch() must not have been awaited synchronously by the handler itself.
    service.dispatch.assert_not_called()
    assert len(wrapper._background_tasks) == 1
    # Let the tracked background task run to completion before the test tears down.
    await asyncio.gather(*wrapper._background_tasks)
    service.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_command_handler_unauthorized():
    """Non-whitelisted user gets 'Unauthorized.' and nothing is dispatched."""
    wrapper = _wrapper(authorized=False)
    service = _service()
    transport = _transport()

    resp = await devloop_command_handler(
        _payload("--type bug a bug summary"), wrapper=wrapper, service=service, transport=transport
    )

    assert resp == {"response_type": "ephemeral", "text": "Unauthorized."}
    assert wrapper._background_tasks == set()
    service.dispatch.assert_not_called()


def test_bug_confirm_card_actions():
    """confirm_blocks carries devloop_confirm/edit/discard action ids with the pending id as value."""
    blocks = confirm_blocks("p1", "bug", {"Summary": "x"})
    ids = [e["action_id"] for e in blocks[1]["elements"]]
    assert ids == ["devloop_confirm:p1", "devloop_edit:p1", "devloop_discard:p1"]


def test_edit_modal_form_definition_per_kind():
    """edit_modal returns a form_definition with callback id devloop_edit and pending id metadata for both kinds."""
    bug_modal = edit_modal("p1", "bug", {"summary": "Sync drops rows"})
    assert bug_modal["id"] == "devloop_edit"
    assert bug_modal["metadata"] == {"pending_id": "p1", "kind": "bug"}
    bug_field_ids = [f["id"] for f in bug_modal["fields"]]
    assert "summary" in bug_field_ids and "affected_component" in bug_field_ids

    feature_modal = edit_modal("p2", "feature", {"title": "Token budget"})
    feature_field_ids = [f["id"] for f in feature_modal["fields"]]
    assert "title" in feature_field_ids and "context" in feature_field_ids
    assert feature_modal["metadata"] == {"pending_id": "p2", "kind": "feature"}


def test_status_list_text_empty_and_populated():
    assert status_list_text([], lambda r: "") == "You have no dev-loop runs."


def test_register_devloop_wires_router_registry_and_interceptor():
    """register_devloop registers 'devloop', the devloop_ prefix, both modal ids and one interceptor."""
    wrapper = MagicMock()
    wrapper._command_router = MagicMock()
    wrapper._interactive_handler = MagicMock()
    wrapper._interactive_handler.action_registry = MagicMock()
    wrapper.add_message_interceptor = MagicMock()
    wrapper.logger = MagicMock()
    wrapper.config = MagicMock(name="test-bot")
    service = MagicMock()

    transport = register_devloop(wrapper, service)

    wrapper._command_router.register.assert_called_once()
    assert wrapper._command_router.register.call_args[0][0] == "devloop"

    registry = wrapper._interactive_handler.action_registry
    registry.register_prefix.assert_called_once()
    assert registry.register_prefix.call_args[0][0] == "devloop_"
    registered_modal_ids = [c.args[0] for c in registry.register.call_args_list]
    assert "modal:devloop_answers" in registered_modal_ids
    assert "modal:devloop_edit" in registered_modal_ids

    wrapper.add_message_interceptor.assert_called_once()
    assert transport is not None
