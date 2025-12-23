from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from navconfig import config
from parrot.bots import Agent
from parrot.registry import register_agent
from parrot.tools.jiratoolkit import JiraToolkit
from parrot.tools.databasequery import DatabaseQueryTool


class JiraTicket(BaseModel):
    """Model representing a Jira Ticket."""
    project: str = Field(..., description="The project key (e.g., NAV).")
    issue_number: str = Field(..., description="The issue key (e.g., NAV-5972).")
    title: str = Field(..., description="Summary or title of the ticket.")
    description: str = Field(..., description="Description of the ticket.")
    assignee: Optional[str] = Field(None, description="The person assigned to the ticket.")
    reporter: Optional[str] = Field(None, description="The person who reported the ticket.")
    created_at: datetime = Field(..., description="Date of creation.")
    updated_at: datetime = Field(..., description="Date of last update.")
    labels: List[str] = Field(default_factory=list, description="List of labels associated with the ticket.")
    components: List[str] = Field(default_factory=list, description="List of components.")


class HistoryItem(BaseModel):
    field: str
    fromString: Optional[str]
    toString: Optional[str]

class HistoryEvent(BaseModel):
    author: Optional[str]
    created: datetime
    items: List[HistoryItem]

class JiraTicketDetail(BaseModel):
    """Detailed Jira Ticket model with history."""
    issue_number: str = Field(..., alias="key")
    title: str = Field(..., alias="summary")
    description: Optional[str]
    status: str
    assignee: Optional[str]
    reporter: Optional[str]
    labels: List[str]
    created: datetime
    updated: datetime
    history: List[HistoryEvent] = Field(default_factory=list)

class JiraTicketResponse(BaseModel):
    tickets: List[JiraTicket] = Field(default_factory=list, description="List of Jira tickets found.")

@register_agent(name="jira_specialist", at_startup=True)
class JiraSpecialist(Agent):
    """A specialist agent for interacting with Jira."""
    agent_id: str = "jira_specialist"
    model = 'gemini-2.5-pro'
    max_tokens = 8000

    def agent_tools(self):
        """Return the agent-specific tools."""
        jira_instance = config.get("JIRA_INSTANCE")
        jira_api_token = config.get("JIRA_API_TOKEN")
        jira_username = config.get("JIRA_USERNAME")
        jira_project = config.get("JIRA_PROJECT")

        # Determine authentication method based on available config
        auth_type = "basic_auth"
        if not jira_api_token and not jira_username:
            # Fallback or alternative auth logic if needed
            pass

        self.jira_toolkit = JiraToolkit(
            server_url=jira_instance,
            auth_type=auth_type,
            username=jira_username,
            password=jira_api_token,
            default_project=jira_project
        )

        # Link the toolkit to the agent's ToolManager to enable DataFrame sharing
        if hasattr(self, 'tool_manager') and self.tool_manager:
            self.jira_toolkit.set_tool_manager(self.tool_manager)

        return [
            DatabaseQueryTool(),
        ] + self.jira_toolkit.get_tools()

    async def create_ticket(self, summary: str, description: str, **kwargs) -> str:
        """Create a Jira ticket using the JiraToolkit."""
        question = f"""
        Create a Jira ticket for project NAV type bug with summary:
*{summary}*
Description:
*{description}*"
        """
        response = await self.ask(
            question=question,
        )
        return response

    async def search_all_tickets(self, max_tickets: Optional[int] = None, **kwargs) -> List[JiraTicket]:
        """
        Search for due Jira tickets using the JiraToolkit and return structured output.
        Uses dataframe storage optimization to avoid token limits.
        """
        question = f"""
        Use the tool `jira_search_issues` to search for tickets with the following parameters:
        - jql: 'project IN (NAV, NVP, NVS, AC) AND created >= "2024-10-01" AND created <= "2025-12-31"'
        - fields: 'project,key,status,title,assignee,reporter,created,updated,labels,components'
        - max_results:  {max_tickets or 'None'}
        - store_as_dataframe: True
        - dataframe_name: 'jira_tickets_2025'

        Just execute the search and confirm when done. Do not attempt to list the tickets.
        """

        # Execute the tool call
        await self.ask(question=question)

        # Retrieve the stored DataFrame directly from the ToolManager
        try:
            df = self.tool_manager.get_shared_dataframe('jira_tickets_2025')
        except (KeyError, AttributeError):
            # Fallback if dataframe wasn't stored or found
            return []

        if df.empty:
            return []

        return df

    async def get_ticket(self, issue_number: str) -> JiraTicketDetail:
        """Get detailed information for a specific Jira ticket, including history."""
        question = f"""
        Use the tool `jira_get_issue` to retrieve details for issue {issue_number}.
        Parameters:
        - issue: "{issue_number}"
        - fields: "key,summary,description"
        - expand: "changelog"
        - include_history: True

        The tool will return the issue details including a 'history' list.
        """

        # We ask the LLM to call the tool and return the result formatted as JiraTicketDetail
        return await self.ask(
            question=question,
            structured_output=JiraTicketDetail
        )

    async def extract_all_tickets(self, max_tickets: Optional[int] = None, **kwargs) -> JiraTicketResponse:
        """Extract all Jira tickets created in 2025 and return structured response."""
        tickets = await self.search_all_tickets(max_tickets=max_tickets)
        # Iterate over all tickets, extracting detailed info, and added to the dataframe:
        if 'history' not in tickets.columns:
            tickets['history'] = None
        for idx, ticket in tickets.iterrows():
            issue_number = ticket['key']
            repeat = 0
            while repeat < 3:
                response = await self.get_ticket(issue_number=issue_number)
                detailed_ticket = response.output
                if isinstance(detailed_ticket, str):
                    repeat += 1
                    continue
                if detailed_ticket is None or hasattr(detailed_ticket, 'description') is False:
                    repeat += 1
                    continue
                break
            # detailed_ticket is a dataframe with summary,description and history
            # append to ticket response
            tickets.at[idx, 'summary'] = detailed_ticket.title
            tickets.at[idx, 'description'] = detailed_ticket.description
            # we need to filter the history to include only
            # when field is "Status", "Assignee", or "Reporter" or "Resolution"
            filtered_events = []
            for event in detailed_ticket.history:
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
            # sort filtered_events by created date:
            filtered_events.sort(key=lambda x: x.created)

            # add filtered event as dict to tickets dataframe:
            tickets.at[idx, 'history'] = [event.model_dump() for event in filtered_events]
        # return dataframe:
        # save as a CSV file before returning:
        tickets.to_csv('jira_tickets_2025.csv', index=False)
        return tickets
