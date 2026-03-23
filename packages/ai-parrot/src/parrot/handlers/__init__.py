"""
Parrot basic Handlers.
"""

def __getattr__(name: str):
    """Lazy imports for handlers that may cause circular imports."""
    if name == "ChatbotHandler":
        from .bots import ChatbotHandler
        return ChatbotHandler
    if name == "DashboardHandler":
        from .dashboard_handler import DashboardHandler
        return DashboardHandler
    if name == "DashboardTabHandler":
        from .dashboard_handler import DashboardTabHandler
        return DashboardTabHandler
    if name == "LLMClient":
        from .llm import LLMClient
        return LLMClient
    if name == "BotConfigHandler":
        from .config_handler import BotConfigHandler
        return BotConfigHandler
    if name == "LyriaMusicHandler":
        from .lyria_music import LyriaMusicHandler
        return LyriaMusicHandler
    if name == "PlanogramComplianceHandler":
        from .planogram_compliance import PlanogramComplianceHandler
        return PlanogramComplianceHandler
    if name == "VideoReelHandler":
        from .video_reel import VideoReelHandler
        return VideoReelHandler
    if name == "DatasetManagerHandler":
        from .datasets import DatasetManagerHandler
        return DatasetManagerHandler
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
