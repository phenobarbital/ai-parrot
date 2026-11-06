---
kind: jira
jira_key: NAV-7762
fetched_at: 2026-11-06T15:57:17Z
summary_oneline: "Epson360 Planogram Compliance — Office Depot EcoTank End Cap Backlit / Not Backlit planograms (Reopened 2026-10-21)"
---

# NAV-7762 — Epson360: Planogram Compliance – Create Office Depot Planograms: EcoTank End Cap Backlit & EcoTank End Cap Not Backlit

- **Type**: Story · **Priority**: Major · **Status**: Reopened
- **Parent**: NAV-6184 (Epson360) · **Component**: Epson360 · **Labels**: Planograms
- **Reporter**: Mylene Lopez · **Assignee**: Jonathan Uzcategui
- **Created**: 2026-03-05 · **Updated**: 2026-10-21
- **Requested slug** (user invocation): `fix-planogram-complaince` → normalised to `fix-planogram-compliance`

## Status history (changelog)

| When | Who | Change |
|---|---|---|
| 2026-03-05 | Mylene Lopez | Backlog → Open |
| 2026-03-06 | Jonathan Uzcategui | Open → In Progress |
| 2026-03-16 | Mylene Lopez | description edited (media tags added) |
| 2026-03-17 | Jonathan Uzcategui | In Progress → Resolved (Done); attached 2 task logs + 2 screenshots |
| 2026-10-21 | Jonathan Uzcategui | Resolved → **Reopened** (resolution cleared) — **no comment explains why** |

## Description

Create two planogram types in the Epson360 Planogram Compliance module for Office Depot related to EcoTank End Cap displays.

Additionally, update the name of the existing “EcoTank End Cap” planogram to clearly distinguish it as the Backlit version.

Business Context / Objective

Office Depot is using now two different EcoTank End Cap display configurations (Backlit and Not Backlit). To ensure accurate compliance tracking and reporting, both display types must be represented as separate planograms in the system.

This will allow field users to correctly evaluate compliance based on the specific display type present in-store.

Requested Changes

1. Update Existing Planogram Type

Rename the current planogram:

Current Name:

EcoTank End Cap

New Name:

EcoTank End Cap Backlit

Retailer:

Office Depot

Media Tag:

Office Depot EcoTank End Cap (Backlit)

No other configuration should change unless required for consistency with the new structure.

2. Create New Planogram Type

Planogram Name:

EcoTank End Cap Not Backlit

Retailer:

Office Depot

Media Tag:

Office Depot EcoTank End Cap (Non-Backlit)

Compliance Components (for the Not Backlit Planogram)

The following compliance components should be evaluated:

	- Top Graphic is present

	- Top Graphic is correct image

	- Middle Graphic is present

	- Bottom Graphic is present

Reference Materials

	- Attached images showing:

		- EcoTank End Cap Backlit

		-

70843 OD Q1 ET-4950 Rendering_Backlit_4ft_P3.pdf

		- EcoTank End Cap Not Backlit

		-

70843 OD Q1 ET-4950 Rendering_4ft_3ft_P3.pdf

These images should be used as the reference for how the planograms are structured.

Expected Behavior

	- The Planogram Compliance module should display two distinct planogram types for Office Depot:

		- EcoTank End Cap Backlit

		- EcoTank End Cap Not Backlit

	- Users should select the appropriate planogram based on the display present in-store.

	- Compliance should be evaluated according to the defined components.

Acceptance Criteria

	- The existing Office Depot planogram “EcoTank End Cap” is renamed to “EcoTank End Cap Backlit.”

	- A new planogram “EcoTank End Cap Not Backlit” is created for Office Depot.

	- The new planogram includes the following compliance checks:

		- Top Graphic is present

		- Top Graphic is correct image

		- Middle Graphic is present

		- Bottom Graphic is present

	- Attached images are used as reference for the display structure.

	- Both planograms appear correctly in the Planogram Compliance module for Office Depot.

	- No existing planogram compliance records are broken by the rename.

## Comments

**Jonathan Uzcategui** (11/Mar/26 3:45 PM):

The planogram was created according to the instructions.

We are waiting for you to create the media tag (category) for the photos that will be subject to compliance testing.

**Mylene Lopez** (16/Mar/26 3:56 PM):

Media Tags have been created and added to the description of the ticket in BLUE.

**Jonathan Uzcategui** (17/Mar/26 1:14 PM):

The indicated adjustments have been made.

Attached is the task log, which shows that it executed without errors.

I have also included a screenshot as evidence, showing that the planograms are now available. One minor detail, however: only a single photo has been uploaded per category.

epson_endcap_compliance_ecotank_end_cap_backlit.txt epson_endcap_compliance_ecotank_end_cap_not_backlit.txt

## Attachments (12)

- 6 store photos (Office Depot stores 107, 201, 6600, 2270, 2363, 143; Jan–Feb 2026).
- `70843 OD Q1 ET-4950 Rendering_Backlit_4ft_P3.pdf`, `70843 OD Q1 ET-4950 Rendering_4ft_3ft_P3.pdf` — reference renderings.
- `epson_endcap_compliance_ecotank_end_cap_backlit.txt`, `epson_endcap_compliance_ecotank_end_cap_not_backlit.txt` — FlowTask logs of 2026-03-17.
- `image-20260317-121106.png`, `image-20260317-121147.png` — Epson360 UI screenshots.

## Evidence extracted from the attachments (2026-03-17 runs, legacy "Pure-LLM" pipeline)

- FlowTask tasks `epson.endcap_compliance_ecotank_end_cap_backlit` / `..._not_backlit`
  (YAML in `navigator-dataintegrator-tasks/programs/epson/tasks/`, outside this repo): steps
  `QueryToPandas` → `DownloadS3File` → `PlanogramCompliance` → `FilterRows` → `TableOutput`
  (table `epson.compliance_photo_reports`).
- Photo selection: `epson.store_photos WHERE categories_names @> '{"Office Depot EcoTank End Cap (Backlit)"}'`
  (resp. `(Non-Backlit)`); one photo per category in the window.
- Planogram rows: `planogram_id=23`, `config_name='epson_depot_ecotank_backlit_planogram_config'`;
  `planogram_id=24`, `config_name='epson_depot_ecotank_not_backlit_planogram_config'`.
  Both rows are in the **legacy format**: `shelves[].products[]` with `text_requirements` /
  `visual_features`, `advertisement_endcap`, `roi_detection_prompt`, `object_identification_prompt`,
  `detection_model='yolo11l.pt'`, `reference_images={}`, `endcap_geometry`.
- The backlit check was encoded as a prompt trick: label `Epson_Top_Backlit_ON` when lit, otherwise
  `ERROR_LIGHT_IS_OFF` so the product "goes missing".
- **Backlit run (photo 1383422, store OD2740)**: ROI = whole image (0,0,1125,1500), "Detected 0 items
  from LLM", header NON_COMPLIANT 0.36, middle/bottom MISSING 0.30 → overall **32.0 %, not compliant**.
  The rendered markdown still prints `HEADER Shelf: ✅` and `Text Score: 100.0%` next to failed text
  requirements. The ticket was resolved with this log attached as "executed without errors".
- **Not-backlit run (photo 1382759, store OD2705)**: 3 detections, all three shelves COMPLIANT 1.0 →
  overall **100 %**. This is the result shown in the UI screenshot.
- UI screenshot: the "Planogram Type" filter lists `EcoTank End Cap Backlit` and
  `EcoTank End Cap Not Backlit`.
