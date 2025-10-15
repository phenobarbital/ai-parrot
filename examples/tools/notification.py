"""
NotificationTool - Usage Examples and Integration Guide

This document shows how to integrate and use NotificationTool in AI-parrot agents.
"""
import asyncio
from pathlib import Path
from parrot.bots.agent import BasicAgent, Agent
from parrot.clients import OpenAIClient
from parrot.tools.notification import NotificationTool


# =============================================================================
# Example 1: Basic Agent Integration
# =============================================================================

async def example_basic_integration():
    """Show basic integration of NotificationTool with an agent."""

    # Create notification tool
    notification_tool = NotificationTool()

    # Create agent with notification capability
    agent = Agent(
        name="ReportAgent",
        role="Data Analyst",
        goal="Generate and deliver reports to stakeholders",
        llm=OpenAIClient(model="gpt-4"),
        tools=[notification_tool]  # Add to agent's tools
    )

    # Agent can now use the notification tool
    response = await agent.ask(
        "Generate a sales report and email it to manager@company.com with subject 'Q4 Sales Report'"
    )

    print(response.output)


# =============================================================================
# Example 2: Direct Tool Usage (without LLM)
# =============================================================================

async def example_direct_usage():
    """Direct usage of the notification tool."""

    tool = NotificationTool()

    # Send email
    result = await tool._execute(
        message="Your daily report is ready!",
        type="email",
        recipients="user@example.com",
        subject="Daily Report - Oct 15",
        files="/path/to/report.pdf"
    )
    print(result)

    # Send to Telegram with image
    result = await tool._execute(
        message="Check out this chart",
        type="telegram",
        recipients="123456789",  # Your Telegram chat_id
        files="/path/to/chart.png,/path/to/data.csv"
    )
    print(result)

    # Send to Slack
    result = await tool._execute(
        message="Deployment completed successfully! ✅",
        type="slack",
        recipients="C123456"  # Slack channel ID
    )
    print(result)


# =============================================================================
# Example 3: Custom Agent with Notification Workflow
# =============================================================================

class ReportingAgent(Agent):
    """Agent specialized in generating and delivering reports."""

    def __init__(self, **kwargs):
        # Initialize with notification tool
        notification_tool = NotificationTool(
            teams_config={
                "tenant_id": "your-tenant-id",
                "client_id": "your-client-id",
                "client_secret": "your-secret",
                "username": "bot@company.com",
                "password": "password"
            }
        )

        # Add notification to tools
        tools = kwargs.pop('tools', [])
        tools.append(notification_tool)

        super().__init__(
            name="ReportingAgent",
            role="Report Generator and Distributor",
            goal="Create insightful reports and deliver them to stakeholders",
            tools=tools,
            **kwargs
        )

    async def generate_and_send_report(
        self,
        report_type: str,
        recipients: str,
        notification_type: str = "email"
    ):
        """High-level method to generate and send reports."""

        # Generate report (this would use other tools)
        prompt = (
            f"Generate a {report_type} report. "
            f"Then send it to {recipients} via {notification_type}."
        )

        response = await self.chat(prompt)
        return response


# =============================================================================
# Example 4: Multi-Channel Notification Strategy
# =============================================================================

async def example_multi_channel():
    """Send same notification through multiple channels."""

    tool = NotificationTool()

    message = "🚀 New feature deployed successfully!"
    report_file = "/path/to/deployment-report.pdf"

    # Send to email
    await tool._execute(
        message=message,
        type="email",
        recipients="team@company.com,manager@company.com",
        subject="Deployment Notification",
        files=report_file
    )

    # Send to Slack
    await tool._execute(
        message=message,
        type="slack",
        recipients="deployments"
    )

    # Send to Telegram
    await tool._execute(
        message=message,
        type="telegram",
        recipients="123456789",
        files=report_file
    )


# =============================================================================
# Example 5: LLM-Driven Smart Notifications
# =============================================================================

async def example_smart_notifications():
    """Let LLM decide when and how to send notifications."""

    tool = NotificationTool()

    agent = Agent(
        name="MonitoringAgent",
        role="System Monitor",
        goal="Monitor systems and notify stakeholders of important events",
        llm=OpenAIClient(model="gpt-4"),
        tools=[tool]
    )

    # Agent autonomously decides notification details
    await agent.ask(
        "The server CPU usage just hit 95%. Analyze the situation and "
        "send appropriate notifications to the ops team via Slack and "
        "emergency contacts via email."
    )


# =============================================================================
# Example 6: Telegram Smart File Handling
# =============================================================================

async def example_telegram_smart_files():
    """Demonstrate Telegram's smart file handling."""

    tool = NotificationTool()

    # Images sent as photos
    await tool._execute(
        message="Monthly performance dashboard",
        type="telegram",
        recipients="123456789",
        files="/reports/dashboard.png,/reports/chart1.jpg,/reports/chart2.png"
    )

    # Documents sent as files
    await tool._execute(
        message="Quarterly financial statements",
        type="telegram",
        recipients="123456789",
        files="/reports/q4-2024.pdf,/reports/summary.xlsx"
    )

    # Mixed media
    await tool._execute(
        message="Project update with visuals and data",
        type="telegram",
        recipients="123456789",
        files="/project/cover.png,/project/report.pdf,/project/demo.mp4"
    )


# =============================================================================
# Example 7: Tool Manager Registration
# =============================================================================

def example_tool_manager():
    """Register notification tool in tool manager for shared access."""

    from parrot.tools.manager import ToolManager

    # Create tool manager
    tool_manager = ToolManager()

    # Register notification tool
    notification_tool = NotificationTool()
    tool_manager.add_tool(notification_tool)

    # Now multiple agents can share the same tool
    agent1 = Agent(
        name="DataAgent",
        tool_manager=tool_manager  # Shares tools
    )

    agent2 = Agent(
        name="ReportAgent",
        tool_manager=tool_manager  # Shares tools
    )

    # Both agents can now use send_notification


# =============================================================================
# Example 8: Error Handling and Fallback
# =============================================================================

async def example_error_handling():
    """Demonstrate error handling in notifications."""

    tool = NotificationTool()

    # Primary: Try Telegram
    result = await tool._execute(
        message="Important update",
        type="telegram",
        recipients="123456789"
    )

    # Check result and fallback to email if needed
    if "Failed" in result or "❌" in result:
        print("Telegram failed, falling back to email...")
        result = await tool._execute(
            message="Important update (via fallback)",
            type="email",
            recipients="fallback@company.com",
            subject="Urgent: Notification Delivery Issue"
        )

    print(result)


# =============================================================================
# Example 9: Scheduled Notifications with Agent
# =============================================================================

async def example_scheduled_notifications():
    """Use agent for scheduled reporting."""

    import schedule
    import time

    tool = NotificationTool()
    agent = Agent(
        name="ScheduledReporter",
        tools=[tool],
        llm=OpenAIClient()
    )

    async def daily_report():
        """Generate and send daily report."""
        await agent.chat(
            "Generate today's metrics summary and email it to "
            "team@company.com with subject 'Daily Metrics - {date}'"
        )

    # Schedule (pseudo-code)
    # schedule.every().day.at("09:00").do(lambda: asyncio.run(daily_report()))


# =============================================================================
# Example 10: Integration with Other Tools
# =============================================================================

async def example_tool_composition():
    """Compose notification tool with other tools."""

    from parrot.tools import PythonREPLTool  # Hypothetical

    notification_tool = NotificationTool()
    python_tool = PythonREPLTool()

    agent = Agent(
        name="AnalyticsAgent",
        tools=[python_tool, notification_tool],
        llm=OpenAIClient()
    )

    # Agent can analyze data AND send results
    await agent.chat(
        "Analyze the sales data in sales.csv, create a visualization, "
        "and send the chart to sales-team@company.com via email with "
        "a summary of key insights."
    )


# =============================================================================
# Configuration Examples
# =============================================================================

# Environment variable configuration (recommended)
"""
# .env file
NOTIFICATION_EMAIL_FROM=noreply@company.com
NOTIFICATION_SLACK_TOKEN=xoxb-your-token
NOTIFICATION_TELEGRAM_TOKEN=bot_token
NOTIFICATION_TEAMS_TENANT_ID=tenant-id
NOTIFICATION_TEAMS_CLIENT_ID=client-id
NOTIFICATION_TEAMS_CLIENT_SECRET=secret
"""

# Programmatic configuration
TEAMS_CONFIG = {
    "tenant_id": "your-tenant-id",
    "client_id": "your-client-id",
    "client_secret": "your-secret",
    "username": "bot@company.com",
    "password": "password"
}

notification_tool = NotificationTool(teams_config=TEAMS_CONFIG)


# =============================================================================
# LLM Prompt Examples
# =============================================================================

LLM_PROMPT_EXAMPLES = """
User prompts that will trigger NotificationTool:

1. "Send an email to john@company.com with the report"
2. "Notify the team on Slack channel #engineering about the deployment"
3. "Send me the results via Telegram"
4. "Email the analysis to stakeholders@company.com with subject 'Q4 Analysis'"
5. "Ping the ops team on Slack that the server is back online"
6. "Send this chart to my Telegram"
7. "Notify manager@company.com about the completed task"

The LLM will recognize these patterns and invoke send_notification tool with
appropriate parameters.
"""


if __name__ == "__main__":
    # Run examples
    asyncio.run(example_basic_integration())
    asyncio.run(example_direct_usage())
    asyncio.run(example_multi_channel())
