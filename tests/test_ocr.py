"""Quick OCR diagnostic script."""
from src.ocr_engine import extract_text_from_file
from pathlib import Path
import traceback

test_files = [
    "reference/invoices/快递费.pdf",
    "reference/invoices/马修onboard聚餐.jpg",
    "reference/invoices/名片制作.png",
    "reference/invoices/Claude软件费.jpg",
    "reference/invoices/信用卡账单-统计所有明细.pdf",
    "reference/invoices/宽带.pdf",
    "reference/invoices/coding session午饭.jpg",
]

for f in test_files:
    p = Path(f)
    print(f"=== {p.name} ===")
    try:
        result = extract_text_from_file(p)
        text = result["text"]
        method = result["method"]
        print(f"  Method: {method}")
        print(f"  Text length: {len(text)}")
        if len(text) < 20:
            print(f"  WARNING: Very little text extracted!")
            print(f"  Full text: {repr(text)}")
        else:
            print(f"  Preview: {text[:200]}")
    except Exception as e:
        print(f"  ERROR: {e}")
        traceback.print_exc()
    print()
