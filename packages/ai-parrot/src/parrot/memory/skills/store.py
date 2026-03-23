"""
SkillRegistry - Git-like versioned skill/knowledge store.

Provides:
- Skill CRUD with automatic versioning
- Unified diff storage for efficiency
- Vector search for skill discovery
- Auto-extraction of skills from conversations
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, Union
import asyncio
import difflib
import json
from datetime import datetime
from pathlib import Path
import numpy as np
from navconfig.logging import logging

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    faiss = None

try:
    from redis.asyncio import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None

from .models import (
    Skill,
    SkillVersion,
    SkillMetadata,
    SkillCategory,
    SkillStatus,
    ContentType,
    SkillSearchResult,
    ExtractedSkill,
)


def compute_unified_diff(old_content: str, new_content: str, context_lines: int = 3) -> str:
    """Compute unified diff between two versions."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile='previous',
        tofile='current',
        n=context_lines,
    )
    return ''.join(diff)


def apply_unified_diff(base_content: str, diff_content: str) -> str:
    """Apply unified diff to reconstruct content."""
    # Simple implementation - for production, use patch library
    base_lines = base_content.splitlines(keepends=True)
    result_lines = []
    
    diff_lines = diff_content.splitlines(keepends=True)
    i = 0
    base_idx = 0
    
    while i < len(diff_lines):
        line = diff_lines[i]
        
        # Skip header lines
        if line.startswith('---') or line.startswith('+++'):
            i += 1
            continue
        
        # Parse hunk header
        if line.startswith('@@'):
            # @@ -start,count +start,count @@
            parts = line.split()
            old_range = parts[1]  # -start,count
            old_start = int(old_range.split(',')[0][1:]) - 1
            
            # Add unchanged lines before this hunk
            while base_idx < old_start and base_idx < len(base_lines):
                result_lines.append(base_lines[base_idx])
                base_idx += 1
            
            i += 1
            continue
        
        if line.startswith('-'):
            # Removed line - skip in base
            base_idx += 1
            i += 1
        elif line.startswith('+'):
            # Added line - add to result
            result_lines.append(line[1:])
            i += 1
        elif line.startswith(' '):
            # Context line
            result_lines.append(line[1:])
            base_idx += 1
            i += 1
        else:
            i += 1
    
    # Add remaining base lines
    while base_idx < len(base_lines):
        result_lines.append(base_lines[base_idx])
        base_idx += 1
    
    return ''.join(result_lines)


class SkillRegistry:
    """
    Git-like versioned skill registry.
    
    Features:
    - Create/update skills with automatic versioning
    - Store diffs for space efficiency
    - Reconstruct any historical version
    - Vector search for skill discovery
    - Agent-driven skill extraction
    """
    
    def __init__(
        self,
        namespace: str = "default",
        embedding_model: Union[str, Any] = "sentence-transformers/all-mpnet-base-v2",
        dimension: int = 768,
        redis_url: Optional[str] = None,
        persistence_path: Optional[Path] = None,
        extraction_llm: Optional[Any] = None,
        min_diff_threshold: int = 50,  # Min chars changed to create new version
    ):
        """
        Initialize SkillRegistry.
        
        Args:
            namespace: Namespace for skill isolation (org_id/agent_id)
            embedding_model: Model for vector search
            dimension: Embedding dimension
            redis_url: Redis URL for storage
            persistence_path: Path for file-based persistence
            extraction_llm: LLM for auto-extracting skills
            min_diff_threshold: Minimum change size to create version
        """
        self.logger = logging.getLogger(f"parrot.skills.{self.__class__.__name__}")
        self.namespace = namespace
        self.min_diff_threshold = min_diff_threshold
        
        # Embedding
        self._embedding_model_name = embedding_model
        self._embedding_model = None
        self.dimension = dimension
        
        # Storage
        self.redis_url = redis_url
        self._redis: Optional[Redis] = None
        self._use_redis = bool(redis_url) and REDIS_AVAILABLE
        
        # In-memory storage
        self._skills: Dict[str, Skill] = {}
        self._versions: Dict[str, List[SkillVersion]] = {}  # skill_id -> versions
        
        # FAISS index for search
        self._faiss_index: Optional[Any] = None
        self._skill_ids: List[str] = []  # Maps index position to skill_id
        
        # Persistence
        self.persistence_path = Path(persistence_path) if persistence_path else None
        
        # Extraction LLM
        self._extraction_llm = extraction_llm
        
        # State
        self._configured = False
        self._lock = asyncio.Lock()
    
    async def configure(
        self,
        extraction_llm: Optional[Any] = None,
        embedding_model: Optional[Any] = None,
    ) -> None:
        """Configure the registry."""
        if self._configured:
            return
        
        self.logger.info("Configuring SkillRegistry...")
        
        # Initialize embedding model
        if embedding_model:
            self._embedding_model = embedding_model
        elif isinstance(self._embedding_model_name, str):
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer(self._embedding_model_name)
                self.dimension = self._embedding_model.get_sentence_embedding_dimension()
            except ImportError:
                self.logger.warning("sentence-transformers not available")
        
        # Initialize FAISS
        if FAISS_AVAILABLE:
            self._faiss_index = faiss.IndexFlatIP(self.dimension)
            self.logger.info(f"FAISS index created, dim={self.dimension}")
        
        # Initialize Redis
        if self._use_redis:
            try:
                self._redis = Redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5,
                )
                await self._redis.ping()
                self.logger.info("Redis connected")
            except Exception as e:
                self.logger.warning(f"Redis failed: {e}, using in-memory")
                self._use_redis = False
        
        # Load persisted data
        if self.persistence_path and self.persistence_path.exists():
            await self._load_from_disk()
        
        if extraction_llm:
            self._extraction_llm = extraction_llm
        
        self._configured = True
        self.logger.info(f"SkillRegistry configured: {len(self._skills)} skills loaded")
    
    async def _embed(self, text: str) -> np.ndarray:
        """Generate embedding."""
        if self._embedding_model is None:
            raise RuntimeError("Embedding model not configured")
        
        if hasattr(self._embedding_model, 'encode'):
            embedding = self._embedding_model.encode(
                [text],
                convert_to_numpy=True,
                normalize_embeddings=True,
            )
            return embedding[0].astype(np.float32)
        elif callable(self._embedding_model):
            embedding = await self._embedding_model(text)
            return np.array(embedding, dtype=np.float32)
        else:
            raise RuntimeError(f"Unknown embedding model: {type(self._embedding_model)}")
    
    async def upload_skill(
        self,
        name: str,
        content: str,
        agent_id: str,
        description: str = "",
        category: Union[SkillCategory, str] = SkillCategory.GENERAL,
        tags: Optional[List[str]] = None,
        triggers: Optional[List[str]] = None,
        related_tools: Optional[List[str]] = None,
        commit_message: str = "",
        skill_id: Optional[str] = None,
    ) -> Tuple[Skill, SkillVersion]:
        """
        Upload a new skill or new version of existing skill.
        
        Args:
            name: Skill name
            content: Full skill content (Markdown)
            agent_id: Creating agent
            description: Brief description
            category: Skill category
            tags: Searchable tags
            triggers: Activation patterns
            related_tools: Tools this skill uses
            commit_message: Why this version was created
            skill_id: Existing skill to update (None for new)
            
        Returns:
            Tuple of (Skill, SkillVersion)
        """
        if not self._configured:
            await self.configure()
        
        async with self._lock:
            # Normalize category
            if isinstance(category, str):
                category = SkillCategory(category.lower())
            
            # Check if updating existing skill
            existing_skill = None
            if skill_id and skill_id in self._skills:
                existing_skill = self._skills[skill_id]
            
            if existing_skill:
                # Update existing skill
                return await self._create_new_version(
                    skill=existing_skill,
                    content=content,
                    agent_id=agent_id,
                    name=name,
                    description=description,
                    category=category,
                    tags=tags,
                    triggers=triggers,
                    related_tools=related_tools,
                    commit_message=commit_message,
                )
            else:
                # Create new skill
                return await self._create_new_skill(
                    content=content,
                    agent_id=agent_id,
                    name=name,
                    description=description,
                    category=category,
                    tags=tags or [],
                    triggers=triggers or [],
                    related_tools=related_tools or [],
                    commit_message=commit_message,
                )
    
    async def _create_new_skill(
        self,
        content: str,
        agent_id: str,
        name: str,
        description: str,
        category: SkillCategory,
        tags: List[str],
        triggers: List[str],
        related_tools: List[str],
        commit_message: str,
    ) -> Tuple[Skill, SkillVersion]:
        """Create a new skill with version 0."""
        # Create metadata
        metadata = SkillMetadata(
            name=name,
            description=description,
            category=category,
            tags=tags,
            triggers=triggers,
            related_tools=related_tools,
        )
        
        # Create skill
        skill = Skill(
            namespace=self.namespace,
            owner_agent_id=agent_id,
            metadata=metadata,
            status=SkillStatus.ACTIVE,
            current_version=0,
            version_count=1,
        )
        
        # Create version 0 (full content)
        version = SkillVersion(
            skill_id=skill.skill_id,
            version_number=0,
            content_type=ContentType.FULL,
            content=content,
            created_by=agent_id,
            commit_message=commit_message or "Initial version",
        )
        
        # Generate embedding
        embedding = await self._embed(skill.searchable_text + " " + content[:500])
        skill.embedding = embedding.tolist()
        
        # Store
        self._skills[skill.skill_id] = skill
        self._versions[skill.skill_id] = [version]
        
        # Update FAISS
        if self._faiss_index is not None:
            faiss.normalize_L2(embedding.reshape(1, -1))
            self._faiss_index.add(embedding.reshape(1, -1))
            self._skill_ids.append(skill.skill_id)
        
        # Persist
        await self._persist_skill(skill)
        await self._persist_version(version)
        
        self.logger.info(f"Created skill: {skill.skill_id} ({name}) v0")
        return skill, version
    
    async def _create_new_version(
        self,
        skill: Skill,
        content: str,
        agent_id: str,
        name: str,
        description: str,
        category: SkillCategory,
        tags: Optional[List[str]],
        triggers: Optional[List[str]],
        related_tools: Optional[List[str]],
        commit_message: str,
    ) -> Tuple[Skill, SkillVersion]:
        """Create new version of existing skill."""
        # Get current content
        current_content = await self.read_skill(skill.skill_id)
        
        # Check if change is significant
        diff = compute_unified_diff(current_content, content)
        if len(diff) < self.min_diff_threshold and current_content.strip() == content.strip():
            self.logger.debug(f"No significant changes for {skill.skill_id}")
            latest_version = self._versions[skill.skill_id][-1]
            return skill, latest_version
        
        # Update metadata
        skill.metadata.name = name
        if description:
            skill.metadata.description = description
        skill.metadata.category = category
        if tags is not None:
            skill.metadata.tags = tags
        if triggers is not None:
            skill.metadata.triggers = triggers
        if related_tools is not None:
            skill.metadata.related_tools = related_tools
        
        # Create new version with diff
        new_version_number = skill.current_version + 1
        prev_version = self._versions[skill.skill_id][-1]
        
        version = SkillVersion(
            skill_id=skill.skill_id,
            version_number=new_version_number,
            content_type=ContentType.DELTA,
            content=diff,
            created_by=agent_id,
            commit_message=commit_message or f"Update v{new_version_number}",
            parent_version_id=prev_version.version_id,
        )
        # Set hash of reconstructed content
        version.content_hash = SkillVersion._compute_hash(content)
        
        # Update skill
        skill.current_version = new_version_number
        skill.version_count += 1
        skill.updated_at = datetime.now()
        
        # Update embedding
        embedding = await self._embed(skill.searchable_text + " " + content[:500])
        skill.embedding = embedding.tolist()
        
        # Store version
        self._versions[skill.skill_id].append(version)
        
        # Update FAISS (replace embedding)
        await self._update_faiss_embedding(skill.skill_id, embedding)
        
        # Persist
        await self._persist_skill(skill)
        await self._persist_version(version)
        
        self.logger.info(
            f"Created version {new_version_number} for {skill.skill_id} ({name})"
        )
        return skill, version
    
    async def read_skill(
        self,
        skill_id: str,
        version: Optional[int] = None,
    ) -> str:
        """
        Read skill content, reconstructing from diffs if needed.
        
        Args:
            skill_id: Skill to read
            version: Specific version (None for latest)
            
        Returns:
            Reconstructed content
        """
        if skill_id not in self._skills:
            raise KeyError(f"Skill not found: {skill_id}")
        
        versions = self._versions.get(skill_id, [])
        if not versions:
            raise KeyError(f"No versions for skill: {skill_id}")
        
        # Determine target version
        target_version = version if version is not None else self._skills[skill_id].current_version
        
        # Filter versions up to target
        relevant_versions = [v for v in versions if v.version_number <= target_version]
        relevant_versions.sort(key=lambda v: v.version_number)
        
        # Reconstruct content
        content = ""
        for v in relevant_versions:
            if v.content_type == ContentType.FULL:
                content = v.content
            else:
                content = apply_unified_diff(content, v.content)
        
        # Update access count
        skill = self._skills[skill_id]
        skill.access_count += 1
        
        return content
    
    async def search_skills(
        self,
        query: str,
        category: Optional[SkillCategory] = None,
        tags: Optional[List[str]] = None,
        include_deprecated: bool = False,
        max_results: int = 5,
    ) -> List[SkillSearchResult]:
        """
        Search for relevant skills.
        
        Args:
            query: Search query
            category: Filter by category
            tags: Filter by tags (any match)
            include_deprecated: Include deprecated skills
            max_results: Maximum results
            
        Returns:
            List of SkillSearchResult
        """
        if not self._configured:
            await self.configure()
        
        if self._faiss_index is None or self._faiss_index.ntotal == 0:
            return []
        
        # Generate query embedding
        query_embedding = await self._embed(query)
        faiss.normalize_L2(query_embedding.reshape(1, -1))
        
        # Search
        search_k = min(max_results * 3, self._faiss_index.ntotal)
        distances, indices = self._faiss_index.search(
            query_embedding.reshape(1, -1),
            search_k,
        )
        
        results: List[SkillSearchResult] = []
        
        for idx, distance in zip(indices[0], distances[0]):
            if idx < 0 or idx >= len(self._skill_ids):
                continue
            
            skill_id = self._skill_ids[idx]
            skill = self._skills.get(skill_id)
            
            if skill is None:
                continue
            
            # Apply filters
            if not include_deprecated and skill.status == SkillStatus.DEPRECATED:
                continue
            if skill.status == SkillStatus.REVOKED:
                continue
            if category and skill.metadata.category != category:
                continue
            if tags and not any(t in skill.metadata.tags for t in tags):
                continue
            
            # Get content
            content = await self.read_skill(skill_id)
            
            # Calculate relevance
            similarity = float(distance)
            usefulness = skill.usefulness_score
            relevance = 0.7 * similarity + 0.3 * (usefulness / 10.0)
            
            results.append(SkillSearchResult(
                skill=skill,
                content=content,
                similarity_score=similarity,
                relevance_score=relevance,
            ))
            
            if len(results) >= max_results:
                break
        
        results.sort(key=lambda x: x.relevance_score, reverse=True)
        return results
    
    async def get_skill_versions(
        self,
        skill_id: str,
    ) -> List[Dict[str, Any]]:
        """Get version history for a skill."""
        if skill_id not in self._versions:
            return []
        
        versions = []
        for v in self._versions[skill_id]:
            versions.append({
                "version_id": v.version_id,
                "version_number": v.version_number,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat(),
                "commit_message": v.commit_message,
                "content_type": v.content_type.value,
                "content_hash": v.content_hash,
            })
        return versions
    
    async def deprecate_skill(
        self,
        skill_id: str,
        reason: str = "",
    ) -> Skill:
        """Mark skill as deprecated."""
        if skill_id not in self._skills:
            raise KeyError(f"Skill not found: {skill_id}")
        
        skill = self._skills[skill_id]
        skill.status = SkillStatus.DEPRECATED
        skill.updated_at = datetime.now()
        
        await self._persist_skill(skill)
        self.logger.info(f"Deprecated skill: {skill_id} - {reason}")
        return skill
    
    async def revoke_skill(
        self,
        skill_id: str,
        reason: str = "",
    ) -> Skill:
        """Mark skill as revoked (do not use)."""
        if skill_id not in self._skills:
            raise KeyError(f"Skill not found: {skill_id}")
        
        skill = self._skills[skill_id]
        skill.status = SkillStatus.REVOKED
        skill.updated_at = datetime.now()
        
        await self._persist_skill(skill)
        self.logger.info(f"Revoked skill: {skill_id} - {reason}")
        return skill
    
    async def extract_skill_from_conversation(
        self,
        conversation: str,
        agent_id: str,
        context: Optional[str] = None,
    ) -> Optional[Tuple[Skill, SkillVersion]]:
        """
        Use LLM to extract a skill from conversation.
        
        Args:
            conversation: Conversation text to analyze
            agent_id: Agent doing the extraction
            context: Additional context
            
        Returns:
            Created Skill and Version, or None if nothing worth saving
        """
        if not self._extraction_llm:
            self.logger.warning("No extraction LLM configured")
            return None
        
        prompt = f"""Analyze this conversation and determine if there's a reusable skill or pattern worth documenting.

CONVERSATION:
{conversation[:3000]}

{f"CONTEXT: {context}" if context else ""}

If there's a valuable skill or pattern, extract it. Consider:
- Tool usage patterns that worked well
- Problem-solving approaches
- Domain knowledge discovered
- Error handling strategies

Respond with JSON:
{{
    "name": "skill name",
    "description": "brief description",
    "content": "full skill documentation in Markdown",
    "category": "tool_usage|workflow|domain|error_handling|general",
    "tags": ["tag1", "tag2"],
    "triggers": ["when to use this skill"],
    "confidence": 0.0-1.0
}}

If nothing worth saving, respond with {{"confidence": 0.0}}"""
        
        try:
            response = await self._extraction_llm.ask(
                prompt=prompt,
                structured_output=ExtractedSkill,
                temperature=0.3,
                max_tokens=2000,
            )
            
            extracted = None
            if hasattr(response, 'output') and isinstance(response.output, ExtractedSkill):
                extracted = response.output
            else:
                # Parse from JSON
                content = response.content if hasattr(response, 'content') else str(response)
                data = json.loads(content)
                extracted = ExtractedSkill(**data)
            
            if extracted.confidence < 0.5:
                self.logger.debug("Extraction confidence too low")
                return None
            
            # Create the skill
            return await self.upload_skill(
                name=extracted.name,
                content=extracted.content,
                agent_id=agent_id,
                description=extracted.description,
                category=extracted.category,
                tags=extracted.tags,
                triggers=extracted.triggers,
                commit_message="Auto-extracted from conversation",
            )
            
        except Exception as e:
            self.logger.warning(f"Skill extraction failed: {e}")
            return None
    
    async def get_relevant_skills(
        self,
        query: str,
        max_skills: int = 3,
        max_tokens: int = 2000,
    ) -> str:
        """
        Get relevant skills formatted for context injection.
        
        Returns formatted Markdown suitable for system prompt.
        """
        results = await self.search_skills(query, max_results=max_skills)
        
        if not results:
            return ""
        
        sections = ["<relevant_skills>"]
        tokens_used = 0
        
        for r in results:
            skill_section = f"""
### {r.skill.metadata.name}
{r.skill.metadata.description}

{r.content[:1000]}
"""
            section_tokens = len(skill_section) // 4  # Rough estimate
            if tokens_used + section_tokens > max_tokens:
                break
            
            sections.append(skill_section)
            tokens_used += section_tokens
        
        sections.append("</relevant_skills>")
        return "\n".join(sections)
    
    async def list_skills(
        self,
        include_deprecated: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all skills with summary info."""
        skills = []
        for skill in self._skills.values():
            if not include_deprecated and skill.status == SkillStatus.DEPRECATED:
                continue
            if skill.status == SkillStatus.REVOKED:
                continue
            
            skills.append({
                "skill_id": skill.skill_id,
                "name": skill.metadata.name,
                "description": skill.metadata.description,
                "category": skill.metadata.category.value,
                "tags": skill.metadata.tags,
                "status": skill.status.value,
                "version_count": skill.version_count,
                "current_version": skill.current_version,
                "access_count": skill.access_count,
            })
        return skills
    
    async def _update_faiss_embedding(
        self,
        skill_id: str,
        embedding: np.ndarray,
    ) -> None:
        """Update embedding in FAISS (rebuild index for simplicity)."""
        if self._faiss_index is None:
            return
        
        # Find index
        if skill_id in self._skill_ids:
            idx = self._skill_ids.index(skill_id)
            # FAISS doesn't support in-place updates easily
            # For production, consider using IndexIDMap
            # For now, we just add (duplicates handled by search filtering)
        
        faiss.normalize_L2(embedding.reshape(1, -1))
        self._faiss_index.add(embedding.reshape(1, -1))
        if skill_id not in self._skill_ids:
            self._skill_ids.append(skill_id)
    
    async def _persist_skill(self, skill: Skill) -> None:
        """Persist skill to storage."""
        if self._use_redis and self._redis:
            key = f"skill:{self.namespace}:{skill.skill_id}"
            await self._redis.hset(key, "data", json.dumps(skill.to_dict()))
        
        if self.persistence_path:
            await self._save_to_disk()
    
    async def _persist_version(self, version: SkillVersion) -> None:
        """Persist version to storage."""
        if self._use_redis and self._redis:
            key = f"skill_version:{self.namespace}:{version.skill_id}:{version.version_id}"
            await self._redis.set(key, json.dumps(version.to_dict()))
    
    async def _save_to_disk(self) -> None:
        """Save all data to disk."""
        if not self.persistence_path:
            return
        
        self.persistence_path.mkdir(parents=True, exist_ok=True)
        
        # Save skills
        skills_file = self.persistence_path / "skills.json"
        with open(skills_file, 'w') as f:
            json.dump({k: v.to_dict() for k, v in self._skills.items()}, f, indent=2)
        
        # Save versions
        versions_file = self.persistence_path / "versions.json"
        versions_data = {}
        for skill_id, versions in self._versions.items():
            versions_data[skill_id] = [v.to_dict() for v in versions]
        with open(versions_file, 'w') as f:
            json.dump(versions_data, f, indent=2)
    
    async def _load_from_disk(self) -> None:
        """Load data from disk."""
        if not self.persistence_path:
            return
        
        skills_file = self.persistence_path / "skills.json"
        versions_file = self.persistence_path / "versions.json"
        
        if skills_file.exists():
            with open(skills_file, 'r') as f:
                data = json.load(f)
                self._skills = {k: Skill.from_dict(v) for k, v in data.items()}
        
        if versions_file.exists():
            with open(versions_file, 'r') as f:
                data = json.load(f)
                self._versions = {}
                for skill_id, versions in data.items():
                    self._versions[skill_id] = [
                        SkillVersion.from_dict(v) for v in versions
                    ]
        
        # Rebuild FAISS index
        if self._faiss_index is not None and self._skills:
            for skill_id, skill in self._skills.items():
                if skill.embedding:
                    embedding = np.array(skill.embedding, dtype=np.float32)
                    faiss.normalize_L2(embedding.reshape(1, -1))
                    self._faiss_index.add(embedding.reshape(1, -1))
                    self._skill_ids.append(skill_id)
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        await self._save_to_disk()
        if self._redis:
            await self._redis.close()
        self._configured = False


def create_skill_registry(
    namespace: str,
    persistence_path: Optional[str] = None,
    redis_url: Optional[str] = None,
    **kwargs,
) -> SkillRegistry:
    """Factory function for SkillRegistry."""
    if persistence_path is None:
        persistence_path = Path.home() / ".parrot" / "skills" / namespace
    
    return SkillRegistry(
        namespace=namespace,
        persistence_path=Path(persistence_path),
        redis_url=redis_url,
        **kwargs,
    )