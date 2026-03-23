"""
SkillRegistry Models for AI-Parrot Framework.

Git-like versioned skill/knowledge registry that allows:
- Agents to document learned skills and patterns
- Version control with unified diffs
- Skill discovery and retrieval
- Provenance tracking (who created/updated)
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
import hashlib
import uuid


class SkillStatus(str, Enum):
    """Lifecycle status of a skill."""
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REVOKED = "revoked"
    DRAFT = "draft"


class SkillCategory(str, Enum):
    """Categories for organizing skills."""
    TOOL_USAGE = "tool_usage"           # How to use specific tools
    WORKFLOW = "workflow"               # Multi-step processes
    DOMAIN_KNOWLEDGE = "domain"         # Domain-specific facts
    ERROR_HANDLING = "error_handling"   # How to handle specific errors
    USER_PREFERENCE = "user_preference" # User-specific patterns
    INTEGRATION = "integration"         # External system patterns
    OPTIMIZATION = "optimization"       # Performance/quality patterns
    GENERAL = "general"


class ContentType(str, Enum):
    """How the version content is stored."""
    FULL = "full"       # Complete content
    DELTA = "delta"     # Unified diff from previous version


@dataclass
class SkillMetadata:
    """Searchable metadata for a skill."""
    name: str
    description: str
    category: SkillCategory = SkillCategory.GENERAL
    tags: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)  # Patterns that activate this skill
    related_tools: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['category'] = self.category.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillMetadata":
        data = data.copy()
        if 'category' in data:
            data['category'] = SkillCategory(data['category'])
        return cls(**data)


@dataclass
class SkillVersion:
    """
    A single immutable version of a skill.
    
    Version 0: stores full content
    Version 1+: stores unified diff against previous version
    """
    version_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    skill_id: str = ""
    version_number: int = 0
    
    # Content storage
    content_type: ContentType = ContentType.FULL
    content: str = ""  # Full content or unified diff
    content_hash: str = ""  # SHA256 of reconstructed content
    
    # Provenance
    created_by: str = ""  # agent_id
    created_at: datetime = field(default_factory=datetime.now)
    commit_message: str = ""  # Why this version was created
    
    # Parent reference (for delta reconstruction)
    parent_version_id: Optional[str] = None
    
    def __post_init__(self):
        if not self.content_hash and self.content:
            self.content_hash = self._compute_hash(self.content)
    
    @staticmethod
    def _compute_hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['content_type'] = self.content_type.value
        data['created_at'] = self.created_at.isoformat()
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillVersion":
        data = data.copy()
        data['content_type'] = ContentType(data['content_type'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        return cls(**data)


@dataclass
class Skill:
    """
    A versioned skill/knowledge document.
    
    Contains metadata + version history.
    The actual content is stored in SkillVersion objects.
    """
    skill_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # Ownership
    namespace: str = "default"  # org_id/agent_id
    owner_agent_id: str = ""    # Original creator
    
    # Metadata (mutable, updated with latest version)
    metadata: SkillMetadata = field(default_factory=lambda: SkillMetadata(
        name="Untitled Skill",
        description=""
    ))
    
    # Status
    status: SkillStatus = SkillStatus.ACTIVE
    
    # Version tracking
    current_version: int = 0
    version_count: int = 0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Stats
    access_count: int = 0
    usefulness_score: float = 0.0  # Can be updated based on feedback
    
    # Vector embedding of current content (for search)
    embedding: Optional[List[float]] = field(default=None, repr=False)
    
    def to_dict(self) -> Dict[str, Any]:
        data = {
            'skill_id': self.skill_id,
            'namespace': self.namespace,
            'owner_agent_id': self.owner_agent_id,
            'metadata': self.metadata.to_dict(),
            'status': self.status.value,
            'current_version': self.current_version,
            'version_count': self.version_count,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'access_count': self.access_count,
            'usefulness_score': self.usefulness_score,
        }
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        data = data.copy()
        data['metadata'] = SkillMetadata.from_dict(data['metadata'])
        data['status'] = SkillStatus(data['status'])
        data['created_at'] = datetime.fromisoformat(data['created_at'])
        data['updated_at'] = datetime.fromisoformat(data['updated_at'])
        data.pop('embedding', None)
        return cls(**data)
    
    @property
    def searchable_text(self) -> str:
        """Text for embedding generation."""
        parts = [
            self.metadata.name,
            self.metadata.description,
            " ".join(self.metadata.tags),
            " ".join(self.metadata.triggers),
        ]
        return " | ".join(filter(None, parts))


@dataclass 
class SkillSearchResult:
    """Result from skill search."""
    skill: Skill
    content: str  # Reconstructed current content
    similarity_score: float
    relevance_score: float  # Combined score
    
    @property
    def summary(self) -> str:
        """Brief summary for context injection."""
        return f"[{self.skill.metadata.name}] {self.skill.metadata.description[:100]}"


# Pydantic schemas for tool arguments

class UploadSkillArgs(BaseModel):
    """Arguments for uploading/updating a skill."""
    name: str = Field(..., description="Skill name (human readable)")
    content: str = Field(..., description="Full skill content in Markdown")
    description: str = Field(default="", description="Brief description of what this skill does")
    category: str = Field(default="general", description="Category: tool_usage, workflow, domain, error_handling, etc.")
    tags: List[str] = Field(default_factory=list, description="Tags for search")
    triggers: List[str] = Field(default_factory=list, description="Patterns that should activate this skill")
    commit_message: str = Field(default="", description="Why this version was created")
    skill_id: Optional[str] = Field(default=None, description="Existing skill_id to update, or None for new")


class SearchSkillArgs(BaseModel):
    """Arguments for searching skills."""
    query: str = Field(..., description="Search query")
    category: Optional[str] = Field(default=None, description="Filter by category")
    tags: Optional[List[str]] = Field(default=None, description="Filter by tags (any match)")
    include_deprecated: bool = Field(default=False, description="Include deprecated skills")
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum results")


class ReadSkillArgs(BaseModel):
    """Arguments for reading a skill."""
    skill_id: str = Field(..., description="Skill ID to read")
    version: Optional[int] = Field(default=None, description="Specific version, or None for latest")


class SkillVersionsArgs(BaseModel):
    """Arguments for listing skill versions."""
    skill_id: str = Field(..., description="Skill ID")


class DeprecateSkillArgs(BaseModel):
    """Arguments for deprecating a skill."""
    skill_id: str = Field(..., description="Skill ID to deprecate")
    reason: str = Field(default="", description="Reason for deprecation")


# Structured output for skill extraction

class ExtractedSkill(BaseModel):
    """LLM-extracted skill from conversation."""
    name: str = Field(..., description="Concise skill name")
    description: str = Field(..., description="What this skill does (1-2 sentences)")
    content: str = Field(..., description="Full skill content in Markdown format")
    category: str = Field(default="general", description="Skill category")
    tags: List[str] = Field(default_factory=list, description="Relevant tags")
    triggers: List[str] = Field(default_factory=list, description="When to use this skill")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence this is worth saving")