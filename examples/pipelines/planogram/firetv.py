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
        aspect_ratio=0.75,  # Taller display ratio for vertical TV stacking
        left_margin_ratio=0.02,
        right_margin_ratio=0.02,
        top_margin_ratio=0.01,
        bottom_margin_ratio=0.03,
        inter_shelf_padding=0.015,  # Tight spacing for clean look
        width_margin_percent=0.15,
        height_margin_percent=0.20,
        top_margin_percent=0.02,
        side_margin_percent=0.03
    )

    planogram_config = {
        "brand": "Amazon",
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
            "hisense",
            "amazon"
        ],
        "shelves": [
            {
                "level": "header",
                "height_ratio": 0.15,  # 15% of ROI height for top branding
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
                "text_requirements": [
                    {
                        "required_text": "firetv",
                        "match_type": "contains",
                        "mandatory": True
                    }
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.95
            },
            {
                "level": "middle",
                "height_ratio": 0.55,  # 55% of ROI height for TV displays
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
                            "fire tv interface",
                            "dynamic graphics",
                            "entertainment content"
                        ]
                    },
                    {
                        "name": "Generic Fire TV",
                        "product_type": "tv",
                        "quantity_range": [1, 1],
                        "position_preference": "center",
                        "mandatory": True,
                        "visual_features": [
                            "active display",
                            "colorful content showing",
                            "fire tv interface",
                            "dynamic graphics",
                            "entertainment content",
                            "bring your entertainment to life text"
                        ]
                    }
                ],
                "compliance_threshold": 0.90,
                "allow_extra_products": False,
                "position_strict": True
            },
            {
                "level": "bottom_promo",
                "height_ratio": 0.20,  # 20% for promotional materials shelf
                "products": [
                    {
                        "name": "Fire TV Promotional Materials",
                        "product_type": "promotional_materials",
                        "quantity_range": [3, 6],
                        "mandatory": True,
                        "visual_features": [
                            "colorful promotional cards",
                            "fire tv branding",
                            "product information",
                            "retail signage"
                        ]
                    }
                ],
                "compliance_threshold": 0.80,
                "allow_extra_products": True
            },
            {
                "level": "bottom_brand",
                "height_ratio": 0.10,  # 10% for bottom brand placement
                "products": [
                    {
                        "name": "FireTV Bottom Branding",
                        "product_type": "promotional_base",
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
            "product_weight": 0.7,
            "text_weight": 0.3,
            "text_requirements": [
                {
                    "required_text": "firetv",
                    "match_type": "contains",
                    "mandatory": True,
                    "case_sensitive": False
                },
                {
                    "required_text": "fire tv",
                    "match_type": "contains",
                    "mandatory": True,
                    "case_sensitive": False
                },
                {
                    "required_text": "bring your entertainment to life",
                    "match_type": "contains",
                    "mandatory": False,
                    "case_sensitive": False
                }
            ],
            "size_constraints": {
                "header_height_ratio": 0.15,  # Header branding area
                "tv_display_ratio": 0.55,     # Combined TV area
                "promo_shelf_ratio": 0.20,    # Promotional materials
                "brand_base_ratio": 0.10      # Bottom branding
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

Return all detections with the following criteria:

1. **'brand_logo'**: A bounding box for the 'FireTV' or 'fire tv' brand logo at the top of the display.
2. **'tv_display'**: Bounding boxes for each active TV screen showing content. These should tightly enclose the visible screen area.
3. **'promotional_graphic'**: A bounding box for any promotional signage or graphics, including the "Bring your entertainment to life" messaging.
4. **'promotional_materials'**: A bounding box for the shelf area containing promotional cards, brochures, or informational materials.
5. **'promotional_base'**: A bounding box for the bottom branding area with 'fire tv' text on the black base.
6. **'poster_panel'**: A bounding box that encompasses the entire upper display area including both TV screens and any surrounding framework.
7. **'endcap'**: A bounding box for the complete endcap structure from top branding to the base, including all shelves and displays.

        """,
        object_identification_prompt="""
---
**!! IMPORTANT VISUAL GUIDE FOR FIRE TV DISPLAYS !!**
You MUST identify TV brands by looking for visible brand logos and distinctive design elements.
* **Hisense Fire TV:** Look for 'HISENSE' branding on the TV bezel or in the corner of the display.
* **Generic Fire TV:** TVs without clear brand identification but showing Fire TV interface.
* **Active Display:** TVs must be powered on and showing content (not black screens).

---
**!! CRITICAL IDENTIFICATION RULES !!**

1. **ANALYZE EACH TV INDEPENDENTLY:** Each TV display should be identified separately based on brand markings and display content.

2. **VISUAL FEATURE REQUIREMENTS:**
   - **Active Display:** TV must be showing colorful content, not blank/black screen
   - **Fire TV Interface:** Look for Fire TV-specific UI elements or content
   - **Brand Identification:** Check for manufacturer logos (Hisense, etc.)

3. **PRODUCT TYPES & PLACEMENT:**
   - **tv_demonstration:** Active TV displays showing content
   - **promotional_graphic:** Header branding and signage
   - **promotional_materials:** Shelf items, cards, brochures
   - **promotional_base:** Bottom branding on black surface

4. **POSITIONING HIERARCHY:**
   - **Header:** Fire TV branding at top
   - **Upper TV:** Top television display
   - **Lower TV:** Bottom television display
   - **Promotional Shelf:** Middle shelf with materials
   - **Base:** Bottom branding area

5. **MANDATORY ELEMENTS:**
   - At least one TV must be identifiable as Hisense brand
   - Both TVs must show active content (visual_features: "active display")
   - FireTV branding must be visible in header and base areas

6. **NEW OBJECT HANDLING:**
   - If you find a prominent TV or promotional element not pre-detected, set `detection_id` to `null`
   - Provide `detection_box` coordinates `[x1, y1, x2, y2]` for new items
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
