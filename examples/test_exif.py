from PIL import Image
from parrot.interfaces.images.plugins.exif import EXIFPlugin

async def test_exif():
    # Initialize the plugin
    exif_plugin = EXIFPlugin(extract_geoloc=True)
    
    # Test with a sample image that contains EXIF data
    image_path = "examples/sample_image.jpg"  # You'll need to provide a sample image
    
    # Test both PIL and raw bytes methods
    with open(image_path, 'rb') as f:
        # Get raw bytes for exif library
        raw_bytes = f.read()
        
        # Get PIL image
        image = Image.open(image_path)
        
        print("Testing EXIF extraction...")
        print(f"Image: {image_path}")
        
        # Test the plugin with both PIL image and raw bytes
        result = await exif_plugin.analyze(
            image=image,
            raw_bytes=raw_bytes
        )
        
        print("\nExtracted EXIF data:")
        for key, value in result.items():
            print(f"{key}: {value}")

async def test_exif_cases():
    exif_plugin = EXIFPlugin(extract_geoloc=True)
    
    # Test cases with different image types
    test_images = [
        "/home/juanfran/Downloads/Telegram Desktop/IMG_20250514_193521_403.jpg",     # JPEG with EXIF
        "/home/juanfran/Downloads/plain_black_hd_black-t2.heic",     # HEIC image
        "/home/juanfran/Pictures/Selection_001.png",          # Image without EXIF
    ]
    
    for image_path in test_images:
        print(f"\nTesting: {image_path}")
        try:
            with open(image_path, 'rb') as f:
                raw_bytes = f.read()
                image = Image.open(image_path)
                
                result = await exif_plugin.analyze(
                    image=image,
                    raw_bytes=raw_bytes
                )
                
                print("EXIF data found:")
                if result:
                    for key, value in result.items():
                        print(f"  {key}: {value}")
                else:
                    print("  No EXIF data found")
                    
        except Exception as e:
            print(f"Error processing {image_path}: {e}")

if __name__ == "__main__":
    import asyncio
    asyncio.run(test_exif_cases()) 