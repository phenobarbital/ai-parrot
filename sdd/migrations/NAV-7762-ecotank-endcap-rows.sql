-- ============================================================
-- NAV-7762: Office Depot EcoTank End Cap planograms on the
--           perceive -> identify -> compare cycle
-- ============================================================
-- Table  : troc.planograms_configurations
-- Rows   : epson_depot_ecotank_backlit_planogram_config
--          epson_depot_ecotank_not_backlit_planogram_config
--          (keyed by config_name; the numeric id differs between environments)
-- Sets   : planogram_type, slots_definition, planogram_config,
--          roi_detection_prompt, updated_at
-- Keeps  : description, account_name, reference_images, llm_backend and
--          every other column
-- Safe   : data-only UPDATE of two rows, one transaction, no schema change.
--          Fails (and rolls back) unless exactly one active row matches each name.
-- Needs  : the slots_definition column (migration runbook, step "alter") and
--          ai-parrot-pipelines >= 1.2.5 on the worker that runs the compliance.
-- Status : NOT APPLIED
-- ============================================================
-- Generated from packages/ai-parrot-pipelines/tests/planogram_cycle/data/nav_7762/*.json;
-- test_nav_7762_ecotank_endcap_rows.py fails when this file and the fixtures differ.
--
-- Before applying (psql, same session):
--   \copy (SELECT row_to_json(t) FROM troc.planograms_configurations t WHERE config_name IN ('epson_depot_ecotank_backlit_planogram_config', 'epson_depot_ecotank_not_backlit_planogram_config')) TO 'nav7762_rows_backup.json'
-- After applying:
--   SELECT config_name, planogram_type, slots_definition IS NOT NULL AS migrated, updated_at
--     FROM troc.planograms_configurations WHERE config_name LIKE 'epson_depot_ecotank_%backlit%';
-- Rollback: restore planogram_type, slots_definition, planogram_config and
--   roi_detection_prompt of both rows from nav7762_rows_backup.json.
-- ============================================================

BEGIN;

-- epson_depot_ecotank_backlit_planogram_config
DO $row$
DECLARE
    n integer;
BEGIN
    UPDATE troc.planograms_configurations
       SET planogram_type = $pgm$endcap_no_shelves_promotional$pgm$,
           slots_definition = $pgm${"version": "1", "meta": {"brand": "Epson", "category": "Printers", "planogram_type": "endcap_no_shelves_promotional"}, "shelves": [], "zones": [{"zone_id": "zone-header-1", "kind": "backlit", "shelf_id": null, "required": true}, {"zone_id": "zone-comparison-1", "kind": "graphic", "shelf_id": null, "required": true}, {"zone_id": "zone-base-1", "kind": "graphic", "shelf_id": null, "required": true}]}$pgm$,
           planogram_config = $pgm${"brand": "Epson", "category": "Printers", "aisle": {"name": "Epson EcoTank Endcap"}, "layout_profile": {"perception_mode": "llm_detector", "roi_zone_labels": ["backlit_header", "comparison_panel", "base_graphic"], "zone_selectors": [{"zone_id": "zone-header-1", "kind": "zone", "band": [0.0, 0.35]}, {"zone_id": "zone-comparison-1", "kind": "zone", "band": [0.35, 0.65]}, {"zone_id": "zone-base-1", "kind": "zone", "band": [0.65, 1.0]}]}, "rule_bindings": [{"rule_id": "zone_present:zone-header-1", "kind": "zone_present", "target_id": "zone-header-1", "params": {}, "mandatory": true}, {"rule_id": "illumination:zone-header-1", "kind": "illumination", "target_id": "zone-header-1", "params": {"required": "on", "penalty": 0.5}, "mandatory": true}, {"rule_id": "text_requirements:zone-header-1", "kind": "text_requirements", "target_id": "zone-header-1", "params": {"requirements": [{"required_text": "EPSON", "match_type": "contains", "mandatory": true}, {"required_text": "Goodbye Cartridges", "match_type": "contains", "mandatory": true}, {"required_text": "Hello Savings", "match_type": "contains", "mandatory": true}]}, "mandatory": true}, {"rule_id": "visual_features:zone-header-1", "kind": "visual_features", "target_id": "zone-header-1", "params": {"expected": ["EPSON logo", "image of Shaquille O'Neal", "EcoTank printer", "Goodbye Cartridges Hello Savings"]}, "mandatory": true}, {"rule_id": "zone_present:zone-comparison-1", "kind": "zone_present", "target_id": "zone-comparison-1", "params": {}, "mandatory": true}, {"rule_id": "zone_present:zone-base-1", "kind": "zone_present", "target_id": "zone-base-1", "params": {}, "mandatory": true}]}$pgm$,
           roi_detection_prompt = $pgm$Analyze the {brand} promotional endcap (no shelves, no products) in this photo.
Return one detection per element below, with its label and a confidence. In 'content', transcribe verbatim
every text you can actually read on that element; never write text you cannot read, and leave it empty when
nothing is legible.

DETECTIONS:
1. 'endcap': the whole endcap, from the top of its header lightbox down to the floor base it stands on. Exclude neighbouring aisles and shelves.
2. 'backlit_header': the large lightbox at the very top of the endcap (brand logo, headline, a photo of a person and printers). Also add 'Light: ON' to 'content' when it emits its own glow, or 'Light: OFF' when it is matte print lit only by the store.
3. 'comparison_panel': the panel right below the header, with the columns comparing printer models.
4. 'base_graphic': the sign at the bottom of the endcap, resting on the floor base.
Only report elements of this endcap; skip any element that is not visible.$pgm$,
           updated_at = now()
     WHERE config_name = $pgm$epson_depot_ecotank_backlit_planogram_config$pgm$
       AND is_active = TRUE;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN
        RAISE EXCEPTION 'expected exactly 1 active row named %, updated %', $pgm$epson_depot_ecotank_backlit_planogram_config$pgm$, n;
    END IF;
END$row$;

-- epson_depot_ecotank_not_backlit_planogram_config
DO $row$
DECLARE
    n integer;
BEGIN
    UPDATE troc.planograms_configurations
       SET planogram_type = $pgm$endcap_no_shelves_promotional$pgm$,
           slots_definition = $pgm${"version": "1", "meta": {"brand": "Epson", "category": "Printers", "planogram_type": "endcap_no_shelves_promotional"}, "shelves": [], "zones": [{"zone_id": "zone-header-1", "kind": "header", "shelf_id": null, "required": true}, {"zone_id": "zone-backlit-1", "kind": "backlit", "shelf_id": null, "required": true}, {"zone_id": "zone-comparison-1", "kind": "graphic", "shelf_id": null, "required": true}, {"zone_id": "zone-base-1", "kind": "graphic", "shelf_id": null, "required": true}]}$pgm$,
           planogram_config = $pgm${"brand": "Epson", "category": "Printers", "aisle": {"name": "Epson EcoTank Endcap Not Backlit"}, "layout_profile": {"perception_mode": "llm_detector", "roi_zone_labels": ["header_sign", "backlit_panel", "comparison_panel", "base_graphic"], "zone_selectors": [{"zone_id": "zone-header-1", "kind": "zone", "band": [0.0, 0.2]}, {"zone_id": "zone-backlit-1", "kind": "zone", "band": [0.2, 0.42]}, {"zone_id": "zone-comparison-1", "kind": "zone", "band": [0.42, 0.7]}, {"zone_id": "zone-base-1", "kind": "zone", "band": [0.7, 1.0]}]}, "rule_bindings": [{"rule_id": "zone_present:zone-header-1", "kind": "zone_present", "target_id": "zone-header-1", "params": {}, "mandatory": true}, {"rule_id": "text_requirements:zone-header-1", "kind": "text_requirements", "target_id": "zone-header-1", "params": {"requirements": [{"required_text": "EPSON", "match_type": "contains", "mandatory": true}, {"required_text": "EcoTank", "match_type": "contains", "mandatory": true}, {"required_text": "Printers", "match_type": "contains", "mandatory": true}]}, "mandatory": true}, {"rule_id": "zone_present:zone-backlit-1", "kind": "zone_present", "target_id": "zone-backlit-1", "params": {}, "mandatory": true}, {"rule_id": "illumination:zone-backlit-1", "kind": "illumination", "target_id": "zone-backlit-1", "params": {"required": "off", "penalty": 0.5}, "mandatory": true}, {"rule_id": "text_requirements:zone-backlit-1", "kind": "text_requirements", "target_id": "zone-backlit-1", "params": {"requirements": [{"required_text": "Goodbye Cartridges", "match_type": "contains", "mandatory": true}, {"required_text": "Hello Savings", "match_type": "contains", "mandatory": true}]}, "mandatory": true}, {"rule_id": "visual_features:zone-backlit-1", "kind": "visual_features", "target_id": "zone-backlit-1", "params": {"expected": ["image of Shaquille O'Neal", "EcoTank printer", "Goodbye Cartridges Hello Savings"]}, "mandatory": true}, {"rule_id": "zone_present:zone-comparison-1", "kind": "zone_present", "target_id": "zone-comparison-1", "params": {}, "mandatory": true}, {"rule_id": "zone_present:zone-base-1", "kind": "zone_present", "target_id": "zone-base-1", "params": {}, "mandatory": true}]}$pgm$,
           roi_detection_prompt = $pgm$Analyze the {brand} promotional endcap (no shelves, no products) in this photo.
Return one detection per element below, with its label and a confidence. In 'content', transcribe verbatim
every text you can actually read on that element; never write text you cannot read, and leave it empty when
nothing is legible.

DETECTIONS:
1. 'endcap': the whole endcap, from the top of its header sign down to the floor base it stands on. Exclude neighbouring aisles and shelves.
2. 'header_sign': the sign at the very top of the endcap, with the brand logo and headline.
3. 'backlit_panel': the large lightbox panel right below the header sign (a photo of a person and printers). Also add 'Light: ON' to 'content' when it emits its own glow, or 'Light: OFF' when it is matte print lit only by the store.
4. 'comparison_panel': the panel in the middle with the columns comparing printer models.
5. 'base_graphic': the sign at the bottom of the endcap, resting on the floor base.
Only report elements of this endcap; skip any element that is not visible.$pgm$,
           updated_at = now()
     WHERE config_name = $pgm$epson_depot_ecotank_not_backlit_planogram_config$pgm$
       AND is_active = TRUE;
    GET DIAGNOSTICS n = ROW_COUNT;
    IF n <> 1 THEN
        RAISE EXCEPTION 'expected exactly 1 active row named %, updated %', $pgm$epson_depot_ecotank_not_backlit_planogram_config$pgm$, n;
    END IF;
END$row$;

COMMIT;
