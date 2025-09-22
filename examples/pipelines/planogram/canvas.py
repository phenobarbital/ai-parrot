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

    canvas_endcap_geometry = EndcapGeometry(
        aspect_ratio=0.85,
        left_margin_ratio=0.02,
        right_margin_ratio=0.02,
        top_margin_ratio=0.02,
        bottom_margin_ratio=0.02,
        inter_shelf_padding=0.01,
        width_margin_percent=0.10,
        height_margin_percent=0.15,
        top_margin_percent=0.02,
        side_margin_percent=0.02
    )

    planogram_config = {
        "brand": "Hisense",
        "category": "Canvas TV Display",
        "aisle": {
            "name": "Electronics > TVs & Home Theater",
            "lighting_conditions": "bright"
        },
        "text_tokens": [
            "hisense",
            "canvas tv",
            "canvastv",
            "learn more",
            "official partner",
            "world cup",
            "fifa"
        ],
        "shelves": [
            {
                "level": "header",
                "height_ratio": 0.16,  # 15% for top Hisense branding
                "products": [
                    {
                        "name": "Hisense Logo",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "hisense logo",
                            "white text on black background",
                            "brand header signage"
                        ]
                    }
                ],
                "allow_extra_products": True,
                "compliance_threshold": 0.95
            },
            {
                "level": "middle",
                "height_ratio": 0.50,  # 55% for the main TV display
                "products": [
                    {
                        "name": "Hisense Canvas TV 85-inch",
                        "product_type": "tv",
                        "quantity_range": [1, 1],
                        "position_preference": "center",
                        "mandatory": True,
                        "visual_features": [
                            "active display",
                            "85 inch screen",
                            "wooden bezel",
                            "canvas tv model",
                            "city scene content",
                            "hisense branding"
                        ]
                    }
                ],
                "compliance_threshold": 0.90,
                "allow_extra_products": False,
                "position_strict": True
            },
            {
                "level": "promo_shelf",
                "height_ratio": 0.24,  # 20% for promotional materials area
                "products": [
                    {
                        "name": "Canvas TV",
                        "product_type": "promotional_graphic",
                        "quantity_range": [2, 5],
                        "mandatory": True,
                        "visual_features": [
                            "learn more interactive display",
                            "canvastv branding",
                            "promotional cards",
                            "product information displays"
                        ]
                    }
                ],
                "compliance_threshold": 0.80,
                "allow_extra_products": True
            },
            {
                "level": "bottom_brand",
                "height_ratio": 0.10,  # 10% for bottom branding
                "products": [
                    {
                        "name": "Hisense Official Partner Branding",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "hisense logo",
                            "official partner text",
                            "world cup fifa branding",
                            "gold emblem"
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
            "product_weight": 0.85,  # High product weight for simple display
            "text_weight": 0.15,    # Lower text weight
            "brand_weight": 0.0,    # Disabled to avoid brand matching issues
            "text_requirements": [
                {
                    "required_text": "hisense",
                    "match_type": "contains",
                    "mandatory": True,
                    "case_sensitive": False,
                    "confidence_threshold": 0.2
                }
            ],
            "size_constraints": {
                "header_height_ratio": 0.16,
                "tv_display_ratio":   0.50,
                "promo_shelf_ratio":  0.24,
                "brand_base_ratio":   0.10
            }
        }
    }

    canvas_config = PlanogramConfig(
        config_name="canvas_hisense_display",
        planogram_config=planogram_config,
        reference_images={},
        confidence_threshold=0.15,
        detection_model="yolo11l.pt",
        endcap_geometry=canvas_endcap_geometry,
        roi_detection_prompt="""
Analyze the Hisense Canvas TV display and identify its key components. Focus on text extraction.

Your response must be a single JSON object with a 'detections' list. Each detection must have a 'label', 'confidence', a 'content' field with detected text, and a 'bbox' with normalized coordinates (x1, y1, x2, y2).

**MANDATORY TEXT EXTRACTION:**
Look for and extract ALL visible text:
- Header: "Hisense" branding
- TV area: Model information, screen content
- Promotional area: "Learn More", "CanvasTV", product details
- Bottom: "Official Partner", "Hisense", FIFA/World Cup text

Useful phrases to look for: {tag_hint}

**REQUIRED DETECTIONS:**

1. **'brand_logo'**: A bounding box for the '{brand}' brand logo at the top of the sign with black background and white text, return the brand text in 'content'.

2. **'promotional_graphic'**: Main TV display promotional area
   - Must include 'content': Extract any visible model/marketing text
   - Focus on the large TV screen and surrounding signage

3. **'promotional_materials'**: Interactive displays and promotional cards
   - Must include 'content': Extract "Learn More", "CanvasTV", etc.
   - The shelf area with various promotional elements

4. **'promotional_base'**: Bottom official partner branding
   - Must include 'content': Extract "Official Partner", "Hisense", FIFA text
   - The black area at bottom with gold emblem

5. **'poster_panel'**: Overall display framework
   - For this detection, 'content' can include general promotional text
   - Should encompass the main display area

6. **'endcap'**: Complete structure boundary
   - For this detection, 'content' can be null
   - Must include entire display from top to bottom

Useful phrases to look for: {tag_hint}
        """,
        object_identification_prompt="""
---
**!! MANDATORY SHELF ASSIGNMENT RULES !!**
You MUST assign objects to the correct shelf using these EXACT mappings:

- **Header (top 15%)**: "Hisense Brand Header" → product_type="promotional_graphic" → shelf_location="header"
- **Middle (15-70%)**: "Hisense Canvas TV" → product_type="tv" → shelf_location="middle"
- **Promo Shelf (70-90%)**: Promotional materials → product_type="product_box" → shelf_location="promo_shelf"
- **Bottom (90-100%)**: "Official Partner" → product_type="promotional_graphic" → shelf_location="bottom_brand"

---
**!! TV IDENTIFICATION GUIDE !!**
- **Hisense Canvas TV**: Look for large display with wooden bezel frame.
- **85-inch model**: Large screen size, premium positioning
- **Active Display**: Must show colorful content.

---
**!! CRITICAL TEXT EXTRACTION RULES !!**

For ALL promotional_graphic items, include readable text in visual_features:
- Add "hisense text: [text]" for Hisense branding
- Add "canvas text: [text]" for Canvas TV references
- Add "partner text: [text]" for Official Partner text

---
**!! POSITION ENFORCEMENT RULES !!**

- If Y-coordinate < 0.15: shelf_location="header"
- If 0.15 ≤ Y-coordinate < 0.70: shelf_location="middle"
- If 0.70 ≤ Y-coordinate < 0.90: shelf_location="promo_shelf"
- If Y-coordinate ≥ 0.90: shelf_location="bottom_brand"

    """,
    )

    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        planogram_config=canvas_config,
    )

    # Other Brand?
    image_path = BASE_DIR / "examples" / "pipelines" / "planogram" / "hisense.jpg"

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
