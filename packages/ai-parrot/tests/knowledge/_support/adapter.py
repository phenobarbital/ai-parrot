"""Scripted LLM adapter and fake PageIndex indexer shared by knowledge tests (FEAT-601)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional


def section_node_key(prompt: str) -> Optional[str]:
    """Return the id after ``Section node: `` in a prompt, if present."""
    match = re.search(r"Section node: ([^\n]+)", prompt)
    return match.group(1) if match else None


class FakeAdapter:
    """Count structured calls and replay scripted outputs by type and prompt key."""

    def __init__(self, *, key_of: Callable[[str], Optional[str]] = section_node_key) -> None:
        self.key_of = key_of
        self.scripts: dict[tuple[type, Optional[str]], Any] = {}
        self.defaults: dict[type, Callable[[], Any]] = {}
        self.calls: list[tuple[str, type]] = []
        self.prompts: list[str] = []
        self.system_prompts: list[Optional[str]] = []
        self.image_calls: list[tuple[str, Any, Any]] = []
        self.fail_types: set[type] = set()
        self.fail_keys: set[str] = set()

    def script(self, output_type: type, value: Any, *, key: Optional[str] = None) -> None:
        """Register a result for an output type, optionally for one prompt key."""
        self.scripts[(output_type, key)] = value

    async def ask_structured(
        self, prompt: str, output_type: type, temperature: float = 0.0, system_prompt: Optional[str] = None
    ) -> Any:
        """Replay keyed, then unkeyed, then default scripts or instantiate the type."""
        key = self.key_of(prompt)
        self.calls.append((prompt, output_type))
        self.prompts.append(prompt)
        self.system_prompts.append(system_prompt)
        if output_type in self.fail_types or key in self.fail_keys:
            raise RuntimeError("model unavailable")
        if (output_type, key) in self.scripts:
            return self.scripts[(output_type, key)]
        if (output_type, None) in self.scripts:
            return self.scripts[(output_type, None)]
        if output_type in self.defaults:
            return self.defaults[output_type]()
        return output_type()

    async def ask_to_image(self, prompt: str, image: Any, *, structured_output: Any = None, **kwargs: Any) -> Any:
        """Replay a vision result, rejecting URL strings to enforce local image inputs."""
        if isinstance(image, str):
            raise ValueError("image must be a Path or bytes, not a URL")
        self.image_calls.append((prompt, image, structured_output))
        if structured_output is not None:
            return await self.ask_structured(prompt, structured_output)
        return type("VisionResponse", (), {"output": ""})()


_HEADING = re.compile(r"^##?\s+(.*)$")


class FakeIndexer:
    """Minimal PageIndex tree builder over a real content store."""

    def __init__(self, storage_dir: Path, adapter: Any = None) -> None:
        from parrot.knowledge.pageindex.content_store import NodeContentStore
        from parrot.knowledge.pageindex.store import JSONTreeStore

        self.storage_dir = Path(storage_dir)
        self.adapter = adapter
        self.content = NodeContentStore(self.storage_dir)
        self.store = JSONTreeStore(self.storage_dir)
        self.fail_on: set[str] = set()

    async def create_tree(self, tree_name: str, doc_name: Optional[str] = None) -> dict[str, Any]:
        """Create an empty tree."""
        if tree_name in self.fail_on:
            raise RuntimeError("indexer exploded")
        tree = {"doc_name": doc_name or tree_name, "structure": []}
        self.store.save(tree_name, tree)
        return {"tree_name": tree_name}

    async def insert_markdown(
        self,
        tree_name: str,
        markdown: str,
        parent_node_id: Optional[str] = None,
        doc_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """Split markdown headings into nodes and save their bodies as sidecars."""
        if tree_name in self.fail_on:
            raise RuntimeError("indexer exploded")
        tree = self.store.load(tree_name)
        nodes: list[dict[str, Any]] = []
        current_title = doc_name or tree_name
        current_lines: list[str] = []

        def _flush() -> None:
            if not current_lines and not nodes:
                return
            node_id = f"{len(nodes):04d}"
            body = "\n".join(current_lines).strip()
            nodes.append({"node_id": node_id, "title": current_title, "nodes": []})
            self.content.save(tree_name, node_id, f"{current_title}\n\n{body}")

        for line in markdown.splitlines():
            match = _HEADING.match(line)
            if match:
                _flush()
                current_title = match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)
        _flush()

        tree["structure"] = nodes
        self.store.save(tree_name, tree)
        return {"tree_name": tree_name, "new_node_ids": [node["node_id"] for node in nodes]}

    async def get_tree(self, tree_name: str) -> dict[str, Any]:
        """Load a tree."""
        return self.store.load(tree_name)

    async def delete_tree(self, tree_name: str) -> dict[str, Any]:
        """Delete a tree and its node-content sidecars."""
        self.store.delete(tree_name)
        self.content.delete_tree(tree_name)
        return {"tree_name": tree_name}
