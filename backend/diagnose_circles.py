#!/usr/bin/env python3
"""Diagnostic script for circle detection on floor plan PDFs.

Converts representative pages from PDFs, runs circle detection analysis,
and saves annotated images for visual inspection.
"""

import os
import sys
import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from app.services.pdf_service import PDFService
from app.services.cv_service import CVService

PDF_FILES = [
    "/Users/horsy/Downloads/PJ-3017 Signage Location Plan (2026-02-25).pdf",
    "/Users/horsy/Downloads/[PJ-2981] Podium & External Area Signage Location Plan (2026-02-24).pdf",
]

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "diagnose_output")
PAGES_TO_TEST = [1, 2, 3, 4, 5]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    pdf_service = PDFService(dpi=200)
    cv_service = CVService()

    print("=" * 70, flush=True)
    print("CIRCLE DETECTION DIAGNOSTIC (FINAL VALIDATION)", flush=True)
    print("=" * 70, flush=True)

    for pdf_path in PDF_FILES:
        pdf_name = os.path.basename(pdf_path)
        print(f"\n{'='*70}", flush=True)
        print(f"PDF: {pdf_name}", flush=True)
        print(f"{'='*70}", flush=True)

        if not os.path.exists(pdf_path):
            print(f"  ERROR: File not found!", flush=True)
            continue

        page_count = pdf_service.get_page_count(pdf_path)
        print(f"  Total pages: {page_count}", flush=True)

        for page_num in PAGES_TO_TEST:
            if page_num > page_count:
                continue

            print(f"\n  --- Page {page_num} ---", flush=True)
            safe_name = pdf_name.replace(" ", "_").replace("[", "").replace("]", "").replace("(", "").replace(")", "")
            prefix = os.path.join(OUTPUT_DIR, f"{safe_name}_p{page_num}")

            img_path = f"{prefix}.png"
            if not os.path.exists(img_path):
                pdf_service.convert_single_page(pdf_path, page_num, img_path)

            img = cv2.imread(img_path)
            h, w = img.shape[:2]

            sample_info = cv_service._analyze_sample_circle(img)
            if sample_info:
                color = sample_info.get('color_type', '?')
                radius = sample_info['radius']
                circ = sample_info['circularity']
                print(f"  Sample: {color}, r={radius}, circularity={circ:.3f}", flush=True)
            else:
                print(f"  Sample: NOT FOUND", flush=True)

            detected = cv_service.detect_circles_by_template(img_path)
            print(f"  Detected: {len(detected)} circles", flush=True)

            if detected:
                annotated = img.copy()
                for c in detected:
                    cv2.circle(annotated, (c['center_x'], c['center_y']), c['radius'], (0, 255, 0), 2)
                    cv2.circle(annotated, (c['center_x'], c['center_y']), 2, (0, 0, 255), 3)
                cv2.imwrite(f"{prefix}_detected.png", annotated)

    print(f"\n{'='*70}", flush=True)
    print(f"DONE. Output: {OUTPUT_DIR}", flush=True)
    print(f"{'='*70}", flush=True)


if __name__ == "__main__":
    main()
