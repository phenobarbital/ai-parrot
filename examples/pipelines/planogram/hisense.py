import asyncio
from navconfig import BASE_DIR
from parrot.pipelines.planogram import PlanogramCompliancePipeline
from parrot.clients.google import (
    GoogleGenAIClient,
    GoogleModel
)

async def main():
    """Example usage of the 3-step pipeline"""
    llm = GoogleGenAIClient(model=GoogleModel.GEMINI_2_5_PRO)

    # Initialize pipeline
    pipeline = PlanogramCompliancePipeline(
        llm=llm,
        # detection_model="yolov9m.pt"  # or "yolov8s", "yolov8m", etc.
        detection_model="yolo11l.pt",
        # reference_images=reference_images,
        confidence_threshold=0.15,
    )

    planogram_config = {
        "brand": "Hisense",
        "category": "TVs",
        "aisle": {
            "name": "Electronics > TVs & Home Theater",
            "lighting_conditions": "retail_standard"
        },
        "shelves": [
            {
                "level": "header_branding",
                "height_ratio": 0.15,
                "products": [
                    {
                        "name": "Hisense Brand Logo",
                        "product_type": "Hisense Logo",
                        "mandatory": True,
                        "description": "Backlit white Hisense logo on dark background",
                        "text_requirements": [
                            {
                                "required_text": "Hisense",
                                "match_type": "exact",
                                "mandatory": True
                            }
                        ],
                        "visual_features": [
                            "White illuminated text"
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
                        "name": "Hisense U7 TV Display",
                        "product_type": "tv_demonstration",
                        "model_identifier": "U7",
                        "quantity_range": [1, 1],
                        "position_preference": "center",
                        "description": "Active TV display showing dynamic content with U7 model indicator",
                        "visual_features": [
                            "Active TV display"
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
                        "name": "Hisense U8 TV Display",
                        "product_type": "tv_demonstration",
                        "model_identifier": "U8",
                        "quantity_range": [1, 1],
                        "position_preference": "center",
                        "description": "Active TV display showing dynamic content with U8 model indicator",
                        "visual_features": [
                            "Active TV display"
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
                        "name": "Hisense U6 TV Display",
                        "product_type": "tv_demonstration",
                        "model_identifier": "U6",
                        "quantity_range": [1, 1],
                        "position_preference": "center",
                        "description": "Active TV display showing tiger image with U6 model indicator and AI features text",
                        "visual_features": [
                            "Active TV display"
                        ]
                    }
                ],
                "compliance_threshold": 0.9
            },
            {
                "level": "bottom_branding",
                "height_ratio": 0.10,
                "products": [
                    {
                        "name": "Hisense Official Partner Branding",
                        "product_type": "promotional_base",
                        "mandatory": True,
                        "description": "Dark base with Hisense logo and official partner certification",
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
                ],
                "allow_extra_products": False,
                "compliance_threshold": 0.9
            }
        ],
        "display_requirements": {
            "total_tvs_expected": 3,
            "tv_models": ["U7", "U8", "U6"],
            "branding_elements": 2,  # Top logo + bottom partner branding
            "active_displays": True,
            "model_identification": {
                "enabled": True,
                "position": "overlay_on_screen",
                "required_models": ["U7", "U8", "U6"]
            }
        },
        "detection_criteria": {
            "tv_characteristics": {
                "active_screen": True,
                "dynamic_content": True,
                "model_overlay": True,
                "size_variation": "large_format"
            },
            "branding_characteristics": {
                "illuminated_logo": True,
                "official_partner_certification": True,
                "consistent_brand_colors": True
            }
        },
        "advertisement_endcap": {
            "enabled": True,
            "promotional_type": "integrated_display",
            "position": "bottom",
            "structure": "stacked_displays",
            "text_requirements": [
                {
                    "required_text": "Hisense",
                    "match_type": "contains",
                    "mandatory": True,
                    "locations": ["header", "footer"]
                },
                {
                    "required_text": "OFFICIAL PARTNER",
                    "match_type": "contains",
                    "mandatory": True,
                    "locations": ["footer"]
                }
            ],
            "size_constraints": {
                "total_height_ratio": 1.0,
                "header_height_ratio": 0.15,
                "tv_section_height_ratio": 0.75,
                "footer_height_ratio": 0.10
            }
        }
    }

    planogram = pipeline.create_planogram_description(
        config=planogram_config
    )

    # Other Brand?
    image_path = BASE_DIR / "examples" / "pipelines" / "hisense-2.jpg"

    # Run complete pipeline
    results = await pipeline.run(
        image=image_path,
        planogram_description=planogram,
        return_overlay="identified",
        overlay_save_path="/tmp/data/planogram_overlay.jpg",
    )

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
