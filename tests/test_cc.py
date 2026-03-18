"""Test credit card statement processing."""
from pathlib import Path
from src.ocr_engine import extract_text_from_file
from src.invoice_parser import process_file
from src.utils import is_credit_card_statement, credit_card_mode

files = [
    Path("reference/invoices/信用卡账单-统计所有明细.pdf"),
    Path("reference/invoices/信用卡账单-统计highlight的明细.pdf"),
]

for f in files:
    print(f"=== {f.name} ===")
    print(f"  is_credit_card: {is_credit_card_statement(f.name)}")
    print(f"  mode: {credit_card_mode(f.name)}")

    ocr = extract_text_from_file(f)
    print(f"  OCR method: {ocr['method']}, text length: {len(ocr['text'])}")
    print(f"  Pages: {len(ocr['pages'])}")
    for i, p in enumerate(ocr['pages']):
        has_img = p.get('image') is not None
        n_entries = len(p.get('ocr_entries', []))
        print(f"    Page {i}: text_len={len(p.get('text',''))}, has_image={has_img}, ocr_entries={n_entries}")

    print(f"  Text preview: {ocr['text'][:300]}")
    print()

    try:
        records = process_file(f, ocr)
        print(f"  Records: {len(records)}")
        for r in records:
            print(f"    - {r.get('date')} | {r.get('vendor')} | {r.get('amount')} {r.get('currency')} | error={r.get('_parse_error', False)}")
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()

    print()
