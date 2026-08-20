"""Unit tests for public_form_paths helper (FEAT-241 M5, FEAT-421 tenant-qualified).

Tests cover:
- Returns exactly 5 paths
- Default base_path /api/v1
- Custom base_path
- Trailing slash stripped from base_path
- Render path is a glob ending with /render/*
- Exact path content check
- Different form IDs produce non-overlapping path sets
- All paths are tenant-qualified (/{tenant}/)
"""
import fnmatch

from parrot_formdesigner.services.public_forms import public_form_paths


class TestPublicFormPaths:
    def test_returns_five_paths(self):
        paths = public_form_paths("contact", "flexroc")
        assert len(paths) == 5

    def test_paths_are_tenant_qualified(self):
        paths = public_form_paths("abc-uid", "flexroc")
        assert len(paths) == 5
        assert all("/flexroc/forms/abc-uid" in p for p in paths)
        assert paths[0].endswith("/forms/abc-uid")
        assert any(p.endswith("/render/*") for p in paths)

    def test_default_base_path(self):
        paths = public_form_paths("contact", "flexroc")
        assert all("/api/v1/flexroc/forms/contact" in p for p in paths)

    def test_custom_base_path(self):
        paths = public_form_paths("survey", "flexroc", base_path="/api/v2")
        assert all("/api/v2/flexroc/forms/survey" in p for p in paths)

    def test_trailing_slash_stripped(self):
        paths = public_form_paths("x", "flexroc", base_path="/api/v1/")
        assert paths[0] == "/api/v1/flexroc/forms/x"

    def test_render_is_glob(self):
        paths = public_form_paths("contact", "flexroc")
        render = next(p for p in paths if "render" in p)
        assert render.endswith("/render/*")
        # Glob should match any format suffix:
        assert fnmatch.fnmatch(
            "/api/v1/flexroc/forms/contact/render/html", render
        )
        assert fnmatch.fnmatch(
            "/api/v1/flexroc/forms/contact/render/pdf", render
        )

    def test_exact_paths_content(self):
        paths = public_form_paths("my-form", "flexroc")
        bp = "/api/v1/flexroc/forms/my-form"
        assert paths[0] == bp
        assert paths[1] == f"{bp}/schema"
        assert paths[2] == f"{bp}/render/*"
        assert paths[3] == f"{bp}/data"
        assert paths[4] == f"{bp}/validate"

    def test_different_form_ids(self):
        """Different form IDs produce different path sets with no overlap."""
        p1 = public_form_paths("form-a", "flexroc")
        p2 = public_form_paths("form-b", "flexroc")
        assert not set(p1) & set(p2)

    def test_different_tenants_same_form_id(self):
        """Different tenants produce different path sets with no overlap."""
        p1 = public_form_paths("form-a", "flexroc")
        p2 = public_form_paths("form-a", "navigator")
        assert not set(p1) & set(p2)

    def test_schema_path(self):
        paths = public_form_paths("test", "flexroc")
        schema_path = paths[1]
        assert schema_path == "/api/v1/flexroc/forms/test/schema"

    def test_data_path(self):
        paths = public_form_paths("test", "flexroc")
        data_path = paths[3]
        assert data_path == "/api/v1/flexroc/forms/test/data"

    def test_validate_path(self):
        paths = public_form_paths("test", "flexroc")
        validate_path = paths[4]
        assert validate_path == "/api/v1/flexroc/forms/test/validate"

    def test_returns_list(self):
        result = public_form_paths("test", "flexroc")
        assert isinstance(result, list)
        assert all(isinstance(p, str) for p in result)
