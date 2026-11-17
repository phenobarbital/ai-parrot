"""Discover and parse expert bundles (FEAT-778 M2)."""

from __future__ import annotations

import importlib.resources
import logging
from pathlib import Path
from typing import Any, Final, Literal

import yaml

from parrot.bots.prompts.identity import IDENTITY_FILES, load_identity
from parrot.experts.models import ExpertBundle, ExpertBundleError, ExpertManifest
from parrot.experts.rules import parse_rules

EXPERTS_DIRNAME: Final[str] = "experts"
MANIFEST_FILENAME: Final[str] = "expert.yaml"
BUNDLED_EXPERTS_DIR: Final[Path] = Path(str(importlib.resources.files("parrot.experts.bundled")))
_LOGGER = logging.getLogger(__name__)


def parse_expert_bundle(
    bundle_dir: Path,
    *,
    tenant: str | None = None,
    origin: Literal["bundled", "workspace"] = "workspace",
) -> ExpertBundle:
    """Parse one expert bundle.

    Args:
        bundle_dir: Directory containing the expert manifest and bundle files.
        tenant: Optional tenant that owns this bundle overlay.
        origin: Root from which the bundle was discovered.

    Returns:
        The validated expert bundle.

    Raises:
        ExpertBundleError: If the manifest, identity, or governance rules are invalid.
    """
    manifest_path = bundle_dir / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ExpertBundleError(f"{bundle_dir}: missing {MANIFEST_FILENAME}")

    try:
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        manifest = ExpertManifest.model_validate(manifest_data)
    except Exception as exc:
        raise ExpertBundleError(f"{manifest_path}: {exc}") from exc

    if manifest.name != bundle_dir.name:
        raise ExpertBundleError(
            f"{manifest_path}: manifest name {manifest.name!r} does not match bundle directory {bundle_dir.name!r}"
        )

    identity_dir = bundle_dir / "identity"
    identity = load_identity(identity_dir)
    identity_values = identity.as_kwargs()
    if not identity_values:
        raise ExpertBundleError(f"{identity_dir}: identity has no readable field")
    for field_name in IDENTITY_FILES:
        value = identity_values.get(field_name)
        if value is not None and "$" in value:
            identity_path = identity_dir / f"{field_name}.md"
            raise ExpertBundleError(f"{identity_path}: identity placeholders containing '$' are not permitted")

    knowledge_dir = bundle_dir / "knowledge"
    knowledge_files = sorted(path for path in knowledge_dir.glob("*.md") if path.is_file())

    rules_path = bundle_dir / "rules" / "governance.md"
    if rules_path.is_file():
        try:
            rules = parse_rules(rules_path, layer="expert")
        except Exception as exc:
            raise ExpertBundleError(f"{rules_path}: {exc}") from exc
    else:
        rules = None
        _LOGGER.warning(
            "expert %s: no rules/governance.md — org/team/project rules still apply",
            manifest.name,
        )

    persona_path = bundle_dir / "persona.md"
    adr_path = bundle_dir / "adr"
    return ExpertBundle(
        manifest=manifest,
        root=bundle_dir,
        identity_dir=identity_dir,
        persona_doc=persona_path if persona_path.is_file() else None,
        knowledge_files=knowledge_files,
        rules=rules,
        adr_dir=adr_path if adr_path.is_dir() else None,
        tenant=tenant,
        origin=origin,
    )


def discover_expert_bundles(
    directory: Path,
    *,
    origin: Literal["bundled", "workspace"] = "workspace",
    logger: logging.Logger = _LOGGER,
) -> tuple[list[ExpertBundle], list[dict[str, Any]]]:
    """Discover valid expert bundles directly beneath one directory.

    Args:
        directory: Root directory to scan non-recursively.
        origin: Root from which the bundles are being discovered.
        logger: Logger used for malformed bundle warnings.

    Returns:
        A tuple of parsed bundles and reports for skipped malformed bundles.
    """
    bundles: list[ExpertBundle] = []
    skipped: list[dict[str, Any]] = []
    if not directory.is_dir():
        return bundles, skipped
    for entry in sorted(directory.iterdir()):
        if not entry.is_dir() or entry.name.startswith((".", "_")) or not (entry / MANIFEST_FILENAME).is_file():
            continue
        try:
            bundles.append(parse_expert_bundle(entry, origin=origin))
        except ExpertBundleError as exc:
            logger.warning("Skipping expert bundle %s: %s", entry, exc)
            skipped.append({"path": str(entry), "reason": str(exc)})
    return bundles, skipped
