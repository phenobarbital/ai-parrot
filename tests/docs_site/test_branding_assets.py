"""FEAT-803 AC5: brand assets exist with the required geometry."""

from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
BRANDING = ROOT / "docs" / "branding"
PRESERVED = [
    "ai-parrot-wordmark-on-dark.svg",
    "parrot-mono-dark.svg",
    "parrot-mono-light.svg",
    "parrot-transparent.png",
    "parrot.svg",
]


def test_favicon_exists_with_16_and_32_frames() -> None:
    """favicon.ico carries 16x16 and 32x32 frames."""
    ico = BRANDING / "favicon.ico"
    assert ico.is_file()

    data = ico.read_bytes()
    reserved, image_type, image_count = struct.unpack_from("<HHH", data)
    assert (reserved, image_type) == (0, 1)
    assert len(data) >= 6 + image_count * 16

    sizes = {
        (width or 256, height or 256)
        for width, height in (struct.unpack_from("<BB", data, 6 + index * 16) for index in range(image_count))
    }
    assert {(16, 16), (32, 32)} <= sizes


def test_social_card_is_1200x630() -> None:
    """social-card.png is exactly 1200x630."""
    png = BRANDING / "social-card.png"
    assert png.is_file()

    data = png.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    assert struct.unpack(">II", data[16:24]) == (1200, 630)


def test_existing_brand_assets_preserved() -> None:
    """The five pre-existing assets still exist."""
    for name in PRESERVED:
        assert (BRANDING / name).is_file(), name
