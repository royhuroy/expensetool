"""Test credit card parsing fix."""
import sys
sys.path.insert(0, ".")
from src.invoice_parser import parse_credit_card_all
from src.ocr_engine import extract_text_from_file
from pathlib import Path

ocr = extract_text_from_file(Path("reference/invoices/信用卡账单-统计所有明细.pdf"))
result = parse_credit_card_all(ocr["text"], "信用卡账单-统计所有明细.pdf")
txns = result.get("transactions", [])
print(f"Transaction count: {len(txns)}")
print(f"Card: {result.get('card_last_four')}")
print(f"Period: {result.get('statement_period')}")
print(f"Total: {result.get('total_amount')}")
for t in txns:
    print(f"  {t.get('date')}  {t.get('vendor'):40s}  {t.get('amount'):>8}  {t.get('currency')}")
