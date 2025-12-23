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
    created_at: str = Field(..., description="Date of creation.")
    updated_at: str = Field(..., description="Date of last update.")
    labels: List[str] = Field(default_factory=list, description="List of labels associated with the ticket.")
    components: List[str] = Field(default_factory=list, description="List of components.")


class HistoryItem(BaseModel):
    field: str
    fromString: Optional[str]
    toString: Optional[str]

class HistoryEvent(BaseModel):
    author: Optional[str]
    created: str
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
    created: str
    updated: str
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

    async def search_all_tickets(self, **kwargs) -> List[JiraTicket]:
        """
        Search for due Jira tickets using the JiraToolkit and return structured output.
        Uses dataframe storage optimization to avoid token limits.
        """
        question = """
        Use the tool `jira_search_issues` to search for tickets with the following parameters:
        - jql: 'created >= "2025-01-01" AND created <= "2025-12-31"'
        - fields: 'project,key,summary,description,assignee,reporter,created,updated,labels,components'
        - max_results: None  (to fetch ALL matching tickets)
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
        - fields: "summary,description,status,assignee,reporter,created,updated,labels"
        - expand: "changelog"
        - include_history: True
        
        The tool will return the issue details including a 'history' list.
        """
        
        # We ask the LLM to call the tool and return the result formatted as JiraTicketDetail
        response = await self.ask(
            question=question,
            structured_output=JiraTicketDetail
        )
        return response
