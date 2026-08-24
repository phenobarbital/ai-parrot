import pytest

from tests.fixtures.jira_payloads import raw_issue_payload, remote_links_payload


@pytest.fixture
def raw_issue() -> dict:
    return raw_issue_payload()


@pytest.fixture
def remote_links() -> list[dict]:
    return remote_links_payload()
