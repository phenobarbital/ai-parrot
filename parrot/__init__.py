# -*- coding: utf-8 -*-
"""Navigator Parrot.

Basic Chatbots for Navigator Services.
"""
import os
from pathlib import Path
from .version import (
    __author__,
    __author_email__,
    __description__,
    __title__,
    __version__
)

os.environ["USER_AGENT"] = "Parrot.AI/1.0"

def get_project_root() -> Path:
    return Path(__file__).parent.parent

ABS_PATH = get_project_root()
