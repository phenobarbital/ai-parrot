"""Multi-layer YAML ontology composition engine.

Merges base → domain → client ontology layers into a single MergedOntology
with deterministic rules for entity extension, relation concatenation, and
traversal pattern overrides.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import FrameworkOverrideError, OntologyIntegrityError, OntologyMergeError
from .parser import OntologyParser
from .schema import (
    EntityDef,
    MergedOntology,
    OntologyDefinition,
    RelationDef,
    TraversalPattern,
)

logger = logging.getLogger("Parrot.Ontology.Merger")


class OntologyMerger:
    """Merge multiple ontology YAML layers into a single MergedOntology.

    Merge rules:

    **Entities with extend=True:**
        - properties: concatenated (no name collisions allowed)
        - vectorize: unioned
        - source: overridden (last layer wins)
        - key_field, collection: immutable

    **Entities without extend=True:**
        - If entity already exists → OntologyMergeError
        - If entity is new → added

    **Relations:**
        - New relation → added (endpoints validated)
        - Same name → from/to immutable, discovery.rules concatenated

    **Traversal patterns:**
        - New → added
        - Same name → trigger_intents concatenated (deduped),
          query_template overridden, post_action overridden
    """

    def merge(self, yaml_paths: list[Path]) -> MergedOntology:
        """Merge multiple YAML layers sequentially into a MergedOntology.

        Args:
            yaml_paths: Ordered list of YAML file paths (base first, client last).

        Returns:
            Fully merged and validated MergedOntology.

        Raises:
            OntologyMergeError: If merge rules are violated.
            OntologyIntegrityError: If the final result fails integrity checks.
        """
        result_entities: dict[str, EntityDef] = {}
        result_relations: dict[str, RelationDef] = {}
        result_patterns: dict[str, TraversalPattern] = {}
        layers: list[str] = []
        last_name = "unnamed"

        for path in yaml_paths:
            layer = OntologyParser.load(path)
            layers.append(str(path))
            last_name = layer.name

            self._merge_entities(result_entities, layer.entities, path)
            self._merge_relations(
                result_relations, layer.relations, result_entities, path
            )
            self._merge_patterns(result_patterns, layer.traversal_patterns)

        merged = MergedOntology(
            name=last_name,
            version="1.0",
            entities=result_entities,
            relations=result_relations,
            traversal_patterns=result_patterns,
            layers=layers,
            merge_timestamp=datetime.now(timezone.utc),
        )

        self._validate_integrity(merged)
        logger.info(
            "Merged %d layers into ontology '%s': %d entities, %d relations, %d patterns",
            len(layers), last_name,
            len(result_entities), len(result_relations), len(result_patterns),
        )
        return merged

    def merge_definitions(
        self, definitions: list[OntologyDefinition]
    ) -> MergedOntology:
        """Merge pre-loaded OntologyDefinition objects (no file I/O).

        Args:
            definitions: Ordered list of OntologyDefinition instances.

        Returns:
            Fully merged and validated MergedOntology.
        """
        result_entities: dict[str, EntityDef] = {}
        result_relations: dict[str, RelationDef] = {}
        result_patterns: dict[str, TraversalPattern] = {}
        layers: list[str] = []
        last_name = "unnamed"

        for layer in definitions:
            layers.append(layer.name)
            last_name = layer.name

            self._merge_entities(
                result_entities, layer.entities, Path(layer.name)
            )
            self._merge_relations(
                result_relations, layer.relations, result_entities,
                Path(layer.name),
            )
            self._merge_patterns(result_patterns, layer.traversal_patterns)

        merged = MergedOntology(
            name=last_name,
            version="1.0",
            entities=result_entities,
            relations=result_relations,
            traversal_patterns=result_patterns,
            layers=layers,
            merge_timestamp=datetime.now(timezone.utc),
        )

        self._validate_integrity(merged)
        return merged

    def merge_with_overlay(
        self,
        yaml_paths: list[Path],
        overlay_defs: list[OntologyDefinition],
    ) -> MergedOntology:
        """Merge YAML layers + in-memory PG-sourced overlay definitions.

        First merges all YAML layers via the standard merge() logic, identifying
        the framework layer (first YAML path) whose entity/relation/pattern keys
        are immutable. Then merges each overlay definition on top, raising
        FrameworkOverrideError if any overlay attempts to redefine a framework item.

        Regression safety: when overlay_defs is empty, the output is identical
        to merge(yaml_paths).

        Args:
            yaml_paths: Ordered list of YAML file paths (base first, client last).
            overlay_defs: Ordered list of in-memory OntologyDefinition overlays
                (e.g. approved PG rows). Applied left-to-right on top of the YAML chain.

        Returns:
            Fully merged and validated MergedOntology including overlay content.

        Raises:
            FrameworkOverrideError: An overlay attempts to mutate a framework
                entity, relation, or traversal pattern.
            OntologyMergeError: If merge rules are violated within the YAML chain.
            OntologyIntegrityError: If the final result fails integrity checks.
        """
        # Step 1: Identify framework (base) keys from the first YAML layer.
        framework_entity_keys: set[str] = set()
        framework_relation_keys: set[str] = set()
        framework_pattern_keys: set[str] = set()

        if yaml_paths:
            try:
                base_layer = OntologyParser.load(yaml_paths[0])
                framework_entity_keys = set(base_layer.entities.keys())
                framework_relation_keys = set(base_layer.relations.keys())
                framework_pattern_keys = set(base_layer.traversal_patterns.keys())
            except Exception as exc:
                # S6 fix: log the failure so operators know the guard is disabled.
                # The standard merge() call below will surface the real parse error.
                logger.warning(
                    "Could not load base layer '%s' for FrameworkOverrideError guard — "
                    "protection disabled for this merge: %s",
                    yaml_paths[0],
                    exc,
                )

        # Step 2: Merge all YAML layers normally.
        result_entities: dict[str, EntityDef] = {}
        result_relations: dict[str, RelationDef] = {}
        result_patterns: dict[str, TraversalPattern] = {}
        layers: list[str] = []
        last_name = "unnamed"

        for path in yaml_paths:
            layer = OntologyParser.load(path)
            layers.append(str(path))
            last_name = layer.name
            self._merge_entities(result_entities, layer.entities, path)
            self._merge_relations(result_relations, layer.relations, result_entities, path)
            self._merge_patterns(result_patterns, layer.traversal_patterns)

        # Step 3: Apply each overlay definition on top.
        for overlay in overlay_defs:
            overlay_path = Path(overlay.name)

            # Framework-override guard — overlays may NOT redefine framework items.
            for name in overlay.entities:
                if name in framework_entity_keys:
                    raise FrameworkOverrideError(
                        f"Overlay '{overlay.name}' attempts to override framework "
                        f"entity '{name}'. Framework items are immutable.",
                        entity_name=name,
                    )
            for name in overlay.relations:
                if name in framework_relation_keys:
                    raise FrameworkOverrideError(
                        f"Overlay '{overlay.name}' attempts to override framework "
                        f"relation '{name}'. Framework items are immutable.",
                        entity_name=name,
                    )
            for name in overlay.traversal_patterns:
                if name in framework_pattern_keys:
                    raise FrameworkOverrideError(
                        f"Overlay '{overlay.name}' attempts to override framework "
                        f"traversal pattern '{name}'. Framework items are immutable.",
                        entity_name=name,
                    )

            # Merge overlay content using the standard helpers.
            self._merge_entities(result_entities, overlay.entities, overlay_path)
            self._merge_relations(
                result_relations, overlay.relations, result_entities, overlay_path
            )
            self._merge_patterns(result_patterns, overlay.traversal_patterns)
            layers.append(overlay.name)
            last_name = overlay.name or last_name

        merged = MergedOntology(
            name=last_name,
            version="1.0",
            entities=result_entities,
            relations=result_relations,
            traversal_patterns=result_patterns,
            layers=layers,
            merge_timestamp=datetime.now(timezone.utc),
        )

        self._validate_integrity(merged)
        logger.info(
            "merge_with_overlay: %d YAML layers + %d overlays → ontology '%s': "
            "%d entities, %d relations, %d patterns",
            len(yaml_paths),
            len(overlay_defs),
            last_name,
            len(result_entities),
            len(result_relations),
            len(result_patterns),
        )
        return merged

    # ── Entity merging ──

    def _merge_entities(
        self,
        target: dict[str, EntityDef],
        source: dict[str, EntityDef],
        source_path: Path,
    ) -> None:
        """Merge entities from a layer into the target dict."""
        for name, entity in source.items():
            if name in target:
                if not entity.extend:
                    raise OntologyMergeError(
                        f"Entity '{name}' exists in parent layer. "
                        f"Set 'extend: true' in {source_path} to modify it."
                    )
                self._extend_entity(target[name], entity, name)
            else:
                target[name] = entity.model_copy(deep=True)

    def _extend_entity(
        self, existing: EntityDef, extension: EntityDef, name: str
    ) -> None:
        """Apply entity extension merge rules.

        - properties: concatenated (no name collisions)
        - vectorize: unioned
        - source: overridden if provided
        - key_field, collection: immutable
        """
        # Immutability checks
        if extension.key_field and extension.key_field != existing.key_field:
            raise OntologyMergeError(
                f"Cannot change key_field of entity '{name}': "
                f"'{existing.key_field}' → '{extension.key_field}'"
            )
        if extension.collection and extension.collection != existing.collection:
            raise OntologyMergeError(
                f"Cannot change collection name of entity '{name}': "
                f"'{existing.collection}' → '{extension.collection}'"
            )

        # Concatenate properties (check for name collisions)
        existing_prop_names = existing.get_property_names()
        for prop_dict in extension.properties:
            for prop_name in prop_dict:
                if prop_name in existing_prop_names:
                    raise OntologyMergeError(
                        f"Property '{prop_name}' already exists in entity "
                        f"'{name}'. Cannot override properties via extend."
                    )
            existing.properties.append(prop_dict)

        # Union vectorize fields
        existing.vectorize = list(set(existing.vectorize + extension.vectorize))

        # Override source if provided
        if extension.source:
            existing.source = extension.source

    # ── Relation merging ──

    def _merge_relations(
        self,
        target: dict[str, RelationDef],
        source: dict[str, RelationDef],
        entities: dict[str, EntityDef],
        source_path: Path,
    ) -> None:
        """Merge relations from a layer into the target dict."""
        for name, relation in source.items():
            if name in target:
                existing = target[name]
                # Validate endpoints haven't changed
                if (
                    relation.from_entity != existing.from_entity
                    or relation.to_entity != existing.to_entity
                ):
                    raise OntologyMergeError(
                        f"Relation '{name}' endpoints cannot change. "
                        f"Expected {existing.from_entity} → {existing.to_entity}, "
                        f"got {relation.from_entity} → {relation.to_entity} "
                        f"in {source_path}."
                    )
                # Concatenate discovery rules
                existing.discovery.rules.extend(relation.discovery.rules)
            else:
                # Validate that referenced entities exist
                self._validate_relation_endpoints(relation, entities, source_path)
                target[name] = relation.model_copy(deep=True)

    def _validate_relation_endpoints(
        self,
        relation: RelationDef,
        entities: dict[str, EntityDef],
        source_path: Path,
    ) -> None:
        """Check that from/to entities exist in the merged entity set."""
        if relation.from_entity not in entities:
            raise OntologyMergeError(
                f"Relation references unknown entity '{relation.from_entity}' "
                f"in {source_path}. Define the entity first."
            )
        if relation.to_entity not in entities:
            raise OntologyMergeError(
                f"Relation references unknown entity '{relation.to_entity}' "
                f"in {source_path}. Define the entity first."
            )

    # ── Pattern merging ──

    def _merge_patterns(
        self,
        target: dict[str, TraversalPattern],
        source: dict[str, TraversalPattern],
    ) -> None:
        """Merge traversal patterns from a layer into the target dict."""
        for name, pattern in source.items():
            if name in target:
                existing = target[name]
                # Concatenate trigger intents (dedup)
                existing.trigger_intents = list(
                    set(existing.trigger_intents + pattern.trigger_intents)
                )
                # Override template and post-action
                if pattern.query_template:
                    existing.query_template = pattern.query_template
                if pattern.post_action:
                    existing.post_action = pattern.post_action
                if pattern.post_query is not None:
                    existing.post_query = pattern.post_query
            else:
                target[name] = pattern.model_copy(deep=True)

    # ── Integrity validation ──

    def _validate_integrity(self, merged: MergedOntology) -> None:
        """Cross-validate the fully merged ontology.

        Checks:
            1. All relation endpoints reference existing entities.
            2. All vectorize fields reference existing entity properties.

        Raises:
            OntologyIntegrityError: If any check fails.
        """
        entity_names = set(merged.entities.keys())

        # Check relation endpoints
        for name, rel in merged.relations.items():
            if rel.from_entity not in entity_names:
                raise OntologyIntegrityError(
                    f"Relation '{name}' references unknown entity "
                    f"'{rel.from_entity}'"
                )
            if rel.to_entity not in entity_names:
                raise OntologyIntegrityError(
                    f"Relation '{name}' references unknown entity "
                    f"'{rel.to_entity}'"
                )

        # Check vectorize fields
        for name, entity in merged.entities.items():
            prop_names = entity.get_property_names()
            for vec_field in entity.vectorize:
                if vec_field not in prop_names:
                    raise OntologyIntegrityError(
                        f"Entity '{name}' vectorize field '{vec_field}' "
                        f"not found in properties: {sorted(prop_names)}"
                    )
