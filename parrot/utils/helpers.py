from typing import Any, Optional
import inspect
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


class RequestBot:
    """RequestBot.

    This class is a wrapper around the AbstractBot to provide request-specific context.
    """
    def __init__(self, delegate: Any, context: RequestContext):
        self.delegate = delegate
        self.ctx = context

    def __getattr__(self, name: str):
        attr = getattr(self.delegate, name)
        # If the attribute is a callable method (and not just a property)
        if callable(attr):
            # Check if the original method is async
            if inspect.iscoroutinefunction(attr):
                # Return a new ASYNC function that wraps the original
                async def async_wrapper(*args, **kwargs):
                    # Inject the context into the call
                    if 'ctx' not in kwargs:
                        kwargs['ctx'] = self.ctx
                    # Await the original async method with the modified arguments
                    return await attr(*args, **kwargs)
                return async_wrapper
            else:
                # Return a new SYNC function that wraps the original
                def sync_wrapper(*args, **kwargs):
                    # Inject the context into the call
                    if 'ctx' not in kwargs:
                        kwargs['ctx'] = self.ctx
                    # Call the original sync method with the modified arguments
                    return attr(*args, **kwargs)
                return sync_wrapper
        else:
            # If it's a simple attribute (e.g., self.delegate.name), return it directly
            return attr
