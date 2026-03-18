"""Test full highlight credit card processing pipeline."""
import sys
sys.path.insert(0, ".")
from src.invoice_parser import process_file
from src.ocr_engine import extract_text_from_file
from pathlib import Path

fp = Path("reference/invoices/信用卡账单-统计highlight的明细.pdf")
ocr = extract_text_from_file(fp)
print(f"OCR: {len(ocr['pages'])} pages, {len(ocr['text'])} chars")

records = process_file(fp, ocr)
print(f"Records returned: {len(records)}")
total = 0
for i, r in enumerate(records):
    vendor = str(r.get('vendor', ''))[:40].ljust(40)
    amt = r.get('amount', 0)
    total += float(amt) if amt else 0
    print(f"  [{i:2d}] {r.get('date')}  {vendor}  {amt:>8}  {r.get('currency')}  {r.get('category_hint','')}")
print(f"Total amount: {total:.2f}")
