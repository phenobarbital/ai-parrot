import asyncio
from navconfig import BASE_DIR
from parrot.pipelines.planogram import PlanogramCompliancePipeline
from parrot.pipelines.models import PlanogramConfig, EndcapGeometry
from parrot.clients.google import (
    GoogleGenAIClient,
    GoogleModel
)

async def main():
    """Example usage of the 3-step pipeline"""
    llm = GoogleGenAIClient(model=GoogleModel.GEMINI_2_5_PRO)

    hisense_geometry = EndcapGeometry(
        aspect_ratio=0.78,           # ~3:4 portrait; fits this unit well
        left_margin_ratio=0.03,      # wood slat + bezel
        right_margin_ratio=0.03,
        top_margin_ratio=0.015,      # thin gap above header cap
        bottom_margin_ratio=0.03,    # kicker base space
        inter_shelf_padding=0.014,   # tiny gutters between bands

        # ROI margins used by your detector/LLM ROI
        width_margin_percent=0.10,
        height_margin_percent=0.22,
        top_margin_percent=0.015,
        side_margin_percent=0.03
    )

    # Hisense planogram configuration
    hisense_planogram_config = {
        "brand": "Hisense",
        "category": "TVs",
        "category": "TV Endcap Tower",
        "text_tokens": [
            "hisense", "google tv", "u8", "u7", "u6",
            "official partner", "fifa", "learn more"
        ],
        "visual_features_weight": 0.3,
        "aisle": {
            "name": "Electronics > TVs & Home Theater",
            "lighting_conditions": "normal"
        },
        "shelves": [
            {
                "level": "header_branding",
                "height_ratio": 0.10,
                "products": [
                    {
                        "name": "Hisense Brand Logo",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "illuminated white text hisense"  # Matches: "Illuminated white text 'Hisense' on a black header."
                        ]
                    }
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.95
            },
            {
                "level": "top_tv_u7",
                "height_ratio": 0.25,
                "products": [
                    {
                        "name": "Hisense U7 TV",
                        "product_type": "tv",
                        "visual_features": [
                            "active tv screen displaying dynamic colorful content u7"  # Matches: "Active TV screen displaying dynamic, colorful content with 'U7' visible in the top right corner."
                        ]
                    }
                ],
                "compliance_threshold": 0.9
            },
            {
                "level": "middle_tv_u8",
                "height_ratio": 0.25,
                "products": [
                    {
                        "name": "Hisense U8 TV",
                        "product_type": "tv",
                        "visual_features": [
                            "active tv screen displaying dynamic content u8"  # Matches: "Active TV screen displaying dynamic content with 'U8' visible in the top right corner and a feature list on the left."
                        ]
                    }
                ],
                "compliance_threshold": 0.9
            },
            {
                "level": "bottom_tv_u6",
                "height_ratio": 0.25,
                "products": [
                    {
                        "name": "Hisense U6 TV",
                        "product_type": "tv",
                        "visual_features": [
                            "active tv screen displaying tiger u6"  # Matches: "Active TV screen displaying an image of a tiger with 'U6' visible in the top right corner."
                        ]
                    }
                ],
                "compliance_threshold": 0.9
            },
            # 3) Promo shelf (tablet/cards/price strips)
            {
                "level": "promo_shelf",
                "height_ratio": 0.20,      # ~20%
                "products": [
                    {
                        "name": "Hisense Promo Materials",
                        "product_type": "promotional_graphic",  # normalize for your matcher
                        "quantity_range": [3, 8],
                        "mandatory": True,
                        "visual_features": [
                            "tablet learn more display",
                            "product cards",
                            "price tags"
                        ]
                    }
                ],
                "allow_extra_products": True,
                "compliance_threshold": 0.80
            },
            # 4) Bottom brand kicker ("Hisense" + OFFICIAL PARTNER + FIFA emblem)
            {
                "level": "bottom_brand",
                "height_ratio": 0.12,      # ~12% (kicker plus base)
                "products": [
                    {
                        "name": "Bottom Official Partner Branding",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "hisense logo",
                            "official partner text",
                            "fifa emblem"
                        ],
                        "text_requirements": [
                            {"required_text": "Hisense", "match_type": "contains", "mandatory": True},
                            {"required_text": "OFFICIAL PARTNER", "match_type": "contains", "mandatory": True}
                        ]
                    }
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.95
            }
        ],
        "advertisement_endcap": {
            "enabled": True,
            "promotional_type": "integrated_display",
            "position": "bottom",
            "product_weight": 0.7,
            "text_weight": 0.3,
            "text_requirements": [
                {
                    "required_text": "Hisense",
                    "match_type": "contains",
                    "mandatory": True
                },
                {
                    "required_text": "OFFICIAL PARTNER",
                    "match_type": "contains",
                    "mandatory": True
                }
            ]
        }
    }

    # Reference images (empty for Hisense - relies on visual recognition)
    hisense_reference_images = {}

    # Create the PlanogramConfig for Hisense
    hisense_planogram = PlanogramConfig(
        planogram_config=hisense_planogram_config,
        reference_images=hisense_reference_images,
        detection_model="yolo11m.pt",
        confidence_threshold=0.15,
        roi_detection_prompt="""
Analyze the image to identify the entire Hisense TV retail endcap display and its key components.

Your response must be a single JSON object with a 'detections' list. Each detection must have a 'label', 'confidence', a 'content' with any detected text, and a 'bbox' with normalized coordinates (x1, y1, x2, y2).

Useful phrases to look for: {tag_hint}, 'Hisense', 'Official Partner', 'U7', 'U8', 'U6'

Return all detections with the following strict criteria:

1. **'brand_logo'**: A bounding box for the '{brand}' brand logo at the top of the display (illuminated white text).
2. **'poster_text'**: A bounding box for any visible text elements including model numbers (U7, U8, U6) and partner certifications.
3. **'promotional_graphic'**: A bounding box for the main TV demonstration area showing the three active TV screens with content.
4. **'poster_panel'**: A bounding box that encompasses the main TV display area containing all three television screens arranged vertically.
5. **'endcap'**: A bounding box for the entire Hisense display structure including the illuminated logo at top, three TV screens in middle, and partner branding at bottom.

    """,
        object_identification_prompt="""
---
**!! TV DISPLAY IDENTIFICATION GUIDE !!**
You are analyzing a Hisense TV display endcap with 5 distinct shelf areas.

---
**!! MANDATORY SHELF LOCATION MAPPING !!**

You MUST use these EXACT shelf location names:

1. **"header_branding"** - Top area with illuminated Hisense logo
2. **"top_tv_u7"** - Upper TV display area (should show U7 content)
3. **"middle_tv_u8"** - Middle TV display area (should show U8 content)
4. **"bottom_tv_u6"** - Lower TV display area (should show U6 content with tiger)
5. **"bottom_branding"** - Very bottom area with "Official Partner" text and logos

**CRITICAL**: Each TV and branding element must be assigned to its correct shelf area based on vertical position.

CRITICAL SHELF ASSIGNMENT RULES:
Use the CENTER Y-coordinate of each detection box to determine shelf_location:

**MANDATORY Y-coordinate assignments:**
- Center Y < 400: Use "header_branding"
- Center Y 400-800: Use "top_tv_u7"
- Center Y 800-1200: Use "middle_tv_u8"
- Center Y 1200-1600: Use "bottom_tv_u6"
- Center Y > 1600: Use "bottom_branding"

**For overlapping boxes:** If a detection spans multiple Y ranges, use the range that contains the CENTER point of the bounding box.

---
**!! CRITICAL IDENTIFICATION RULES !!**

1. **TV MODEL VERIFICATION:** Each TV must show its model (U7, U8, U6) on screen
2. **SPATIAL ASSIGNMENT:** Use Y-coordinate to determine correct shelf
3. **BRANDING SEPARATION:** Logo at top = "header_branding", Partner text at bottom = "bottom_branding"

**EXPECTED LAYOUT:**
- **header_branding:** Illuminated "Hisense" logo (top of display)
- **top_tv_u7:** Active TV screen showing U7 content (upper TV)
- **middle_tv_u8:** Active TV screen showing U8 content (middle TV)
- **bottom_tv_u6:** Active TV screen showing U6 content with tiger (lower TV)
- **bottom_branding:** "Official Partner" text and logos (bottom of display)

**DO NOT DEFAULT TO "middle_tv_u8"** - each item must be assigned to its proper vertical location.

Valid shelf locations: {shelf_names}

For each detected object, carefully check its Y-coordinate and assign the appropriate shelf_location from the 5 options above.
""",
        endcap_geometry=hisense_geometry,
    )

    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        planogram_config=hisense_planogram,
    )

    # Other Brand?
    image_path = BASE_DIR / "examples" / "pipelines" / "hisense-2.jpg"

    # Run complete pipeline
    results = await pipeline.run(
        image=image_path,
        return_overlay="identified",
        overlay_save_path="/tmp/data/planogram_overlay.jpg",
    )

    # Generate reports
    json_report = pipeline.generate_compliance_json(
        results=results
    )

    markdown_report = pipeline.generate_compliance_markdown(
        results=results
    )

    print(f"JSON: {json_report}")
    print(f"Markdown: {markdown_report}")

    # Print results
    print("\n" + "="*60)
    print(f"\nOVERALL COMPLIANCE: {results['overall_compliant']}")
    print(f"COMPLIANCE SCORE: {results['overall_compliance_score']:.1%}")
    print("="*60)

    # Print results will now show text compliance
    print("\nSHELF-BY-SHELF RESULTS:")
    for result in results['step3_compliance_results']:
        print(f"{result.shelf_level.upper()}: {result.compliance_status}")
        print(f"  Expected: {result.expected_products}")
        print(f"  Found: {result.found_products}")
        print(f"  Product Score: {result.compliance_score:.1%}")
        print(f"  Text Score: {result.text_compliance_score:.1%}")
        print(f"  Text Compliant: {'✅' if result.overall_text_compliant else '❌'}")

        # Show text compliance details
        if result.text_compliance_results:
            print("  Text Requirements:")
            for text_result in result.text_compliance_results:
                status = "✅" if text_result.found else "❌"
                print(f"    {status} '{text_result.required_text}' (confidence: {text_result.confidence:.2f})")
                if text_result.matched_features:
                    print(f"        Matched: {text_result.matched_features}")
        print()

    # Render the Image:
    print(results['overlay_path'])


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
