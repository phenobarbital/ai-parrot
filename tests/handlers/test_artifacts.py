"""Tests for Artifact CRUD views (TASK-724).

Verifies import and structure of artifact views.
"""

import pytest
from parrot.handlers.artifacts import ArtifactListView, ArtifactDetailView


class TestArtifactViewImports:
    """Verify artifact views can be imported and have expected methods."""

    def test_artifact_list_view_exists(self):
        assert ArtifactListView is not None

    def test_artifact_detail_view_exists(self):
        assert ArtifactDetailView is not None

    def test_list_view_has_get(self):
        assert hasattr(ArtifactListView, "get")

    def test_list_view_has_post(self):
        assert hasattr(ArtifactListView, "post")

    def test_detail_view_has_get(self):
        assert hasattr(ArtifactDetailView, "get")

    def test_detail_view_has_put(self):
        assert hasattr(ArtifactDetailView, "put")

    def test_detail_view_has_delete(self):
        assert hasattr(ArtifactDetailView, "delete")

    def test_list_view_logger_name(self):
        assert ArtifactListView._logger_name == "Parrot.ArtifactListView"

    def test_detail_view_logger_name(self):
        assert ArtifactDetailView._logger_name == "Parrot.ArtifactDetailView"
