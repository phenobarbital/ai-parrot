"""Example: Generate a PlanogramConfig JSON for the endcap_no_shelves_promotional type.

This script generates a complete planogram configuration JSON payload for a
shelf-less promotional endcap display (e.g. an Epson retro-illuminated endcap
with a backlit upper panel and a lower promotional poster) and prints it ready
for insertion into ``troc.planograms_configurations`` in PostgreSQL.

Usage::

    python endcap_no_shelves_config.py

The output JSON can be inserted into the database with:

    INSERT INTO troc.planograms_configurations
        (config_name, planogram_type, planogram_config,
         roi_detection_prompt, object_identification_prompt,
         confidence_threshold)
    VALUES
        (%(config_name)s, %(planogram_type)s, %(planogram_config)s::jsonb,
         %(roi_detection_prompt)s, %(object_identification_prompt)s,
         %(confidence_threshold)s);
"""
import json
import sys


def build_config() -> dict:
    """Build the PlanogramConfig dict for an Epson promotional endcap display.

    The display consists of:
    - A retro-illuminated upper panel (backlit lightbox) with Epson branding.
    - A lower promotional poster with product/campaign visuals.

    Returns:
        Dict matching the ``PlanogramConfig`` model schema, ready for JSON
        serialisation and database insertion.
    """
    return {
        "config_name": "epson_endcap_promo",
        "planogram_type": "endcap_no_shelves_promotional",
        "planogram_config": {
            "brand": "Epson",
            "expected_elements": [
                "backlit_panel",
                "lower_poster",
            ],
            # Expected illumination state of the backlit panel.
            # 'ON'  → the lightbox must be illuminated for compliance.
            # 'OFF' → illumination is not required (or should be off).
            "illumination_expected": "ON",
        },
        "roi_detection_prompt": (
            "Identify the full promotional Epson endcap display in this retail "
            "image.  Focus on the retro-illuminated upper backlit lightbox panel "
            "at the top of the display.  Return a single bounding box labeled "
            "'endcap' that covers the complete endcap area — from the top edge of "
            "the backlit panel all the way down to the bottom edge of the lower "
            "promotional poster.  Do not crop the lower section."
        ),
        "object_identification_prompt": (
            "Within this Epson promotional endcap display, identify the following "
            "zones and return their bounding boxes:\n"
            "1) 'backlit_panel' — the large retro-illuminated lightbox panel at the "
            "   TOP of the display.  It is a self-illuminated graphic sign featuring "
            "   the Epson brand logo or campaign graphic.  It should appear brighter "
            "   than the lower section when the backlight is ON.\n"
            "2) 'lower_poster' — the promotional poster or printed graphic at the "
            "   BOTTOM of the display, below the backlit panel.  It may show product "
            "   images, pricing, or campaign messaging.\n"
            "Return each detected zone with its label and normalised bounding box."
        ),
        "reference_images": {},
        "confidence_threshold": 0.25,
        "detection_model": "yolo11l.pt",
    }


def print_sql(cfg: dict) -> None:
    """Print an example SQL INSERT statement for the config.

    Args:
        cfg: The config dict to embed in the SQL.
    """
    pc = json.dumps(cfg["planogram_config"], ensure_ascii=False, indent=2)
    print("\n-- Example SQL INSERT (use parameterised queries in production):")
    print("INSERT INTO troc.planograms_configurations")
    print("    (config_name, planogram_type, planogram_config,")
    print("     roi_detection_prompt, object_identification_prompt,")
    print("     confidence_threshold)")
    print("VALUES (")
    print(f"    '{cfg['config_name']}',")
    print(f"    '{cfg['planogram_type']}',")
    print(f"    '{pc}'::jsonb,")
    print(f"    '{cfg['roi_detection_prompt'][:60]}...',")
    print(f"    '{cfg['object_identification_prompt'][:60]}...',")
    print(f"    {cfg['confidence_threshold']}")
    print(");")


def main() -> None:
    """Entry point: build config, print JSON, and print example SQL."""
    cfg = build_config()
    print("=== PlanogramConfig JSON for endcap_no_shelves_promotional ===")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))
    print_sql(cfg)

    # Validate JSON round-trip
    serialised = json.dumps(cfg)
    parsed = json.loads(serialised)
    assert parsed["planogram_type"] == "endcap_no_shelves_promotional", "planogram_type mismatch"
    assert parsed["planogram_config"]["illumination_expected"] == "ON", "illumination_expected missing"
    print("\n✅  JSON valid and parseable.")


if __name__ == "__main__":
    main()
