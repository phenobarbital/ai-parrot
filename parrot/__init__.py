# -*- coding: utf-8 -*-
"""Navigator Parrot.

Basic Chatbots for Navigator Services.
"""
import os
from pathlib import Path
from navconfig.logging import logging
from .version import (
    __author__,
    __author_email__,
    __description__,
    __title__,
    __version__
)

logging.getLogger('h5py').setLevel(logging.ERROR)
logging.getLogger('tensorflow').setLevel(logging.ERROR)
logging.getLogger('matplotlib').setLevel(logging.ERROR)
logging.getLogger('langchain').setLevel(logging.ERROR)
logging.getLogger("grpc").setLevel(logging.CRITICAL)

os.environ["USER_AGENT"] = "Parrot.AI/1.0"
# This environment variable can help prevent some gRPC cleanup issues
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "false"

def get_project_root() -> Path:
    return Path(__file__).parent.parent

ABS_PATH = get_project_root()
