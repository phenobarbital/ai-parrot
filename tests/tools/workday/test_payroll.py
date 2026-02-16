import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from parrot.tools.workday.tool import WorkdayToolkit, WorkdayService

@pytest.fixture
def mock_workday_client():
    client = AsyncMock()
    # Mock helper methods to avoid actual processing logic if not relevant for basic flow
    client._build_worker_reference = MagicMock(return_value={"ID": [{"type": "Employee_ID", "_value_1": "12345"}]})
    return client

@pytest.fixture
def workday_toolkit(mock_workday_client):
    with patch("parrot.tools.workday.tool.WorkdaySOAPClient") as MockClient:
        MockClient.return_value = mock_workday_client
        
        credentials = {
            "client_id": "test_id",
            "client_secret": "test_secret",
            "token_url": "https://test.url",
            "refresh_token": "test_token",
            "wsdl_path": "https://test.wsdl"
        }
        
        toolkit = WorkdayToolkit(
            credentials=credentials,
            tenant_name="test_tenant",
            wsdl_paths={
                "payroll": "https://test.payroll.wsdl"
            }
        )
        # Manually inject the mocked client into the toolkit's cache to bypass _get_client_for_service
        toolkit._clients[WorkdayService.PAYROLL] = mock_workday_client
        toolkit._initialized = True
        return toolkit

@pytest.mark.asyncio
async def test_wd_get_payroll_balances(workday_toolkit, mock_workday_client):
    # Mock response
    mock_response = {
        "Payroll_Balance_Data": {
            "Balance_Item": "Test Balance"
        }
    }
    mock_workday_client.run.return_value = mock_response

    result = await workday_toolkit.wd_get_payroll_balances(
        worker_id="12345",
        start_date="2023-01-01",
        end_date="2023-12-31",
        pay_component_group_ids=["PCG1"]
    )

    # Verify method call
    mock_workday_client.run.assert_awaited_with(
        "Get_Payroll_Balances",
        Request_References={'Worker_Reference': {'ID': [{'type': 'Employee_ID', '_value_1': '12345'}]}}, 
        Response_Filter={'Start_Date': '2023-01-01', 'End_Date': '2023-12-31'},
        Request_Criteria={'Pay_Component_Group_Reference': [{'ID': [{'type': 'Pay_Component_Group_ID', '_value_1': 'PCG1'}]}]}
    )
    
    # Verify result (implicit serialization by helper)
    assert result == mock_response

@pytest.mark.asyncio
async def test_wd_get_payroll_results(workday_toolkit, mock_workday_client):
    # Mock response
    mock_response = {
        "Payroll_Result_Data": [
            {"Period": "2023-01"},
            {"Period": "2023-02"}
        ]
    }
    mock_workday_client.run.return_value = mock_response

    result = await workday_toolkit.wd_get_payroll_results(
        worker_id="12345",
        start_date="2023-01-01",
        include_details=True
    )

    # Verify method call
    mock_workday_client.run.assert_awaited_with(
        "Get_Payroll_Results",
        Request_References={'Worker_Reference': {'ID': [{'type': 'Employee_ID', '_value_1': '12345'}]}}, 
        Response_Filter={'Start_Date': '2023-01-01'},
        Response_Group={'Include_Payroll_Result_Lines': True}
    )

    # Verify result
    assert len(result) == 2
    assert result[0]["Period"] == "2023-01"

@pytest.mark.asyncio
async def test_wd_get_company_payment_dates(workday_toolkit, mock_workday_client):
    # Mock response
    mock_response = {
        "Company_Payment_Dates_Data": [
            {"Payment_Date": "2023-01-15"},
            {"Payment_Date": "2023-01-31"}
        ]
    }
    mock_workday_client.run.return_value = mock_response

    result = await workday_toolkit.wd_get_company_payment_dates(
        start_date="2023-01-01",
        end_date="2023-01-31",
        pay_group_id="PG1"
    )

    # Verify method call
    mock_workday_client.run.assert_awaited_with(
        "Get_Company_Payment_Dates",
        Request_Criteria={
            'Start_Date': '2023-01-01', 
            'End_Date': '2023-01-31',
            'Pay_Group_Reference': {'ID': [{'type': 'Pay_Group_ID', '_value_1': 'PG1'}]}
        }
    )

    # Verify result
    assert len(result) == 2
    assert result[0]["Payment_Date"] == "2023-01-15"
