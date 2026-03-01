"""Pulumi Toolkit for infrastructure deployment.

Provides agent tools for Pulumi operations:
- pulumi_plan: Preview changes
- pulumi_apply: Apply changes
- pulumi_destroy: Tear down resources
- pulumi_status: Check stack state

Example:
    from parrot.tools.pulumi import PulumiToolkit

    toolkit = PulumiToolkit()
    agent = Agent(tools=toolkit.get_tools())

Or with custom configuration:
    from parrot.tools.pulumi import PulumiToolkit, PulumiConfig

    config = PulumiConfig(
        default_stack="staging",
        use_docker=True,
    )
    toolkit = PulumiToolkit(config)
"""

from .config import (
    PulumiApplyInput,
    PulumiConfig,
    PulumiDestroyInput,
    PulumiOperationResult,
    PulumiPlanInput,
    PulumiResource,
    PulumiStatusInput,
)
from .executor import PulumiExecutor
from .toolkit import PulumiToolkit

__all__ = [
    # Main classes
    "PulumiToolkit",
    "PulumiExecutor",
    "PulumiConfig",
    # Input models
    "PulumiPlanInput",
    "PulumiApplyInput",
    "PulumiDestroyInput",
    "PulumiStatusInput",
    # Output models
    "PulumiResource",
    "PulumiOperationResult",
]

# Note: PulumiToolkit is registered in parrot/tools/registry.py
# via the _get_supported_toolkits() function for lazy loading.
