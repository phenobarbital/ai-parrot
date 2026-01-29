import asyncio
from datetime import datetime
from parrot.bots.jira_specialist import HistoryItem, HistoryEvent, JiraTicketDetail
import pandas as pd

async def verify_logic():
    # 1. Mock Data (similar to what get_ticket would return)
    # The user provided history has mixed datetime strings, but our model now expects datetime objects.
    # Pydantic should handle conversion if the string is ISO format.
    
    # Mocking the raw data that would be parsed into the model
    # Note: In the real app, Pydantic parses the string from Jira to datetime.
    # Here we simulate an already parsed object.
    
    history_data = [
        HistoryEvent(
            author="Author 1",
            created=datetime(2025, 12, 23, 14, 34, 17),
            items=[
                HistoryItem(field="status", fromString="Open", toString="To Do"), # Match "status"
                HistoryItem(field="other", fromString="A", toString="B") 
            ]
        ),
        HistoryEvent(
            author="Author 2",
            created=datetime(2025, 12, 23, 14, 34, 12), # Earlier
            items=[
                HistoryItem(field="IssueParentAssociation", fromString=None, toString="NAV-5642") # Should be filtered out
            ]
        ),
         HistoryEvent(
            author="Author 3",
            created=datetime(2025, 12, 23, 14, 34, 15), # Middle
            items=[
                HistoryItem(field="Status", fromString="Backlog", toString="Open") # Match "Status" (test case-insensitivity)
            ]
        )
    ]
    
    ticket_detail = JiraTicketDetail(
        key="NAV-123",
        summary="Test Ticket",
        description="Test Description",
        status="To Do",
        assignee="Test User",  # Added
        reporter="Test Reporter", # Added
        labels=[], # Added
        created=datetime(2025, 12, 23, 14, 0, 0),
        updated=datetime(2025, 12, 23, 15, 0, 0),
        history=history_data
    )

    # 2. Simulate extract_all_tickets logic
    # Assume we have a dataframe row
    tickets = pd.DataFrame([{'key': 'NAV-123', 'summary': '', 'description': '', 'history': None}])
    
    for idx, ticket in tickets.iterrows():
        # ... get_ticket call simulation ...
        detailed_ticket = ticket_detail
        
        filtered_events = []
        for event in detailed_ticket.history:
            # Logic from file:
            if filtered_items := [
                item for item in event.items
                if item.field.lower() in ["status", "assignee", "reporter", "resolution"]
            ]:
                filtered_event = HistoryEvent(
                    author=event.author,
                    created=event.created,
                    items=filtered_items
                )
                filtered_events.append(filtered_event)
        
        # Sort
        filtered_events.sort(key=lambda x: x.created)
        
        print("\n--- Filtered & Sorted Events ---")
        for event in filtered_events:
            print(f"Time: {event.created}, Items: {[i.field for i in event.items]}")
            
        # Verify order
        if len(filtered_events) == 2:
            assert filtered_events[0].created < filtered_events[1].created
            print("\nSUCCESS: Events are sorted correctly.")
        else:
            print(f"\nFAILURE: Expected 2 events, got {len(filtered_events)}")
            
        # Verify filtering
        fields = [item.field for event in filtered_events for item in event.items]
        if "IssueParentAssociation" not in fields and "status" in fields and "Status" in fields:
             print("SUCCESS: Filtering worked correctly (case-insensitive).")
        else:
             print(f"FAILURE: Filtering incorrect. Fields found: {fields}")

if __name__ == "__main__":
    asyncio.run(verify_logic())
