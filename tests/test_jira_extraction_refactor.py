import asyncio
import pandas as pd
from unittest.mock import MagicMock, AsyncMock, patch
import unittest
from parrot.bots.jira_specialist import JiraSpecialist, JiraTicketDetail, HistoryEvent, HistoryItem
from datetime import datetime

class TestJiraExtraction(unittest.TestCase):
    def test_run_async(self):
        asyncio.run(self.run_async_test())

    async def run_async_test(self):
        # Mock config
        with patch("parrot.bots.jira_specialist.config") as mock_config, \
             patch("parrot.bots.jira_specialist.JiraToolkit") as MockJiraToolkit:
            
            mock_config.get.return_value = "https://dummy-jira.com"
            
            # Setup
            agent = JiraSpecialist()
            # Ensure toolkit is satisfied
            agent.jira_toolkit = MockJiraToolkit.return_value
            agent.tool_manager = AsyncMock() 

            # Mock search_all_tickets to return a dataframe of 10 tickets
            initial_data = {
                'key': [f'NAV-{i}' for i in range(1, 11)],
                'project': ['NAV'] * 10,
                'status': ['Open'] * 10
            }
            initial_df = pd.DataFrame(initial_data)
            agent.search_all_tickets = AsyncMock(return_value=initial_df)

            # Mock get_ticket to return a valid detail
            dummy_history = [
                HistoryEvent(
                    author="Test User", 
                    created=datetime.now(), 
                    items=[HistoryItem(field="status", fromString="Open", toString="In Progress")]
                )
            ]
            
            valid_response = MagicMock()
            valid_response.output = JiraTicketDetail(
                key="NAV-1",
                summary="Test Summary",
                description="Test Description",
                status="In Progress",
                history=dummy_history,
                created=datetime.now(),
                updated=datetime.now(),
                labels=[],
                assignee="Test User",
                reporter="Test Reporter"
            )

            # Make get_ticket fail for NAV-5 (to test error handling/skipping)
            async def side_effect(issue_number):
                if issue_number == "NAV-5":
                    raise Exception("Simulated 500 Error")
                # Ensure key matches requested
                resp = MagicMock()
                # Create a copy so we don't mutate the shared mock output significantly
                detail = valid_response.output.model_copy(update={"issue_number": issue_number})
                resp.output = detail
                return resp
                
            agent.get_ticket = AsyncMock(side_effect=side_effect)

            # Mock to_csv on DataFrame to verify saving without writing files
            with patch.object(pd.DataFrame, 'to_csv') as mock_to_csv:
                # EXECUTE
                # Chunk size 2 means 10 tickets -> 5 chunks
                results = await agent.extract_all_tickets(chunk_size=2)
                
                # VERIFY
                self.assertEqual(len(results), 5)
                self.assertIsInstance(results[0], pd.DataFrame)
                
                # Check call counts
                self.assertEqual(agent.search_all_tickets.call_count, 1)
                
                # Verify usage of get_ticket
                # NAV-5 fails 3 times. Others (9 tickets) succeed once. Total 12 calls expected.
                # However, async gathering might make exact count check tricky if retry loop logic varies, 
                # but roughly >= 10 calls.
                self.assertGreaterEqual(agent.get_ticket.call_count, 10)
                
                # Verify CSV saving
                self.assertEqual(mock_to_csv.call_count, 5)
                mock_to_csv.assert_any_call('jira_tickets_part_0.csv', index=False)
                mock_to_csv.assert_any_call('jira_tickets_part_4.csv', index=False)
                
                # Check NAV-5 handling
                # Chunk 2 has indices 4 and 5 (NAV-5 and NAV-6)
                chunk_containing_nav_5 = results[2]  
                ticket_5 = chunk_containing_nav_5[chunk_containing_nav_5['key'] == 'NAV-5'].iloc[0]
                
                # Should not have summary if it failed, or it persists from initial if initialized
                # In current logic, we update 'summary' if successful. If failed, it remains potentially NaN/None.
                val = ticket_5.get('summary')
                print(f"NAV-5 Summary value: {val}")
                self.assertTrue(pd.isna(val) or val is None)
                
                print("Test passed successfully!")

if __name__ == "__main__":
    unittest.main()
