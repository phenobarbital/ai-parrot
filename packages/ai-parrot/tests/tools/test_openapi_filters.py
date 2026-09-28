"""FEAT-602 TASK-3731 — OpenAPIToolkit operation filters and path defaults."""

import logging

import pytest

from parrot.tools.openapitoolkit import OpenAPIToolkit


def _path_parameter(name: str) -> dict:
    """Create a required integer OpenAPI path parameter."""
    return {
        "name": name,
        "in": "path",
        "required": True,
        "schema": {"type": "integer"},
    }


def _spec() -> dict:
    """Return a small spec with Invoice and Contact operations."""
    return {
        "openapi": "3.0.0",
        "info": {"title": "Test API", "version": "1.0.0"},
        "servers": [{"url": "https://api.test"}],
        "paths": {
            "/accounts/{accountId}/invoices": {
                "get": {
                    "operationId": "list_invoices",
                    "tags": ["Invoice"],
                    "parameters": [_path_parameter("accountId")],
                },
                "post": {
                    "operationId": "create_invoice",
                    "tags": ["Invoice"],
                    "parameters": [_path_parameter("accountId")],
                },
            },
            "/accounts/{accountId}/invoices/{invoiceId}:issue": {
                "post": {
                    "operationId": "issue_invoice",
                    "tags": ["Invoice"],
                    "parameters": [_path_parameter("accountId"), _path_parameter("invoiceId")],
                },
            },
            "/accounts/{accountId}/invoices/{invoiceId}": {
                "delete": {
                    "operationId": "delete_invoice",
                    "tags": ["Invoice"],
                    "parameters": [_path_parameter("accountId"), _path_parameter("invoiceId")],
                },
            },
            "/accounts/{accountId}/contacts": {
                "get": {
                    "operationId": "list_contacts",
                    "tags": ["Contact"],
                    "parameters": [_path_parameter("accountId")],
                },
            },
        },
    }


def test_defaults_generate_every_operation_unchanged():
    """No new arguments retain all generated operations and names."""
    toolkit = OpenAPIToolkit(spec=_spec(), service="test")

    assert len(toolkit.operations) == 5
    assert {operation["operation_id"] for operation in toolkit.operations} == {
        "list_invoices",
        "create_invoice",
        "issue_invoice",
        "delete_invoice",
        "list_contacts",
    }
    assert len(toolkit.get_tools()) == 5


def test_include_tags_first_tag_only():
    """Only operations whose first tag is included survive."""
    toolkit = OpenAPIToolkit(spec=_spec(), service="test", include_tags=("Invoice",))

    assert {operation["operation_id"] for operation in toolkit.operations} == {
        "list_invoices",
        "create_invoice",
        "issue_invoice",
        "delete_invoice",
    }


def test_exclude_methods_and_paths():
    """Excluded methods and raw-path regular expressions remove operations."""
    toolkit = OpenAPIToolkit(
        spec=_spec(),
        service="test",
        exclude_methods=("DELETE",),
        exclude_paths=(r":issue$",),
    )

    assert {operation["operation_id"] for operation in toolkit.operations} == {
        "list_invoices",
        "create_invoice",
        "list_contacts",
    }


def test_operation_filter_receives_upper_method_and_raw_path():
    """The operation filter receives the normalized method and unmodified path."""
    calls = []

    def filter_contacts(method: str, path: str) -> bool:
        calls.append((method, path))
        return path != "/accounts/{accountId}/contacts"

    toolkit = OpenAPIToolkit(spec=_spec(), service="test", operation_filter=filter_contacts)

    assert ("GET", "/accounts/{accountId}/contacts") in calls
    assert "list_contacts" not in {operation["operation_id"] for operation in toolkit.operations}


def test_tags_recorded_on_operations():
    """Kept operations retain the tags declared in the OpenAPI document."""
    toolkit = OpenAPIToolkit(spec=_spec(), service="test")

    contacts = next(operation for operation in toolkit.operations if operation["operation_id"] == "list_contacts")
    assert contacts["tags"] == ["Contact"]


def test_max_tools_exceeded_raises():
    """The generated operation budget fails before dynamic tool creation."""
    with pytest.raises(ValueError, match=r"5 operations exceed max_tools=1"):
        OpenAPIToolkit(spec=_spec(), service="test", max_tools=1)


def test_path_defaults_hidden_from_schema():
    """Toolkit-provided path defaults are excluded from generated tool schemas."""
    toolkit = OpenAPIToolkit(spec=_spec(), service="test", path_defaults={"accountId": 23549})

    method = toolkit.test_get_accounts_accountid_invoices
    assert "accountId" not in method._args_schema.model_fields


def test_path_defaults_override_caller_value(caplog):
    """Toolkit defaults replace caller values without logging the caller value."""
    toolkit = OpenAPIToolkit(spec=_spec(), service="test", path_defaults={"accountId": 23549})
    operation = next(operation for operation in toolkit.operations if operation["operation_id"] == "list_invoices")

    with caplog.at_level(logging.WARNING):
        url = toolkit._build_operation_url(operation, {"accountId": 1})

    assert url == "https://api.test/accounts/23549/invoices"
    assert "Ignoring caller value for defaulted path parameter accountId" in caplog.text
    assert "1" not in caplog.text
