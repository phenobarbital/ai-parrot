"""FEAT-775 M6: Teams connection cards."""

from parrot.auth.oauth2.models import IntegrationDescriptor
from parrot.integrations.msteams.connections import (
    connect_card,
    connections_status_card,
    device_code_card,
    provider_picker_card,
)


def test_connect_card_open_url() -> None:
    """The connect card has one OpenUrl action using the supplied URL."""
    auth_url = "https://auth.example.test/authorize"

    card = connect_card("Jira", auth_url)

    assert card["actions"] == [{"type": "Action.OpenUrl", "title": "Connect Jira", "url": auth_url}]


def test_device_code_card_has_code_and_uri_no_oauth_url() -> None:
    """The device-code card exposes only its verification URL."""
    verification_uri = "https://microsoft.com/devicelogin"

    card = device_code_card("Microsoft 365", "ABCD-EFGH", verification_uri, 900)

    body_text = " ".join(block["text"] for block in card["body"])
    urls = [action["url"] for action in card["actions"] if action["type"] == "Action.OpenUrl"]
    assert "ABCD-EFGH" in body_text
    assert verification_uri in body_text
    assert urls == [verification_uri]


def test_provider_picker_submit_commands() -> None:
    """Picker actions use the same commands as typed Teams messages."""
    card = provider_picker_card([("jira", "Jira"), ("o365", "Microsoft 365")])

    assert [action["data"]["command"] for action in card["actions"]] == ["/connect jira", "/connect o365"]


def test_status_card_rows() -> None:
    """Connected and disconnected providers produce their respective actions."""
    connected = IntegrationDescriptor(
        provider="jira",
        display_name="Jira",
        status="connected",
        display_account_name="Ada Lovelace",
    )
    disconnected = IntegrationDescriptor(provider="o365", display_name="Microsoft 365", status="disconnected")

    card = connections_status_card([connected, disconnected])

    body_text = " ".join(block["text"] for block in card["body"])
    assert "Jira: connected as Ada Lovelace" in body_text
    assert "Microsoft 365: not connected" in body_text
    assert [action["data"]["command"] for action in card["actions"]] == ["/disconnect jira", "/connect o365"]
