from typing import Any, Optional
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
        **kwargs
    ):
        """Initialize the RequestContext with the given parameters."""
        self.request = request
        self.app = app
        self.llm = llm
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass
