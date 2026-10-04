"""FEAT-602 TASK-3737 — generated Hooba tool surface."""

import pytest

from parrot_tools.business_automation.models import OperationKind
from parrot_tools.hooba.openapi import DRAFT_OPERATIONS, HoobaOpenAPIToolkit, classify_operation, is_allowed
from parrot_tools.hooba.settings import HoobaSettings
from parrot_tools.hooba.spec import load_pinned_spec


async def _no_login(http):
    """Fail if generation unexpectedly attempts a network login."""
    raise AssertionError("login must not run during generation")


@pytest.fixture
def toolkit():
    """Return the default, account-bound Hooba generated toolkit."""
    return HoobaOpenAPIToolkit(HoobaSettings(account_id=23549), _no_login)


def test_default_surface_size_and_no_submit(toolkit):
    """The pinned specification produces only the bounded read/draft surface."""
    assert len(toolkit.get_tools()) == 58
    assert set(toolkit.operation_kinds().values()) <= {OperationKind.READ, OperationKind.DRAFT}


def test_default_deny_writes(toolkit):
    """Non-draft writes from the pinned document cannot become generated tools."""
    tool_names = {tool.name for tool in toolkit.get_tools()}
    for path, path_item in load_pinned_spec()["paths"].items():
        for method in ("post", "put", "patch", "delete", "options"):
            if method not in path_item:
                continue
            normalized_method = method.upper()
            if (normalized_method, path) in DRAFT_OPERATIONS:
                continue
            operation = {"method": normalized_method, "path": path}
            assert classify_operation(normalized_method, path) is OperationKind.SUBMIT
            assert toolkit._create_method_name(operation) not in tool_names

    blocked_operations = (
        ("POST", "/accounts/{accountId}/contacts"),
        ("POST", "/accounts/{accountId}/invoice-series"),
        ("POST", "/accounts/{accountId}/invoice-series/{invoiceSerieId}:set-default"),
        ("POST", "/accounts/{accountId}/invoices/{invoiceId}:schedule"),
        ("POST", "/accounts/{accountId}/invoices/{invoiceId}:duplicate"),
        ("POST", "/accounts/{accountId}/invoices/{invoiceId}:issue"),
        ("POST", "/accounts/{accountId}/purchase-invoices/{purchaseInvoiceId}:confirm"),
    )
    for method, path in blocked_operations:
        assert not is_allowed(method, path)
        assert classify_operation(method, path) is OperationKind.SUBMIT


def test_generated_tools_carry_operation_kind_routing_meta(toolkit):
    """Every generated tool has a readable routing operation kind."""
    for tool in toolkit.get_tools():
        assert tool.routing_meta["operation_kind"] in {OperationKind.READ.value, OperationKind.DRAFT.value}
        assert "requires_confirmation" not in tool.routing_meta


def test_account_id_hidden_from_schemas(toolkit):
    """The account id supplied by settings is never exposed to an LLM schema."""
    for tool in toolkit.get_tools():
        assert "accountId" not in tool.args_schema.model_json_schema().get("properties", {})


def test_generated_tool_names_match_openapitoolkit_convention(toolkit):
    """Generated tool names use the inherited OpenAPIToolkit naming convention."""
    expected_names = {toolkit._create_method_name(operation) for operation in toolkit.operations}
    assert {tool.name for tool in toolkit.get_tools()} == expected_names


def test_is_allowed_and_classify_unit():
    """Pure policy helpers classify reads, drafts, and denied writes deterministically."""
    assert is_allowed("GET", "/accounts/{accountId}/invoices")
    assert not is_allowed("GET", "/accounts/{accountId}/invoices/{invoiceId}:download")
    assert is_allowed("POST", "/accounts/{accountId}/invoices")
    assert not is_allowed("POST", "/accounts/{accountId}/invoices/{invoiceId}:issue")
    assert classify_operation("HEAD", "/accounts/{accountId}/invoices") is OperationKind.READ
    assert classify_operation("POST", "/accounts/{accountId}/invoices") is OperationKind.DRAFT
    assert classify_operation("POST", "/accounts/{accountId}/invoices/{invoiceId}:issue") is OperationKind.SUBMIT
