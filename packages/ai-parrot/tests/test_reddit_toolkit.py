"""
Tests for RedditToolkit.

These tests verify:
1. RedditToolkit inherits from AbstractToolkit
2. Toolkit structure and initialization
3. reddit_extract_subreddit_posts method with mocked PRAW
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

# Import the toolkit
from parrot.tools.reddit import RedditToolkit, SubredditSearchInput

class TestRedditToolkitStructure:
    """Test the toolkit structure."""

    def test_toolkit_inherits_from_abstract_toolkit(self):
        """Verify RedditToolkit inherits from AbstractToolkit."""
        from parrot.tools.toolkit import AbstractToolkit
        toolkit = RedditToolkit()
        assert isinstance(toolkit, AbstractToolkit)

    def test_toolkit_initialization(self):
        """Verify toolkit initializes with correct defaults and overrides."""
        # Test with kwargs
        toolkit = RedditToolkit(
            client_id="test_id",
            client_secret="test_secret",
            user_agent="test_agent",
            username="test_user",
            password="test_password"
        )
        assert toolkit.client_id == "test_id"
        assert toolkit.client_secret == "test_secret"
        assert toolkit.user_agent == "test_agent"
        assert toolkit.username == "test_user"
        assert toolkit.password == "test_password"

        # Test with env vars (mocked)
        with patch.dict('os.environ', {
            'REDDIT_CLIENT_ID': 'env_id',
            'REDDIT_CLIENT_SECRET': 'env_secret'
        }):
            toolkit_env = RedditToolkit(client_id=None, client_secret=None)
            assert toolkit_env.client_id == 'env_id'
            assert toolkit_env.client_secret == 'env_secret'

    @pytest.mark.asyncio
    async def test_get_tools(self):
        """Verify get_tools returns the expected tool."""
        toolkit = RedditToolkit()
        tools = toolkit.get_tools()
        tool_names = [t.name for t in tools]
        assert "reddit_extract_subreddit_posts" in tool_names
        
        # Verify schema generation
        tool = toolkit.get_tool("reddit_extract_subreddit_posts")
        assert tool is not None
        # Check that arguments are correctly detected (e.g. subreddit_name)
        assert "subreddit_name" in tool.args_schema.model_fields


class TestRedditExtraction:
    """Test the reddit_extract_subreddit_posts method."""

    @pytest.fixture
    def mock_praw(self):
        """Mock PRAW Reddit instance."""
        with patch('parrot.tools.reddit.praw') as mock_praw_module, \
             patch('parrot.tools.reddit.PRAW_AVAILABLE', True):
            # Mock the Reddit class
            mock_reddit_instance = MagicMock()
            mock_praw_module.Reddit.return_value = mock_reddit_instance
            yield mock_praw_module, mock_reddit_instance

    @pytest.mark.asyncio
    async def test_extract_posts_success(self, mock_praw):
        """Test successful extraction of posts and comments."""
        mock_praw_mod, mock_reddit = mock_praw
        
        # Setup mock subreddit
        mock_subreddit = MagicMock()
        mock_reddit.subreddit.return_value = mock_subreddit
        
        # Setup mock submission
        mock_submission = MagicMock()
        mock_submission.id = "123"
        mock_submission.title = "Test Post"
        mock_submission.selftext = "Content"
        mock_submission.url = "http://reddit.com/123"
        mock_submission.permalink = "/r/test/comments/123"
        mock_submission.created_utc = 1600000000.0
        mock_submission.author = MagicMock()
        mock_submission.author.name = "test_user"
        mock_submission.score = 10
        mock_submission.num_comments = 5
        mock_submission.is_self = True
        
        # Setup mock comments
        mock_comment = MagicMock()
        mock_comment.id = "c1"
        mock_comment.body = "Test Comment"
        mock_comment.permalink = "/r/test/comments/123/c1"
        mock_comment.created_utc = 1600000100.0
        mock_comment.author = MagicMock()
        mock_comment.author.name = "comment_user"
        mock_comment.score = 2
        mock_comment.parent_id = "t3_123"
        
        # Configure search return
        mock_subreddit.search.return_value = [mock_submission]
        
        # Configure comments
        mock_submission.comments = MagicMock()
        mock_submission.comments.__iter__.return_value = [mock_comment]
        
        # Initialize toolkit
        toolkit = RedditToolkit(client_id="dummy", client_secret="dummy")
        
        # Execute
        result = await toolkit.reddit_extract_subreddit_posts(
            subreddit_name="test_sub",
            query="test query",
            limit=1
        )
        
        # Verify
        assert result.status == "success"
        items = result.result
        assert len(items) == 2  # 1 submission + 1 comment
        
        # Check submission record
        sub_rec = items[0]
        assert sub_rec["record_type"] == "submission"
        assert sub_rec["title"] == "Test Post"
        assert sub_rec["author"] == "test_user"
        
        # Check comment record
        com_rec = items[1]
        assert com_rec["record_type"] == "comment"
        assert com_rec["comment_body"] == "Test Comment"
        assert com_rec["submission_id"] == "123"
        
        # Verify PRAW calls
        mock_reddit.subreddit.assert_called_with("test_sub")
        mock_subreddit.search.assert_called_once()
        mock_submission.comments.replace_more.assert_called_with(limit=0)

    @pytest.mark.asyncio
    async def test_extract_posts_no_praw(self):
        """Test graceful handling when PRAW is missing (simulated)."""
        with patch('parrot.tools.reddit.PRAW_AVAILABLE', False):
            toolkit = RedditToolkit()
            result = await toolkit.reddit_extract_subreddit_posts(
                subreddit_name="test",
                query="test"
            )
            assert result.status == "error"
            assert "not installed" in result.error

    @pytest.mark.asyncio
    async def test_extract_posts_forbidden(self, mock_praw):
        """Test handling of Forbidden exception."""
        mock_praw_mod, mock_reddit = mock_praw
        
        # Import the exception class from the module code (or mock it if it was safely imported)
        from parrot.tools.reddit import Forbidden
        
        # Setup mock to raise Forbidden
        mock_subreddit = MagicMock()
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_subreddit.search.side_effect = Forbidden(MagicMock(status_code=403))
        
        toolkit = RedditToolkit(client_id="dummy", client_secret="dummy")
        
        result = await toolkit.reddit_extract_subreddit_posts(
            subreddit_name="private_sub",
            query="test"
        )
        
        assert result.status == "error"
        assert "Access denied" in result.error
