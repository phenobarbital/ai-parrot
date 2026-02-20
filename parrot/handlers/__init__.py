"""
Parrot basic Handlers.
"""
from .bots import ChatbotHandler
from .dashboard_handler import DashboardHandler, DashboardTabHandler
from .llm import LLMClient


def __getattr__(name: str):
    """Lazy imports for handlers that may cause circular imports."""
    if name == "BotConfigHandler":
        from .config_handler import BotConfigHandler
        return BotConfigHandler
    if name == "LyriaMusicHandler":
        from .lyria_music import LyriaMusicHandler
        return LyriaMusicHandler
    if name == "VideoReelHandler":
        from .video_reel import VideoReelHandler
        return VideoReelHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
