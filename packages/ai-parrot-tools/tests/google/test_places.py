import pytest
from unittest.mock import MagicMock, AsyncMock
from parrot.tools.google.places import GoogleBusinessTool

@pytest.fixture
def mock_google_client():
    client = MagicMock()
    client.execute_api_call = AsyncMock()
    return client

@pytest.mark.asyncio
async def test_google_business_tool_list_accounts(mock_google_client):
    tool = GoogleBusinessTool(credentials={"type": "service_account"})
    # Inject mock client into the tool's cache or mock _get_client
    tool._get_client = AsyncMock(return_value=mock_google_client)
    
    mock_google_client.execute_api_call.return_value = {
        'accounts': [{'name': 'accounts/12345', 'accountName': 'Test Account'}]
    }
    
    result = await tool.run(command='list_accounts')
    
    assert len(result.result) == 1
    assert result.result[0]['name'] == 'accounts/12345'
    mock_google_client.execute_api_call.assert_called_with(
        'mybusinessaccountmanagement', 'accounts', 'list', version='v1'
    )

@pytest.mark.asyncio
async def test_google_business_tool_get_reviews(mock_google_client):
    tool = GoogleBusinessTool(credentials={"type": "service_account"})
    tool._get_client = AsyncMock(return_value=mock_google_client)
    
    mock_google_client.execute_api_call.return_value = {
        'reviews': [
            {
                'reviewId': 'r1',
                'comment': 'Great place! I loved it.',
                'starRating': 'FIVE'
            },
            {
                'reviewId': 'r2',
                'comment': 'Terrible service.',
                'starRating': 'ONE'
            }
        ]
    }
    
    result = await tool.run(
        command='get_reviews', 
        account_id='accounts/123', 
        location_id='locations/456'
    )
    
    assert result.result['total_reviews'] == 2
    assert result.result['reviews'][0]['sentiment']['assessment'] == 'positive'
    assert result.result['reviews'][1]['sentiment']['assessment'] == 'negative'

@pytest.mark.asyncio
async def test_google_business_tool_reply_review(mock_google_client):
    tool = GoogleBusinessTool(credentials={"type": "service_account"})
    tool._get_client = AsyncMock(return_value=mock_google_client)
    
    mock_google_client.execute_api_call.return_value = {'comment': 'Thank you!'}
    
    result = await tool.run(
        command='reply_review',
        account_id='accounts/123',
        location_id='locations/456',
        review_id='r1',
        reply_text='Thank you!'
    )
    
    assert result.result['status'] == 'success'
    mock_google_client.execute_api_call.assert_called()
    call_args = mock_google_client.execute_api_call.call_args[1]
    assert call_args['name'] == 'accounts/123/locations/456/reviews/r1/reply'
    assert call_args['json']['comment'] == 'Thank you!'
