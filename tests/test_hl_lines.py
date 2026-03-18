"""Test highlight line extraction on credit card PDF."""
import sys
sys.path.insert(0, ".")
from src.ocr_engine import extract_text_from_file, ocr_image
from src.highlight_detect import detect_highlighted_regions, has_highlights, extract_highlighted_lines
from pathlib import Path
import numpy as np

ocr = extract_text_from_file(Path("reference/invoices/信用卡账单-统计highlight的明细.pdf"))
print(f"Pages: {len(ocr['pages'])}")

all_lines = []
for i, p in enumerate(ocr["pages"]):
    img = p["image"]
    if img is not None:
        hl = has_highlights(img)
        print(f"\nPage {i}: has_highlights={hl}")
        if hl:
            entries = p.get("ocr_entries", [])
            if not entries:
                entries = ocr_image(img)
            mask = detect_highlighted_regions(img)
            lines = extract_highlighted_lines(entries, mask)
            all_lines.extend(lines)
            for line in lines:
                print(f"  >> {line}")

print(f"\nTotal highlighted lines: {len(all_lines)}")
