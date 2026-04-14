"""Pydantic models for Backstage Catalog API responses."""

from typing import Any, Optional
from pydantic import BaseModel, Field


class EntityMeta(BaseModel):
    """Backstage entity metadata."""
    uid: Optional[str] = None
    etag: Optional[str] = None
    name: str = Field(..., description="Entity name")
    namespace: str = Field(default="default", description="Entity namespace")
    title: Optional[str] = None
    description: Optional[str] = None
    labels: Optional[dict[str, str]] = None
    annotations: Optional[dict[str, str]] = None
    tags: Optional[list[str]] = None
    links: Optional[list[dict[str, Any]]] = None


class EntityRelation(BaseModel):
    """Relationship between entities."""
    type: str = Field(..., description="Relation type (e.g. ownedBy, dependsOn)")
    targetRef: str = Field(..., description="Target entity reference")


class Entity(BaseModel):
    """Backstage catalog entity."""
    apiVersion: str = Field(default="backstage.io/v1alpha1")
    kind: str = Field(..., description="Entity kind (Component, API, System, etc.)")
    metadata: EntityMeta
    spec: Optional[dict[str, Any]] = None
    relations: Optional[list[EntityRelation]] = None


class EntitiesQueryResponse(BaseModel):
    """Paginated entity query response."""
    items: list[Entity] = Field(default_factory=list)
    totalItems: int = 0
    pageInfo: Optional[dict[str, Any]] = None


class EntityFacet(BaseModel):
    """A single facet value with its count."""
    value: str
    count: int


class EntityFacetsResponse(BaseModel):
    """Response from entity-facets endpoint."""
    facets: dict[str, list[EntityFacet]] = Field(default_factory=dict)


class Location(BaseModel):
    """Backstage catalog location."""
    id: Optional[str] = None
    type: str = Field(..., description="Location type (e.g. url)")
    target: str = Field(..., description="Location target (e.g. URL to catalog-info.yaml)")


class LocationResponse(BaseModel):
    """Response from location registration."""
    location: Location
    entities: list[Entity] = Field(default_factory=list)
