"""Dev-loop configuration helpers (FEAT-253).

Provides :func:`parse_repo_specs` — a pure, synchronous helper that
converts raw ``DEV_LOOP_REPOS`` env entries into
:class:`~parrot.flows.dev_loop.models.RepoSpec` objects.

``conf.py`` must never import ``dev_loop``, so this parser lives here
and is called by the demo server (``examples/dev_loop/server.py``) and
any other consumer that needs to turn string env-var entries into
``RepoSpec`` instances.
"""

import json
from typing import List

from parrot.flows.dev_loop.models import RepoSpec


def _alias_from_url(url: str) -> str:
    """Derive a short alias (repo name) from any supported URL format.

    Handles:
    - ``git@github.com:owner/name.git``  -> ``name``
    - ``https://github.com/owner/name(.git)`` -> ``name``
    - ``owner/name`` slug -> ``name``

    Args:
        url: A repo URL or slug string.

    Returns:
        The derived alias (trailing ``.git`` stripped).
    """
    # For SSH URLs like git@github.com:owner/name.git, split on ":"
    # and take the path portion; for everything else use the URL as-is.
    tail = url.rsplit(":", 1)[-1] if url.startswith("git@") else url
    name = tail.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def parse_repo_specs(raw: List[str]) -> List[RepoSpec]:
    """Parse ``DEV_LOOP_REPOS`` entries into :class:`RepoSpec` objects.

    Each entry is one of:

    * a **JSON object string** — ``RepoSpec(**json.loads(entry))``
      (honors ``alias`` / ``branch`` / ``private``).
    * a **full clone URL** — ``RepoSpec(alias=<derived>, url=<entry>)``.
      Supports ``https://github.com/owner/name(.git)`` and
      ``git@github.com:owner/name.git``.
    * an **``owner/name`` slug** — ``RepoSpec(alias=<name>, url=<entry>)``.

    The alias defaults to the repo's ``<name>`` component with any
    trailing ``.git`` stripped.  ``branch`` defaults to ``"main"`` and
    ``private`` to ``False`` unless supplied in the JSON form.

    Blank / whitespace-only entries are silently skipped.  Invalid JSON
    falls back to URL/slug handling so a slightly-malformed entry still
    produces a usable ``RepoSpec``.

    Args:
        raw: List of raw string entries from ``DEV_LOOP_REPOS``.

    Returns:
        List of :class:`RepoSpec` instances, in order.
    """
    specs: List[RepoSpec] = []
    for entry in raw or []:
        entry = (entry or "").strip()
        if not entry:
            continue
        if entry.startswith("{"):
            try:
                specs.append(RepoSpec(**json.loads(entry)))
                continue
            except (ValueError, TypeError, KeyError):
                pass  # fall through to url/slug handling
        specs.append(RepoSpec(alias=_alias_from_url(entry), url=entry))
    return specs
