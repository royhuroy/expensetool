"""Test highlight detection on credit card PDF."""
import sys
sys.path.insert(0, ".")
from src.ocr_engine import extract_text_from_file, ocr_image
from src.highlight_detect import detect_highlighted_regions, has_highlights, filter_highlighted_text
from pathlib import Path
import numpy as np

ocr = extract_text_from_file(Path("reference/invoices/信用卡账单-统计highlight的明细.pdf"))
print(f"Pages: {len(ocr['pages'])}")
print(f"Text len: {len(ocr['text'])}")

for i, p in enumerate(ocr["pages"]):
    img = p["image"]
    if img is not None:
        hl = has_highlights(img)
        print(f"\nPage {i}: shape={img.shape}, has_highlights={hl}")
        if hl:
            mask = detect_highlighted_regions(img)
            highlight_pct = np.count_nonzero(mask) / mask.size * 100
            print(f"  Highlight coverage: {highlight_pct:.2f}%")
            entries = p.get("ocr_entries", [])
            if not entries:
                entries = ocr_image(img)
                print(f"  OCR entries: {len(entries)}")
            filtered = filter_highlighted_text(entries, mask)
            print(f"  Highlighted entries: {len(filtered)}")
            for e in filtered[:15]:
                print(f"    [{e['text']}]")
        else:
            print("  No highlights detected on this page")
    else:
        print(f"\nPage {i}: no image")
