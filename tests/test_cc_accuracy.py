"""Test credit card parsing accuracy after currency fix."""
import sys
sys.path.insert(0, ".")
from src.invoice_parser import process_file
from src.ocr_engine import extract_text_from_file
from pathlib import Path

# Test 1: All transactions card (USD should be correct, no CAD/EXCHG RATE entries)
print("=" * 60)
print("Test: 统计所有明细.pdf")
print("=" * 60)
fp = Path("reference/invoices/信用卡账单-统计所有明细.pdf")
ocr = extract_text_from_file(fp)
records = process_file(fp, ocr)
print(f"Records: {len(records)}")
total = 0
for i, r in enumerate(records):
    amt = float(r.get("amount", 0)) if r.get("amount") else 0
    total += amt
    vendor = str(r.get("vendor", ""))[:35].ljust(35)
    cur = r.get("currency", "")
    print(f"  [{i:2d}] {r.get('date')}  {vendor}  {amt:>8.2f}  {cur}")
print(f"  Total: {total:.2f}")

# Test 2: Highlight card
print()
print("=" * 60)
print("Test: 统计highlight的明细.pdf")
print("=" * 60)
fp2 = Path("reference/invoices/信用卡账单-统计highlight的明细.pdf")
ocr2 = extract_text_from_file(fp2)
records2 = process_file(fp2, ocr2)
print(f"Records: {len(records2)}")
total2 = 0
cad_count = 0
for i, r in enumerate(records2):
    amt = float(r.get("amount", 0)) if r.get("amount") else 0
    total2 += amt
    vendor = str(r.get("vendor", ""))[:35].ljust(35)
    cur = r.get("currency", "")
    if "CAD" in cur:
        cad_count += 1
    print(f"  [{i:2d}] {r.get('date')}  {vendor}  {amt:>8.2f}  {cur}")
print(f"  Total: {total2:.2f}  (target: 1452.42)")
print(f"  CAD entries: {cad_count} (should be 0)")
