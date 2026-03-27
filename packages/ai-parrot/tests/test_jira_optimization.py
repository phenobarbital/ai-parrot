
import asyncio
import pandas as pd
from unittest.mock import MagicMock, AsyncMock
from parrot.bots.jira_specialist import JiraSpecialist, JiraTicket
from parrot.tools.manager import ToolManager

async def test_optimization():
    print("Initializing JiraSpecialist...")
    # Mock config to avoid real initialization issues if any
    agent = JiraSpecialist()
    
    # Mock ToolManager
    agent.tool_manager = MagicMock(spec=ToolManager)
    
    # Create sample DataFrame that mimics what JiraToolkit would produce
    data = {
        'project_key': ['NAV', 'NAV'],
        'key': ['NAV-123', 'NAV-124'],
        'summary': ['Test Ticket 1', 'Test Ticket 2'],
        'description': ['Desc 1', 'Desc 2'],
        'assignee_name': ['John Doe', None],
        'reporter_name': ['Jane Doe', 'Jane Doe'],
        'created': ['2025-01-01T10:00:00', '2025-01-02T11:00:00'],
        'updated': ['2025-01-01T10:00:00', '2025-01-02T11:00:00'],
        'labels': ['bug,urgent', ''],
        'components': ['backend', 'frontend']
    }
    df = pd.DataFrame(data)
    
    # Mock get_shared_dataframe to return our sample DF
    agent.tool_manager.get_shared_dataframe.return_value = df
    
    # Mock ask to do nothing (simulate successful tool call)
    agent.ask = AsyncMock()
    
    print("Testing search_all_tickets logic...")
    tickets = await agent.search_all_tickets()
    
    print(f"Got {len(tickets)} tickets.")
    for t in tickets:
        print(f"Ticket: {t.issue_number} - {t.title}")
        print(f"  Assignee: {t.assignee}")
        print(f"  Labels: {t.labels}")
        print(f"  Components: {t.components}")
        
    # Assertions
    assert len(tickets) == 2
    assert tickets[0].issue_number == 'NAV-123'
    assert tickets[0].labels == ['bug', 'urgent']
    assert tickets[1].assignee is None
    assert tickets[1].components == ['frontend']
    
    print("Verification Passed!")

if __name__ == "__main__":
    asyncio.run(test_optimization())
