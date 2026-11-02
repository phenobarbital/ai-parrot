"""ExpertRegistry: discover, seed, build and register domain experts (FEAT-778 M2)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from parrot.conf import AGENTS_DIR
from parrot.experts.agent import ExpertAgent
from parrot.experts.knowledge.resolver import KnowledgeResolver
from parrot.experts.knowledge.sources.adr import ADRSource
from parrot.experts.knowledge.sources.bookstore import BookstoreSource
from parrot.experts.knowledge.sources.bundled import BundledSource
from parrot.experts.knowledge.sources.graphindex import GraphIndexSource
from parrot.experts.knowledge.sources.wiki import WikiSource
from parrot.experts.knowledge.sources.workspace import WorkspaceSource
from parrot.experts.loader import BUNDLED_EXPERTS_DIR, EXPERTS_DIRNAME, discover_expert_bundles
from parrot.experts.models import DuplicateExpertError, ExpertBundle, ExpertKnowledgeError
from parrot.experts.policy import effective_allowlist, effective_toolkits, expert_policy_rules, model_config_for
from parrot.experts.view import ExpertView


class ExpertRegistry:
    """Own expert bundles and the ExpertAgents built from them."""

    def __init__(
        self,
        *,
        agent_registry: Any,
        agents_dir: Path | None = None,
        workspace: Path | None = None,
        bundled_dir: Path | None = BUNDLED_EXPERTS_DIR,
        wiki_toolkit: Any = None,
        bookstore: Any = None,
        decisions: Any = None,
        seed_knowledge: bool = True,
    ) -> None:
        """Initialize the registry and its optional host-owned dependencies."""
        self.agent_registry = agent_registry
        self.agents_dir = Path(agents_dir or AGENTS_DIR)
        self.workspace = Path(workspace) if workspace is not None else self.agents_dir
        self.bundled_dir = bundled_dir
        self.wiki_toolkit = wiki_toolkit
        self.bookstore = bookstore
        self.decisions = decisions
        self.seed_knowledge = seed_knowledge
        self._experts: dict[str, ExpertAgent] = {}
        self._contexts: dict[str, Any] = {}
        self._report: dict[str, Any] = {"loaded": [], "skipped": [], "shadowing": {}, "seeded": {}}
        self.logger = logging.getLogger(__name__)

    def report(self) -> dict[str, Any]:
        """Return a shallow copy of the loading report."""
        return {key: dict(value) if isinstance(value, dict) else list(value) for key, value in self._report.items()}

    def names(self) -> list[str]:
        """Return loaded expert names in deterministic order."""
        return sorted(self._experts)

    def get(self, name: str, *, tenant: str | None = None) -> ExpertAgent:
        """Return the global phase-one expert instance by name.

        Tenant-specific expert views are intentionally not built during phase one.

        Args:
            name: Loaded expert name.
            tenant: Accepted for forward compatibility; ignored with a warning in phase one.

        Returns:
            The global expert instance.

        Raises:
            KeyError: No expert with that name is loaded.
        """
        if tenant is not None:
            self.logger.warning(
                "ExpertRegistry.get(%r, tenant=%r): tenant-specific expert views are not built in phase one; "
                "returning the global instance",
                name,
                tenant,
            )
        return self._experts[name]

    def _discover(self) -> list[ExpertBundle]:
        """Discover both roots, reject local duplicates, and overlay workspace bundles."""
        bundled, skipped_bundled = (
            discover_expert_bundles(self.bundled_dir, origin="bundled") if self.bundled_dir else ([], [])
        )
        workspace, skipped_workspace = discover_expert_bundles(self.agents_dir / EXPERTS_DIRNAME, origin="workspace")
        self._report["skipped"].extend([*skipped_bundled, *skipped_workspace])
        for bundles in (bundled, workspace):
            names = [bundle.manifest.name for bundle in bundles]
            if len(names) != len(set(names)):
                duplicate = next(name for name in names if names.count(name) > 1)
                raise DuplicateExpertError(f"duplicate expert name {duplicate!r} within one root")
        view = ExpertView(bundled, workspace, label="workspace")
        self._report["shadowing"].update(view.shadowing)
        return view.bundles()

    async def _admit(self, bundle: ExpertBundle) -> bool:
        """Probe or seed the expert wiki namespace before constructing an agent."""
        name = bundle.manifest.name
        source = WikiSource(self.wiki_toolkit, namespace=f"expert-{name}")
        try:
            pages = await source.probe()
            if pages == 0 and self.seed_knowledge and bundle.knowledge_files:
                pages = await source.seed(bundle.knowledge_files, asserted_by=f"expert:{name}")
                self._report["seeded"][name] = pages
            if pages == 0:
                raise ExpertKnowledgeError(f"empty-wiki-namespace: expert-{name}")
        except ExpertKnowledgeError as exc:
            reason = (
                "wiki-not-writable" if "writable" in str(exc) or "read only" in str(exc) else "empty-wiki-namespace"
            )
            self.logger.error("Skipping expert bundle %s: %s", bundle.root, exc)
            self._report["skipped"].append({"path": str(bundle.root), "reason": reason})
            return False
        return True

    def _toolkits_for(self, bundle: ExpertBundle, wiki_source: WikiSource) -> list[Any]:
        """Build the toolkit set requested by one manifest, lazily importing tools extras."""
        toolkits: list[Any] = []
        for toolkit_name in effective_toolkits(bundle.manifest):
            if toolkit_name == "LLMWikiToolkit":
                if self.wiki_toolkit is None:
                    self.logger.warning("expert %s: LLMWikiToolkit is unavailable; skipping", bundle.manifest.name)
                else:
                    toolkits.append(self.wiki_toolkit)
            elif toolkit_name == "BookstoreToolkit":
                if self.bookstore is None:
                    self.logger.warning(
                        "expert %s: BookstoreToolkit requires a configured bookstore; skipping", bundle.manifest.name
                    )
                else:
                    from parrot.knowledge.bookstore.toolkit import BookstoreToolkit

                    toolkits.append(BookstoreToolkit(self.bookstore))
            elif toolkit_name == "CVEToolkit":
                from parrot_tools.security.cve import CVEToolkit

                sources_dir = self.agents_dir / ".experts_wiki" / bundle.manifest.name
                toolkits.append(CVEToolkit(store_resolver=wiki_source.store_for, sources_dir=sources_dir))
            elif toolkit_name == "ExpertKnowledgeToolkit":
                from parrot_tools.experts import ExpertKnowledgeToolkit

                toolkits.append(
                    ExpertKnowledgeToolkit(
                        self._contexts[bundle.manifest.name],
                        bundle.manifest,
                        wiki=self.wiki_toolkit,
                        bookstore=self.bookstore,
                        decisions=self.decisions,
                    )
                )
            else:
                self.logger.warning("expert %s: unknown toolkit %s; skipping", bundle.manifest.name, toolkit_name)
        return toolkits

    async def _build(self, bundle: ExpertBundle) -> ExpertAgent:
        """Build the resolver, toolkits, policy, and agent for an admitted bundle."""
        shared_dir = self.agents_dir / "knowledge"
        sources: list[Any] = [
            BundledSource(None),
            WorkspaceSource(shared_dir if shared_dir.is_dir() else None),
            WikiSource(self.wiki_toolkit, namespace=f"expert-{bundle.manifest.name}"),
            BookstoreSource(),
            GraphIndexSource(),
        ]
        if self.decisions is not None:
            sources.append(ADRSource(self.decisions))
        resolver = KnowledgeResolver(sources)
        model_config = model_config_for(bundle.manifest.tier)
        self._contexts[bundle.manifest.name] = await resolver.resolve(
            bundle, None, self.workspace, model=model_config.model
        )
        wiki_source = next(source for source in sources if isinstance(source, WikiSource))
        toolkits = self._toolkits_for(bundle, wiki_source)
        discovered = [tool.name for toolkit in toolkits for tool in toolkit.get_tools()]
        return ExpertAgent(
            bundle,
            resolver=resolver,
            model_config=model_config,
            toolkits=toolkits,
            allowed_tools=effective_allowlist(bundle.manifest, discovered),
            workspace=self.workspace,
        )

    async def load(self) -> int:
        """Discover, admit, build, register, and apply PBAC policies for experts."""
        for bundle in self._discover():
            if not await self._admit(bundle):
                continue
            name = bundle.manifest.name
            try:
                agent = await self._build(bundle)
            except Exception as exc:  # noqa: BLE001 - one broken bundle must not disable its siblings
                self.logger.error("Skipping expert bundle %s: build failed: %s", bundle.root, exc)
                self._report["skipped"].append({"path": str(bundle.root), "reason": f"build-failed: {exc}"})
                continue
            if self.agent_registry.has(name):
                raise DuplicateExpertError(f"agent name {name!r} is already registered")
            self.agent_registry.register_instance(
                name,
                agent,
                tags={"expert", f"expert:{name}", f"origin:{bundle.origin}"},
            )
            self.agent_registry.register_db_bot_policies(name, expert_policy_rules(bundle.manifest))
            self._experts[name] = agent
            self._report["loaded"].append({"name": name, "origin": bundle.origin})
        return len(self._experts)
