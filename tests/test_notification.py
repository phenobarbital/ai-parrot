"""
Test Suite for NotificationTool

Demonstrates testing strategies for the notification tool.
"""
import pytest
import asyncio
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from parrot.tools.notification import NotificationTool, NotificationType, FileType


class TestNotificationTool:
    """Test suite for NotificationTool."""

    @pytest.fixture
    def tool(self):
        """Create a NotificationTool instance for testing."""
        return NotificationTool()

    @pytest.fixture
    def sample_files(self, tmp_path):
        """Create sample files for testing."""
        files = {
            'image': tmp_path / "chart.png",
            'document': tmp_path / "report.pdf",
            'video': tmp_path / "demo.mp4",
            'audio': tmp_path / "podcast.mp3"
        }

        for file in files.values():
            file.write_bytes(b"test content")

        return files

    # =========================================================================
    # File Classification Tests
    # =========================================================================

    def test_classify_file_image(self, tool, sample_files):
        """Test image file classification."""
        result = tool._classify_file(sample_files['image'])
        assert result == FileType.IMAGE

    def test_classify_file_document(self, tool, sample_files):
        """Test document file classification."""
        result = tool._classify_file(sample_files['document'])
        assert result == FileType.DOCUMENT

    def test_classify_file_video(self, tool, sample_files):
        """Test video file classification."""
        result = tool._classify_file(sample_files['video'])
        assert result == FileType.VIDEO

    def test_classify_file_audio(self, tool, sample_files):
        """Test audio file classification."""
        result = tool._classify_file(sample_files['audio'])
        assert result == FileType.AUDIO

    def test_classify_nonexistent_file(self, tool):
        """Test classification of non-existent file."""
        result = tool._classify_file(Path("/nonexistent/file.png"))
        assert result == FileType.UNKNOWN

    def test_categorize_files(self, tool, sample_files):
        """Test file categorization."""
        files = list(sample_files.values())
        categorized = tool._categorize_files(files)

        assert len(categorized[FileType.IMAGE]) == 1
        assert len(categorized[FileType.DOCUMENT]) == 1
        assert len(categorized[FileType.VIDEO]) == 1
        assert len(categorized[FileType.AUDIO]) == 1

    # =========================================================================
    # Recipient Parsing Tests
    # =========================================================================

    def test_parse_email_single(self, tool):
        """Test parsing single email recipient."""
        result = tool._parse_recipients(
            "user@example.com",
            NotificationType.EMAIL
        )
        assert result.account["address"] == "user@example.com"

    def test_parse_email_multiple(self, tool):
        """Test parsing multiple email recipients."""
        result = tool._parse_recipients(
            "user1@example.com,user2@example.com",
            NotificationType.EMAIL
        )
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].account["address"] == "user1@example.com"

    def test_parse_telegram_chat_id(self, tool):
        """Test parsing Telegram chat ID."""
        result = tool._parse_recipients(
            "123456789",
            NotificationType.TELEGRAM
        )
        assert result.chat_id == "123456789"

    def test_parse_slack_channel(self, tool):
        """Test parsing Slack channel."""
        result = tool._parse_recipients(
            "#engineering",
            NotificationType.SLACK
        )
        assert result.channel_name == "engineering"

    # =========================================================================
    # File Parsing Tests
    # =========================================================================

    def test_parse_files_single(self, tool, sample_files):
        """Test parsing single file path."""
        file_path = str(sample_files['image'])
        result = tool._parse_files(file_path)

        assert len(result) == 1
        assert result[0] == sample_files['image']

    def test_parse_files_multiple(self, tool, sample_files):
        """Test parsing multiple file paths."""
        file_paths = ",".join([
            str(sample_files['image']),
            str(sample_files['document'])
        ])
        result = tool._parse_files(file_paths)

        assert len(result) == 2

    def test_parse_files_nonexistent(self, tool):
        """Test parsing with non-existent files."""
        result = tool._parse_files("/nonexistent/file.pdf,/another/missing.png")
        assert len(result) == 0

    def test_parse_files_empty(self, tool):
        """Test parsing empty file string."""
        result = tool._parse_files("")
        assert len(result) == 0

    # =========================================================================
    # Email Sending Tests (Mocked)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_send_email(self, tool, sample_files):
        """Test email sending with mock."""
        with patch('notification_tool.Email') as MockEmail:
            mock_conn = AsyncMock()
            MockEmail.return_value.__aenter__.return_value = mock_conn
            mock_conn.send = AsyncMock(return_value={"status": "sent"})

            result = await tool._execute(
                message="Test message",
                type="email",
                recipients="test@example.com",
                subject="Test",
                files=str(sample_files['document'])
            )

            assert "✅" in result
            assert "email" in result

    # =========================================================================
    # Telegram Sending Tests (Mocked)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_send_telegram_text(self, tool):
        """Test Telegram text message."""
        with patch('notification_tool.Telegram') as MockTelegram:
            mock_conn = AsyncMock()
            MockTelegram.return_value.__aenter__.return_value = mock_conn
            mock_conn.send = AsyncMock(return_value={"status": "sent"})

            result = await tool._execute(
                message="Test message",
                type="telegram",
                recipients="123456789"
            )

            assert "✅" in result

    @pytest.mark.asyncio
    async def test_send_telegram_with_image(self, tool, sample_files):
        """Test Telegram with image (sent as photo)."""
        with patch('notification_tool.Telegram') as MockTelegram:
            mock_conn = AsyncMock()
            MockTelegram.return_value.__aenter__.return_value = mock_conn
            mock_conn.send_photo = AsyncMock(return_value={"status": "sent"})

            result = await tool._execute(
                message="Check this",
                type="telegram",
                recipients="123456789",
                files=str(sample_files['image'])
            )

            assert "✅" in result
            assert "1" in result  # 1 file

    # =========================================================================
    # Slack Sending Tests (Mocked)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_send_slack(self, tool):
        """Test Slack message sending."""
        with patch('notification_tool.Slack') as MockSlack:
            mock_conn = AsyncMock()
            MockSlack.return_value.__aenter__.return_value = mock_conn
            mock_conn.send = AsyncMock(return_value={"status": "sent"})

            result = await tool._execute(
                message="Deployment complete",
                type="slack",
                recipients="C123456"
            )

            assert "✅" in result

    # =========================================================================
    # Teams Sending Tests (Mocked)
    # =========================================================================

    @pytest.mark.asyncio
    async def test_send_teams(self, tool):
        """Test Teams message sending."""
        with patch('notification_tool.Teams') as MockTeams:
            mock_conn = AsyncMock()
            MockTeams.return_value.__aenter__.return_value = mock_conn
            mock_conn.send = AsyncMock(return_value={"status": "sent"})

            result = await tool._execute(
                message="Meeting reminder",
                type="teams",
                recipients="team@company.com"
            )

            assert "✅" in result

    # =========================================================================
    # Error Handling Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_invalid_notification_type(self, tool):
        """Test handling of invalid notification type."""
        result = await tool._execute(
            message="Test",
            type="invalid_type",
            recipients="test@example.com"
        )

        assert "❌" in result or "Failed" in result

    @pytest.mark.asyncio
    async def test_send_with_exception(self, tool):
        """Test error handling when provider raises exception."""
        with patch('notification_tool.Email') as MockEmail:
            MockEmail.return_value.__aenter__.side_effect = Exception("Connection failed")

            result = await tool._execute(
                message="Test",
                type="email",
                recipients="test@example.com"
            )

            assert "❌" in result
            assert "Failed" in result

    # =========================================================================
    # Integration Tests (Require Real Credentials)
    # =========================================================================

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_email_send(self, tool):
        """Integration test for real email sending."""
        # Skip if credentials not available
        pytest.skip("Requires real email credentials")

        result = await tool._execute(
            message="Test message from integration test",
            type="email",
            recipients="test@example.com",
            subject="Integration Test"
        )

        assert "✅" in result

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_telegram_send(self, tool):
        """Integration test for real Telegram sending."""
        pytest.skip("Requires real Telegram credentials")

        result = await tool._execute(
            message="Test from integration",
            type="telegram",
            recipients="YOUR_CHAT_ID"
        )

        assert "✅" in result


# =============================================================================
# Fixture for Agent Integration Tests
# =============================================================================

@pytest.fixture
def mock_agent():
    """Create a mock agent for testing tool integration."""
    from parrot.bots.agent import Agent
    from parrot.clients.gpt import OpenAIClient

    agent = Agent(
        name="TestAgent",
        llm=OpenAIClient(model="gpt-4"),
        tools=[NotificationTool()]
    )
    return agent


class TestAgentIntegration:
    """Test NotificationTool integration with agents."""

    @pytest.mark.asyncio
    async def test_agent_has_notification_tool(self, mock_agent):
        """Test that agent has notification tool registered."""
        tool_names = [tool.name for tool in mock_agent.tools]
        assert "send_notification" in tool_names

    @pytest.mark.asyncio
    async def test_agent_can_invoke_tool(self, mock_agent):
        """Test that agent can invoke notification tool."""
        # This would require mocking LLM responses
        # Simplified test checking tool availability
        notification_tool = next(
            tool for tool in mock_agent.tools
            if tool.name == "send_notification"
        )
        assert notification_tool is not None


# =============================================================================
# Performance Tests
# =============================================================================

class TestPerformance:
    """Performance tests for NotificationTool."""

    @pytest.mark.asyncio
    async def test_file_categorization_performance(self, tool, tmp_path):
        """Test performance of file categorization with many files."""
        # Create 100 test files
        files = []
        for i in range(100):
            file = tmp_path / f"file_{i}.png"
            file.write_bytes(b"test")
            files.append(file)

        import time
        start = time.time()
        result = tool._categorize_files(files)
        elapsed = time.time() - start

        assert elapsed < 1.0  # Should complete in under 1 second
        assert len(result[FileType.IMAGE]) == 100


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "--tb=short"])
