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

    google_tv_planogram_config = {
        "brand": "Google",
        "category": "Smart TV Platform",
        "visual_features_weight": 0.3,
        "aisle": {
            "name": "Electronics > TVs & Smart Devices",
            "lighting_conditions": "normal"
        },
        "shelves": [
            {
                "level": "header_branding",
                "height_ratio": 0.12,
                "products": [
                    {
                        "name": "Google TV Brand Logo",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "white google tv text on black background"
                        ]
                    }
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.95
            },
            {
                "level": "middle_tv",
                "height_ratio": 0.45,
                "products": [
                    {
                        "name": "Primary Display TV",
                        "product_type": "tv",
                        "visual_features": [
                            "large black tv screen mounted above"
                        ]
                    },
                    {
                        "name": "Hisense Google TV",
                        "product_type": "tv",
                        "mandatory": True,
                        "visual_features": [
                            "active hisense tv screen displaying colorful content google tv interface"
                        ]
                    }
                ],
                "compliance_threshold": 0.9,
                "allow_extra_products": True
            },
            {
                "level": "bottom_branding",
                "height_ratio": 0.40,
                "products": [
                    {
                        "name": "Product Information Materials",
                        "product_type": "informational_materials",
                        "mandatory": False,
                        "visual_features": [
                            "product brochures pamphlets on wooden shelf"
                        ]
                    },
                    {
                        "name": "Google and Partner Logos",
                        "product_type": "promotional_graphic",
                        "mandatory": True,
                        "visual_features": [
                            "google logo hisense tcl sony partner branding"
                        ],
                        "text_requirements": [
                            {
                                "required_text": "Google",
                                "match_type": "contains",
                                "mandatory": True
                            },
                            {
                                "required_text": "Hisense",
                                "match_type": "contains",
                                "mandatory": True
                            }
                        ]
                    }
                ],
                "allow_extra_products": True,
                "compliance_threshold": 0.8
            }
        ],
        "advertisement_endcap": {
            "enabled": True,
            "promotional_type": "integrated_display",
            "position": "bottom",
            "product_weight": 0.6,
            "text_weight": 0.4,
            "brand_weight": 0.2,
            "text_requirements": [
                {
                    "required_text": "Google TV",
                    "match_type": "contains",
                    "mandatory": True
                },
                {
                    "required_text": "Hisense",
                    "match_type": "contains",
                    "mandatory": True
                }
            ]
        },
        "global_compliance_threshold": 0.8
    }

    # Corresponding EndcapGeometry for Google TV displays
    google_tv_endcap_geometry = EndcapGeometry(
        # Google TV displays tend to be taller with more vertical content
        aspect_ratio=0.9,           # Taller aspect ratio for vertical stacking
        left_margin_ratio=0.02,
        right_margin_ratio=0.02,
        top_margin_ratio=0.01,      # Minimal top margin for header text
        bottom_margin_ratio=0.05,   # Space for partner branding
        inter_shelf_padding=0.02,   # Padding between display sections

        # ROI detection margins - adjusted for Google TV layout
        width_margin_percent=0.20,   # Moderate width margin
        height_margin_percent=0.35,  # More height to capture all vertical elements
        top_margin_percent=0.01,     # Minimal top margin
        side_margin_percent=0.03     # Balanced side margins
    )

    # Usage example for Google TV configuration
    google_tv_config = PlanogramConfig(
        config_name="google_tv_endcap_v1",
        planogram_config=google_tv_planogram_config,

        roi_detection_prompt="""
Analyze the image to identify the entire Google TV retail endcap display and its key components.

Your response must be a single JSON object with a 'detections' list. Each detection must have a 'label', 'confidence', a 'content' with any detected text, and a 'bbox' with normalized coordinates (x1, y1, x2, y2).

Useful phrases to look for: 'Google TV', 'Google', 'Hisense', 'TCL', 'Sony', smart TV interface content

Return all detections with the following strict criteria:

1. **'brand_logo'**: A bounding box for the 'Google TV' brand logo at the top of the display (white text on black background).
2. **'poster_text'**: A bounding box for any visible text elements including manufacturer names (Hisense, TCL, Sony) and Google branding.
3. **'promotional_graphic'**: A bounding box for the main TV demonstration area showing the active TV screens with Google TV interface content.
4. **'poster_panel'**: A bounding box that encompasses the main display area containing the TV screens and interactive content.
5. **'endcap'**: A bounding box for the entire Google TV display structure including the header logo, TV screens, product information area, and bottom partner branding.

Focus on the Google TV brand elements and ensure all required detection labels are present in your response.
""",

        object_identification_prompt="""
You are an expert at identifying Google TV retail display components.

CRITICAL SHELF ASSIGNMENT RULES:
Use the CENTER Y-coordinate of each detection box to determine shelf_location:

**Y-coordinate assignments:**
- Center Y < 400: Use "header_branding"
- Center Y 400-1200: Use "middle_tv"
- Center Y > 1200: Use "bottom_branding"

PRODUCT IDENTIFICATION GUIDE:

**Promotional Graphics:**
- Header: "Google TV" text on black background → "google_tv_header" assigned to "header_branding"
- Bottom: Partner logos (Google + manufacturers) → "promotional_graphic" assigned to "bottom_branding"
- Product type: "promotional_graphic"

**TVs:**
- Large black screen: "primary_display_tv"
- Active Hisense TV with Google TV interface: "hisense_google_tv"
- Product type: "tv"

**Information Materials:**
- Brochures, pamphlets, product info → "product_materials", assigned to "bottom_branding"
- Product type: "informational_materials"

Respond with structured JSON containing all detected objects with their correct shelf assignments.
    """,

        reference_images={},
        confidence_threshold=0.15,
        detection_model="yolo11l.pt",
        endcap_geometry=google_tv_endcap_geometry
    )
    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        planogram_config=google_tv_config,
    )

    # Other Brand?
    image_path = BASE_DIR / "examples" / "pipelines" / "planogram" / "google-tv.jpg"

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
