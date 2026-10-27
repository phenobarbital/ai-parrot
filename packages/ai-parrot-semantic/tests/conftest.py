"""Lightweight namespace setup; feature fixtures are imported by their consumers."""

from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]

for source_root in (PACKAGE_ROOT / "src", REPOSITORY_ROOT / "packages" / "ai-parrot" / "src"):
    source_root_str = str(source_root)
    if source_root_str not in sys.path:
        sys.path.insert(0, source_root_str)

semantic_namespace_root = str(PACKAGE_ROOT / "src" / "parrot")
parrot_package = sys.modules.get("parrot")
if parrot_package is not None and semantic_namespace_root not in parrot_package.__path__:
    parrot_package.__path__.insert(0, semantic_namespace_root)
