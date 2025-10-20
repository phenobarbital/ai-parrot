"""
Complete example demonstrating all features of the MS Teams Toolkit.

This script shows:
1. Basic setup and connection
2. Sending messages to channels
3. Creating and sending Adaptive Cards
4. Sending direct messages
5. Using with AI agents
6. Error handling
"""
from typing import Dict, Any
from datetime import datetime, timedelta, timezone
import traceback
import asyncio
import os
from navconfig import config
from parrot.bots.agent import BasicAgent
from parrot.tools.msteams import MSTeamsToolkit, create_msteams_toolkit
from parrot.conf import (
    MS_TEAMS_TENANT_ID,
    MS_TEAMS_CLIENT_ID,
    MS_TEAMS_CLIENT_SECRET,
    MS_TEAMS_USERNAME,
    MS_TEAMS_PASSWORD,
    MS_TEAMS_DEFAULT_TEAMS_ID,
    MS_TEAMS_DEFAULT_CHANNEL_ID
)


# ============================================================================
# Configuration
# ============================================================================

# Option 1: Use environment variables
TENANT_ID = os.getenv("MS_TEAMS_TENANT_ID", MS_TEAMS_TENANT_ID)
CLIENT_ID = os.getenv("MS_TEAMS_CLIENT_ID", MS_TEAMS_CLIENT_ID)
CLIENT_SECRET = os.getenv("MS_TEAMS_CLIENT_SECRET", MS_TEAMS_CLIENT_SECRET)

# For testing, replace these with actual IDs from your Teams environment
TEST_TEAM_ID = config.get('MS_TEAMS_DEFAULT_TEAMS_ID')
TEST_CHANNEL_ID = config.get('MS_TEAMS_DEFAULT_CHANNEL_ID')
TEST_RECIPIENT_EMAIL = "jlara@trocglobal.com"


# ============================================================================
# Example 1: Basic Setup and Connection
# ============================================================================

async def example_basic_setup():
    """Demonstrate basic toolkit setup and connection."""
    print("\n=== Example 1: Basic Setup ===")

    # Create toolkit instance
    toolkit = MSTeamsToolkit(
        tenant_id=TENANT_ID,
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        as_user=True,
        username=MS_TEAMS_USERNAME,
        password=MS_TEAMS_PASSWORD
    )

    try:
        print("✓ Successfully connected to Microsoft Teams")
        # List available tools
        tools = toolkit.get_tools()
        print(f"✓ Available tools: {len(tools)}")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description.split('.')[0]}")

        return toolkit

    except Exception as e:
        print(f"✗ Connection failed: {e}")
        raise


# ============================================================================
# Example 2: Sending Messages to Channels
# ============================================================================

async def example_send_to_channel(toolkit: MSTeamsToolkit):
    """Demonstrate sending messages to a Teams channel."""
    print("\n=== Example 2: Send to Channel ===")

    try:
        # Simple text message
        result = await toolkit.send_message_to_channel(
            team_id=TEST_TEAM_ID,
            channel_id=TEST_CHANNEL_ID,
            message="Hello from AI-Parrot toolkit! 🦜"
        )
        print("✓ Message sent successfully")
        print(f"  Message ID: {result['id']}")
        print(f"  Created: {result['created_datetime']}")

    except Exception as e:
        print(f"✗ Failed to send message: {e}")


# ============================================================================
# Example 3: Creating and Sending Adaptive Cards
# ============================================================================

async def example_adaptive_cards(toolkit: MSTeamsToolkit):
    """Demonstrate creating and sending Adaptive Cards."""
    print("\n=== Example 3: Adaptive Cards ===")

    try:
        # Create a simple adaptive card
        simple_card = await toolkit.create_adaptive_card(
            title="Daily Standup Reminder",
            body_text="Don't forget to share your updates in today's standup meeting!",
            link_url="https://teams.microsoft.com/meeting",
            link_text="Join Meeting"
        )
        print("✓ Created simple adaptive card")

        # Create a detailed card with facts and image
        detailed_card = await toolkit.create_adaptive_card(
            title="Weekly Sprint Report",
            body_text="Our team had an excellent week with significant progress on all fronts.",
            image_url="https://via.placeholder.com/400x200/4A90E2/FFFFFF?text=Sprint+Chart",
            link_url="https://example.com/sprint-board",
            link_text="View Sprint Board",
            facts=[
                {"title": "Stories Completed", "value": "15"},
                {"title": "Bugs Fixed", "value": "8"},
                {"title": "Code Reviews", "value": "23"},
                {"title": "Sprint Velocity", "value": "34 points"}
            ]
        )
        print("✓ Created detailed adaptive card with facts")

        # Send the detailed card to a channel
        result = await toolkit.send_message_to_channel(
            team_id=TEST_TEAM_ID,
            channel_id=TEST_CHANNEL_ID,
            message=detailed_card
        )
        print("✓ Adaptive card sent to channel")
        print(f"  Message ID: {result['id']}")

    except Exception as e:
        print(f"✗ Failed with adaptive cards: {e}")


# ============================================================================
# Example 4: Sending Direct Messages
# ============================================================================

async def example_direct_messages(toolkit: MSTeamsToolkit):
    """Demonstrate sending direct messages to users."""
    print("\n=== Example 4: Direct Messages ===")

    try:
        # Look up a user
        user = await toolkit.get_user(TEST_RECIPIENT_EMAIL)
        print(f"✓ Found user: {user['displayName']} ({user['mail']})")

        # Send a simple direct message
        result = await toolkit.send_direct_message(
            recipient_email=TEST_RECIPIENT_EMAIL,
            message="Hi! This is an automated message from the AI-Parrot toolkit."
        )
        print("✓ Direct message sent successfully")

        # Send an adaptive card as direct message
        reminder_card = await toolkit.create_adaptive_card(
            title="Task Reminder",
            body_text="You have 3 pending code reviews that need your attention.",
            link_url="https://example.com/code-reviews",
            link_text="View Code Reviews",
            facts=[
                {"title": "High Priority", "value": "1"},
                {"title": "Medium Priority", "value": "2"}
            ]
        )

        result = await toolkit.send_direct_message(
            recipient_email=TEST_RECIPIENT_EMAIL,
            message=reminder_card
        )
        print("✓ Adaptive card sent as direct message")

    except Exception as e:
        print(f"✗ Failed to send direct message: {e}")


# ============================================================================
# Example 5: Advanced - Custom Adaptive Card
# ============================================================================

async def example_custom_adaptive_card(toolkit: MSTeamsToolkit):
    """Demonstrate creating a custom Adaptive Card with advanced features."""
    print("\n=== Example 5: Custom Adaptive Card ===")

    try:
        # Create a custom card with multiple columns and input fields
        custom_card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": [
                {
                    "type": "TextBlock",
                    "text": "Deployment Status",
                    "weight": "Bolder",
                    "size": "Large",
                    "color": "Accent"
                },
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "auto",
                            "items": [
                                {
                                    "type": "Image",
                                    "url": "https://via.placeholder.com/50/00FF00/FFFFFF?text=✓",
                                    "size": "Small",
                                    "altText": "Success"
                                }
                            ]
                        },
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "Production deployment completed successfully",
                                    "wrap": True,
                                    "weight": "Bolder"
                                },
                                {
                                    "type": "TextBlock",
                                    "text": "Version 2.5.0 is now live",
                                    "wrap": True,
                                    "isSubtle": True,
                                    "spacing": "None"
                                }
                            ]
                        }
                    ]
                },
                {
                    "type": "FactSet",
                    "facts": [
                        {"title": "Environment:", "value": "Production"},
                        {"title": "Version:", "value": "2.5.0"},
                        {"title": "Deployed by:", "value": "CI/CD Pipeline"},
                        {"title": "Duration:", "value": "8 minutes 32 seconds"}
                    ]
                },
                {
                    "type": "TextBlock",
                    "text": "Deployment Metrics",
                    "weight": "Bolder",
                    "spacing": "Medium"
                },
                {
                    "type": "ColumnSet",
                    "columns": [
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "Tests Passed",
                                    "wrap": True
                                },
                                {
                                    "type": "TextBlock",
                                    "text": "**127/127**",
                                    "size": "Large",
                                    "color": "Good"
                                }
                            ]
                        },
                        {
                            "type": "Column",
                            "width": "stretch",
                            "items": [
                                {
                                    "type": "TextBlock",
                                    "text": "Coverage",
                                    "wrap": True
                                },
                                {
                                    "type": "TextBlock",
                                    "text": "**94.5%**",
                                    "size": "Large",
                                    "color": "Good"
                                }
                            ]
                        }
                    ]
                }
            ],
            "actions": [
                {
                    "type": "Action.OpenUrl",
                    "title": "View Details",
                    "url": "https://example.com/deployment/12345"
                },
                {
                    "type": "Action.OpenUrl",
                    "title": "View Logs",
                    "url": "https://example.com/logs/12345"
                }
            ]
        }

        # Send the custom card
        result = await toolkit.send_message_to_channel(
            team_id=TEST_TEAM_ID,
            channel_id=TEST_CHANNEL_ID,
            message=custom_card
        )
        print("✓ Custom adaptive card sent successfully")
        print(f"  Message ID: {result['id']}")

    except Exception as e:
        print(f"✗ Failed to send custom card: {e}")


# ============================================================================
# Example 6: Using with AI Agents (Conceptual)
# ============================================================================

async def example_with_agent():
    """Demonstrate how to use the toolkit with an AI agent."""
    print("\n=== Example 6: Integration with AI Agents ===")

    try:
        # This is a conceptual example showing how to integrate with agents
        # Uncomment and adapt if you have BasicAgent available

        # from parrot.bots.agent import BasicAgent

        toolkit = MSTeamsToolkit(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )

        # Get all tools from the toolkit
        tools = toolkit.get_tools()
        print(f"✓ Extracted {len(tools)} tools from toolkit:")
        for tool in tools:
            print(f"  - {tool.name}")

        # These tools can now be passed to an agent
        agent = BasicAgent(
            name="TeamsBot",
            role="Microsoft Teams Communication Manager",
            tools=tools,
            instructions=f"""
            You are a helpful assistant that can send messages to Microsoft Teams.
            You can send messages to channels, chats, and direct messages to users.
            Always use adaptive cards for important announcements.
            If No Team ID or Channel ID is provided, use the default ones.

            Default Team ID: {TEST_TEAM_ID}
            Default Channel ID: {TEST_CHANNEL_ID}
            """
        )

        await agent.configure()

        # The agent can now use all toolkit methods
        response = await agent.ask(
            "Send a sprint summary to the Navigator channel"
        )

        print(response.output)

        print("✓ Tools are ready for agent integration")

    except Exception as e:
        print(f"✗ Failed: {e}")


# ============================================================================
# Example 7: Error Handling
# ============================================================================

async def example_error_handling():
    """Demonstrate proper error handling."""
    print("\n=== Example 7: Error Handling ===")

    # Example 1: Invalid credentials
    try:
        toolkit = MSTeamsToolkit(
            tenant_id="invalid",
            client_id="invalid",
            client_secret="invalid"
        )

    except Exception as e:
        print(f"✓ Caught authentication error: {type(e).__name__}")

    # Example 2: Missing required fields
    try:
        toolkit = MSTeamsToolkit(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID
            # Missing client_secret
        )
    except ValueError as e:
        print(f"✓ Caught configuration error: {e}")

    # Example 3: Invalid team/channel ID
    try:
        toolkit = MSTeamsToolkit(
            tenant_id=TENANT_ID,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET
        )


        await toolkit.send_message_to_channel(
            team_id="invalid-team-id",
            channel_id="invalid-channel-id",
            message="Test"
        )
    except Exception as e:
        print(f"✓ Caught API error: {type(e).__name__}")

    print("✓ Error handling examples completed")

# ============================================================================
# Example 8: Message Extraction
# ============================================================================

async def example_message_extraction(toolkit):
    """Demonstrate message extraction from a channel."""
    print("\n=== Example 8: Message Extraction ===")
    # Extract messages from a channel
    messages = await toolkit.extract_channel_messages(
        team_id=TEST_TEAM_ID,
        channel_id=TEST_CHANNEL_ID,
        start_time="2025-01-01T00:00:00Z",
        end_time="2025-01-31T23:59:59Z",
        max_messages=100
    )

    print(f"✓ Extracted {len(messages)} messages from channel:")
    for msg in messages:
        print(f"  - {msg}")

    print("✓ Message extraction example completed")

async def example_team_channel_discovery(toolkit):
    """Demonstrate finding teams and channels by name."""
    print("\n" + "=" * 70)
    print("Example 1: Team and Channel Discovery")
    print("=" * 70)

    try:
        # Find a team by name
        print("\n1. Finding team by name...")
        team = await toolkit.find_team_by_name("Navigator")

        if team:
            print(f"✓ Found team: {team['displayName']}")
            print(f"  Team ID: {team['id']}")
            print(f"  Description: {team['description']}")

            # Find a channel within that team
            print("\n2. Finding channel by name...")
            channel = await toolkit.find_channel_by_name(
                team_id=team['id'],
                channel_name="Alerts"
            )

            if channel:
                print(f"✓ Found channel: {channel['displayName']}")
                print(f"  Channel ID: {channel['id']}")
                print(f"  Type: {channel['membershipType']}")
            else:
                print("✗ Channel not found")
        else:
            print("✗ Team not found")

    except Exception as e:
        print(f"✗ Error: {e}")

# ============================================================================
# Example 2: Channel Details and Members
# ============================================================================

async def example_channel_info(toolkit):
    """Demonstrate getting channel details and members."""
    print("\n" + "=" * 70)
    print("Example 2: Channel Details and Members")
    print("=" * 70)

    try:
        # First find the team and channel
        team = await toolkit.find_team_by_name("Navigator")
        if not team:
            print("✗ Team not found")
            return

        channel = await toolkit.find_channel_by_name(
            team_id=team['id'],
            channel_name="General"
        )
        if not channel:
            print("✗ Channel not found")
            return

        # Get detailed channel information
        print("\n1. Getting channel details...")
        details = await toolkit.get_channel_details(
            team_id=team['id'],
            channel_id=channel['id']
        )

        print("✓ Channel Details:")
        print(f"  Name: {details['displayName']}")
        print(f"  Email: {details['email']}")
        print(f"  Created: {details['createdDateTime']}")
        print(f"  Web URL: {details['webUrl']}")

        # Get channel members
        print("\n2. Getting channel members...")
        members = await toolkit.get_channel_members(
            team_id=team['id'],
            channel_id=channel['id']
        )

        print(f"✓ Found {len(members)} members:")
        for member in members[:5]:  # Show first 5
            print(f"  - {member['displayName']} ({member['email']})")
            print(f"    Roles: {member['roles']}")

    except Exception as e:
        print(f"✗ Error: {e}")


# ============================================================================
# Example 3: Extract Channel Messages
# ============================================================================

async def example_extract_channel_messages(toolkit):
    """Demonstrate extracting messages from a channel."""
    print("\n" + "=" * 70)
    print("Example 3: Extract Channel Messages")
    print("=" * 70)

    try:
        # Find team and channel
        team = await toolkit.find_team_by_name("Navigator")
        if not team:
            print("✗ Team not found")
            return

        channel = await toolkit.find_channel_by_name(
            team_id=team['id'],
            channel_name="General"
        )
        if not channel:
            print("✗ Channel not found")
            return

        # Extract messages from last 7 days
        print("\n1. Extracting messages from last 7 days...")
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(days=7)

        messages = await toolkit.extract_channel_messages(
            team_id=team['id'],
            channel_id=channel['id'],
            start_time=start_time.isoformat() + 'Z',
            end_time=end_time.isoformat() + 'Z',
            max_messages=50
        )

        print(f"✓ Found {len(messages)} messages")

        # Analyze messages
        if messages:
            print("\n2. Message analysis:")

            # Count unique senders
            senders = {
                msg['from']['displayName']
                for msg in messages
                if msg.get('from') and msg['from'].get('displayName')
            }
            print(f"  Unique participants: {len(senders)}")

            # Show most recent messages
            print("\n3. Recent messages (last 3):")
            for msg in messages[:3]:
                sender = msg['from']['displayName'] if msg.get('from') else "Unknown"
                content = msg['body']['content'][:100] if msg.get('body') else "No content"
                timestamp = msg.get('createdDateTime', 'Unknown time')
                print(f"\n  From: {sender}")
                print(f"  Time: {timestamp}")
                print(f"  Message: {content}...")

    except Exception as e:
        print(f"✗ Error: {e}")

# ============================================================================
# Main Function
# ============================================================================

async def main():
    """Run all examples."""
    print("=" * 70)
    print("MS Teams Toolkit - Complete Examples")
    print("=" * 70)

    # Check if configuration is set
    if TENANT_ID == "your-tenant-id":
        print("\n⚠️  WARNING: Please configure your Azure AD credentials")
        print("Set the following environment variables:")
        print("  - MS_TEAMS_TENANT_ID")
        print("  - MS_TEAMS_CLIENT_ID")
        print("  - MS_TEAMS_CLIENT_SECRET")
        print("\nOr modify the configuration section in this script.")
        return

    try:
        # Example 1: Basic setup
        toolkit = await example_basic_setup()

        # # Example 2: Send to channel
        # await example_send_to_channel(toolkit)

        # # Example 3: Adaptive cards
        # await example_adaptive_cards(toolkit)

        # # Example 4: Direct messages
        await example_direct_messages(toolkit)

        # # Example 5: Custom adaptive card
        # await example_custom_adaptive_card(toolkit)

        # Example 6: Agent integration
        # await example_with_agent()

        # # Example 7: Error handling
        # await example_error_handling()

        # Example 8: Message extraction
        # await example_message_extraction(toolkit)

        # Example 9: Team and Channel Discovery
        # await example_team_channel_discovery(toolkit)

        # Example 10: Channel Details and Members
        await example_channel_info(toolkit)

        # Example 11: Extract Channel Messages
        await example_extract_channel_messages(toolkit)

        print("\n" + "=" * 70)
        print("All examples completed successfully!")
        print("=" * 70)

    except KeyboardInterrupt:
        print("\n\nExecution interrupted by user")
    except Exception as e:
        print(f"\n\nUnexpected error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    """
    Run the examples.

    Usage:
        python examples.py

    Or with environment variables:
        MS_TEAMS_TENANT_ID=xxx MS_TEAMS_CLIENT_ID=yyy MS_TEAMS_CLIENT_SECRET=zzz python examples.py
    """
    asyncio.run(main())
