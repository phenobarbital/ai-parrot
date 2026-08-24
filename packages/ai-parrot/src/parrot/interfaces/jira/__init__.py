"""Shared Jira read interface (FEAT-454).

One connection/auth + parsing core reused by:

* ``parrot_tools.jiratoolkit.JiraToolkit`` — agent-facing tools (TASK-2402
  delegates its read methods here)
* ``parrot.knowledge.wiki.jira_sync`` — the `issues` wiki namespace sweep

This mirrors ``parrot.interfaces.obsidian``, whose docstring states the same
intent: "One vault-access + parsing core reused by ObsidianToolkit, the
loaders, and wiki vault_scan."

The ``jira`` distribution is an optional, lazily-imported dependency —
importing this package must never require it to be installed.
"""

from .client import JiraInterface
from .errors import JiraAuthError, JiraDependencyError, JiraInterfaceError
from .models import (
    JiraAttachmentRef,
    JiraChangeEvent,
    JiraIssue,
    JiraIssueLink,
    JiraIssueLinkKind,
    JiraPerson,
    JiraRemoteLink,
)
from .parse import parse_issue

__all__ = (
    "JiraAttachmentRef",
    "JiraAuthError",
    "JiraChangeEvent",
    "JiraDependencyError",
    "JiraInterface",
    "JiraInterfaceError",
    "JiraIssue",
    "JiraIssueLink",
    "JiraIssueLinkKind",
    "JiraPerson",
    "JiraRemoteLink",
    "parse_issue",
)
