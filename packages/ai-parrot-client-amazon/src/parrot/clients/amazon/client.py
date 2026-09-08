"""Amazon provider aggregator module (FEAT-523 folder convention, TASK-2845).

``amazon/`` is a multi-client provider folder (spec §2: "one package per
provider, several clients per package," like ``google/``, ``anthropic/`` and
``openai/``): Bedrock Converse, Nova and Bedrock Mantle share
:mod:`parrot.clients.amazon.models`. The real client implementations stay in
their own modules — ``bedrock.py`` (:class:`BedrockConverseBase`,
:class:`BedrockConverseClient`) and ``nova/`` (:class:`NovaClient`,
:class:`BedrockMantleClient`) — this module only re-exports them so the
folder satisfies the three-canonical-files convention
(``__init__.py``/``client.py``/``models.py``).
"""

from .bedrock import BedrockConverseBase, BedrockConverseClient
from .nova import BedrockMantleClient, NovaClient

__all__ = [
    "BedrockConverseBase",
    "BedrockConverseClient",
    "NovaClient",
    "BedrockMantleClient",
]
