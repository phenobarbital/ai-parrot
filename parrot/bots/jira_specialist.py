import asyncio
import logging
import math
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
import pandas as pd
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
    max_tokens = 16000

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

        Just execute the search and confirm when done.
        Do not attempt to list the tickets.
        Avoid adding any additional text or comments to the response.
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

    async def process_chunk(
        self,
        chunk_df: pd.DataFrame,
        chunk_index: int,
        delay: float = 2.0
    ) -> pd.DataFrame:
        """Process a chunk of tickets, retrieving details and history."""
        logging.info(f"Starting processing chunk {chunk_index} with {len(chunk_df)} tickets")

        # Ensure history column exists
        if 'history' not in chunk_df.columns:
            chunk_df['history'] = None

        for idx, ticket in chunk_df.iterrows():
            issue_number = ticket['key']
            repeat = 0
            detailed_ticket = None

            # Retry logic: Try up to 3 times (initial + 2 retries)
            while repeat < 3:
                try:
                    response = await self.get_ticket(issue_number=issue_number)
                    detailed_ticket = response.output

                    if isinstance(detailed_ticket, str):
                        # Some error or unexpected string response
                        logging.warning(f"Got string response for {issue_number}, retrying... ({repeat+1}/3)")
                        repeat += 1
                        await asyncio.sleep(delay * (repeat + 1)) # Exponential-ish backoff
                        continue

                    if detailed_ticket is None or not hasattr(detailed_ticket, 'description'):
                        logging.warning(f"Invalid ticket data for {issue_number}, retrying... ({repeat+1}/3)")
                        repeat += 1
                        await asyncio.sleep(delay * (repeat + 1))
                        continue

                    break  # Success

                except Exception as e:
                    logging.error(f"Error processing ticket {issue_number}: {e}")
                    repeat += 1
                    await asyncio.sleep(delay * (repeat + 1))

            if detailed_ticket is None or isinstance(detailed_ticket, str):
                logging.error(f"Failed to retrieve ticket {issue_number} after retries. Skipping.")
                continue

            if detailed_ticket:
                # Update DataFrame with detailed info
                chunk_df.at[idx, 'summary'] = detailed_ticket.title
                chunk_df.at[idx, 'description'] = detailed_ticket.description

                # Filter and process history
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

                # Sort history by creation date
                filtered_events.sort(key=lambda x: x.created)

                # Store as list of dicts
                chunk_df.at[idx, 'history'] = [event.model_dump() for event in filtered_events]
            else:
                 logging.error(f"Failed to retrieve ticket {issue_number} after retries. Skipping.")

            # Respect rate limit between tickets
            await asyncio.sleep(delay)

        # Save partial result
        filename = f"jira_tickets_part_{chunk_index}.csv"
        chunk_df.to_csv(filename, index=False)
        logging.info(f"Saved chunk {chunk_index} to {filename}")

        return chunk_df

    async def extract_all_tickets(self, max_tickets: Optional[int] = None, chunk_size: int = 50, delay: float = 2.0, concurrency: int = 5, **kwargs) -> List[pd.DataFrame]:
        """Extract all Jira tickets created in 2025 using chunked processing with rate limiting."""
        tickets_df = await self.search_all_tickets(max_tickets=max_tickets)

        if tickets_df.empty:
            return []

        # Split DataFrame into chunks
        num_chunks = math.ceil(len(tickets_df) / chunk_size)
        chunks = [
            tickets_df.iloc[i * chunk_size : (i + 1) * chunk_size].copy()
            for i in range(num_chunks)
        ]

        logging.info(f"Split {len(tickets_df)} tickets into {num_chunks} chunks.")

        # Semaphore for concurrency control
        sem = asyncio.Semaphore(concurrency)

        async def sem_process(chunk, i):
            async with sem:
                return await self.process_chunk(chunk, i, delay=delay)

        # Create tasks for all chunks
        tasks = [sem_process(chunk, i) for i, chunk in enumerate(chunks)]

        # Execute in parallel
        processed_chunks = await asyncio.gather(*tasks)

        return processed_chunks
