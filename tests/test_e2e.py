"""End-to-end test: OCR → LLM parse → classify one file."""
from pathlib import Path
from src.ocr_engine import extract_text_from_file
from src.invoice_parser import process_file
from src.classifier import classify_expense
from src.utils import extract_categories_from_sample, load_json
import json

print("=== E2E Test: 快递费.pdf ===\n")

# Step 1: OCR
file_path = Path("reference/invoices/快递费.pdf")
ocr_result = extract_text_from_file(file_path)
print(f"[1] OCR OK - method={ocr_result['method']}, length={len(ocr_result['text'])}")

# Step 2: LLM Parse
records = process_file(file_path, ocr_result)
print(f"[2] Parse OK - {len(records)} record(s)")
for r in records:
    print(f"    doc_type={r.get('doc_type')}")
    print(f"    date={r.get('date')}")
    print(f"    vendor={r.get('vendor')}")
    print(f"    amount={r.get('amount')} {r.get('currency')}")
    print(f"    parse_error={r.get('_parse_error', False)}")

# Step 3: Classify
person = load_json(Path("data/persons.json"))["persons"][0]  # Roy
categories = extract_categories_from_sample(Path("reference/sample_report.xlsx"))
print(f"\n[3] Classifying for: {person['name']}")

for r in records:
    if r.get("_parse_error"):
        print("    SKIP (parse error)")
        continue
    cls = classify_expense(r, person, categories)
    print(f"    L1={cls.get('category_l1')}")
    print(f"    L2={cls.get('category_l2')}")
    print(f"    L3={cls.get('category_l3')}")
    print(f"    confidence={cls.get('confidence')}")
    print(f"    reasoning={cls.get('reasoning')}")

print("\n=== DONE ===")
