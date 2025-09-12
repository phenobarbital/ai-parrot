import asyncio
from navconfig import BASE_DIR
from PIL import Image
from parrot.pipelines.planogram import (
    RetailDetector
)
from parrot.models.detections import PlanogramDescriptionFactory
from parrot.clients.gpt import OpenAIClient, OpenAIModel
from parrot.clients.google import (
    GoogleGenAIClient,
    GoogleModel
)

planogram_config = {
    "brand": "Epson",
    "category": "Printers",
    "aisle": {
        "name": "Electronics > Printers & Printer Boxes and Supplies",
        "lighting_conditions": "bright"
    },
    "tags": ["goodbye", "hello", "savings", "cartridges", "ecotank"],
    # Advertisement sizing and positioning
    "advertisement": {
        "width_percent": 0.45,      # 45% of image width
        "height_percent": 0.26,     # 26% of image height
        "top_margin_percent": 0.02, # 2% margin above detected brand
        "side_margin_percent": 0.03  # 3% margin on sides
    },
    "shelves": [
        {
            "level": "header",
            "height_ratio": 0.34,  # 33% of ROI height
            "products": [
                {
                    "name": "Epson EcoTank Advertisement",
                    "product_type": "promotional_graphic",
                    "mandatory": True
                }
            ],
            "allow_extra_products": True,
            "compliance_threshold": 0.95
        },
        {
            "level": "middle",
            "height_ratio": 0.25,  # 30% of ROI height
            "products": [
                {
                    "name": "ET-2980",
                    "product_type": "printer",
                    "quantity_range": [1, 1],
                    "position_preference": "left"
                },
                {
                    "name": "ET-3950",
                    "product_type": "printer",
                    "quantity_range": [1, 1],
                    "position_preference": "center"
                },
                {
                    "name": "ET-4950",
                    "product_type": "printer",
                    "quantity_range": [1, 1],
                    "position_preference": "right"
                }
            ],
            "compliance_threshold": 0.9
        },
        {
            "level": "bottom", # No height_ratio = remaining space
            "products": [
                {
                    "name": "ET-2980 box",
                    "product_type": "printer_box",
                    "quantity_range": [1, 2]
                },
                {
                    "name": "ET-3950 box",
                    "product_type": "printer_box",
                    "quantity_range": [1, 2]
                },
                {
                    "name": "ET-4950 box",
                    "product_type": "printer_box",
                    "quantity_range": [1, 2]
                }
            ],
            "compliance_threshold": 0.8 # More flexibility for boxes
        }
    ],
    "advertisement_endcap": {
        "enabled": True,
        "promotional_type": "backlit_graphic",
        "position": "header",
        "product_weight": 0.8,
        "text_weight": 0.2,
        "text_requirements": [
            {
                "required_text": "Goodbye Cartridges",
                "match_type": "contains",
                "mandatory": True
            },
            {
                "required_text": "Hello Savings",
                "match_type": "contains",
                "mandatory": True
            }
        ]
    }
}

async def test_roi():
    photos = [
        "250714 BBY 501 Kennesaw GA.jpg",
        "original_0.jpg",
        "06668994-c27e-44d9-8d59-f1f65559c2e1-recap.jpeg",
        "eb04d624-a180-4e5c-b592-ab0d40b558f9-recap.jpeg",
        "356e053c-d630-4930-a2fd-cba4ab8f5e2b-recap.jpeg",
        "f7b45f4c-c33f-4312-9afb-e01af138e6f8-recap.jpeg",
        "check-compliance.jpeg",
        "669d25e9-f490-478b-b699-a30d6e15b49a-recap.jpeg",
        "360cd9f5-842f-41eb-b5b2-8a7f01822693-recap.jpeg",
        "89366c84-b8ef-4319-82f6-fdee61c17490-recap.jpeg",
        "d1179fc4-70ff-4088-8da6-2d1d4d19e44a-recap.jpeg"
    ]
    reference_images = [
        BASE_DIR / "examples" / "pipelines" / "ET-2980.jpg",
        BASE_DIR / "examples" / "pipelines" / "ET-3950.jpg",
        BASE_DIR / "examples" / "pipelines" / "ET-4950.jpg"
    ]
    for photo in photos:
        image_path = BASE_DIR / "examples" / "pipelines" / photo

        detector = RetailDetector(
            yolo_model="yolo11l.pt",
            conf=0.15,
            # llm=OpenAIClient(model=OpenAIModel.GPT_4O_MINI),
            llm=GoogleGenAIClient(model=GoogleModel.GEMINI_2_5_PRO),
            device="cuda",
            reference_images=reference_images
        )
        planogram_description = PlanogramDescriptionFactory.create_planogram_description(
            planogram_config
        )
        pil_image = Image.open(image_path)
        img_name = image_path.name.split(".")[0]
        det_out = await detector.detect(
            image=pil_image,
            planogram=planogram_description,
            debug_raw=f"/tmp/data/{img_name}_yolo_raw_debug.png",
            # debug_phase1=f"/tmp/data/{img_name}_yolo_phase1.png",
            # debug_phases=f"/tmp/data/{img_name}_yolo_phases.png",
        )
        shelves = det_out["shelves"]
        proposals = det_out["proposals"]

        print("PROPOSALS:", proposals)
        print("SHELVES:", shelves)


if __name__ == "__main__":
    asyncio.run(test_roi())
