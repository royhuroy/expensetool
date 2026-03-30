"""Streamlit web application for expense reimbursement tool."""

import os
import sys
import subprocess
import logging
from datetime import datetime
from pathlib import Path

import streamlit as st

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_config, get_path
from src.utils import (
    setup_logging,
    scan_invoice_files,
    list_subfolders,
    extract_categories_from_sample,
    load_json,
    is_credit_card_statement,
)
from src.exchange_rate import fetch_exchange_rates, convert_to_rmb
from src.ocr_engine import extract_text_from_file, get_file_preview_image
from src.invoice_parser import process_file
from src.classifier import classify_expense, classify_expenses_batch, normalize_classifications
from src.dedup import batch_dedup, history_dedup, save_to_history, clear_history_for_period
from src.exporter import generate_report, archive_files, build_filename

logger = logging.getLogger(__name__)

# ─── Page Config ───
st.set_page_config(
    page_title="费用报销自动化工具",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def init_session():
    """Initialize session state variables."""
    defaults = {
        "step": "input",      # input → processing → review → export → done
        "person": None,
        "year": None,
        "month": None,
        "batch_desc": "",
        "rates_info": None,
        "files": [],
        "invoices_dir": None,
        "ocr_results": {},     # filename → ocr_result
        "records": [],         # all parsed records
        "duplicates": [],      # duplicate records
        "review_items": [],    # items needing manual review
        "review_idx": 0,
        "classifications": {}, # filename → classification result
        "final_records": [],   # records after review, ready for export
        "report_path": None,
        "pipeline_complete": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def load_persons(cfg: dict) -> list[dict]:
    persons_path = get_path(cfg, "persons_file")
    data = load_json(persons_path)
    return data.get("persons", []) if isinstance(data, dict) else []


def save_persons(cfg: dict, persons: list[dict]):
    from src.utils import save_json
    persons_path = get_path(cfg, "persons_file")
    save_json(persons_path, {"persons": persons})


# ─── Sidebar: Input Form ───
def render_sidebar(cfg: dict):
    with st.sidebar:
        st.title("📊 费用报销工具")
        st.markdown("---")

        persons = load_persons(cfg)

        # Person selection
        person_names = [f"{p['name']} ({p['role']})" for p in persons] + ["➕ 新增报销人"]
        selected = st.selectbox("报销人", person_names, key="person_select")

        if selected == "➕ 新增报销人":
            _render_new_person_form(cfg, persons)
            return

        person_idx = person_names.index(selected)
        person = persons[person_idx]

        # Show person profile
        with st.expander("👤 报销人信息", expanded=False):
            st.markdown(f"**角色**: {person['role']}")
            st.markdown(f"**餐饮规则**: {person['dining_rule']}")
            st.markdown(f"**海外规则**: {person['overseas_rule']}")
            st.markdown(f"**备注**: {person['notes']}")

        st.markdown("---")

        # Year and month
        current_year = datetime.now().year
        year = st.number_input("报销年度", min_value=2020, max_value=2099, value=current_year, key="year_input")
        month = st.number_input("报销月度", min_value=1, max_value=12, value=datetime.now().month, key="month_input")

        # Batch description
        batch_desc = st.text_area("本次报销说明（可选）", height=80, key="batch_desc_input")

        # Invoice directory with subfolder selection
        invoices_dir = get_path(cfg, "invoices_dir")
        subfolders = list_subfolders(invoices_dir)

        if len(subfolders) > 1:
            folder_labels = []
            for sf in subfolders:
                if sf == invoices_dir:
                    folder_labels.append("📁 根目录 (全部)")
                else:
                    rel = sf.relative_to(invoices_dir)
                    folder_labels.append(f"📂 {rel}")
            selected_folder_idx = st.selectbox(
                "选择发票文件夹", range(len(folder_labels)),
                format_func=lambda i: folder_labels[i],
                key="folder_select",
            )
            selected_dir = subfolders[selected_folder_idx]
        else:
            selected_dir = invoices_dir

        files = scan_invoice_files(selected_dir)
        st.markdown(f"📁 发票目录: `{selected_dir}`")
        st.markdown(f"📄 检测到 **{len(files)}** 个文件")

        if not files:
            st.warning(f"请将发票/收据文件放入:\n{invoices_dir}")

        st.markdown("---")

        # Start button
        if st.button("🚀 开始处理", type="primary", use_container_width=True, disabled=len(files) == 0):
            st.session_state.step = "processing"
            st.session_state.person = person
            st.session_state.year = year
            st.session_state.month = month
            st.session_state.batch_desc = batch_desc
            st.session_state.files = files
            st.session_state.invoices_dir = selected_dir
            st.rerun()

        # Reset button
        if st.session_state.step != "input":
            if st.button("🔄 重新开始", use_container_width=True):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()


def _render_new_person_form(cfg: dict, persons: list[dict]):
    """Render form to add a new person."""
    st.subheader("新增报销人")
    name = st.text_input("姓名")
    role = st.text_input("角色")
    dining_rule = st.text_area("餐饮规则", height=60)
    overseas_rule = st.text_input("海外出差规则", value="海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费")
    notes = st.text_area("备注", height=60)

    if st.button("保存", type="primary"):
        if name and role:
            persons.append({
                "name": name,
                "role": role,
                "dining_rule": dining_rule,
                "overseas_rule": overseas_rule,
                "notes": notes,
            })
            save_persons(cfg, persons)
            st.success(f"已添加: {name}")
            st.rerun()
        else:
            st.error("姓名和角色为必填项")


# ─── Main Content ───
def render_main(cfg: dict):
    step = st.session_state.step

    if step == "input":
        render_welcome()
    elif step == "processing":
        if st.session_state.get("pipeline_complete"):
            # Pipeline already ran — just show results and buttons
            _show_pipeline_results()
        else:
            run_pipeline(cfg)
    elif step == "review":
        render_review(cfg)
    elif step == "export":
        run_export(cfg)
    elif step == "done":
        render_done()


def render_welcome():
    st.title("费用报销自动化工具")
    st.markdown("""
    ### 使用说明

    1. **准备发票**: 将发票/收据/信用卡账单文件放入 `invoices/` 文件夹
    2. **选择报销人**: 在左侧面板选择报销人员
    3. **输入信息**: 填写报销年度、月度
    4. **开始处理**: 点击"开始处理"按钮

    ### 支持的文件类型
    - PDF、JPG、JPEG、PNG、HEIC、HEIF、TIFF

    ### 信用卡账单命名规则
    - 文件名包含 **"识别所有明细"** 或 **"所有明细"** → 识别全部交易
    - 文件名包含 **"highlight"** 或 **"高亮"** → 仅识别高亮标记的交易

    ### 技术方案
    - **OCR**: 本地 RapidOCR（支持中英文识别）
    - **智能分析**: DeepSeek API（文本解析与费用分类）
    - **汇率**: 中国人民银行外汇交易中心官方数据
    """)


def run_pipeline(cfg: dict):
    """Run the full processing pipeline with progress display."""
    st.title("处理中...")

    person = st.session_state.person
    year = st.session_state.year
    month = st.session_state.month
    files = st.session_state.files
    batch_desc = st.session_state.batch_desc

    year_str = f"{year}年"
    month_str = f"{month}月"

    # Step 0: Clear history for this person+period to avoid false duplicates on re-run
    clear_history_for_period(
        get_path(cfg, "processed_file"), person["name"], year, month
    )

    # Step 1: Exchange rates
    with st.status("📈 获取汇率...", expanded=True) as status:
        cache_dir = get_path(cfg, "exchange_rate_cache_dir")
        currencies = cfg.get("exchange_rate", {}).get("currencies", ["USD", "HKD"])
        rates_info = fetch_exchange_rates(year, month, cache_dir, currencies)
        st.session_state.rates_info = rates_info

        rates = rates_info.get("rates", {})
        source_label = "人民银行" if rates_info.get("source") == "chinamoney" else "备用"
        st.write(f"数据来源: {source_label} | 日期: {rates_info.get('date', 'N/A')}")
        for code in sorted(rates.keys()):
            note = "（每100日元）" if code == "JPY" else ""
            st.write(f"  {code}: {rates[code]} {note}")
        status.update(label=f"✅ 汇率获取成功（{len(rates)} 种货币）", state="complete")

    # Step 2: OCR + Parse (concurrent)
    all_records = []
    with st.status(f"🔍 OCR识别中... (共{len(files)}个文件)", expanded=True) as status:
        progress = st.progress(0)
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _ocr_and_parse(file_path):
            ocr_result = extract_text_from_file(file_path, dpi=cfg.get("ocr", {}).get("pdf_dpi", 300))
            records = process_file(file_path, ocr_result)
            return file_path, ocr_result, records

        futures = {}
        with ThreadPoolExecutor(max_workers=3) as executor:
            for file_path in files:
                fut = executor.submit(_ocr_and_parse, file_path)
                futures[fut] = file_path

            inv_dir = st.session_state.invoices_dir
            done_count = 0
            for fut in as_completed(futures):
                done_count += 1
                file_path = futures[fut]
                try:
                    fp, ocr_result, records = fut.result()
                    # Use relative path from invoices_dir to support subfolders
                    try:
                        rel_path = str(fp.relative_to(inv_dir)).replace("\\", "/")
                    except ValueError:
                        rel_path = fp.name
                    st.session_state.ocr_results[rel_path] = ocr_result
                    for r in records:
                        r["_source_file"] = rel_path
                    all_records.extend(records)
                    st.write(f"[{done_count}/{len(files)}] {rel_path} → {len(records)} 条记录")
                except Exception as e:
                    st.error(f"❌ {file_path.name}: {e}")
                    try:
                        rel_path = str(file_path.relative_to(inv_dir)).replace("\\", "/")
                    except ValueError:
                        rel_path = file_path.name
                    all_records.append({
                        "doc_type": "处理失败",
                        "_source_file": rel_path,
                        "_parse_error": True,
                        "notes": str(e),
                    })
                progress.progress(done_count / len(files))

        status.update(label=f"✅ OCR完成，共 {len(all_records)} 条记录", state="complete")

    # Step 3: Dedup
    with st.status("🔄 检查重复...", expanded=True) as status:
        dedup_cfg = cfg.get("dedup", {})
        threshold = dedup_cfg.get("fuzzy_match_threshold", 0.85)
        tolerance = dedup_cfg.get("amount_tolerance", 0.01)

        batch_dups = batch_dedup(all_records, threshold, tolerance)
        history_dups = history_dedup(all_records, get_path(cfg, "processed_file"), threshold, tolerance)

        all_dups = []
        dup_set = set()
        for d in batch_dups + history_dups:
            key = id(d)
            if key not in dup_set:
                dup_set.add(key)
                all_dups.append(d)

        if all_dups:
            st.write(f"⚠️ 发现 {len(all_dups)} 条可能重复的记录")
            for d in all_dups:
                src = d.get("_duplicate_of") or d.get("_duplicate_of_history", "")
                st.write(f"  - {d.get('_source_file', '')} (与 {src} 重复)")
        else:
            st.write("未发现重复记录")

        st.session_state.duplicates = all_dups
        status.update(label=f"✅ 去重完成 ({len(all_dups)} 条重复)", state="complete")

    # Step 4: Classification (batch)
    with st.status("🏷️ 费用分类中...", expanded=True) as status:
        categories = extract_categories_from_sample(get_path(cfg, "sample_report"))
        review_items = []

        # Separate parse errors from classifiable records
        error_records = [r for r in all_records if r.get("_parse_error")]
        classifiable = [r for r in all_records if not r.get("_parse_error")]

        for rec in error_records:
            rec["needs_review"] = True
            rec["_review_reason"] = "OCR/解析失败，需人工处理"
            review_items.append(rec)

        if classifiable:
            st.write(f"批量分类 {len(classifiable)} 条记录...")
            batch_results = classify_expenses_batch(
                classifiable, person, categories, batch_desc, batch_size=10
            )
            for rec, cls_result in zip(classifiable, batch_results):
                rec.update(cls_result)
                if cls_result.get("confidence") in ("low", "medium") or cls_result.get("needs_review"):
                    rec["_review_reason"] = f"分类置信度: {cls_result.get('confidence', 'unknown')} — {cls_result.get('reasoning', '')}"
                    review_items.append(rec)

        # Add duplicates to review
        for dup in all_dups:
            if dup not in review_items:
                dup["_review_reason"] = f"疑似重复: 与 {dup.get('_duplicate_of') or dup.get('_duplicate_of_history', '')} 重复"
                review_items.append(dup)

        status.update(label=f"✅ 分类完成 ({len(review_items)} 条需人工确认)", state="complete")

    # Step 4.5: Normalize similar classifications
    normalize_classifications(all_records)

    # Step 5: Exchange rate conversion
    with st.status("💱 汇率换算...", expanded=True) as status:
        for rec in all_records:
            amount = rec.get("amount")
            currency = rec.get("currency", "RMB")
            if amount is not None:
                try:
                    rmb_amount, rate_used = convert_to_rmb(float(amount), currency, rates)
                    rec["rmb_amount"] = rmb_amount
                    rec["rate_used"] = rate_used
                except (TypeError, ValueError):
                    rec["rmb_amount"] = amount
                    rec["rate_used"] = 1
            else:
                rec["rmb_amount"] = 0
                rec["rate_used"] = 1
        status.update(label="✅ 汇率换算完成", state="complete")

    st.session_state.records = all_records
    st.session_state.review_items = review_items
    st.session_state.pipeline_complete = True

    _show_pipeline_results()


def _show_pipeline_results():
    """Display pipeline results and action buttons (safe to call on rerender)."""
    all_records = st.session_state.records

    st.title("📋 识别结果确认")
    st.markdown("请检查以下识别结果，可直接在表格中修改分类。**置信度低**的行建议点击文件名查看原件后确认。")

    _render_editable_table(all_records)


def _open_file_button(file_path: Path):
    """Open a file in the system default viewer."""
    try:
        os.startfile(str(file_path))
    except Exception:
        subprocess.Popen(["explorer", "/select,", str(file_path)])


def _render_editable_table(records: list[dict]):
    """Render an editable table for all records with confidence and file links."""
    import pandas as pd

    L1_OPTIONS = [
        "软件费", "会议培训费", "会议费", "礼品费",
        "美国出差打车", "宣传费", "快递费", "通讯费", "办公费",
        "美国-招待费", "团建费", "美国-办公费", "交通费", "招待费", "差旅费",
    ]

    # ── Reorder records so duplicates appear right after their original ──
    ordered_indices: list[int] = []
    used: set[int] = set()
    for i, rec in enumerate(records):
        if i in used:
            continue
        # Skip records that are themselves duplicates; they'll be placed after their original
        if rec.get("_duplicate_of") or rec.get("_duplicate_of_history"):
            continue
        ordered_indices.append(i)
        used.add(i)
        # Attach any duplicates that reference this record's source file
        src = rec.get("_source_file", "")
        if src:
            for j, other in enumerate(records):
                if j in used:
                    continue
                if other.get("_duplicate_of") == src or other.get("_duplicate_of_history") == src:
                    ordered_indices.append(j)
                    used.add(j)
    # Remaining (orphan dups whose originals aren't in this batch)
    for i in range(len(records)):
        if i not in used:
            ordered_indices.append(i)

    # Build editable dataframe (using reordered indices)
    rows = []
    for i in ordered_indices:
        rec = records[i]
        conf = rec.get("confidence", "")
        is_dup = "_duplicate_of" in rec or "_duplicate_of_history" in rec
        dup_src = rec.get("_duplicate_of") or rec.get("_duplicate_of_history", "")
        if is_dup:
            conf = f"⚠️重复({Path(dup_src).name})" if dup_src else "⚠️重复"
        elif conf == "high":
            conf = "✅高"
        elif conf == "medium":
            conf = "⚡中"
        elif conf == "low":
            conf = "❌低"
        elif rec.get("_parse_error"):
            conf = "❌失败"

        rows.append({
            "_idx": i,
            "保留": not (rec.get("_skipped", False) or is_dup),
            "置信度": conf,
            "文件": rec.get("_source_file", ""),
            "类型": rec.get("doc_type", ""),
            "日期": rec.get("date", "") or "",
            "供应商": rec.get("vendor", "") or "",
            "描述": rec.get("description", "") or "",
            "金额": rec.get("amount", None),
            "币种": rec.get("currency", "") or "",
            "人民币": f"{rec.get('rmb_amount', 0):.2f}" if isinstance(rec.get("rmb_amount"), (int, float)) else "",
            "一级": rec.get("category_l1", "") or "",
            "二级": rec.get("category_l2", "") or "",
            "三级": rec.get("category_l3", "") or "",
            "AI理由": rec.get("reasoning", "") or "",
        })

    df = pd.DataFrame(rows)

    # Editable table
    column_config = {
        "_idx": None,  # hidden
        "保留": st.column_config.CheckboxColumn("保留", default=True, width="small"),
        "置信度": st.column_config.TextColumn("置信度", width="small", disabled=True),
        "文件": st.column_config.TextColumn("文件", width="medium", disabled=True),
        "类型": st.column_config.TextColumn("类型", width="small", disabled=True),
        "日期": st.column_config.TextColumn("日期", width="small"),
        "供应商": st.column_config.TextColumn("供应商", width="medium"),
        "描述": st.column_config.TextColumn("描述", width="medium"),
        "金额": st.column_config.NumberColumn("金额", width="small"),
        "币种": st.column_config.TextColumn("币种", width="small"),
        "人民币": st.column_config.TextColumn("人民币", width="small", disabled=True),
        "一级": st.column_config.TextColumn("一级", width="medium"),
        "二级": st.column_config.TextColumn("二级", width="medium"),
        "三级": st.column_config.TextColumn("三级", width="medium"),
        "AI理由": st.column_config.TextColumn("AI理由", width="large", disabled=True),
    }

    table_height = min(800, 50 + len(rows) * 35)

    # Layout: file-open buttons on the left, table on the right
    invoices_dir = st.session_state.get("invoices_dir")
    if invoices_dir:
        btn_col, table_col = st.columns([1, 14])
        with btn_col:
            st.markdown("<small>📂 打开</small>", unsafe_allow_html=True)
            for row_num, rec_idx in enumerate(ordered_indices):
                fname = records[rec_idx].get("_source_file", "")
                if fname:
                    fpath = Path(invoices_dir) / fname
                    if fpath.exists():
                        if st.button(
                            f"#{row_num+1}",
                            key=f"open_row_{row_num}",
                            help=fname,
                            use_container_width=True,
                        ):
                            _open_file_button(fpath)
                    else:
                        st.button(f"#{row_num+1}", key=f"open_row_{row_num}", disabled=True, use_container_width=True)
                else:
                    st.button(f"#{row_num+1}", key=f"open_row_{row_num}", disabled=True, use_container_width=True)
        with table_col:
            edited_df = st.data_editor(
                df,
                column_config=column_config,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                height=table_height,
                key="records_editor",
            )
    else:
        edited_df = st.data_editor(
            df,
            column_config=column_config,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            height=table_height,
            key="records_editor",
        )

    # Apply edits back to records
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 确认并生成报告", type="primary", use_container_width=True):
            # Apply table edits back to records
            for _, row in edited_df.iterrows():
                idx = int(row["_idx"])
                rec = records[idx]
                rec["category_l1"] = row["一级"] or rec.get("category_l1", "")
                rec["category_l2"] = row["二级"] or rec.get("category_l2", "")
                rec["category_l3"] = row["三级"] or rec.get("category_l3", "")
                rec["date"] = row["日期"] or rec.get("date", "")
                rec["vendor"] = row["供应商"] or rec.get("vendor", "")
                rec["description"] = row["描述"] or rec.get("description", "")
                # Update amount/currency if user edited them
                if row["金额"] is not None and row["金额"] != "":
                    rec["amount"] = float(row["金额"])
                if row["币种"]:
                    rec["currency"] = row["币种"]
                if not row["保留"]:
                    rec["_skipped"] = True

            st.session_state.step = "export"
            st.session_state.final_records = records
            st.rerun()

    with col2:
        total_kept = edited_df["保留"].sum()
        total_rmb = sum(
            r.get("rmb_amount", 0) for r in records
            if isinstance(r.get("rmb_amount"), (int, float))
        )
        st.metric("保留记录 / 总计", f"{total_kept} / {len(records)}")


# ─── Review Interface (now unused - merged into editable table) ───
def render_review(cfg: dict):
    """Legacy review - redirect to editable table view."""
    st.session_state.step = "processing"
    st.session_state.pipeline_complete = True
    st.rerun()


# ─── Export ───
def run_export(cfg: dict):
    st.title("📊 生成报告")

    records = st.session_state.records
    person = st.session_state.person
    year = st.session_state.year
    month = st.session_state.month
    rates_info = st.session_state.rates_info

    # Filter out skipped records
    final_records = [r for r in records if not r.get("_skipped")]
    st.session_state.final_records = final_records

    year_str = f"{year}年"
    month_str = f"{month}月"

    output_dir = get_path(cfg, "output_dir") / f"{person['name']}_{year}_{month:02d}"

    with st.status("📊 生成报表...", expanded=True) as status:
        # Generate Excel
        report_path = generate_report(
            final_records, year_str, month_str, person["name"], rates_info, output_dir
        )
        st.session_state.report_path = report_path
        status.update(label=f"✅ 报表已生成", state="complete")

    with st.status("📁 归档文件...", expanded=True) as status:
        invoices_dir = st.session_state.get("invoices_dir", get_path(cfg, "invoices_dir"))
        renamed = archive_files(final_records, invoices_dir, output_dir, person["name"])
        st.write(f"已归档 {len(renamed)} 个文件")
        for old, new in renamed.items():
            st.write(f"  {old} → {new}")
        status.update(label=f"✅ 文件归档完成 ({len(renamed)} 个)", state="complete")

    # Save to history for future dedup
    with st.status("💾 保存处理记录...", expanded=True) as status:
        for rec in final_records:
            rec["_processed_at"] = datetime.now().isoformat()
        save_to_history(
            final_records, get_path(cfg, "processed_file"),
            person["name"], year, month,
        )
        status.update(label="✅ 历史记录已更新", state="complete")

    st.session_state.step = "done"
    st.rerun()


def render_done():
    st.title("✅ 处理完成")

    person = st.session_state.person
    year = st.session_state.year
    month = st.session_state.month
    records = st.session_state.final_records
    report_path = st.session_state.report_path

    # Summary
    total = len(records)
    total_rmb = sum(r.get("rmb_amount", 0) for r in records if isinstance(r.get("rmb_amount"), (int, float)))

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("报销人", person["name"])
    col2.metric("期间", f"{year}年{month}月")
    col3.metric("记录数", total)
    col4.metric("合计金额 (RMB)", f"¥{total_rmb:,.2f}")

    # Final records table
    st.markdown("### 📋 最终报销明细")
    import pandas as pd
    rows = []
    for rec in records:
        rows.append({
            "文件": rec.get("_source_file", ""),
            "日期": rec.get("date", ""),
            "供应商": rec.get("vendor", ""),
            "金额": rec.get("amount", ""),
            "币种": rec.get("currency", ""),
            "人民币": f"{rec.get('rmb_amount', 0):.2f}" if isinstance(rec.get("rmb_amount"), (int, float)) else "",
            "一级": rec.get("category_l1", ""),
            "二级": rec.get("category_l2", ""),
            "三级": rec.get("category_l3", ""),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)

    # Download / Open buttons
    st.markdown("### 📁 输出文件")
    if report_path and Path(report_path).exists():
        st.markdown(f"📊 **报销报表**: `{report_path}`")

        with open(report_path, "rb") as f:
            st.download_button(
                "⬇️ 下载报销报表",
                data=f,
                file_name=Path(report_path).name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

        if st.button("📂 打开输出文件夹", use_container_width=True):
            try:
                os.startfile(str(Path(report_path).parent))
            except Exception:
                subprocess.Popen(["explorer", str(Path(report_path).parent)])


# ─── Main ───
def main():
    setup_logging(PROJECT_ROOT / "data" / "expense_tool.log")
    cfg = load_config()
    init_session()

    # Ensure invoices directory exists
    invoices_dir = get_path(cfg, "invoices_dir")
    invoices_dir.mkdir(parents=True, exist_ok=True)

    render_sidebar(cfg)
    render_main(cfg)


if __name__ == "__main__":
    main()
else:
    # When run via `streamlit run`
    main()
