"""Example usage script for :mod:`parrot.tools.gittoolkit`."""

import asyncio
import os
from typing import List

from parrot.tools.gittoolkit import (
    GitHubFileChange,
    GitPatchFile,
    GitToolkit,
    GitToolkitError,
)


async def main() -> None:
    """Demonstrate the high-level GitToolkit helpers."""

    repository = os.getenv("GITHUB_REPOSITORY")
    default_branch = os.getenv("GITHUB_DEFAULT_BRANCH", "main")
    github_token = os.getenv("GITHUB_TOKEN")

    toolkit = GitToolkit(
        default_repository=repository,
        default_branch=default_branch,
        github_token=github_token,
    )

    available_tools = [tool.name for tool in toolkit.get_tools()]
    print("Available tools:", ", ".join(available_tools))

    files: List[GitPatchFile] = [
        GitPatchFile(
            path="README.md",
            original="Hello, world!\n",
            updated="Hello from GitToolkit!\n",
        )
    ]
    patch_result = await toolkit.generate_git_apply_patch(
        files=files,
        context_lines=1,
        include_apply_snippet=True,
    )

    print("\nGenerated diff:\n")
    print(patch_result["patch"])  # Unified diff string

    if patch_result.get("git_apply"):
        print("git apply snippet:\n")
        print(patch_result["git_apply"])

    if not (repository and github_token):
        print(
            "\nSet GITHUB_REPOSITORY and GITHUB_TOKEN to run the pull request example."
        )
        return

    try:
        pr_result = await toolkit.create_pull_request(
            repository=repository,
            title="Demo change from GitToolkit example",
            body=(
                "This pull request was created by the examples/tool/github.py script.\n"
                "It demonstrates how to call the GitToolkit.create_pull_request helper."
            ),
            head_branch=None,  # auto-generate a unique branch name
            files=[
                GitHubFileChange(
                    path="gittoolkit-demo.txt",
                    content="Created by GitToolkit example.\n",
                    encoding="utf-8",
                    change_type="add",
                )
            ],
            draft=True,
            labels=["demo", "automated"],
        )
    except GitToolkitError as exc:
        print("\nPull request creation skipped:", exc)
    else:
        print("\nPull request created:")
        print(f"  URL: {pr_result['html_url']}")
        print(f"  Number: {pr_result['number']}")
        print(f"  Branch: {pr_result['head_branch']}")


if __name__ == "__main__":
    asyncio.run(main())
