"""
Tests for DatasetManager Request/Response Models
=================================================

Unit tests for the Pydantic models used by DatasetManagerHandler endpoints.
"""
import pytest
from pydantic import ValidationError

from parrot.models.datasets import (
    DatasetAction,
    DatasetPatchRequest,
    DatasetQueryRequest,
    DatasetListResponse,
    DatasetUploadResponse,
    DatasetDeleteResponse,
    DatasetErrorResponse,
)


# =============================================================================
# DATASET ACTION ENUM TESTS
# =============================================================================


class TestDatasetAction:
    """Tests for DatasetAction enum."""

    def test_activate_value(self):
        """ACTIVATE should have value 'activate'."""
        assert DatasetAction.ACTIVATE.value == "activate"

    def test_deactivate_value(self):
        """DEACTIVATE should have value 'deactivate'."""
        assert DatasetAction.DEACTIVATE.value == "deactivate"

    def test_enum_is_string(self):
        """DatasetAction should be a string enum."""
        assert isinstance(DatasetAction.ACTIVATE, str)
        assert isinstance(DatasetAction.DEACTIVATE, str)

    def test_enum_from_string(self):
        """Should be able to create enum from string value."""
        assert DatasetAction("activate") == DatasetAction.ACTIVATE
        assert DatasetAction("deactivate") == DatasetAction.DEACTIVATE


# =============================================================================
# DATASET PATCH REQUEST TESTS
# =============================================================================


class TestDatasetPatchRequest:
    """Tests for DatasetPatchRequest model."""

    def test_valid_activate_request(self):
        """Valid request with ACTIVATE action."""
        req = DatasetPatchRequest(
            dataset_name="sales_data",
            action=DatasetAction.ACTIVATE,
        )
        assert req.dataset_name == "sales_data"
        assert req.action == DatasetAction.ACTIVATE

    def test_valid_deactivate_request(self):
        """Valid request with DEACTIVATE action."""
        req = DatasetPatchRequest(
            dataset_name="old_data",
            action=DatasetAction.DEACTIVATE,
        )
        assert req.action == DatasetAction.DEACTIVATE

    def test_action_from_string(self):
        """Action can be provided as string."""
        req = DatasetPatchRequest(
            dataset_name="test",
            action="activate",
        )
        assert req.action == "activate"

    def test_missing_dataset_name_fails(self):
        """Missing dataset_name should raise ValidationError."""
        with pytest.raises(ValidationError):
            DatasetPatchRequest(action=DatasetAction.ACTIVATE)

    def test_missing_action_fails(self):
        """Missing action should raise ValidationError."""
        with pytest.raises(ValidationError):
            DatasetPatchRequest(dataset_name="test")

    def test_invalid_action_fails(self):
        """Invalid action value should raise ValidationError."""
        with pytest.raises(ValidationError):
            DatasetPatchRequest(
                dataset_name="test",
                action="invalid_action",
            )


# =============================================================================
# DATASET QUERY REQUEST TESTS
# =============================================================================


class TestDatasetQueryRequest:
    """Tests for DatasetQueryRequest model."""

    def test_valid_with_query(self):
        """Valid request with raw SQL query."""
        req = DatasetQueryRequest(
            name="sales",
            query="SELECT * FROM sales",
        )
        assert req.name == "sales"
        assert req.query == "SELECT * FROM sales"
        assert req.query_slug is None
        req.validate_query_source()  # Should not raise

    def test_valid_with_slug(self):
        """Valid request with query slug."""
        req = DatasetQueryRequest(
            name="sales",
            query_slug="sales_monthly",
        )
        assert req.query_slug == "sales_monthly"
        assert req.query is None
        req.validate_query_source()  # Should not raise

    def test_description_optional(self):
        """Description should be optional with empty default."""
        req = DatasetQueryRequest(
            name="test",
            query="SELECT 1",
        )
        assert req.description == ""

    def test_description_provided(self):
        """Description can be provided."""
        req = DatasetQueryRequest(
            name="test",
            query="SELECT 1",
            description="Test dataset",
        )
        assert req.description == "Test dataset"

    def test_neither_query_nor_slug_fails_validation(self):
        """Neither query nor slug should fail validation."""
        req = DatasetQueryRequest(name="test")
        with pytest.raises(ValueError, match="Either 'query' or 'query_slug'"):
            req.validate_query_source()

    def test_both_query_and_slug_fails_validation(self):
        """Both query and slug should fail validation."""
        req = DatasetQueryRequest(
            name="test",
            query="SELECT 1",
            query_slug="some_slug",
        )
        with pytest.raises(ValueError, match="not both"):
            req.validate_query_source()

    def test_missing_name_fails(self):
        """Missing name should raise ValidationError."""
        with pytest.raises(ValidationError):
            DatasetQueryRequest(query="SELECT 1")


# =============================================================================
# DATASET LIST RESPONSE TESTS
# =============================================================================


class TestDatasetListResponse:
    """Tests for DatasetListResponse model."""

    def test_valid_response(self):
        """Valid response with datasets."""
        resp = DatasetListResponse(
            datasets=[
                {"name": "df1", "rows": 100, "active": True},
                {"name": "df2", "rows": 200, "active": False},
            ],
            total=2,
            active_count=1,
        )
        assert resp.total == 2
        assert resp.active_count == 1
        assert len(resp.datasets) == 2

    def test_empty_datasets(self):
        """Response with no datasets."""
        resp = DatasetListResponse(
            datasets=[],
            total=0,
            active_count=0,
        )
        assert resp.datasets == []
        assert resp.total == 0

    def test_missing_fields_fails(self):
        """Missing required fields should fail."""
        with pytest.raises(ValidationError):
            DatasetListResponse(datasets=[])


# =============================================================================
# DATASET UPLOAD RESPONSE TESTS
# =============================================================================


class TestDatasetUploadResponse:
    """Tests for DatasetUploadResponse model."""

    def test_valid_response(self):
        """Valid upload response."""
        resp = DatasetUploadResponse(
            name="uploaded_file",
            rows=500,
            columns=10,
            columns_list=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        )
        assert resp.name == "uploaded_file"
        assert resp.rows == 500
        assert resp.columns == 10
        assert len(resp.columns_list) == 10

    def test_default_message(self):
        """Default success message."""
        resp = DatasetUploadResponse(
            name="test",
            rows=1,
            columns=1,
            columns_list=["col1"],
        )
        assert resp.message == "Dataset uploaded successfully"

    def test_custom_message(self):
        """Custom message can be provided."""
        resp = DatasetUploadResponse(
            name="test",
            rows=1,
            columns=1,
            columns_list=["col1"],
            message="Custom success message",
        )
        assert resp.message == "Custom success message"

    def test_missing_required_fields_fails(self):
        """Missing required fields should fail."""
        with pytest.raises(ValidationError):
            DatasetUploadResponse(name="test", rows=1)


# =============================================================================
# DATASET DELETE RESPONSE TESTS
# =============================================================================


class TestDatasetDeleteResponse:
    """Tests for DatasetDeleteResponse model."""

    def test_valid_response(self):
        """Valid delete response."""
        resp = DatasetDeleteResponse(name="deleted_dataset")
        assert resp.name == "deleted_dataset"
        assert resp.message == "Dataset deleted successfully"

    def test_custom_message(self):
        """Custom message can be provided."""
        resp = DatasetDeleteResponse(
            name="test",
            message="Dataset 'test' has been removed",
        )
        assert resp.message == "Dataset 'test' has been removed"

    def test_missing_name_fails(self):
        """Missing name should fail."""
        with pytest.raises(ValidationError):
            DatasetDeleteResponse()


# =============================================================================
# DATASET ERROR RESPONSE TESTS
# =============================================================================


class TestDatasetErrorResponse:
    """Tests for DatasetErrorResponse model."""

    def test_error_only(self):
        """Error response with just error message."""
        resp = DatasetErrorResponse(error="Dataset not found")
        assert resp.error == "Dataset not found"
        assert resp.detail is None

    def test_error_with_detail(self):
        """Error response with detail."""
        resp = DatasetErrorResponse(
            error="Upload failed",
            detail="File format not supported: .xyz",
        )
        assert resp.error == "Upload failed"
        assert resp.detail == "File format not supported: .xyz"

    def test_missing_error_fails(self):
        """Missing error should fail."""
        with pytest.raises(ValidationError):
            DatasetErrorResponse()


# =============================================================================
# IMPORT TESTS
# =============================================================================


class TestModuleExports:
    """Test that models are properly exported from parrot.models."""

    def test_import_from_models_package(self):
        """Models should be importable from parrot.models."""
        from parrot.models import (
            DatasetAction,
            DatasetPatchRequest,
            DatasetQueryRequest,
            DatasetListResponse,
            DatasetUploadResponse,
            DatasetDeleteResponse,
            DatasetErrorResponse,
        )

        assert DatasetAction is not None
        assert DatasetPatchRequest is not None
        assert DatasetQueryRequest is not None
        assert DatasetListResponse is not None
        assert DatasetUploadResponse is not None
        assert DatasetDeleteResponse is not None
        assert DatasetErrorResponse is not None
