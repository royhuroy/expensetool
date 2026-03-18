"""Expense classifier using DeepSeek LLM."""

import logging
from pathlib import Path

from .llm_client import chat_completion, parse_json_response

logger = logging.getLogger(__name__)

CLASSIFY_PROMPT = """你是一个专业的费用报销分类专家。请根据以下信息，为这笔费用进行分类。

## 报销人信息
- 姓名: {person_name}
- 角色: {person_role}
- 餐饮规则: {dining_rule}
- 海外出差规则: {overseas_rule}
- 特性: {person_notes}

## 本次报销说明
{batch_desc}

## 待分类费用信息
- 文件名: {filename}
- 文档类型: {doc_type}
- 日期: {date}
- 供应商/商户: {vendor}
- 费用描述: {description}
- 金额: {amount} {currency}
- 分类提示: {category_hint}

## 分类体系

### 一级明细（必选其一）:
软件费、会议培训费、会议费、礼品费、美国出差打车、宣传费、快递费、通讯费、办公费、美国-招待费、团建费、美国-办公费、交通费、招待费

### 二级明细规则:
- 招待费/美国-招待费：发票/账单中的开票方名称或餐饮店名称
- 交通费/美国出差打车：提供商名称（如uber、滴滴、高铁等）
- 办公费/美国-办公费：物品的性质（如电子设备、装修、网络费、打印费、办公用品、家具、饮用水等）
- 软件费：软件名称（如飞书、Quickbook、ChatGPT、Microsoft365等）
- 宣传费：活动/服务描述（如播客剪辑费、海报设计等）
- 团建费：活动/事件名称（如"coding session"、"团建聚餐"等）。从文件名中提取活动名称作为二级明细，同一活动的不同消费应使用相同的二级明细。
- 快递费：快递公司或类型
- 通讯费：电话费/数据费等描述
- 会议费/会议培训费：会议/培训名称
- 礼品费：礼品描述

### 三级明细规则:
- 招待费、交通费：具体消费日期（格式YYYY/MM/DD）
- 软件费：具体月份（如"3月"、"3月费用"）
- 办公费：具体物品描述（如"便签纸"、"茶具柜"、"小米摄像头"）
- 通讯费：对应月份
- 团建费：同一活动下的具体消费项目（如"午饭"、"咖啡"、"晚餐"等），用来区分同一活动中的不同笔消费。例如文件名"coding session午饭"→ L3="午饭"，"coding session咖啡"→ L3="咖啡"
- 其他：具体内容描述（如相关人员名称、具体事项等）

### 已有分类参考（历史数据中出现过的分类组合）:
{category_examples}

## 请返回以下JSON格式:
{{
  "category_l1": "一级明细",
  "category_l2": "二级明细",
  "category_l3": "三级明细（如不适用可以为空字符串）",
  "confidence": "high/medium/low",
  "reasoning": "分类依据（简要说明为什么这样分类）",
  "needs_review": false
}}

重要规则：
1. 严格根据报销人的餐饮规则判断餐饮类费用的分类
2. 美国相关费用（美元、美国商户）使用带"美国"前缀的分类（美国出差打车、美国-招待费、美国-办公费）
3. 如果无法确定分类或有多种可能，将confidence设为"low"并将needs_review设为true
4. 二级明细和三级明细要简洁，不要过长
5. 文件路径和文件名是最重要的分类依据！规则：
   - 如果文件在子文件夹中（如"招待 ¥1,771/xxx.pdf"），子文件夹名称是重要的分类提示！例如子文件夹含"招待"→招待费，含"软件"→软件费
   - 文件名中用"-"分隔的部分往往对应二级和三级明细。例如"装修-小米摄像头和储存卡" → L2="装修", L3="小米摄像头和储存卡"
   - 文件名含"coding session"、"团建-xxx"等明确团建活动名称 → 一级明细为团建费。但注意：如果子文件夹指示了其他类型（如"招待"），以子文件夹为准
   - 文件名含"播客"→ 宣传费
   - 文件名含"装修"→ 办公费，二级明细为"装修"，三级明细为具体物品
   - 文件名含"新同事飞书"→ 二级明细应写"新同事飞书费用"而非仅"飞书"
   - 文件名中描述+数字金额的模式（如"港澳直通车600"），二级明细只用描述部分（"港澳直通车"），不含金额数字
6. 商户名称识别规则（不要因为地址含城市名就当作交通费）：
   - AI/软件公司 → 软件费：FRONTIER AI、OPENAI、CLAUDE.AI、DESCRIPT、GENSPARK.AI、HANABI AI、APPLE.COM/BILL、GOOGLE(订阅)、UA INFLT(机上WiFi)等
   - 打车公司 → 美国出差打车：UBER、LYFT、WAYMO
   - 美国餐饮商户 → 美国-招待费：STARBUCKS、BLUE BOTTLE、餐厅名等
   - 判断依据是商户的业务性质，不是地址中的城市名
   - 重要：同类商户的一级明细必须统一！
7. 团建费的分类拆解规则（非常重要）：
   - 二级明细 = 活动/事件名称（从文件名提取），如"coding session"、"团建聚餐"
   - 三级明细 = 同一活动下的具体消费项（从文件名提取），如"午饭"、"咖啡"
   - 例: "coding session午饭.jpg" → L1=团建费, L2=coding session, L3=午饭
   - 例: "coding session咖啡.pdf" → L1=团建费, L2=coding session, L3=咖啡
   - 同一活动的不同消费，L1和L2必须相同，L3必须不同
8. 同一批次中文件名类似的费用都含同一活动名时，二级明细应保持一致
9. 三级明细应优先使用文件名或费用描述中的具体内容，而非仅写月份或日期"""


def classify_expense(
    record: dict,
    person: dict,
    categories: list[dict],
    batch_desc: str = "",
) -> dict:
    """Classify a single expense record.

    Args:
        record: Parsed invoice/receipt data
        person: Person profile from persons.json
        categories: Reference category combinations from sample
        batch_desc: Optional batch description

    Returns:
        Classification result with l1, l2, l3, confidence, reasoning
    """
    # Build category examples string (limit to relevant ones)
    cat_examples = _build_category_examples(categories, record)

    prompt = CLASSIFY_PROMPT.format(
        person_name=person.get("name", ""),
        person_role=person.get("role", ""),
        dining_rule=person.get("dining_rule", ""),
        overseas_rule=person.get("overseas_rule", ""),
        person_notes=person.get("notes", ""),
        batch_desc=batch_desc or "（无）",
        filename=record.get("_source_file", ""),
        doc_type=record.get("doc_type", ""),
        date=record.get("date", ""),
        vendor=record.get("vendor", ""),
        description=record.get("description", ""),
        amount=record.get("amount", ""),
        currency=record.get("currency", ""),
        category_hint=record.get("category_hint", ""),
        category_examples=cat_examples,
    )

    messages = [
        {"role": "system", "content": "你是专业的费用报销分类助手。请严格按JSON格式回答。"},
        {"role": "user", "content": prompt},
    ]

    try:
        response = chat_completion(messages, json_mode=True)
        result = parse_json_response(response)
        return result
    except Exception as e:
        logger.error(f"分类失败: {record.get('_source_file', '')}: {e}")
        return {
            "category_l1": "",
            "category_l2": "",
            "category_l3": "",
            "confidence": "low",
            "reasoning": f"分类失败: {e}",
            "needs_review": True,
        }


BATCH_CLASSIFY_PROMPT = """你是一个专业的费用报销分类专家。请为以下多笔费用逐一分类。

## 报销人信息
- 姓名: {person_name}
- 角色: {person_role}
- 餐饮规则: {dining_rule}
- 海外出差规则: {overseas_rule}
- 特性: {person_notes}

## 本次报销说明
{batch_desc}

## 分类体系
### 一级明细（必选其一）:
软件费、会议培训费、会议费、礼品费、美国出差打车、宣传费、快递费、通讯费、办公费、美国-招待费、团建费、美国-办公费、交通费、招待费

### 二级明细规则:
- 招待费/美国-招待费：开票方/餐饮店名称
- 交通费/美国出差打车：提供商名称（uber、滴滴、高铁等）
- 办公费：物品性质（电子设备、装修、网络费等）
- 软件费：软件名称（飞书、ChatGPT等）
- 宣传费：活动/服务描述
- 团建费：活动/事件名称（从文件名提取，如"coding session"）
- 快递费/通讯费/会议费/礼品费：对应描述

### 三级明细规则:
- 招待费、交通费：消费日期YYYY/MM/DD
- 软件费/通讯费：月份（如"3月"）
- 办公费：具体物品
- 团建费：同一活动的具体消费项（午饭/咖啡等）
- 其他：具体内容

### 已有分类参考:
{category_examples}

## 待分类费用列表（共{count}笔）:
{items_text}

## 重要规则:
1. 严格根据报销人餐饮规则判断餐饮类费用
2. 美国相关费用使用带"美国"前缀的分类（美国出差打车、美国-招待费、美国-办公费）
3. 文件路径和文件名是最重要的分类依据！子文件夹名称是重要提示（如子文件夹含"招待"→招待费，含"软件"→软件费）。"-"分隔的部分对应二三级明细
4. AI/软件公司→软件费：FRONTIER AI、OPENAI、CLAUDE.AI、DESCRIPT、GENSPARK.AI等
5. 打车服务→美国出差打车：UBER、LYFT、WAYMO。美国餐饮/娱乐→美国-招待费。判断依据是商户业务性质，不是地址
6. 团建费：L2=活动名，L3=具体消费项。同一活动L1和L2必须相同，L3不同
7. 文件名含"装修"→ 办公费-装修-具体物品
8. 文件名含"新同事飞书"→ L2应为"新同事飞书费用"。L2要忠实反映文件名中的完整描述
9. 同类商户L1必须统一！所有Uber/Lyft→美国出差打车，所有AI公司→软件费
10. 文件名中描述+数字金额模式（如"港澳直通车600"），L2只用描述部分（"港澳直通车"），不含金额

请返回JSON，包含与输入顺序一致的分类数组：
{{
  "results": [
    {{
      "id": 0,
      "category_l1": "一级明细",
      "category_l2": "二级明细",
      "category_l3": "三级明细",
      "confidence": "high/medium/low",
      "reasoning": "简要分类依据",
      "needs_review": false
    }}
  ]
}}"""


def classify_expenses_batch(
    records: list[dict],
    person: dict,
    categories: list[dict],
    batch_desc: str = "",
    batch_size: int = 10,
) -> list[dict]:
    """Classify multiple records in batches to reduce API calls.

    Args:
        records: List of parsed expense records
        person: Person profile
        categories: Reference categories from sample
        batch_desc: Optional batch description
        batch_size: Records per API call (default 10)

    Returns:
        List of classification results in same order as input
    """
    import json as _json

    cat_examples = _build_category_examples(categories, records[0] if records else {})
    results = [None] * len(records)

    # Split into batches
    for start in range(0, len(records), batch_size):
        chunk = records[start : start + batch_size]
        chunk_indices = list(range(start, start + len(chunk)))

        # Build items text
        items = []
        for i, rec in enumerate(chunk):
            items.append(
                f"[{i}] 文件名: {rec.get('_source_file', '')} | "
                f"类型: {rec.get('doc_type', '')} | "
                f"日期: {rec.get('date', '')} | "
                f"供应商: {rec.get('vendor', '')} | "
                f"描述: {rec.get('description', '')} | "
                f"金额: {rec.get('amount', '')} {rec.get('currency', '')} | "
                f"提示: {rec.get('category_hint', '')}"
            )

        prompt = BATCH_CLASSIFY_PROMPT.format(
            person_name=person.get("name", ""),
            person_role=person.get("role", ""),
            dining_rule=person.get("dining_rule", ""),
            overseas_rule=person.get("overseas_rule", ""),
            person_notes=person.get("notes", ""),
            batch_desc=batch_desc or "（无）",
            category_examples=cat_examples,
            count=len(chunk),
            items_text="\n".join(items),
        )

        messages = [
            {"role": "system", "content": "你是专业的费用报销分类助手。请严格按JSON格式回答。"},
            {"role": "user", "content": prompt},
        ]

        try:
            response = chat_completion(messages, max_tokens=8000, json_mode=True)
            data = parse_json_response(response)
            batch_results = data.get("results", []) if isinstance(data, dict) else data

            for item in batch_results:
                idx = item.get("id", -1)
                if 0 <= idx < len(chunk):
                    results[chunk_indices[idx]] = item
        except Exception as e:
            logger.error(f"批量分类失败 (batch {start}~{start+len(chunk)}): {e}")

        # Fill any missing results with fallback single-classification
        for i, global_idx in enumerate(chunk_indices):
            if results[global_idx] is None:
                logger.warning(f"Batch miss for record {global_idx}, falling back to single classify")
                results[global_idx] = classify_expense(chunk[i], person, categories, batch_desc)

    return results


def _build_category_examples(categories: list[dict], record: dict) -> str:
    """Build a concise list of relevant category examples."""
    if not categories:
        return "（无历史数据参考）"

    # Get unique L1 categories
    l1_set = sorted(set(c["l1"] for c in categories))
    lines = []
    for l1 in l1_set:
        l2s = set()
        for c in categories:
            if c["l1"] == l1 and c.get("l2"):
                l2s.add(c["l2"])
        # Limit to 5 examples per L1
        l2_list = sorted(l2s)[:5]
        if l2_list:
            lines.append(f"- {l1}: {', '.join(l2_list)}")
        else:
            lines.append(f"- {l1}")

    return "\n".join(lines)


def normalize_classifications(records: list[dict]) -> list[dict]:
    """Post-process: enforce consistent L1 categories and unify L2 for similar records."""
    from difflib import SequenceMatcher

    # ── Phase 0: Remap any legacy/removed L1 values ──
    _remap_legacy_l1(records)

    # ── Phase 1: LLM-based L1 consolidation ──
    _consolidate_l1_via_llm(records)

    # ── Phase 1.5: Filename-based L2 enrichment ──
    _enrich_l2_from_filename(records)

    # ── Phase 2: Cluster-based L2 unification (non-credit-card only) ──
    classified = [
        r for r in records
        if r.get("category_l1") and not r.get("_parse_error") and not r.get("_is_credit_card")
    ]
    if len(classified) < 2:
        return records

    # Group by L1
    l1_groups: dict[str, list[dict]] = {}
    for rec in classified:
        l1 = rec["category_l1"]
        l1_groups.setdefault(l1, []).append(rec)

    for l1, group in l1_groups.items():
        if len(group) < 2:
            continue

        # Find similar pairs by filename/description
        clusters: list[list[dict]] = []
        used = set()

        for i, a in enumerate(group):
            if i in used:
                continue
            cluster = [a]
            used.add(i)
            desc_a = _norm_key(a)
            for j, b in enumerate(group):
                if j in used:
                    continue
                desc_b = _norm_key(b)
                if SequenceMatcher(None, desc_a, desc_b).ratio() > 0.6:
                    cluster.append(b)
                    used.add(j)
            if len(cluster) > 1:
                clusters.append(cluster)

        # Unify each cluster: pick the most detailed L2 only (L3 stays unique per record)
        for cluster in clusters:
            best_l2 = ""
            for rec in cluster:
                l2 = rec.get("category_l2", "")
                if len(l2) > len(best_l2):
                    best_l2 = l2
            for rec in cluster:
                rec["category_l2"] = best_l2

    return records


def _norm_key(rec: dict) -> str:
    """Build a comparison key from filename and description."""
    parts = []
    fname = rec.get("_source_file", "")
    # Strip extension and common prefixes
    name = Path(fname).stem if fname else ""
    parts.append(name)
    desc = rec.get("description", "")
    if desc:
        parts.append(desc)
    return " ".join(parts).lower()


# ── Valid L1 categories (single source of truth) ──
VALID_L1 = [
    "软件费", "会议培训费", "会议费", "礼品费", "美国出差打车",
    "宣传费", "快递费", "通讯费", "办公费", "美国-招待费",
    "团建费", "美国-办公费", "交通费", "招待费",
]

# ── Legacy L1 → merged L1 mapping ──
_LEGACY_L1_MAP = {
    "美国-交通费": "美国出差打车",
    "美国出差餐饮": "美国-招待费",
}


def _remap_legacy_l1(records: list[dict]) -> None:
    """Remap any removed/legacy L1 values to their merged equivalents."""
    for rec in records:
        l1 = rec.get("category_l1", "")
        if l1 in _LEGACY_L1_MAP:
            rec["category_l1"] = _LEGACY_L1_MAP[l1]


def _enrich_l2_from_filename(records: list[dict]) -> None:
    """Apply deterministic L2 enrichment from filename patterns."""
    for rec in records:
        l1 = rec.get("category_l1", "")
        l2 = rec.get("category_l2", "")
        fname = (rec.get("_source_file") or "").lower()
        stem = Path(fname).stem if fname else ""

        if "新同事" in stem and "飞书" in stem and "新同事" not in l2:
            rec["category_l2"] = "新同事飞书费用"
        if "装修" in stem and l1 == "办公费" and "装修" not in l2:
            rec["category_l2"] = "装修"


# ── LLM-based L1 consolidation ──
CONSOLIDATE_L1_PROMPT = """你是费用报销分类审核专家。请审核以下一批费用的一级分类(L1)是否一致、合理。

## 合法的一级明细列表:
{l1_list}

## 当前分类结果:
{records_summary}

## 审核要求:
1. 相同/相似商户的L1必须一致（例如所有Uber应该都是同一个L1）
2. 所有L1必须在合法列表中。如果当前L1不在列表中，请映射到最接近的合法L1
3. 判断商户性质（AI公司→软件费，打车→美国出差打车，餐饮→招待费/美国-招待费）
4. 重要！文件路径中的子文件夹名称是强分类信号。例如子文件夹名含"招待" → 应为招待费，不应因为其他记录是团建费就把它改成团建费
5. 团建费 vs 招待费的区分：文件路径/文件夹明确指示"招待"的 → 招待费；文件名含具体团建活动名(如"coding session"、"团建-xxx") → 团建费
6. 如果所有分类都合理且一致，返回空corrections数组

请返回JSON:
{{
  "corrections": [
    {{"id": 记录序号, "category_l1": "修正后的L1", "reason": "修正原因"}}
  ]
}}
只返回需要修正的记录。如果全部正确，返回 {{"corrections": []}}"""


def _consolidate_l1_via_llm(records: list[dict]) -> None:
    """Use LLM to review and consolidate L1 categories across all records."""
    classified = [
        (i, r) for i, r in enumerate(records)
        if r.get("category_l1") and not r.get("_parse_error")
    ]
    if len(classified) < 2:
        return

    # Build concise summary
    lines = []
    for idx, (global_i, rec) in enumerate(classified):
        lines.append(
            f"[{idx}] 文件={rec.get('_source_file', '')} | "
            f"商户={rec.get('vendor', '')} | "
            f"描述={rec.get('description', '')[:30]} | "
            f"L1={rec.get('category_l1', '')}"
        )

    prompt = CONSOLIDATE_L1_PROMPT.format(
        l1_list="、".join(VALID_L1),
        records_summary="\n".join(lines),
    )

    messages = [
        {"role": "system", "content": "你是专业的费用分类审核助手。请严格返回JSON格式。"},
        {"role": "user", "content": prompt},
    ]

    try:
        response = chat_completion(messages, json_mode=True)
        data = parse_json_response(response)
        corrections = data.get("corrections", []) if isinstance(data, dict) else []

        for corr in corrections:
            idx = corr.get("id", -1)
            new_l1 = corr.get("category_l1", "")
            if 0 <= idx < len(classified) and new_l1 in VALID_L1:
                global_i = classified[idx][0]
                old_l1 = records[global_i].get("category_l1", "")
                if old_l1 != new_l1:
                    logger.info(f"L1 consolidation: [{records[global_i].get('_source_file')}] "
                                f"{old_l1} → {new_l1} ({corr.get('reason', '')})")
                    records[global_i]["category_l1"] = new_l1
    except Exception as e:
        logger.warning(f"LLM L1 consolidation failed, skipping: {e}")
