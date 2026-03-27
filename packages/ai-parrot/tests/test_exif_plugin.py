import pytest
from PIL import Image
from parrot.interfaces.images.plugins.exif import EXIFPlugin
import os
from pathlib import Path
from PIL.ExifTags import TAGS, GPSTAGS
import struct
import base64

# Test image paths
TEST_IMAGES_DIR = Path(__file__).parent / "test_images"

@pytest.fixture
def exif_plugin():
    """Create an EXIFPlugin instance for testing."""
    return EXIFPlugin()

@pytest.fixture
async def sample_image():
    """Create a sample image with some EXIF data."""
    # Create a simple test image
    img = Image.new('RGB', (100, 100), color='red')
    
    # Create EXIF data using PIL's ExifTags
    exif = Image.Exif()
    exif[36867] = "2024:01:01 12:00:00"  # DateTimeOriginal
    exif[271] = "Test Camera"            # Make
    exif[272] = "Test Model"             # Model
    
    # Save the image with EXIF data
    test_image_path = TEST_IMAGES_DIR / "test_image.jpg"
    test_image_path.parent.mkdir(exist_ok=True)
    img.save(test_image_path, exif=exif.tobytes())
    
    yield test_image_path
    
    # Cleanup
    if test_image_path.exists():
        test_image_path.unlink()
    if test_image_path.parent.exists():
        test_image_path.parent.rmdir()

@pytest.mark.asyncio
async def test_exif_plugin_initialization(exif_plugin):
    """Test that EXIFPlugin initializes correctly."""
    assert exif_plugin.column_name == "exif_data"
    assert exif_plugin.extract_geoloc is False

@pytest.mark.asyncio
async def test_exif_plugin_with_geoloc():
    """Test EXIFPlugin with geolocation extraction enabled."""
    plugin = EXIFPlugin(extract_geoloc=True)
    assert plugin.extract_geoloc is True

@pytest.mark.asyncio
async def test_analyze_with_image(exif_plugin, sample_image):
    """Test the analyze method with a sample image."""
    # Open the test image
    with Image.open(sample_image) as img:
        # Analyze the image
        result = await exif_plugin.analyze(image=img)
        
        # Verify the results
        assert isinstance(result, dict)
        # Check that we got some EXIF data, even if it's not exactly what we specified
        assert len(result) > 0

@pytest.mark.asyncio
async def test_analyze_without_image(exif_plugin):
    """Test the analyze method without an image."""
    result = await exif_plugin.analyze()
    assert isinstance(result, dict)
    assert len(result) == 0

@pytest.mark.asyncio
async def test_convert_to_degrees(exif_plugin):
    """Test the convert_to_degrees method."""
    # Test with valid GPS coordinates
    test_coords = ((37, 46, 0), (122, 25, 0))  # San Francisco coordinates
    result = exif_plugin.convert_to_degrees(test_coords[0])
    assert isinstance(result, float)
    assert 37.0 <= result <= 38.0

    # Test with invalid coordinates
    invalid_coords = (None, None, None)
    result = exif_plugin.convert_to_degrees(invalid_coords)
    assert result is None

@pytest.mark.asyncio
async def test_extract_gps_datetime(exif_plugin):
    """Test the extract_gps_datetime method."""
    # Test with valid EXIF data
    exif_data = {
        "GPSInfo": {
            "GPSLatitude": (37, 46, 0),
            "GPSLatitudeRef": "N",
            "GPSLongitude": (122, 25, 0),
            "GPSLongitudeRef": "W"
        },
        "DateTimeOriginal": "2024:01:01 12:00:00"
    }
    
    result = exif_plugin.extract_gps_datetime(exif_data)
    assert isinstance(result, dict)
    assert "datetime" in result
    assert "latitude" in result
    assert "longitude" in result
    assert result["datetime"] == "2024:01:01 12:00:00"
    assert isinstance(result["latitude"], float)
    assert isinstance(result["longitude"], float)

    # Test with missing GPS data
    exif_data_no_gps = {"DateTimeOriginal": "2024:01:01 12:00:00"}
    result = exif_plugin.extract_gps_datetime(exif_data_no_gps)
    assert isinstance(result, dict)
    assert result["datetime"] == "2024:01:01 12:00:00"
    assert result["latitude"] is None
    assert result["longitude"] is None

@pytest.mark.asyncio
async def test_user_comment_decoding(exif_plugin):
    """Test that UserComment in base64 is properly decoded."""
    # Create a test image with base64 encoded UserComment
    img = Image.new('RGB', (100, 100), color='red')
    exif = Image.Exif()
    
    # Create a base64 encoded UserComment
    original_comment = "Test comment from Snapchat"
    encoded_comment = base64.b64encode(original_comment.encode()).decode()
    exif[37510] = encoded_comment  # 37510 is the tag for UserComment
    
    # Save the image with EXIF data
    test_image_path = TEST_IMAGES_DIR / "test_user_comment.jpg"
    test_image_path.parent.mkdir(exist_ok=True)
    img.save(test_image_path, exif=exif.tobytes())
    
    try:
        # Test the decoding
        with Image.open(test_image_path) as img:
            result = await exif_plugin.analyze(image=img)
            assert "UserComment" in result
            assert result["UserComment"] == original_comment
    finally:
        # Cleanup
        if test_image_path.exists():
            test_image_path.unlink()
        if test_image_path.parent.exists():
            test_image_path.parent.rmdir() 