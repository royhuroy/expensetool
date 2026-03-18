"""Invoice parser: OCR text → structured data via DeepSeek LLM."""

import logging
import re
from pathlib import Path

from .llm_client import chat_completion, parse_json_response
from .utils import is_credit_card_statement, credit_card_mode

logger = logging.getLogger(__name__)


def _validate_highlight_total(data: dict, highlighted_text: str) -> None:
    """Log a warning if LLM-parsed total differs from regex-extracted amounts."""
    txns = data.get("transactions", [])
    llm_total = sum(float(t.get("amount", 0) or 0) for t in txns)

    # Extract dollar amounts from highlighted OCR text (patterns like 12.34, 1,234.56)
    amounts = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})*\.\d{2})(?!\d)", highlighted_text)
    if not amounts:
        return
    ocr_amounts = [float(a.replace(",", "")) for a in amounts]
    ocr_total = sum(ocr_amounts)

    if abs(llm_total - ocr_total) > 1.0 and ocr_total > 0:
        logger.warning(
            f"Highlight total mismatch: LLM={llm_total:.2f}, "
            f"OCR regex={ocr_total:.2f} (diff={abs(llm_total - ocr_total):.2f}). "
            f"LLM records={len(txns)}, OCR amounts={len(ocr_amounts)}"
        )

INVOICE_PARSE_PROMPT = """你是一个专业的发票/收据/账单识别专家。请根据以下OCR提取的文本内容，识别并提取结构化信息。

文件名称: {filename}

OCR识别文本:
---
{ocr_text}
---

请严格按照以下JSON格式返回（确保是有效的JSON）：
{{
  "doc_type": "文档类型",
  "date": "YYYY-MM-DD（消费日期/开票日期）",
  "vendor": "销售方/服务提供方/商户名称（注意：对于中国发票，这是【销售方】而非购买方）",
  "buyer": "购买方名称（仅中国发票需要）",
  "description": "费用描述（简要说明这是什么费用，包含项目名称中的具体内容）",
  "amount": 金额数字（价税合计或实际支付金额）,
  "tax_amount": 税额数字或null,
  "currency": "货币代码（CNY或RMB写RMB，USD/HKD/EUR/GBP/JPY等保持原样）",
  "invoice_code": "发票代码（仅中国发票，否则null）",
  "invoice_number": "发票号码（仅中国发票，否则null）",
  "notes": "其他备注信息"
}}

doc_type可选值：
- 中国增值税普通发票 / 中国增值税专用发票 / 中国电子发票
- 中国火车票 / 中国机票行程单
- 海外receipt / 海外invoice
- 付款截屏 / 转账记录
- 其他

注意事项：
1. 如果是中国发票，currency统一写"RMB"
2. 金额取价税合计（含税总额），如果只有不含税金额则取不含税金额
3. 日期格式统一为YYYY-MM-DD
4. 如果信息无法确定，对应字段写null
5. 付款截屏或转账记录也请尽量提取金额和收款方信息
6. vendor字段务必填写【销售方/收款方/服务提供商】，而非购买方（购买方通常是报销公司自身）
7. 如果是转账截屏，vendor是收款人；如果是中国发票，vendor是销售方信息中的名称
8. 重要：中国电子发票中，"北京卓远共创企业管理咨询有限公司"是购买方（报销公司），不是销售方！请根据业务逻辑判断：提供服务/商品的一方才是vendor。例如快递发票的vendor应该是快递公司，餐饮发票的vendor应该是餐厅。
9. 对于OCR文本中布局被打乱的中国发票，请注意：发票通常左边是购买方信息、右边是销售方信息（或反之），多个公司名称出现时，请根据业务上下文（项目名称、服务类型）来判断谁是销售方"""

CREDIT_CARD_ALL_PROMPT = """你是一个专业的信用卡账单识别专家。请从以下OCR识别的信用卡账单文本中，识别所有消费明细。

文件名称: {filename}

OCR识别文本:
---
{ocr_text}
---

请提取每一笔消费交易，按以下JSON格式返回（确保是有效的JSON数组）：
{{
  "transactions": [
    {{
      "date": "YYYY-MM-DD",
      "vendor": "商户名称",
      "description": "消费描述",
      "amount": 金额数字（正数表示消费，负数表示退款/返还），
      "currency": "USD/HKD/EUR等",
      "category_hint": "根据商户名称推测的消费类型（如餐饮/交通/购物等）"
    }}
  ],
  "card_last_four": "信用卡后四位（如果能识别到）",
  "statement_period": "账单周期（如2026-01至2026-02）",
  "total_amount": 账单总金额
}}

注意：
1. 只提取消费交易（purchases/transactions），不要提取还款、利息、手续费等非消费条目
2. 金额用正数表示消费支出
3. 日期统一为YYYY-MM-DD格式
4. 如果日期只有月/日，请根据账单周期推断年份
5. 重要！货币识别规则：美国信用卡账单的主货币通常是USD。如果看到"CANADIAN DOLLAR"、"EXCHG RATE"等字样，这只是说明该笔交易原始用了外币并被折算为美元——此时amount应为折算后的美元金额（即账单上显示的美元数字），currency仍然是USD。不要把汇率说明行（如"9.01 X 0.724750277 (EXCHG RATE)"）当作单独的交易。
6. 每一行交易的格式通常是：日期  商户名称  金额。注意区分交易行和它下方的外币说明附注行（CANADIAN DOLLAR / EXCHG RATE等），附注行不是独立交易。
7. category_hint要准确判断商户性质。常见AI/软件公司：FRONTIER AI、OPENAI、CLAUDE.AI、DESCRIPT、GENSPARK、HANABI AI、APPLE.COM/BILL、GOOGLE(订阅)等应归类为"软件/AI订阅"，不要因为地址含城市名就当作交通费。"""

CREDIT_CARD_HIGHLIGHT_PROMPT = """你是一个专业的信用卡账单识别专家。以下是从信用卡账单中提取的被高亮/标记区域的文本。请仅从这些高亮文本中识别消费明细。

文件名称: {filename}

高亮区域OCR文本:
---
{ocr_text}
---

完整账单文本（参考上下文）:
---
{full_text}
---

请提取被高亮标记的消费交易，按以下JSON格式返回：
{{
  "transactions": [
    {{
      "date": "YYYY-MM-DD",
      "vendor": "商户名称",
      "description": "消费描述",
      "amount": 金额数字,
      "currency": "USD/HKD/EUR等",
      "category_hint": "消费类型推测"
    }}
  ],
  "card_last_four": "信用卡后四位",
  "statement_period": "账单周期"
}}

只返回被高亮/标记的条目，不要包含未标记的交易。

重要！货币识别规则：
- 美国信用卡账单的主货币通常是USD。如果看到"CANADIAN DOLLAR"、"EXCHG RATE"等字样，这只是外币折算说明——amount应为折算后的USD金额，currency仍然是USD。
- 不要把汇率说明行（如"9.01 X 0.724750277 (EXCHG RATE)"）当作独立交易。
- 每一行交易的格式通常是：日期  商户名称  金额。汇率行只是上一笔交易的附注。
- 重要：某些高亮行可能只有日期和金额没有商户名（如"01/08  20.00"），这些仍然是有效交易，OCR将商户名和金额分到了不同行。请在完整账单文本中查找该日期附近的商户名来补全，如果找不到则vendor写"未识别商户"。不要丢弃这些条目！
- category_hint要准确判断商户性质。常见AI/软件公司：FRONTIER AI、OPENAI、CLAUDE.AI、DESCRIPT、GENSPARK、HANABI AI、APPLE.COM/BILL、GOOGLE(订阅)等应归类为"软件/AI订阅"。"""


def parse_invoice(ocr_text: str, filename: str) -> dict:
    """Parse a regular invoice/receipt using LLM."""
    prompt = INVOICE_PARSE_PROMPT.format(filename=filename, ocr_text=ocr_text[:6000])
    messages = [
        {"role": "system", "content": "你是专业的财务发票识别助手，请严格返回JSON格式。"},
        {"role": "user", "content": prompt},
    ]
    try:
        response = chat_completion(messages, json_mode=True)
        data = parse_json_response(response)
        data["_source_file"] = filename
        return data
    except Exception as e:
        logger.error(f"解析发票失败 {filename}: {e}")
        return {
            "doc_type": "解析失败",
            "date": None,
            "vendor": None,
            "description": f"OCR文本前200字: {ocr_text[:200]}",
            "amount": None,
            "currency": None,
            "notes": str(e),
            "_source_file": filename,
            "_parse_error": True,
        }


def parse_credit_card_all(ocr_text: str, filename: str) -> dict:
    """Parse all transactions from a credit card statement."""
    prompt = CREDIT_CARD_ALL_PROMPT.format(filename=filename, ocr_text=ocr_text)
    messages = [
        {"role": "system", "content": "你是专业的信用卡账单识别助手，请严格返回JSON格式。"},
        {"role": "user", "content": prompt},
    ]
    try:
        response = chat_completion(messages, max_tokens=8000, json_mode=True, temperature=0)
        data = parse_json_response(response)
        data["_source_file"] = filename
        data["_is_credit_card"] = True
        return data
    except Exception as e:
        logger.error(f"解析信用卡账单失败 {filename}: {e}")
        return {
            "transactions": [],
            "_source_file": filename,
            "_is_credit_card": True,
            "_parse_error": True,
            "notes": str(e),
        }


def parse_credit_card_highlight(
    highlighted_text: str, full_text: str, filename: str
) -> dict:
    """Parse only highlighted transactions from a credit card statement."""
    prompt = CREDIT_CARD_HIGHLIGHT_PROMPT.format(
        filename=filename,
        ocr_text=highlighted_text,
        full_text=full_text,
    )
    messages = [
        {"role": "system", "content": "你是专业的信用卡账单识别助手，请严格返回JSON格式。"},
        {"role": "user", "content": prompt},
    ]
    try:
        response = chat_completion(messages, max_tokens=8000, json_mode=True, temperature=0)
        data = parse_json_response(response)
        data["_source_file"] = filename
        data["_is_credit_card"] = True
        data["_highlight_only"] = True

        # Validate: sum parsed amounts and compare with regex-extracted amounts
        _validate_highlight_total(data, highlighted_text)

        return data
    except Exception as e:
        logger.error(f"解析信用卡高亮明细失败 {filename}: {e}")
        return {
            "transactions": [],
            "_source_file": filename,
            "_is_credit_card": True,
            "_highlight_only": True,
            "_parse_error": True,
            "notes": str(e),
        }


def process_file(file_path: Path, ocr_result: dict) -> list[dict]:
    """Process a single file's OCR results into expense records.

    Returns a list of records (1 for regular invoices, N for credit card statements).
    """
    filename = file_path.name
    full_text = ocr_result["text"]
    pages = ocr_result.get("pages", [])

    if is_credit_card_statement(filename):
        mode = credit_card_mode(filename)

        if mode == "highlight" and pages:
            # Use highlight detection
            from .highlight_detect import (
                detect_highlighted_regions,
                extract_highlighted_lines,
                has_highlights,
            )
            from .ocr_engine import ocr_image

            highlighted_texts = []
            for page_data in pages:
                img = page_data.get("image")
                entries = page_data.get("ocr_entries", [])
                if img is not None:
                    # OCR the image if no entries yet (embedded-text PDFs)
                    if not entries:
                        entries = ocr_image(img)
                    if entries and has_highlights(img):
                        mask = detect_highlighted_regions(img)
                        # Extract complete highlighted lines (grouped by row)
                        lines = extract_highlighted_lines(entries, mask)
                        highlighted_texts.extend(lines)

            if highlighted_texts:
                hl_text = "\n".join(highlighted_texts)
                parsed = parse_credit_card_highlight(hl_text, full_text, filename)
            else:
                # No highlights detected, fall back to all
                logger.warning(f"未检测到高亮标记，将识别所有明细: {filename}")
                parsed = parse_credit_card_all(full_text, filename)
        else:
            parsed = parse_credit_card_all(full_text, filename)

        # Convert credit card transactions to individual records
        records = []
        transactions = parsed.get("transactions", [])
        card_info = {
            "card_last_four": parsed.get("card_last_four"),
            "statement_period": parsed.get("statement_period"),
        }
        for txn in transactions:
            record = {
                "doc_type": "信用卡账单明细",
                "date": txn.get("date"),
                "vendor": txn.get("vendor"),
                "description": txn.get("description", ""),
                "amount": txn.get("amount"),
                "currency": txn.get("currency", "USD"),
                "category_hint": txn.get("category_hint"),
                "_source_file": filename,
                "_is_credit_card": True,
                "_card_info": card_info,
            }
            records.append(record)
        return records

    else:
        # Regular invoice/receipt
        parsed = parse_invoice(full_text, filename)
        return [parsed]
