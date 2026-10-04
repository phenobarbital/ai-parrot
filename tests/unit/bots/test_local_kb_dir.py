"""FEAT-621 M10 — test_kb_dir_honours_agents_dir."""
from pathlib import Path

from parrot.bots.stores.local import LocalKBMixin
from parrot.conf import AGENTS_DIR


class _Bot(LocalKBMixin):
    def __init__(self, name: str) -> None:
        self.name = name


def test_kb_dir_honours_agents_dir(tmp_path: Path) -> None:
    bot = _Bot("Sales Bot")
    assert bot._get_agent_kb_directory() == Path(AGENTS_DIR) / "sales_bot" / "kb"
    bot._agents_dir = tmp_path
    assert bot._get_agent_kb_directory() == tmp_path / "sales_bot" / "kb"
    bot._agents_dir = None
    assert bot._get_agent_kb_directory() == Path(AGENTS_DIR) / "sales_bot" / "kb"
