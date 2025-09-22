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

    firetv_endcap_geometry = EndcapGeometry(
        aspect_ratio=0.75,          # ~1200x1600 image → 0.75, fits this endcap well
        left_margin_ratio=0.015,    # the side wood posts are thin
        right_margin_ratio=0.015,
        top_margin_ratio=0.03,      # canopy overhang; give it a bit more room
        bottom_margin_ratio=0.02,
        inter_shelf_padding=0.012,  # tiny gutters between bands

        # secondary margins used by your ROI builder
        width_margin_percent=0.08,
        height_margin_percent=0.12,
        top_margin_percent=0.03,
        side_margin_percent=0.02
    )

    planogram_config = {
        "brand": "Fire TV",
        "category": "Fire TV",
        "aisle": {
            "name": "Electronics > Smart TVs & Streaming Devices",
            "lighting_conditions": "bright"
        },
        "text_tokens": [
            "firetv",
            "fire tv",
            "bring your entertainment to life",
            "streaming device",
            "smart tv",
            "amazon",
            "hisense",
            "insignia",
        ],
        "shelves": [
            {
                "level": "header",
                "height_ratio": 0.22,
                "products": [
                    {
                        "name": "FireTV Header Branding",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "illuminated text",
                            "white fire tv logo",
                            "backlit display",
                            "brand logo visible"
                        ]
                    }
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.95
            },
            {
                "level": "middle",
                "height_ratio": 0.50,
                "products": [
                    {
                        "name": "Hisense Fire TV",
                        "product_type": "tv",
                        "quantity_range": [1, 1],
                        "position_preference": "center",
                        "mandatory": True,
                        "visual_features": [
                            "active display",
                            "colorful content showing",
                            "hisense branding visible",
                        ]
                    },
                    {
                        "name": "Insignia Fire TV",
                        "product_type": "tv",  # FIXED: Use standard type
                        "quantity_range": [1, 1],
                        "position_preference": "center",
                        "mandatory": True,
                        "visual_features": [
                            "active display",
                            "colorful content showing",
                            "insignia branding visible",
                            "fire tv interface"
                        ]
                    }
                ],
                "compliance_threshold": 0.90,
                "allow_extra_products": False,
                "position_strict": True
            },
            {
                "level": "bottom_promo",
                "height_ratio": 0.20,
                "products": [
                    {
                        "name": "Fire TV Promotional Display",
                        "product_type": "product_materials",
                        "quantity_range": [3, 6],
                        "mandatory": True,
                        "visual_features": [
                            "promotional cards",
                            "fire tv cube display",
                            "interactive display",
                            "educational materials",
                            "retail signage"
                        ]
                    }
                ],
                "compliance_threshold": 0.80,
                "allow_extra_products": True
            },
            {
                "level": "bottom_brand",
                "height_ratio": 0.08,  # 10% for bottom brand placement
                "products": [
                    {
                        "name": "FireTV Bottom Branding",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "fire tv text on black background",
                            "amazon logo",
                            "white text on dark surface",
                            "brand placement visible"
                        ]
                    }
                ],
                "compliance_threshold": 0.95,
                "allow_extra_products": False
            }
        ],
        "advertisement_endcap": {
            "enabled": True,
            "promotional_type": "integrated_display",
            "position": "header",
            "product_weight": 0.8,
            "text_weight": 0.2,
            "brand_weight": 0.00, # brand is not critical here
            "text_requirements": [
                {
                    "required_text": "fire tv",
                    "match_type": "contains",
                    "mandatory": True,
                    "case_sensitive": False,
                    "confidence_threshold": 0.5
                }
            ],
            "size_constraints": {
                "header_height_ratio": 0.22,
                "tv_display_ratio":   0.50,
                "promo_shelf_ratio":  0.20,
                "brand_base_ratio":   0.08
            }
        }
    }

    # Usage example for Google TV configuration
    firetv_config = PlanogramConfig(
        config_name="firetv_planogram_config",
        planogram_config=planogram_config,
        endcap_geometry=firetv_endcap_geometry,
        reference_images={},
        confidence_threshold=0.15,
        detection_model="yolo11l.pt",
        roi_detection_prompt="""
Analyze the image to identify the FireTV endcap display and its key components.

Your response must be a single JSON object with a 'detections' list. Each detection must have a 'label', 'confidence', a 'content' with any detected text, and a 'bbox' with normalized coordinates (x1, y1, x2, y2).

Useful phrases to look for: {tag_hint}

**MANDATORY TEXT EXTRACTION:**
Look carefully for text in these areas and include ALL visible text in the 'content' field:
- Header area: Look for "firetv", "fire tv", or similar branding text
- TV displays: Look for "Bring your entertainment to life" or similar promotional text
- Bottom area: Look for "firetv", "fire tv" branding text

Return all detections with the following criteria:

1. **'brand_logo'**: A bounding box for the '{brand}' brand logo at the top of the sign with wooden background and white text, return the brand text in 'content'.
2. **'poster_text'**: Main promotional text on TV displays
   - Must include 'content': Extract "Bring your entertainment to life" or similar
   - Look at the text overlay on both TV screens
3. **'tv_display'**: Both TV screens - identify each separately
4. **'promotional_material'**: A bounding box for the shelf area containing promotional cards, brochures, or informational materials.
5. **'promotional_graphic'**: The "fire tv" text on the black base at bottom (also promotional signage)
6. **'poster_panel'**: A bounding box that encompasses the entire upper display area including both TV screens and any surrounding framework.
7. **'endcap'**: A bounding box for the complete endcap structure from top branding to the base, including all shelves and displays.

        """,
        object_identification_prompt="""
---
**!! MANDATORY SHELF ASSIGNMENT RULES !!**
You MUST assign objects to the correct shelf using these EXACT mappings:

- **Header (top 20%)**: "Fire TV Header Branding" → product_type="promotional_graphic" → shelf_location="header"
- **Middle TVs (20-65%)**:
  * "Hisense Fire TV" → product_type="tv" → shelf_location="middle"
  * "Insignia Fire TV" → product_type="tv" → shelf_location="middle"
- **Promotional Shelf (65-90%)**: All cards/cube/displays → product_type="product_box" → shelf_location="bottom_promo"
- **Bottom Base (90-100%)**: "Fire TV Base Branding" → product_type="promotional_graphic" → shelf_location="bottom_brand"

---
**!! TV IDENTIFICATION GUIDE !!**
- **Hisense Fire TV**: Look for "HISENSE | firetv" logo on bezel
- **Insignia Fire TV**: Look for "INSIGNIA | firetv" logo on bezel
- Both TVs MUST show active displays with colorful content

---
**!! CRITICAL RULES !!**

1. **EXPLICIT SHELF ASSIGNMENT**: Every object must be assigned to exactly one shelf level based on its Y-coordinate position in the image.

2. **PRODUCT TYPE MAPPING**: Use only these exact product_type values:
   - "promotional_graphic" (for top FireTV logo AND bottom FireTV text)
   - "tv" (for both TVs)
   - "product_box" (for all shelf promotional items - cards, cube, displays)

3. **VISUAL FEATURES VALIDATION**:
   - TVs must have "active display" and brand identification
   - Header must have "illuminated text" or "blue text"
   - Base must have "white text on black background"

4. **POSITION ENFORCEMENT**:
   - If Y-coordinate < 0.2: shelf_location="header"
   - If 0.2 ≤ Y-coordinate < 0.65: shelf_location="middle"
   - If 0.65 ≤ Y-coordinate < 0.9: shelf_location="bottom_promo"
   - If Y-coordinate ≥ 0.9: shelf_location="bottom_brand"

5. **visual_features**: Each detected object must include relevant visual features, e.g., "active display" for TVs, "illuminated text" for header, returned as a list of strings.
    """
)
    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        planogram_config=firetv_config,
    )

    # Other Brand?
    image_path = BASE_DIR / "examples" / "pipelines" / "planogram" / "firetv.jpg"

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
