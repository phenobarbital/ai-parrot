from contextvars import ContextVar
from typing import Any, Optional, Union

from aiohttp import web


class RequestContext:
    """RequestContext.

    This class is a context manager for handling request-specific data.
    It is designed to be used with the `async with` statement to ensure
    proper setup and teardown of resources.

    Attributes:
        request (web.Request): The incoming web request.
        app (Optional[Any]): An optional application context.
        llm (Optional[Any]): An optional language model instance.
        kwargs (dict): Additional keyword arguments for customization.
    """

    def __init__(
        self,
        request: web.Request = None,
        app: Optional[Any] = None,
        llm: Optional[Any] = None,
        user_id: Union[str, int] = None,
        session_id: str = None,
        **kwargs
    ):
        """Initialize the RequestContext with the given parameters."""
        self.request = request
        self.app = app
        self.llm = llm
        self.user_id = user_id
        self.session_id = session_id
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass


# Module-level ContextVar for per-asyncio-task RequestContext isolation.
# Set by AbstractBot.session(); read by current_context() anywhere in the stack.
_current_ctx: ContextVar[Optional[RequestContext]] = ContextVar(
    "parrot_request_ctx", default=None
)


def current_context() -> Optional[RequestContext]:
    """Return the RequestContext bound to the current asyncio task, if any.

    Returns:
        The active RequestContext if called within an AbstractBot.session()
        block, or None if no session is active for the current asyncio task.
    """
    return _current_ctx.get()
