#!/usr/bin/env python3
"""Find shelf-label candidates without model weights or training.

Geometry/contrast heuristics, NOT a trained label classifier or price OCR.
Example: python detect_price_labels.py photo1.jpeg photo2.jpeg --output results
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def candidates(image, min_width, max_width):
    """Return contrasting, approximately rectangular components at several thresholds."""
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    found = []
    for threshold in (130, 150, 170, 190, 210, 230):
        mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)[1]
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, bw, bh = cv2.boundingRect(contour)
            if not (min_width*w < bw < max_width*w and
                    .014*h < bh < .06*h and 1.65 < bw/bh < 4.4):
                continue
            (_, _), (rw, rh), _ = cv2.minAreaRect(contour)
            rectangularity = cv2.contourArea(contour) / (rw*rh + 1e-6)
            if rectangularity < .75:
                continue
            contrast = float(gray[y:y+bh, x:x+bw].std())
            if contrast < 25:
                continue
            found.append({"box": [x, y, x+bw, y+bh],
                          "rectangularity": float(rectangularity),
                          "contrast": contrast})
    # Suppress both duplicates across thresholds and nested screen/frame contours.
    kept = []
    for item in sorted(found, key=lambda d: d["rectangularity"], reverse=True):
        x1, y1, x2, y2 = item["box"]
        area = (x2-x1)*(y2-y1)
        duplicate = False
        for other in kept:
            a, b, c, d = other["box"]
            overlap = max(0, min(x2,c)-max(x1,a))*max(0, min(y2,d)-max(y1,b))
            if overlap/min(area, (c-a)*(d-b)) > .5:
                duplicate = True
                break
        if not duplicate:
            kept.append(item)
    return kept


def group_rows(items, image_width, min_row_labels=4, max_slope=.12):
    """Deterministic line consensus: at least four aligned, similarly sized boxes.

    This groups visible label rows, not planogram shelf identities. A line may
    contain a gap; missing labels are never invented to fill that gap.
    """
    if not items:
        return [], []
    boxes = np.array([d["box"] for d in items], dtype=float)
    centers = (boxes[:, :2]+boxes[:, 2:])/2
    widths = boxes[:, 2]-boxes[:, 0]
    heights = boxes[:, 3]-boxes[:, 1]
    available = list(range(len(items)))
    rows = []
    while len(available) >= min_row_labels:
        best = None
        for offset, i in enumerate(available):
            for j in available[offset+1:]:
                dx = centers[j,0]-centers[i,0]
                if abs(dx) < .2*image_width:
                    continue
                a = (centers[j,1]-centers[i,1])/dx
                if abs(a) > max_slope:
                    continue
                b = centers[i,1]-a*centers[i,0]
                indexes = np.array(available)
                residuals = np.abs(centers[indexes,1]-(a*centers[indexes,0]+b))
                med_height = np.median(heights[[i,j]])
                med_width = np.median(widths[[i,j]])
                keep = ((residuals < .40*med_height) &
                        (heights[indexes] > .6*med_height) &
                        (heights[indexes] < 1.6*med_height) &
                        (widths[indexes] > .6*med_width) &
                        (widths[indexes] < 1.6*med_width))
                members = indexes[keep]
                if len(members) < min_row_labels:
                    continue
                span = np.ptp(centers[members,0])
                if span < .25*image_width:
                    continue
                score = (len(members), -float(np.median(residuals[keep])))
                if best is None or score > best[0]:
                    best = (score, members)
        if best is None:
            break
        members = best[1]
        a, b = np.polyfit(centers[members,0], centers[members,1], 1)
        ordered = sorted(members.tolist(), key=lambda i: centers[i,0])
        rows.append({"members": ordered, "slope": float(a), "intercept": float(b)})
        consumed = set(ordered)
        available = [i for i in available if i not in consumed]
    rows.sort(key=lambda row: row["slope"]*image_width/2+row["intercept"])
    return rows, available


def detect(path, output, args):
    original = cv2.imread(str(path))
    if original is None:
        raise ValueError(f"Cannot read image: {path}")
    oh, ow = original.shape[:2]
    scale = min(1., args.work_width/ow)
    image = cv2.resize(original, (round(ow*scale), round(oh*scale)),
                       interpolation=cv2.INTER_AREA) if scale < 1 else original.copy()
    h, w = image.shape[:2]
    sx, sy = ow/w, oh/h
    raw = candidates(image, args.min_width, args.max_width)
    # Optional fixture ROI in normalized original-image coordinates. Detection
    # stays on the full image so the relative size filters do not change.
    if args.roi:
        l,t,r,b = args.roi
        raw = [d for d in raw if l <= (d["box"][0]+d["box"][2])/(2*w) <= r
               and t <= (d["box"][1]+d["box"][3])/(2*h) <= b]
    rows, unassigned = group_rows(raw, w, args.min_row_labels)
    output.mkdir(parents=True, exist_ok=True)
    crops = output/"crops"
    crops.mkdir(exist_ok=True)
    overlay = original.copy()
    palette = [(0,200,0), (255,160,0), (0,170,255), (220,0,220), (0,220,220)]
    records = []

    def full_box(box):
        return [round(box[0]*sx), round(box[1]*sy),
                round(box[2]*sx), round(box[3]*sy)]

    for row_number, row in enumerate(rows, 1):
        labels = []
        for position, index in enumerate(row["members"], 1):
            item = raw[index]
            x1,y1,x2,y2 = full_box(item["box"])
            # Border padding: selected contour may enclose the display inside
            # the white frame. Save pixels from the ORIGINAL resolution for OCR.
            px, py = max(2,round((x2-x1)*.12)), max(2,round((y2-y1)*.18))
            crop_box = [max(0,x1-px), max(0,y1-py), min(ow,x2+px), min(oh,y2+py)]
            a,b,c,d = crop_box
            label_id = f"r{row_number:02d}_p{position:02d}"
            crop_path = crops/f"{label_id}.png"
            if not cv2.imwrite(str(crop_path), original[b:d,a:c]):
                raise IOError(f"Cannot write {crop_path}")
            labels.append({"id": label_id, "position_in_visible_row": position,
                           "box_xyxy": [x1,y1,x2,y2], "crop_box_xyxy": crop_box,
                           "crop": f"crops/{label_id}.png",
                           "rectangularity": round(item["rectangularity"],4),
                           "status": "unverified_label_candidate", "price": None})
            color = palette[(row_number-1)%len(palette)]
            cv2.rectangle(overlay,(x1,y1),(x2,y2),color,max(2,round(ow/800)))
            cv2.putText(overlay,f"{row_number}:{position}",(x1,max(18,y1-5)),
                        cv2.FONT_HERSHEY_SIMPLEX,ow/3000,color,max(1,round(ow/1000)))
        records.append({"visible_row": row_number, "count": len(labels),
                        "line_original_pixels": {
                            "slope": row["slope"]*sy/sx,
                            "intercept": row["intercept"]*sy}, "labels": labels})
    report = {"image": str(path.resolve()), "original_shape": [oh,ow],
              "processing_shape": [h,w], "roi_normalized": args.roi,
              "method": "multithreshold_contours_with_row_consensus",
              "candidate_count": sum(r["count"] for r in records),
              "visible_row_count": len(records), "rows": records,
              "unassigned_candidates": [{"box_xyxy": full_box(raw[i]["box"])}
                                         for i in unassigned],
              "notes": ["Candidates require review; rectangularity is not confidence.",
                        "Row/position indexes are photo-local, not planogram positions.",
                        "No OCR, product recognition, cross-photo deduplication or compliance scoring.",
                        "Glare, partial frames and rows with few labels can be missed."]}
    (output/"labels.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    if not cv2.imwrite(str(output/"annotated.jpg"),overlay):
        raise IOError("Cannot write annotation")
    print(json.dumps({"image":path.name,"candidates":report["candidate_count"],
                      "row_counts":[r["count"] for r in records],"output":str(output)}))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("label_results"))
    parser.add_argument("--work-width",type=int,default=2048,
                        help="Maximum processing width; crops retain input resolution")
    parser.add_argument("--min-width",type=float,default=.025,
                        help="Minimum label width as fraction of full photo width")
    parser.add_argument("--max-width",type=float,default=.09)
    parser.add_argument("--min-row-labels",type=int,default=4)
    parser.add_argument("--roi",type=float,nargs=4,metavar=("LEFT","TOP","RIGHT","BOTTOM"),
                        help="Optional fixture bounds normalized to 0..1")
    args=parser.parse_args()
    if args.work_width < 256 or not (0 < args.min_width < args.max_width <= 1):
        parser.error("Invalid work width or label width limits")
    if args.min_row_labels < 3:
        parser.error("min-row-labels must be >= 3")
    if args.roi and not (0 <= args.roi[0] < args.roi[2] <= 1 and
                         0 <= args.roi[1] < args.roi[3] <= 1):
        parser.error("ROI must be LEFT TOP RIGHT BOTTOM within 0..1")
    # Fail on existing folders to avoid stale crops after changing parameters.
    for n,path in enumerate(args.images,1):
        dest=args.output/f"image_{n:02d}"
        if dest.exists():
            parser.error(f"Output already exists: {dest}. Choose a new --output directory.")
        detect(path,dest,args)


if __name__ == "__main__":
    main()
