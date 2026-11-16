"""Select full CI or post-merge checks using GitHub's merge metadata.

This stdlib-only CLI runs before workspace dependencies are installed. GitHub's
preinstalled ``gh`` CLI supplies authenticated, read-only API access. Uncertain
metadata always keeps the full suite enabled.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def github_json(endpoint: str) -> Any:
    """Read one GitHub API response with bounded execution time."""
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(result.stdout)


def needs_full_suite(event_name: str, event: dict[str, Any], repository: str) -> bool:
    """Keep full coverage unless this push consists solely of a confirmed PR merge.

    Args:
        event_name: GitHub event type.
        event: Decoded webhook payload.
        repository: Trusted owner/repository from the workflow environment.

    Returns:
        False only for a merged PR targeting this exact branch and repository,
        whose merge commit directly follows the pre-push branch tip. This also
        supports squash merges; ambiguous rebase or batched pushes run full CI.
    """
    if event_name != "push":
        return True
    ref = event.get("ref", "")
    before = event.get("before")
    after = event.get("after")
    if ref not in {"refs/heads/main", "refs/heads/dev"} or not before or not after or event.get("forced"):
        return True

    try:
        pulls = github_json(f"repos/{repository}/commits/{after}/pulls?per_page=100")
        merged = any(
            pull.get("merged_at")
            and pull.get("merge_commit_sha") == after
            and pull.get("base", {}).get("ref") == ref.removeprefix("refs/heads/")
            and pull.get("base", {}).get("repo", {}).get("full_name") == repository
            for pull in pulls
        )
        if not merged:
            return True

        commit = github_json(f"repos/{repository}/commits/{after}")
        parents = commit.get("parents", [])
        if commit.get("sha") != after or not parents or parents[0].get("sha") != before:
            return True
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError) as exc:
        # Missing permissions, API outages, or unexpected metadata must never
        # silently turn off tests. Avoid logging response bodies or credentials.
        logger.warning("Cannot confirm a PR merge (%s); running full CI", type(exc).__name__)
        return True

    logger.info("Confirmed PR merge into %s; retaining lint/registry checks", ref)
    return False


def main() -> None:
    """Publish the selection to GitHub Actions, defaulting to full coverage."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    full_suite = True
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        full_suite = needs_full_suite(os.environ["GITHUB_EVENT_NAME"], event, os.environ["GITHUB_REPOSITORY"])
    except (OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
        logger.warning("Cannot read workflow context (%s); running full CI", type(exc).__name__)

    value = "true" if full_suite else "false"
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"full_suite={value}\n")
    logger.info("Full CI suite: %s", value)


if __name__ == "__main__":
    main()
