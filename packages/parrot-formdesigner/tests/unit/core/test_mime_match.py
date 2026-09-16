"""The MIME matcher every upload gate shares.

Found in manual QA on 2026-09-16: a Multi Upload configured through the Form
Designer's own "Images only" preset rejected a JPEG with a 415. The preset
writes ``image/*``, and all three upload gates tested exact membership, so
``'image/jpeg' not in ['image/*']`` was true for every real file. The client
had already accepted it — navigator-svelte's `domain/mime-match.ts` understands
the wildcard — so the two ends disagreed about what the field accepts, and the
configuration the UI makes easiest to pick was the one that could never work.
"""

from __future__ import annotations

import pytest

from parrot_formdesigner.core.mime_match import file_type_allowed


class TestWildcard:
    """The shape the Designer's presets actually write."""

    def test_image_wildcard_accepts_a_real_photo(self):
        # The regression: this returned False and produced a 415.
        assert file_type_allowed(["image/*"], "image/jpeg", "photo.jpg") is True

    def test_image_wildcard_accepts_every_image_subtype(self):
        for mime in ("image/png", "image/heic", "image/webp", "image/gif"):
            assert file_type_allowed(["image/*"], mime, "f") is True

    def test_image_wildcard_refuses_a_pdf(self):
        assert file_type_allowed(["image/*"], "application/pdf", "doc.pdf") is False

    def test_wildcard_does_not_swallow_a_longer_type_name(self):
        # `image/*` must not match `imagex/png` — the prefix comparison has to
        # include the slash.
        assert file_type_allowed(["image/*"], "imagex/png", "f") is False

    def test_images_or_pdf_preset_accepts_both(self):
        allowed = ["image/*", "application/pdf"]
        assert file_type_allowed(allowed, "image/jpeg", "a.jpg") is True
        assert file_type_allowed(allowed, "application/pdf", "a.pdf") is True
        assert file_type_allowed(allowed, "text/csv", "a.csv") is False


class TestExactAndExtension:
    def test_exact_type_still_matches(self):
        assert file_type_allowed(["application/pdf"], "application/pdf", "a.pdf") is True
        assert file_type_allowed(["application/pdf"], "image/jpeg", "a.jpg") is False

    def test_bare_extension_pattern(self):
        # For the types a browser reports with no content type at all.
        assert file_type_allowed([".heic"], None, "IMG_0042.HEIC") is True
        assert file_type_allowed([".heic"], "", "IMG_0042.heic") is True
        assert file_type_allowed([".heic"], None, "IMG_0042.jpg") is False

    def test_extension_pattern_needs_a_name_with_a_dot(self):
        assert file_type_allowed([".pdf"], None, "noextension") is False
        assert file_type_allowed([".pdf"], None, None) is False


class TestEmptyAndMissing:
    def test_no_restriction_accepts_anything(self):
        # The caller does not have to remember which way an empty list goes.
        assert file_type_allowed(None, "application/x-anything", "f") is True
        assert file_type_allowed([], "application/x-anything", "f") is True

    def test_a_file_with_no_reported_type_fails_a_mime_pattern(self):
        # Nothing to compare against: only an extension pattern can save it.
        assert file_type_allowed(["image/*"], None, "photo.jpg") is False
        assert file_type_allowed(["image/*", ".jpg"], None, "photo.jpg") is True


@pytest.mark.parametrize(
    "allowed,mime,name,expected",
    [
        # The five presets the Form Designer offers, against a JPEG.
        ([], "image/jpeg", "a.jpg", True),  # Any file
        (["image/*"], "image/jpeg", "a.jpg", True),  # Images only
        (["application/pdf"], "image/jpeg", "a.jpg", False),  # PDF only
        (["image/*", "application/pdf"], "image/jpeg", "a.jpg", True),  # Images or PDF
    ],
)
def test_designer_presets_against_a_jpeg(allowed, mime, name, expected):
    """Every preset an author can pick behaves the way its label promises."""
    assert file_type_allowed(allowed, mime, name) is expected
