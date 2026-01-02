"""
Reddit Toolkit for AI-Parrot.

This toolkit provides Reddit data extraction capabilities using PRAW (Python Reddit API Wrapper),
implementing proper backoff retry for rate limiting and OAuth2 authentication.
"""
import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import backoff

# Try importing praw, but don't fail if not installed (handle at runtime)
try:
    import praw
    from prawcore.exceptions import (
        Forbidden,
        NotFound,
        TooManyRequests,
        Redirect,
        ResponseException,
        RequestException
    )
    PRAW_AVAILABLE = True
except ImportError:
    praw = None
    PRAW_AVAILABLE = False
    # Define dummy exception classes for type checking reference if PRAW is missing
    class Forbidden(Exception): pass
    class NotFound(Exception): pass
    class TooManyRequests(Exception): pass
    class Redirect(Exception): pass
    class ResponseException(Exception): pass
    class RequestException(Exception): pass

from navconfig.logging import logging
from .toolkit import AbstractToolkit
from .abstract import ToolResult


# -----------------------------
# Input Schemas
# -----------------------------

class SubredditSearchInput(BaseModel):
    """Input parameters for searching a subreddit."""
    subreddit_name: str = Field(description="Name of the subreddit to search (without r/)")
    query: str = Field(description="Search query (e.g. 'hisense OR \"hisense tv\"')")
    limit: int = Field(default=10, description="Maximum number of posts to retrieve")
    search_sort: str = Field(default="new", description="Sort order: new, relevance, hot, top, comments")
    time_filter: str = Field(default="year", description="Time filter: hour, day, week, month, year, all")
    fetch_comments: bool = Field(default=True, description="Whether to fetch top-level comments for each post")
    max_top_level_comments: int = Field(default=10, description="Max top-level comments to fetch per post")


# -----------------------------
# Helpers
# -----------------------------

def utc_iso(ts: Optional[float]) -> Optional[str]:
    """Convert a timestamp to an ISO 8601 string (UTC)."""
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def safe_author(author) -> Optional[str]:
    """Safely get author name, handling deleted users."""
    # deleted users => author is None
    return getattr(author, "name", None) if author else None


# -----------------------------
# Toolkit
# -----------------------------

class RedditToolkit(AbstractToolkit):
    """
    Reddit Toolkit for extracting data from Reddit using PRAW.
    
    Requires PRAW to be installed (`pip install praw`).
    
    Authentication configuration (environment variables recommended):
    - REDDIT_CLIENT_ID
    - REDDIT_CLIENT_SECRET
    - REDDIT_USER_AGENT
    - REDDIT_USERNAME (optional)
    - REDDIT_PASSWORD (optional)
    """

    def __init__(self, **kwargs):
        """Initialize the Reddit toolkit."""
        super().__init__(**kwargs)
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        
        # Check PRAW availability
        if not PRAW_AVAILABLE:
            self.logger.warning("PRAW is not installed. RedditToolkit will not function correctly.")

        # Configuration (can be passed in kwargs or picked up from env by PRAW)
        self.client_id = kwargs.get('client_id') or os.environ.get('REDDIT_CLIENT_ID')
        self.client_secret = kwargs.get('client_secret') or os.environ.get('REDDIT_CLIENT_SECRET')
        self.user_agent = kwargs.get('user_agent') or os.environ.get(
            'REDDIT_USER_AGENT', 'ai-parrot-reddit-toolkit/0.1'
        )
        self.username = kwargs.get('username') or os.environ.get('REDDIT_USERNAME')
        self.password = kwargs.get('password') or os.environ.get('REDDIT_PASSWORD')

        # Backoff configuration
        self.max_retries = kwargs.get('max_retries', 3)
        self.backoff_factor = kwargs.get('backoff_factor', 2.0)
        self.max_wait_time = kwargs.get('max_wait_time', 60.0)

    def _get_backoff_decorator(self):
        """Get the backoff decorator for retry logic."""
        # We need to handle TooManyRequests specifically to check retry-after if available,
        # but backoff library handles exponential backoff nicely for generic exceptions.
        # For PRAW's TooManyRequests, we might want custom logic, but standard backoff is a good start.
        return backoff.on_exception(
            backoff.expo,
            (TooManyRequests, RequestException, ResponseException),
            max_tries=self.max_retries,
            factor=self.backoff_factor,
            max_time=self.max_wait_time,
            logger=self.logger
        )

    def _build_reddit_client(self):
        """Build and return the PRAW Reddit client."""
        if not PRAW_AVAILABLE:
            raise ImportError("PRAW is not installed. Please install it with `pip install praw`.")
            
        if not self.client_id or not self.client_secret:
             raise ValueError("Reddit Client ID and Secret are required.")

        return praw.Reddit(
            client_id=self.client_id,
            client_secret=self.client_secret,
            user_agent=self.user_agent,
            username=self.username,
            password=self.password,
            check_for_async=False, 
        )

    async def reddit_extract_subreddit_posts(
        self,
        subreddit_name: str,
        query: str,
        limit: int = 10,
        search_sort: str = "new",
        time_filter: str = "year",
        fetch_comments: bool = True,
        max_top_level_comments: int = 10
    ) -> ToolResult:
        """
        Extract posts and optionally comments from a subreddit based on a search query.
        
        Args:
            subreddit_name: Name of the subreddit (e.g. "python")
            query: Search query (e.g. "asyncio")
            limit: Maximum number of posts to retrieve
            search_sort: Sort order ("new", "relevance", "hot", "top", "comments")
            time_filter: Time filter ("hour", "day", "week", "month", "year", "all")
            fetch_comments: Whether to fetch top-level comments
            max_top_level_comments: Max top-level comments to fetch per post
            
        Returns:
            ToolResult with a list of flattened records (submissions and comments)
        """
        if not PRAW_AVAILABLE:
             return ToolResult(
                status="error",
                result=[],
                error="PRAW library is not installed.",
                metadata={"subreddit": subreddit_name}
            )

        # Define the synchronous operation
        @self._get_backoff_decorator()
        def _extract():
            reddit = self._build_reddit_client()
            records: List[Dict[str, Any]] = []
            
            try:
                subreddit = reddit.subreddit(subreddit_name)
                # PRAW's search returns a generator
                search_iter = subreddit.search(
                    query, 
                    sort=search_sort, 
                    time_filter=time_filter, 
                    limit=limit
                )

                for submission in search_iter:
                    # Collect submission data
                    subrec: Dict[str, Any] = {
                        "record_type": "submission",
                        "subreddit": subreddit_name,
                        "query": query,
                        "submission_id": submission.id,
                        "submission_fullname": submission.name,  # t3_xxx
                        "title": submission.title,
                        "selftext": submission.selftext,
                        "url": submission.url,
                        "permalink": f"https://www.reddit.com{submission.permalink}",
                        "created_utc": submission.created_utc,
                        "created_iso_utc": utc_iso(submission.created_utc),
                        "author": safe_author(submission.author),
                        "score": submission.score,
                        "upvote_ratio": getattr(submission, "upvote_ratio", None),
                        "num_comments": submission.num_comments,
                        "is_self": submission.is_self,
                        "link_flair_text": getattr(submission, "link_flair_text", None),
                    }
                    records.append(subrec)

                    if fetch_comments:
                        # Fetch comments logic
                        # Getting attributes triggers network calls in PRAW, so we do it here
                        submission.comments.replace_more(limit=0)
                        top_level = list(submission.comments)[:max_top_level_comments]

                        for c in top_level:
                            comrec: Dict[str, Any] = {
                                "record_type": "comment",
                                "subreddit": subreddit_name,
                                "query": query,
                                "submission_id": submission.id,
                                "comment_id": c.id,
                                "comment_fullname": c.name,  # t1_xxx
                                "comment_body": c.body,
                                "comment_permalink": f"https://www.reddit.com{c.permalink}",
                                "created_utc": c.created_utc,
                                "created_iso_utc": utc_iso(c.created_utc),
                                "author": safe_author(c.author),
                                "score": c.score,
                                "parent_id": c.parent_id,
                            }
                            records.append(comrec)
            
            except (Forbidden, NotFound, Redirect) as e:
                # These are likely permanent errors for this query/subreddit
                self.logger.warning(f"Reddit Access Error for r/{subreddit_name}: {type(e).__name__} - {str(e)}")
                # We don't raise here to allow returning partial results or specific error message
                raise e # But backoff might want to retry if it was transient, though these usually aren't.
                        # Actually, Forbidden/NotFound shouldn't trigger retry.
                        # The backoff decorator is configured for network/rate limit errors.
                        # So we catch and re-raise or handle.
                        # Let's let the outer try/catch handle the final return.
                
            return records

        # Run in thread executor
        try:
            loop = asyncio.get_event_loop()
            stats = await loop.run_in_executor(None, _extract)
            
            return ToolResult(
                status="success",
                result=stats,
                metadata={
                    "subreddit": subreddit_name,
                    "query": query,
                    "count": len(stats),
                    "search_sort": search_sort
                }
            )
            
        except (Forbidden, NotFound, Redirect) as e:
             return ToolResult(
                status="error",
                result=[],
                error=f"Access denied or not found: {str(e)}",
                metadata={"subreddit": subreddit_name}
            )
        except Exception as e:
            self.logger.exception(f"Reddit extraction failed for r/{subreddit_name}")
            return ToolResult(
                status="error",
                result=[],
                error=f"Extraction failed: {str(e)}",
                metadata={"subreddit": subreddit_name}
            )
