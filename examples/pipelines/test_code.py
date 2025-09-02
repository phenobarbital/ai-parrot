#!/usr/bin/env python3
"""
Simple YOLO + CLIP test script to detect product boxes and match with reference images
Tests if YOLO can detect card boxes/products and CLIP can match them to references
"""

import cv2
import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import matplotlib.pyplot as plt
from pathlib import Path
from navconfig import BASE_DIR

# Try imports with fallbacks
try:
    from ultralytics import YOLO
    print("✓ YOLO available")
except ImportError:
    print("✗ ultralytics not installed: pip install ultralytics")
    YOLO = None

try:
    import clip
    print("✓ CLIP available")
except ImportError:
    print("✗ CLIP not installed: pip install git+https://github.com/openai/CLIP.git")
    clip = None

def load_models():
    """Load YOLO and CLIP models"""
    models = {}

    # Load YOLO (try different versions)
    if YOLO:
        try:
            # Try YOLO11 first (closest to YOLO12L you mentioned)
            models['yolo'] = YOLO('yolo11l.pt')
            print("✓ Loaded YOLO11L")
        except:
            try:
                models['yolo'] = YOLO('yolov8l.pt')
                print("✓ Loaded YOLOv8L")
            except:
                models['yolo'] = YOLO('yolov8n.pt')
                print("✓ Loaded YOLOv8n (fallback)")

    # Load CLIP
    if clip:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        models['clip_model'], models['clip_preprocess'] = clip.load("ViT-B/32", device=device)
        models['device'] = device
        print(f"✓ Loaded CLIP on {device}")

    return models

def detect_product_areas(image_path, models, conf_threshold=0.3):
    """
    Simple YOLO detection focusing on product-like objects
    """
    if not models.get('yolo'):
        print("No YOLO model available")
        return []

    # Run YOLO detection
    results = models['yolo'](
        image_path,
        conf=conf_threshold,
        iou=0.5,
        verbose=False
    )

    detections = []

    if results and results[0].boxes is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        confidences = results[0].boxes.conf.cpu().numpy()
        class_ids = results[0].boxes.cls.cpu().numpy()

        for i, x in enumerate(boxes):
            x1, y1, x2, y2 = map(int, boxes[i])
            conf = float(confidences[i])
            class_id = int(class_ids[i])
            class_name = models['yolo'].names[class_id]

            # Calculate area (filter very small detections)
            area = (x2 - x1) * (y2 - y1)
            if area > 1000:  # Minimum area threshold
                detections.append({
                    'bbox': (x1, y1, x2, y2),
                    'confidence': conf,
                    'class_name': class_name,
                    'class_id': class_id,
                    'area': area
                })

    print(f"YOLO detected {len(detections)} potential product areas")
    return detections

def compare_with_references(image_path, detections, reference_images, models, similarity_threshold=0.25):
    """
    Use CLIP to compare detected areas with reference product images
    """
    if not models.get('clip_model') or not detections:
        return detections

    # Load main image
    main_image = Image.open(image_path).convert('RGB')

    # Process reference images
    reference_features = []
    for ref_path in reference_images:
        try:
            ref_image = Image.open(ref_path).convert('RGB')
            ref_tensor = models['clip_preprocess'](ref_image).unsqueeze(0).to(models['device'])

            with torch.no_grad():
                ref_features = models['clip_model'].encode_image(ref_tensor)
                ref_features = ref_features / ref_features.norm(dim=-1, keepdim=True)
                reference_features.append({
                    'features': ref_features,
                    'path': ref_path,
                    'name': Path(ref_path).stem
                })
        except Exception as e:
            print(f"Error processing reference {ref_path}: {e}")

    if not reference_features:
        print("No reference images processed")
        return detections

    # Compare each detection with references
    enhanced_detections = []

    for detection in detections:
        x1, y1, x2, y2 = detection['bbox']

        # Extract crop from detection
        crop = main_image.crop((x1, y1, x2, y2))

        # Skip very small crops
        if crop.size[0] < 20 or crop.size[1] < 20:
            enhanced_detections.append(detection)
            continue

        try:
            # Process crop with CLIP
            crop_tensor = models['clip_preprocess'](crop).unsqueeze(0).to(models['device'])

            with torch.no_grad():
                crop_features = models['clip_model'].encode_image(crop_tensor)
                crop_features = crop_features / crop_features.norm(dim=-1, keepdim=True)

                # Calculate similarities with all references
                best_match = None
                best_similarity = 0

                for ref in reference_features:
                    similarity = (crop_features @ ref['features'].T).item()
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = ref

                # Update detection with CLIP results
                detection['clip_similarity'] = best_similarity
                detection['best_match'] = best_match['name'] if best_match else None
                detection['is_product'] = best_similarity > similarity_threshold

        except Exception as e:
            print(f"Error processing detection: {e}")
            detection['clip_similarity'] = 0
            detection['best_match'] = None
            detection['is_product'] = False

        enhanced_detections.append(detection)

    return enhanced_detections

def visualize_results(image_path, detections, output_path="results.jpg"):
    """
    Simple visualization of results
    """
    image = cv2.imread(image_path)
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    # Create PIL image for drawing
    pil_image = Image.fromarray(image_rgb)
    draw = ImageDraw.Draw(pil_image)

    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except:
        font = ImageFont.load_default()

    print(f"\n📊 Detection Results:")
    print("-" * 50)

    for i, det in enumerate(detections):
        x1, y1, x2, y2 = det['bbox']

        # Color based on product match
        if det.get('is_product', False):
            color = 'green'
            status = "✓ PRODUCT"
        else:
            color = 'red'
            status = "✗ NOT PRODUCT"

        # Draw bounding box
        draw.rectangle([x1, y1, x2, y2], outline=color, width=3)

        # Create label
        label_parts = [
            f"{det['class_name']} ({det['confidence']:.2f})",
            f"CLIP: {det.get('clip_similarity', 0):.2f}",
            status
        ]

        if det.get('best_match'):
            label_parts.append(f"Match: {det['best_match']}")

        label = " | ".join(label_parts)

        # Draw label background
        bbox = draw.textbbox((x1, y1-25), label, font=font)
        draw.rectangle(bbox, fill=color)
        draw.text((x1, y1-25), label, fill='white', font=font)

        # Print details
        print(f"Detection {i+1}:")
        print(f"  Class: {det['class_name']} (conf: {det['confidence']:.2f})")
        print(f"  CLIP similarity: {det.get('clip_similarity', 0):.3f}")
        print(f"  Best match: {det.get('best_match', 'None')}")
        print(f"  Is product: {det.get('is_product', False)}")
        print(f"  Area: {det['area']}")
        print()

    # Save result
    path = BASE_DIR.joinpath('examples', 'pipelines', output_path)
    pil_image.save(path)
    print(f"💾 Results saved to: {path}")

    return pil_image

def main():
    """
    Simple test function
    """
    print("🧪 Testing YOLO + CLIP Product Detection")
    print("=" * 50)

    # Configuration
    test_image = BASE_DIR / "examples" / "pipelines" / "original_0.jpg"
    reference_images = [
        BASE_DIR / "examples" / "pipelines" / "ET-2980.jpg",
        BASE_DIR / "examples" / "pipelines" / "ET-3950.jpg",
        BASE_DIR / "examples" / "pipelines" / "ET-4950.jpg"
    ]

    # Load models
    models = load_models()

    if not models.get('yolo'):
        print("❌ Cannot run test without YOLO model")
        return

    # # Test with your uploaded images (adjust paths as needed)
    # try:
    #     # Try to detect the uploaded images from your conversation
    #     possible_images = ["image1.jpg", "image2.jpg", "Image 1", "Image 2"]

    #     for img_path in possible_images:
    #         if Path(img_path).exists():
    #             test_image = img_path
    #             print(f"📸 Using image: {test_image}")
    #             break
    #     else:
    #         print(f"⚠️  Using default: {test_image}")
    #         print("   (Make sure to update the path to your test image)")
    # except:
    #     pass

    # Step 1: YOLO Detection
    print("\n🔍 Step 1: YOLO Object Detection")
    detections = detect_product_areas(test_image, models)

    # Step 2: CLIP Comparison (if reference images available)
    print("\n🧠 Step 2: CLIP Reference Comparison")
    if reference_images and any(Path(ref).exists() for ref in reference_images):
        existing_refs = [ref for ref in reference_images if Path(ref).exists()]
        detections = compare_with_references(test_image, detections, existing_refs, models)
    else:
        print("⚠️  No reference images found - skipping CLIP comparison")
        print("   Add reference product images to enable product matching")

    # Step 3: Visualization
    print("\n📊 Step 3: Results Visualization")
    visualize_results(test_image, detections)

    # Summary
    product_count = sum(1 for d in detections if d.get('is_product', False))
    print(f"\n📈 Summary:")
    print(f"   Total detections: {len(detections)}")
    print(f"   Identified as products: {product_count}")
    print(f"   Detection rate: {product_count/len(detections)*100:.1f}%" if detections else "0%")

if __name__ == "__main__":
    main()
