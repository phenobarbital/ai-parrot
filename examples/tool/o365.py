"""
Examples: Using Office365 Tools with AI-Parrot

This file demonstrates various ways to use the Office365 tools:
1. Direct usage with credentials
2. Integration with BasicAgent
3. Tool registration and management
4. Different authentication modes
5. Practical use cases
"""
import asyncio
from typing import List
from parrot.bots.agent import BasicAgent

# Import our O365 tools
from parrot.tools.o365 import (
    CreateDraftMessageTool,
    CreateEventTool,
    SearchEmailTool,
    SendEmailTool
)
from parrot.conf import (
    O365_CLIENT_ID,
    O365_CLIENT_SECRET,
    O365_TENANT_ID
)


# ============================================================================
# EXAMPLE 1: Direct Tool Usage with Client Credentials (Admin Mode)
# ============================================================================

async def example_direct_usage():
    """Example of using tools directly with admin credentials."""

    # Set up credentials
    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID,
        'user_id': 'jlara@trocglobal.com'
    }

    # Create tool instances
    draft_tool = CreateDraftMessageTool(credentials=credentials, user_id='jlara@trocglobal.com')
    send_tool = SendEmailTool(credentials=credentials, user_id='jlara@trocglobal.com')
    search_tool = SearchEmailTool(credentials=credentials, user_id='jlara@trocglobal.com')
    event_tool = CreateEventTool(credentials=credentials, user_id='jlara@trocglobal.com')

    # Create a draft email
    draft_result = await draft_tool.run(
        subject="Project Status Update",
        body="Here's the latest update on our project...",
        to_recipients=["jlara@trocglobal.com"],
        cc_recipients=["jlara@trocglobal.com"]
    )
    print(f"Draft created: {draft_result.result['id']}")

    # Search for emails
    search_result = await search_tool.run(
        query="invoice hasAttachments:true",
        max_results=5,
        include_attachments=True
    )
    print(f"Found {search_result.result['total_results']} emails")

    # Create a calendar event
    event_result = await event_tool.run(
        subject="DEV Meeting",
        start_datetime="2025-10-20T16:00:00",
        end_datetime="2025-10-20T17:00:00",
        timezone="America/New_York",
        attendees=["jlara@trocglobal.com"],
        is_online_meeting=True
    )
    print(f"Event created: {event_result.result['join_url']}")

    # Send an email
    send_result = await send_tool.run(
        subject="Welcome!",
        body="<h1>Welcome to our team!</h1><p>We're excited to have you.</p>",
        to_recipients=["jleon@trocglobal.com", "jlara@trocglobal.com"],
        is_html=True
    )
    print(f"Email sent at: {send_result.result['sent_datetime']}")


# ============================================================================
# EXAMPLE 2: Using with BasicAgent and ToolManager
# ============================================================================

async def example_agent_integration():
    """Example of integrating O365 tools with an agent."""

    # Set up credentials
    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID
    }

    # Create O365 tools
    o365_tools = [
        CreateDraftMessageTool(credentials=credentials),
        CreateEventTool(credentials=credentials),
        SearchEmailTool(credentials=credentials),
        SendEmailTool(credentials=credentials)
    ]

    # Create an agent with O365 tools
    assistant = BasicAgent(
        name="Office365Assistant",
        role="Email and Calendar Manager",
        goal="Help users manage their Office365 emails and calendar efficiently",
        backstory=(
            "You are an expert at managing Office365 services. "
            "You can create drafts, send emails, search through messages, "
            "and schedule calendar events."
        ),
        tools=o365_tools,  # Pass tools directly
        llm_client='google',
        model='gemini-2.0-flash-exp'
    )

    # Now the agent can use the tools
    response = await assistant.chat(
        "Can you search for all emails from john@company.com in the last week "
        "and create a draft reply summarizing the key points?"
    )
    print(response)


# ============================================================================
# EXAMPLE 3: Manual Tool Registration
# ============================================================================

async def example_manual_registration():
    """Example of manually registering tools with ToolManager."""

    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID
    }

    # Create agent without tools
    assistant = BasicAgent(
        name="Office365Assistant",
        role="Personal Assistant",
        goal="Manage communication and scheduling"
    )

    # Register tools manually
    assistant.tool_manager.register_tool(
        CreateDraftMessageTool(credentials=credentials)
    )
    assistant.tool_manager.register_tool(
        SendEmailTool(credentials=credentials)
    )
    assistant.tool_manager.register_tool(
        SearchEmailTool(credentials=credentials)
    )
    assistant.tool_manager.register_tool(
        CreateEventTool(credentials=credentials)
    )

    # Sync tools to LLM
    if hasattr(assistant, '_sync_tools_to_llm'):
        assistant._sync_tools_to_llm()

    # Use the agent
    response = await assistant.chat(
        "Schedule a meeting with the team for tomorrow at 2 PM "
        "and send them an invitation email."
    )
    print(response)


# ============================================================================
# EXAMPLE 4: On-Behalf-Of (OBO) Authentication
# ============================================================================

async def example_obo_auth():
    """Example using On-Behalf-Of authentication with a user token."""

    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID
    }

    # Assume we have a user assertion token from authentication middleware
    user_assertion_token = "eyJ0eXAiOiJKV1QiLCJhbGc..."

    # Create tool with OBO as default mode
    send_tool = SendEmailTool(
        credentials=credentials,
        default_auth_mode='on_behalf_of'
    )

    # Send email on behalf of the authenticated user
    result = await send_tool.run(
        subject="Action Required",
        body="Please review the attached document.",
        to_recipients=["colleague@company.com"],
        user_assertion=user_assertion_token  # Pass the user's token
    )
    print(f"Email sent on behalf of user: {result.result}")


# ============================================================================
# EXAMPLE 5: Delegated Permissions (Interactive Login)
# ============================================================================

async def example_delegated_auth():
    """Example using delegated permissions with interactive login."""

    credentials = {
        'client_id': O365_CLIENT_ID,  # Public client app
        'tenant_id': O365_TENANT_ID,
        'user_id': 'jlara@trocglobal.com'
    }

    # Create tool with delegated mode
    search_tool = SearchEmailTool(
        credentials=credentials,
        default_auth_mode='delegated',
        scopes=[
            "User.Read",
            "Mail.Read",
            "Mail.Send",
            "Calendars.ReadWrite"
        ]
    )

    # First use will trigger interactive login in browser
    result = await search_tool.run(
        query="important",
        max_results=10,
        auth_mode='delegated'  # Explicitly use delegated
    )
    print(f"Found {result.result['total_results']} emails")

    # Subsequent calls can use cached session
    result2 = await search_tool.run(
        query="meetings",
        auth_mode='cached'  # Use cached interactive session
    )
    print(f"Found {result2.result['total_results']} more emails")


# ============================================================================
# EXAMPLE 6: Building an Email Management Agent
# ============================================================================

class EmailManagerAgent(BasicAgent):
    """Specialized agent for email management."""

    def __init__(self, credentials: dict, **kwargs):
        # Default scopes if not provided
        if scopes is None:
            scopes = [
                "User.Read",
                "Mail.Read",
                "Mail.ReadWrite",
                "Mail.Send",
                "Calendars.ReadWrite"
            ]
        # Initialize O365 tools
        self.o365_tools = [
            SearchEmailTool(
                credentials=credentials,
                default_auth_mode='delegated',
                scopes=scopes
            ),
            CreateDraftMessageTool(
                credentials=credentials,
                default_auth_mode='delegated',
                scopes=scopes
            ),
            SendEmailTool(
                credentials=credentials,
                default_auth_mode='delegated',
                scopes=scopes
            ),
            CreateEventTool(
                credentials=credentials,
                default_auth_mode='delegated',
                scopes=scopes
            )
        ]

        super().__init__(
            name="EmailManager",
            role="Email Management Specialist",
            goal="Efficiently manage, organize, and respond to emails",
            backstory=(
                "You are an expert email manager who helps users stay on top "
                "of their inbox. You can search for specific emails, create "
                "draft responses, and send messages on behalf of users."
            ),
            tools=self.o365_tools,
            **kwargs
        )

    async def find_and_summarize(self, query: str, max_results: int = 5):
        """
        Search for emails and provide a summary.

        Note: No need to pass auth_mode here - it uses the default from initialization.
        """
        search_tool = next(
            t for t in self.o365_tools
            if isinstance(t, SearchEmailTool)
        )

        # NO auth_mode parameter needed - uses default_auth_mode='delegated'
        result = await search_tool.run(
            query=query,
            max_results=max_results
            # auth_mode is automatically 'delegated' from initialization
        )

        if result.status == "success":
            messages = result.result['messages']
            summary = f"Found {len(messages)} emails:\n"
            for msg in messages:
                from_name = msg.get('from_name', msg.get('from', 'Unknown'))
                summary += f"- From {from_name}: {msg['subject']}\n"
            return summary
        else:
            return f"Error searching emails: {result.error}"

    async def draft_reply(self, to: str, subject: str, body: str):
        """
        Create a draft email.

        Note: No need to pass auth_mode here either.
        """
        draft_tool = next(
            t for t in self.o365_tools
            if isinstance(t, CreateDraftMessageTool)
        )

        # NO auth_mode parameter needed
        result = await draft_tool.run(
            subject=subject,
            body=body,
            to_recipients=[to]
            # auth_mode is automatically 'delegated' from initialization
        )

        if result.status == "success":
            return f"Draft created successfully: {result.result['id']}"
        else:
            return f"Error creating draft: {result.error}"

    async def send_email(self, to: list, subject: str, body: str, is_html: bool = False):
        """
        Send an email directly.

        Note: No need to pass auth_mode here either.
        """
        send_tool = next(
            t for t in self.o365_tools
            if isinstance(t, SendEmailTool)
        )

        # NO auth_mode parameter needed
        result = await send_tool.run(
            subject=subject,
            body=body,
            to_recipients=to,
            is_html=is_html
        )

        if result.status == "success":
            return f"Email sent successfully to {to}"
        else:
            return f"Error sending email: {result.error}"


async def example_specialized_agent():
    """Example using a specialized email management agent."""

    credentials = {
        'client_id': O365_CLIENT_ID,
        'tenant_id': O365_TENANT_ID,
        # 'client_secret': O365_CLIENT_SECRET,
        'user_id': 'jlara@trocglobal.com'
    }

    # Create the specialized agent
    email_agent = EmailManagerAgent(
        credentials=credentials,
        scopes=[
            "User.Read",
            "Mail.Read",
            "Mail.ReadWrite",
            "Mail.Send",
            "Calendars.ReadWrite"
        ]
    )

    await email_agent.configure()

    try:
        # First call: Will trigger interactive login if not cached
        print("Searching for important emails...")
        summary = await email_agent.find_and_summarize("important", max_results=5)
        print(summary)
        print()

        # Second call: Will use cached session - NO INTERACTIVE LOGIN PROMPT
        print("Searching for meetings...")
        summary = await email_agent.find_and_summarize("meetings", max_results=3)
        print(summary)
        print()

        # Third call: Create a draft - STILL using cached session
        print("Creating draft email...")
        result = await email_agent.draft_reply(
            to="colleague@company.com",
            subject="Re: Project Update",
            body="Thanks for the update. I'll review and get back to you."
        )
        print(result)

    finally:
        # Cleanup
        for tool in email_agent.o365_tools:
            await tool.cleanup()


# ============================================================================
# EXAMPLE 7: Calendar Management Agent
# ============================================================================

class CalendarManagerAgent(BasicAgent):
    """Specialized agent for calendar management."""

    def __init__(self, credentials: dict, **kwargs):
        self.event_tool = CreateEventTool(credentials=credentials)

        super().__init__(
            name="CalendarManager",
            role="Calendar and Scheduling Specialist",
            goal="Help users manage their calendar and schedule meetings efficiently",
            backstory=(
                "You are an expert at calendar management and scheduling. "
                "You can create events, schedule meetings with attendees, "
                "and set up online meetings."
            ),
            tools=[self.event_tool],
            **kwargs
        )

    async def schedule_meeting(
        self,
        title: str,
        attendees: List[str],
        start_time: str,
        duration_hours: float = 1,
        online: bool = True
    ):
        """Schedule a meeting with standard duration."""
        from datetime import datetime, timedelta

        # Parse start time and calculate end time
        start_dt = datetime.fromisoformat(start_time)
        end_dt = start_dt + timedelta(hours=duration_hours)

        result = await self.event_tool.run(
            subject=title,
            start_datetime=start_dt.isoformat(),
            end_datetime=end_dt.isoformat(),
            attendees=attendees,
            is_online_meeting=online
        )

        return result


async def example_calendar_agent():
    """Example using calendar management agent."""

    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID
    }

    calendar_agent = CalendarManagerAgent(credentials=credentials)

    # Schedule a meeting programmatically
    result = await calendar_agent.schedule_meeting(
        title="Sprint Planning",
        attendees=["dev1@company.com", "dev2@company.com"],
        start_time="2025-01-20T10:00:00",
        duration_hours=2,
        online=True
    )
    print(f"Meeting scheduled: {result.result['join_url']}")

    # Or use natural language
    response = await calendar_agent.chat(
        "Schedule a 30-minute standup meeting with the development team "
        "every day at 9 AM next week, make them all online meetings"
    )
    print(response)


# ============================================================================
# EXAMPLE 8: Multi-Agent Orchestration
# ============================================================================

async def example_orchestrated_agents():
    """Example of using multiple specialized agents together."""
    from parrot.bots.orchestration.agent import OrchestratorAgent

    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID
    }

    # Create specialized agents
    email_agent = EmailManagerAgent(credentials=credentials)
    calendar_agent = CalendarManagerAgent(credentials=credentials)

    # Create orchestrator
    orchestrator = OrchestratorAgent(
        name="Office365Orchestrator",
        role="Office365 Services Coordinator",
        goal="Coordinate email and calendar management efficiently"
    )

    # Register specialists as tools
    email_agent.register_as_tool(
        orchestrator,
        tool_description="Manages emails: search, draft, and send messages"
    )

    calendar_agent.register_as_tool(
        orchestrator,
        tool_description="Manages calendar: create events and schedule meetings"
    )

    # Now the orchestrator can delegate to specialists
    response = await orchestrator.chat(
        "Search for all emails about the Q1 planning meeting, "
        "then schedule a follow-up meeting with all participants "
        "for next Tuesday at 2 PM"
    )
    print(response)


# ============================================================================
# EXAMPLE 9: Error Handling and Retry Logic
# ============================================================================

async def example_error_handling():
    """Example showing proper error handling."""

    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID
    }

    send_tool = SendEmailTool(credentials=credentials)

    try:
        result = await send_tool.run(
            subject="Test Email",
            body="This is a test",
            to_recipients=["invalid-email"]  # Invalid email
        )

        if result.status == "error":
            print(f"Error: {result.error}")
            print(f"Metadata: {result.metadata}")
        else:
            print(f"Success: {result.result}")

    except Exception as e:
        print(f"Exception occurred: {e}")


# ============================================================================
# EXAMPLE 10: Batch Operations
# ============================================================================

async def example_batch_operations():
    """Example of performing batch operations."""

    credentials = {
        'client_id': O365_CLIENT_ID,
        'client_secret': O365_CLIENT_SECRET,
        'tenant_id': O365_TENANT_ID
    }

    send_tool = SendEmailTool(credentials=credentials)

    # Send multiple emails
    recipients = [
        "user1@company.com",
        "user2@company.com",
        "user3@company.com"
    ]

    results = []
    for recipient in recipients:
        result = await send_tool.run(
            subject="Important Announcement",
            body="Please read the attached policy document.",
            to_recipients=[recipient]
        )
        results.append(result)

    # Summary
    successful = sum(1 for r in results if r.status == "success")
    print(f"Sent {successful}/{len(recipients)} emails successfully")


# ============================================================================
# Main function to run examples
# ============================================================================

async def main():
    """Run the examples."""
    print("=" * 60)
    print("Office365 Tools Examples")
    print("=" * 60)

    # Choose which example to run
    # await example_direct_usage()
    # await example_agent_integration()
    # await example_manual_registration()
    # await example_obo_auth()
    # await example_delegated_auth()
    await example_specialized_agent()
    # await example_calendar_agent()
    # await example_orchestrated_agents()
    # await example_error_handling()
    # await example_batch_operations()

    print("\nExamples completed!")


if __name__ == "__main__":
    asyncio.run(main())
