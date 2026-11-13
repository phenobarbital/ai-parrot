"""Finding → inferred decision (FEAT-890 M10)."""
from __future__ import annotations

import logging
from pathlib import Path

from parrot.experts.contributions import load_contribution
from parrot.knowledge.wiki.decisions.service import DecisionService

logger = logging.getLogger(__name__)


async def promote_finding(contribution_path: Path, finding_id: str, *, repo_root: Path) -> str:
    """Return the created decision id; raises ValueError unless the finding is confirmed.
    
    Args:
        contribution_path: Path to the contribution JSON file
        finding_id: ID of the finding to promote
        repo_root: Repository root path
        
    Returns:
        The decision ID of the created inferred decision
        
    Raises:
        ValueError: If the finding is not confirmed or doesn't exist
    """
    # Load the contribution
    contribution = load_contribution(contribution_path)
    
    # Find the specified finding
    finding = None
    for f in contribution.findings:
        if f.id == finding_id:
            finding = f
            break
    
    if finding is None:
        raise ValueError(f"Finding {finding_id} not found in contribution")
    
    # Check that the finding is confirmed
    if finding.status != "confirm":
        raise ValueError(f"Finding {finding_id} is not confirmed (status: {finding.status})")
    
    # Create a DecisionService instance
    # We need to get the store, config, etc. from the repository
    from parrot.knowledge.wiki.store import create_wiki_store
    from parrot.knowledge.wiki.decisions.models import DecisionConfig
    
    store = create_wiki_store(storage_dir=repo_root / "knowledge")
    config = DecisionConfig()
    
    # Try to determine the target for the decision
    # For now, we'll use the document path as the target
    target = contribution.doc_path
    
    decision_service = DecisionService(
        store=store,
        root=repo_root,
        config=config
    )
    
    # Generate the inferred decision
    result = await decision_service.generate(target)
    
    # If we successfully generated decisions, return the first one
    if result.decision_ids:
        return result.decision_ids[0]
    
    # If we reused existing decisions, return the first reused one
    if result.reused:
        return result.reused[0]
    
    # If neither, we couldn't create a decision
    raise ValueError("Failed to create inferred decision for finding")