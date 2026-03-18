# 费用报销自动化工具 — 完整开发 Prompt

> **用途**：将此文件交给 AI（Claude / ChatGPT / DeepSeek 等），让它从零生成整个项目。
> 可根据实际需求修改后再提交。

---

## 一、项目概述

我需要一个 **命令行费用报销自动化工具**，运行环境为 **Windows 11 + Python 3.13**。

核心场景：我是一家基金 GP 的财务负责人，每月需要帮不同同事处理报销。发票/收据/信用卡账单等文件（PDF、JPG、PNG、HEIC）放在一个文件夹里，工具需要：

1. 让我选择**报销人**（从预设名单中选）
2. 输入**报销年月**
3. 自动 OCR 识别所有发票/收据，提取结构化信息
4. 根据**每个人不同的报销规则**自动分类费用
5. 自动获取人民币**汇率**并换算外币
6. 去重检测（与历史记录对比 + 批次内对比）
7. 生成 **Excel 报销报表**（复制我已有的样本格式）
8. 将发票文件**按规则重命名并归档**
9. 全程在终端中有清晰的交互提示和进度展示

---

## 二、技术栈

| 组件 | 选型 | 说明 |
|------|------|------|
| 语言 | Python 3.13 | Windows 环境 |
| LLM API | DeepSeek Chat API | OpenAI 兼容接口，base URL `https://api.deepseek.com/v1` |
| LLM 模型 | `deepseek-chat` | 用于 OCR 和分类（**注意：该模型不支持图片输入，需要替代方案或先用其他OCR引擎提取文字再发给LLM**） |
| SDK | `openai` (v2.x) | 使用 `OpenAI(api_key=..., base_url=...)` 方式 |
| PDF 处理 | `pymupdf` (fitz) | PDF → 图片 |
| 图片处理 | `pillow` + `pillow-heif` | 支持 HEIC/HEIF 格式 |
| Excel | `openpyxl` | 读写 xlsx |
| 终端 UI | `rich` | 彩色表格、进度条、面板 |
| 汇率 | 中国外汇交易中心 API | `chinamoney.com.cn` |
| 环境变量 | `python-dotenv` | 从 `.env` 读取 API Key |
| HTTP | `requests` | 汇率接口 |
| 配置 | `pyyaml` | config.yaml |

### 依赖（requirements.txt）
```
openpyxl>=3.1.0
pymupdf>=1.24.0
pillow>=10.0.0
pillow-heif>=0.18.0
rich>=13.0.0
requests>=2.31.0
openai>=1.0.0
python-dotenv>=1.0.0
pyyaml>=6.0
python-dateutil>=2.8.0
```

---

## 三、项目目录结构

```
expense-tool/
├── .env                          # API Key（不入 Git）
├── config.yaml                   # 全局配置
├── requirements.txt
├── 处理发票.bat                   # Windows 一键启动脚本
├── PROMPT.md                     # 本文件
│
├── data/
│   ├── persons.json              # 报销人员名单 + 每人的报销规则
│   ├── processed.json            # 历史已处理记录（用于去重）
│   ├── expense_tool.log          # 运行日志
│   └── exchange_rate_cache/      # 汇率缓存（按年月）
│       └── rates_2025_03.json
│
├── reference/
│   ├── sample_report.xlsx        # 样本报销 Excel（程序启动时学习格式）
│   ├── sample_files/             # 样本已命名文件（程序启动时学习命名规则）
│   │   ├── 办公费-打印费--RMB-100.pdf
│   │   ├── 软件费-GP记账软件Quickbook-2月-USD-31.pdf
│   │   ├── 信用卡账单1.pdf
│   │   └── ...（共16个样本文件）
│   ├── learned_formats.json      # 学习产出：Excel 格式
│   ├── learned_naming.json       # 学习产出：命名规则
│   └── category_rules.json       # 学习产出：分类规则
│
├── invoices/                     # 用户放入待处理的发票/收据文件
│
├── output/
│   ├── expense_report.xlsx       # 生成的报销报表
│   ├── pending_review.xlsx       # 需人工确认的条目
│   └── renamed_files/            # 归档的重命名文件
│       └── {人名}/
│
└── src/
    ├── main.py                   # 主流程编排
    ├── llm_client.py             # LLM 客户端封装
    ├── ocr_extract.py            # OCR 提取（调用 LLM 识别发票）
    ├── classifier.py             # 费用分类（调用 LLM）
    ├── learn_formats.py          # 学习样本 Excel 格式
    ├── learn_naming.py           # 学习样本文件命名规则
    ├── exchange_rate.py          # 汇率获取（中国人民银行）
    ├── dedup.py                  # 去重检测
    ├── exporter.py               # 生成 Excel + 文件归档
    └── interactive.py            # 终端交互 UI（rich）
```

---

## 四、`.env` 配置

```env
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_API_BASE=https://api.deepseek.com/v1
```

---

## 五、`config.yaml` 配置

```yaml
llm:
  model: deepseek-chat

reference:
  sample_report: "./reference/sample_report.xlsx"
  sample_files_dir: "./reference/sample_files/"
  learned_formats: "./reference/learned_formats.json"
  learned_naming: "./reference/learned_naming.json"
  category_rules: "./reference/category_rules.json"
  force_relearn: false    # 设为 true 会强制重新学习

exchange_rate:
  source: "chinamoney"
  cache_dir: "./data/exchange_rate_cache/"
  currencies:
    - USD
    - HKD
    - EUR
    - GBP
    - JPY
    - SGD
    - AUD
    - CAD
    - CHF

dedup:
  cn_invoice_keys: ["invoice_code", "invoice_number"]
  intl_invoice_keys: ["vendor", "date", "amount", "currency"]
  credit_card_keys: ["card_last_four", "date", "amount", "vendor"]
  fuzzy_match_threshold: 0.95

credit_card:
  highlight_only: true
  highlight_confidence_threshold: 0.7
  no_highlight_action: "ask"

output:
  report_filename: "expense_report.xlsx"
  pending_filename: "pending_review.xlsx"
  renamed_dir: "renamed_files"
```

---

## 六、`data/persons.json` — 报销人员及规则

这是核心数据文件，每个报销人有不同的费用分类规则：

```json
{
  "persons": [
    {
      "name": "Roy",
      "role": "财务负责人",
      "dining_rule": "同事内部聚餐/团队活动 → 团建费；外部客户/合作方 → 招待费",
      "overseas_rule": "海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费",
      "notes": "主要处理办公费/装修/设备/行政采购，软件订阅用软件费"
    },
    {
      "name": "Peter",
      "role": "投资同事",
      "dining_rule": "所有餐饮 → 招待费（投资业务性质，餐饮均视为商务招待）",
      "overseas_rule": "海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费",
      "notes": "差旅较多，机票/酒店/打车频繁"
    },
    {
      "name": "Kaiyan",
      "role": "投资同事",
      "dining_rule": "所有餐饮 → 招待费（投资业务性质，餐饮均视为商务招待）",
      "overseas_rule": "海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费",
      "notes": "差旅较多，机票/酒店/打车频繁"
    },
    {
      "name": "Yang Kong",
      "role": "投资同事",
      "dining_rule": "所有餐饮 → 招待费（投资业务性质，餐饮均视为商务招待）",
      "overseas_rule": "海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费",
      "notes": "差旅较多，机票/酒店/打车频繁"
    },
    {
      "name": "Sibei",
      "role": "新媒体运营",
      "dining_rule": "活动茶歇/聚餐 → 宣传费；普通内部餐饮 → 团建费",
      "overseas_rule": "海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费",
      "notes": "主要处理宣传/活动相关费用：茶歇、场地布置、物料、设计"
    },
    {
      "name": "Matthew",
      "role": "内容与PR",
      "dining_rule": "媒体/KOL相关餐饮 → 宣传费；其他 → 招待费",
      "overseas_rule": "海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费",
      "notes": "主要处理宣传相关：播客制作、视频剪辑、海报设计、活动场地"
    }
  ]
}
```

**重要**：LLM 分类时必须把当前报销人的 `dining_rule`、`overseas_rule`、`notes` 作为分类 prompt 的一部分，因为同一笔餐饮费对不同的人可能分到完全不同的类别。

---

## 七、主流程（main.py）

程序运行流程如下（按步骤编号）：

### Step 0：学习样本格式（静默执行，有缓存就跳过）

- **0a**：读取 `reference/sample_report.xlsx`，学习 Excel 格式（表头、列宽、字体、颜色、边框、合并单元格等），输出 `learned_formats.json`
- **0a**：从样本 Excel 数据行中提取分类规则（一级/二级/三级分类），输出 `category_rules.json`
- **0b**：扫描 `reference/sample_files/` 中的文件名，学习命名模式，输出 `learned_naming.json`
- **缓存机制**：如果 `learned_*.json` 已存在且样本文件未更新，直接加载缓存，**不展示学习结果、不询问确认**，只打一行日志
- 仅当首次学习或 `force_relearn: true` 或样本文件有更新时，才展示学习结果并要求用户确认

### Step 1：选择报销人 + 输入报销年月

**这应该是用户看到的第一个交互界面**（Step 0 应该静默完成）。

1. 展示标题面板 `费用报销自动化工具`
2. 从 `data/persons.json` 加载人员列表
3. 用 `rich.Table` 展示编号表格：`序号 | 姓名 | 角色 | 报销特性`
4. 最后一行为 `新增报销人...`（选择后交互式输入并保存到 persons.json）
5. 选择后展示该人的完整 profile（餐饮规则、海外规则、备注）
6. 输入报销年度（4位数字，范围 2000-2099）
7. 输入报销月度（1-12，自动补零为 01-12）
8. 可选输入"本次报销说明"（直接回车跳过）
9. 显示确认摘要：`✓ 报销人: Roy | 年度: 2025 | 月度: 03`

### Step 2：获取汇率

- 从中国人民银行外汇交易中心获取当月第一个工作日的中间价
- API：`POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew`
- 支持的货币：USD, HKD, EUR, GBP, JPY, SGD, AUD, CAD, CHF
- 按年月缓存到 `data/exchange_rate_cache/rates_{year}_{month}.json`
- 获取失败时有 fallback 机制（试不同日期，试备用 API，最后用硬编码近似值）
- JPY 的汇率是每 100 日元的中间价（换算时注意除以 100）

### Step 3：读取发票文件

- 扫描 `invoices/` 目录，排除以 `.` 开头的隐藏文件
- 支持格式：PDF, JPG, JPEG, PNG, HEIC, HEIF, TIFF
- 没有文件时给出提示并退出

### Step 4：OCR 识别

对每个文件调用 LLM 进行 OCR 提取结构化数据。

#### 普通发票/收据的 Prompt

让 LLM 识别以下信息并返回 JSON：
```json
{
  "doc_type": "文档类型",
  "invoice_code": "发票代码(仅中国发票)",
  "invoice_number": "发票号码(仅中国发票)",
  "date": "YYYY-MM-DD",
  "vendor": "供应商/商户名称",
  "description": "费用描述",
  "amount": "金额数字(价税合计)",
  "tax_amount": "税额",
  "currency": "货币代码(CNY/USD/HKD...)",
  "card_last_four": "信用卡后四位(非信用卡则null)",
  "notes": "备注"
}
```

doc_type 可选值：
- 中国增值税普通发票 / 中国增值税专用发票 / 中国电子发票
- 中国火车票 / 中国机票行程单
- 海外 receipt / 海外 invoice
- 外币信用卡账单 / 其他

#### 信用卡账单的特殊处理

信用卡账单（通常是多页 PDF）需要特殊处理：
- 用户会在账单上用**高亮笔/黑色圈/蓝色标记**标注需要报销的消费条目
- LLM 需要**只提取被高亮/标记的条目**，忽略未标记的
- 每个高亮条目作为一条独立的记录
- 如果整页没有高亮标记，返回 `has_highlights: false`，让用户决定：跳过 / 手动指定 / 全部纳入

#### 关于图像输入的重要说明

**DeepSeek `deepseek-chat` 模型可能不支持图像输入**。需要你评估并选择合适的方案：
- 方案A：如果 DeepSeek 有支持 vision 的模型（如 `deepseek-vision`），使用该模型
- 方案B：使用其他 OCR 引擎（如 Tesseract、PaddleOCR）先提取文字，再将文字发给 DeepSeek 分类
- 方案C：使用 Gemini / GPT-4o 等支持 vision 的 API 做 OCR，用 DeepSeek 做分类
- 请在代码中留好切换入口

图像编码方式：将图片转为 base64，通过 OpenAI 兼容的 `image_url` 格式发送：
```python
{"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{b64_data}"}}
```

PDF 处理：用 pymupdf 将每页渲染为 2x 分辨率的 PNG 图片。

### Step 5：去重

两层去重：

1. **批次内去重**：当前这批文件之间互相对比
2. **历史去重**：与 `data/processed.json` 中的历史记录对比

去重策略：
- 中国发票：`invoice_code` + `invoice_number` 完全匹配
- 海外发票/收据：`vendor`（模糊匹配, 95%阈值） + `date`（完全匹配） + `amount`（差额 ≤ 0.01） + `currency`（完全匹配）
- 信用卡条目：`card_last_four` + `date` + `amount` + `vendor`（模糊匹配）

发现重复时交互式询问：跳过 / 仍然纳入。

### Step 6：费用分类

对每条记录调用 LLM 进行分类。

**关键**：分类 prompt 中必须包含：
1. 发票结构化信息（doc_type, date, vendor, description, amount, currency）
2. `category_rules.json` 中的分类规则
3. **当前报销人的个人规则**（dining_rule, overseas_rule, notes）
4. 可选的"本次报销说明"

返回 JSON：
```json
{
  "category_l1": "一级分类",
  "category_l2": "二级分类",
  "category_l3": "三级分类(可为空)",
  "confidence": "high/medium/low",
  "reasoning": "分类依据"
}
```

置信度为 `low` 或 `medium` 的记录需要人工确认：
- 展示 top 3 候选分类
- 用户选择一个或手动输入

#### 已知的分类体系（从样本 Excel 中学到）

一级分类包括：
`软件费、会议培训费、会议费、礼品费、美国-交通费、美国出差打车、宣传费、快递费、通讯费、办公费、美国-招待费、团建费、美国-办公费、交通费、招待费、美国出差餐饮`

二级分类举例：
- 软件费 → GP记账软件Quickbook / Peter飞书AI会议账号 / Microsoft365 / 火山引擎Coze月费 / Docusign年费 / ChatGPT 等
- 办公费 → 快递费 / 打印费 / 办公用品 / 网络费 / 饮用水 / 家具 / 装修 / 电子设备 等
- 招待费 → 具体的餐厅/场景描述
- 宣传费 → 播客剪辑费 / 微信公众号认证费 / 视频制作 / 海报设计 / 活动场地 等
- 交通费 → 出租车 / 地铁 等

### Step 7：汇率换算

- 人民币（CNY/RMB）不换算
- 外币：`金额 × 汇率 = 人民币金额`
- JPY 特殊：`金额 × 汇率 / 100`（人民银行的 JPY 汇率是每 100 日元的中间价）

### Step 8：生成报告

#### Excel 报表（expense_report.xlsx）

**核心需求**：生成的 Excel 格式要尽量复制我样本 `sample_report.xlsx` 的格式。

样本格式特征（从 learned_formats.json 学到）：
- Sheet 名：Sheet1
- 表头行数：3 行（有表头、有合并单元格）
- 第一行表头列名：`年度, 月度, 一级明细, 二级明细, 三级明细, 币种, 原币金额, 汇率, 人民币金额, 文件名称`
- 共 10 列
- 字体：微软雅黑 10pt
- 表头字体颜色：蓝色 (#4E83FD)，加粗
- 边框：浅灰色细线 (#DEE0E3)
- 表头下边框：蓝色 (#4E83FD)
- 数据行交替底色

如果没有样本文件，使用默认格式（20 列完整格式，含序号、原始文件名、新文件名、文档类型、分类置信度等）。

#### 待确认报表（pending_review.xlsx）

需要人工确认的记录单独输出，额外加一列"待确认原因"。

#### 文件归档

将 `invoices/` 中的文件复制到 `output/renamed_files/{人名}/`，按学习到的命名规则重命名。

命名规则（从 learned_naming.json 学到）：
```
{person}-{category_l2}-{amount}-{currency}-{seq}
```
- 分隔符：`-`
- 金额：整数（无小数位）
- 序号：两位数补零
- 保留原始扩展名
- 信用卡账单统一用"信用卡账单"作为类别

样本文件名示例：
```
办公费-仓库搬运费--RMB-320.jpg
办公费-打印费--RMB-100.pdf
软件费-GP记账软件Quickbook-2月-USD-31.pdf
团建费-马修onboard聚餐-孔阳马修roy-RMB-461.jpg
宣传费-Wuji视频播客剪辑费--RMB-1000.jpg
通讯费-26年2月--RMB-590.58.pdf
信用卡账单1.pdf
```

### Step 9：最终汇总

展示终端汇总表：
- 每条记录一行：序号、文件名、日期、供应商、金额、货币、分类、状态
- 底部统计：报销人、期间、总数、成功数、跳过数、待确认数、合计金额（CNY）
- 输出文件路径

更新 `data/processed.json`（追加本次处理的记录，用于未来去重）。

---

## 八、LLM 客户端封装（llm_client.py）

封装要求：
- 使用 `openai` SDK v2.x 的 `OpenAI()` 客户端
- 从 `.env` 读取 `DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`
- 从 `.env` 读取 `DEEPSEEK_API_BASE` 或 `OPENAI_BASE_URL`，默认 `https://api.deepseek.com/v1`
- 对外暴露 `client.messages.create(model=..., max_tokens=..., messages=[...])` 接口
- 返回的对象需要有 `.content[0].text` 属性（与 Anthropic Claude SDK 接口兼容）
- 内部将 Claude 风格的 image block 转换为 OpenAI 风格的 `image_url` block
- 单例模式：`get_client()` 返回全局唯一实例

---

## 九、终端交互 UI（interactive.py）

使用 `rich` 库，提供以下交互函数：

| 函数 | 说明 |
|------|------|
| `get_user_inputs()` | 选人 + 输入年月 + 可选说明，返回 `(name, year, month_str, person_profile, batch_desc)` |
| `confirm_learned_formats()` | 展示学习结果让用户确认（仅首次学习时调用） |
| `handle_no_highlights()` | 信用卡账单无高亮时的处理选择 |
| `handle_duplicate()` | 重复记录的处理选择 |
| `handle_low_confidence_classification()` | 低置信度分类的人工确认 |
| `show_processing_start(step, desc)` | 显示步骤标题 |
| `show_success(msg)` | 绿色 ✓ 成功信息 |
| `show_warning(msg)` | 黄色 ⚠ 警告信息 |
| `show_error(msg)` | 红色 ✗ 错误信息 |
| `show_records_table(records)` | 表格展示所有记录 |
| `show_final_summary(...)` | 最终汇总面板 |

---

## 十、汇率模块（exchange_rate.py）

### 中国人民银行外汇交易中心 API

```
POST https://www.chinamoney.com.cn/ags/ms/cm-u-bk-ccpr/CcprHisNew
Form数据: startDate=2025-03-03&endDate=2025-03-03
```

需要设置合理的 User-Agent 和 Referer header。

返回 JSON 中的 `records` 数组，每条含：
- `voCod`: 货币代码（如 "USD"）
- `middlePri`: 中间价

### 获取策略
1. 目标日期：该月第一个工作日（周一到周五）
2. 如果当天无数据，向后依次尝试，最多 10 天
3. 失败时尝试备用 API URL
4. 全部失败时使用硬编码近似汇率

### 缓存
- 缓存路径：`data/exchange_rate_cache/rates_{year}_{month}.json`
- 有缓存则直接返回，不再请求

---

## 十一、去重模块（dedup.py）

### 数据持久化
- `data/processed.json` 存储所有历史已处理记录
- 格式：`{"records": [...]}`

### 匹配策略

| 类型 | 匹配字段 | 匹配方式 |
|------|----------|----------|
| 中国发票 | invoice_code + invoice_number | 精确匹配 |
| 海外发票 | vendor + date + amount + currency | vendor 模糊匹配(95%), 其余精确, amount 容差 0.01 |
| 信用卡条目 | card_last_four + date + amount + vendor | vendor 模糊匹配(95%), amount 容差 0.01 |

---

## 十二、学习模块

### learn_formats.py

读取 `sample_report.xlsx`：
- 提取每个 sheet 的格式信息：列宽、行高、合并单元格、冻结窗格、字体/颜色/边框/填充/对齐等
- 提取前 50 行的逐单元格样式
- 从数据行中提取分类规则（一级/二级/三级组合）
- 保存到 `learned_formats.json` 和 `category_rules.json`

### learn_naming.py

扫描 `sample_files/` 中的文件名：
- 检测分隔符（`-` / `_` / 空格）
- 检测日期模式、金额模式、货币代码、类别关键词、序号
- 推断命名 pattern
- 保存到 `learned_naming.json`

---

## 十三、启动脚本（处理发票.bat）

```bat
@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo  ==========================================
echo   费用报销自动化工具
echo  ==========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  [错误] 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

:: Check dependencies
python -c "import openpyxl, rich" >nul 2>&1
if errorlevel 1 (
    echo  正在安装依赖包，请稍候...
    pip install -r requirements.txt -q
    echo  依赖安装完成
    echo.
)

python src\main.py

echo.
pause
```

---

## 十四、已知问题和注意事项

### 1. Windows `\r\n` 问题
在 Windows 上，LLM 返回的 JSON 可能包含 `\r\n`，导致 `json.loads()` 失败。在所有 JSON 解析前统一做：
```python
text = text.replace('\r\n', '\n').replace('\r', '\n')
```

### 2. DeepSeek 模型不支持图像
`deepseek-chat` 是纯文本模型，不支持 `image_url` 类型的输入。需要：
- 要么使用支持 vision 的模型
- 要么先用本地 OCR（如 PaddleOCR/Tesseract）提取文字，再发给 DeepSeek 做分类

### 3. `.env` 加载时机
`main.py` 在检查 API Key 之前必须先加载 `.env`。确保 `load_dotenv()` 使用绝对路径：
```python
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
```

### 4. 学习步骤不应阻断用户
Step 0 的学习过程（读取样本格式、命名规则）在有缓存的情况下应该**完全静默**，用户第一个看到的交互界面应该是"选择报销人"。只有在首次运行或样本更新时才展示学习结果并要求确认。

### 5. 信用卡账单高亮识别
这是一个难点——需要 LLM 能"看到"图片中的高亮标记。如果 LLM 不支持图像，可以考虑：
- 让用户手动创建一个文本清单
- 或者使用支持 vision 的模型专门处理信用卡账单

### 6. 文件名中的中文和特殊字符
生成新文件名时需要过滤掉文件系统不允许的字符：`\ / : * ? " < > |`

---

## 十五、样本数据参考

### 样本文件名（reference/sample_files/）

```
信用卡账单1.pdf
信用卡账单2.pdf
办公费-仓库搬运费--RMB-320.jpg
办公费-打印费--RMB-100.pdf
办公费-新同事书籍-思贝-RMB-64.9.jpg
办公费-电子设备-LOOKAI-RMB-1493.72.pdf
办公费-网络费-宽带改线安装-RMB-320.pdf
办公费-装修-2个小米摄像头+128G存储卡-RMB-798.jpg
团建费-马修onboard聚餐-孔阳马修roy-RMB-461.jpg
宣传费-Wuji视频播客剪辑费--RMB-1000.jpg
宣传费-播客EP06剪辑费--RMB-900.jpg
快递费-顺丰--RMB-271.pdf
软件费-ChatGPT-2月-RMB-113.jpg
软件费-GP记账软件Quickbook-2月-USD-31.pdf
通讯费-26年1月--RMB-290.7.pdf
通讯费-26年2月--RMB-590.58.pdf
```

### 样本 Excel 的列名

`年度 | 月度 | 一级明细 | 二级明细 | 三级明细 | 币种 | 原币金额 | 汇率 | 人民币金额 | 文件名称`

### 分类规则样本（category_rules.json 节选）

```json
[
  {"l1": "软件费", "l2": "GP记账软件Quickbook", "l3": "5月费用", "amount": "201.62"},
  {"l1": "软件费", "l2": "Microsoft365", "amount": "498"},
  {"l1": "办公费", "l2": "快递费", "amount": "44"},
  {"l1": "办公费", "l2": "办公室开荒清洁费", "amount": "1500"},
  {"l1": "办公费", "l2": "网络费", "l3": "宽带安装", "amount": "299"},
  {"l1": "办公费", "l2": "家具", "l3": "茶具柜", "amount": "2300"},
  {"l1": "招待费", "l2": "8月深圳office all hands", "l3": "团餐", "amount": "470.55"},
  {"l1": "宣传费", "l2": "微信公众号认证费", "amount": "300"},
  {"l1": "快递费", "l2": "跨境EMS", "amount": "224"},
  {"l1": "通讯费", "l2": "Roy电话费", "l3": "5月", "amount": "218"},
  {"l1": "交通费", "l2": "高铁", "amount": "149.5"},
  {"l1": "美国-交通费", "l2": "纽约出租车", "amount": "74.74"},
  {"l1": "美国-招待费", "l2": "GP Annual Meeting晚宴", "amount": "200"},
  {"l1": "美国-办公费", "l2": "打印", "amount": "22.47"},
  {"l1": "团建费", "l2": "马修onboard聚餐", "amount": "461"},
  {"l1": "美国出差打车", "l2": "uber", "amount": "74.74"}
]
```

---

## 十六、期望的运行效果

```
==========================================
  费用报销自动化工具
==========================================

┌──────────────────────────┐
│  费用报销自动化工具       │
└──────────────────────────┘

请选择报销人：

 序号   姓名          角色              报销特性
 1      Roy           财务负责人        主要处理办公费/装修/设备/行政采购...
 2      Peter         投资同事          差旅较多...；餐饮规则: 所有餐饮 → 招待费
 3      Kaiyan        投资同事          差旅较多...
 4      Yang Kong     投资同事          差旅较多...
 5      Sibei         新媒体运营        主要处理宣传/活动相关费用...
 6      Matthew       内容与PR          主要处理宣传相关...
 7      新增报销人...

请选择序号: 1

已选择: Roy (财务负责人)
  主要处理办公费/装修/设备/行政采购，软件订阅用软件费
  餐饮: 同事内部聚餐/团队活动 → 团建费；外部客户/合作方 → 招待费
  海外: 海外出差使用 美国-交通费 / 美国-招待费 / 美国-办公费

请输入报销年度（如 2025）: 2025
请输入报销月度（如 03）: 03
本次报销说明（可为空，直接回车跳过）:

✓ 报销人: Roy | 年度: 2025 | 月度: 03

Step 2  获取汇率
✓ 汇率获取成功（9 种货币）
  USD: 7.1755 CNY / 1 USD
  HKD: 0.92288 CNY / 1 HKD
  ...

Step 3  读取发票文件
✓ 找到 5 个文件

Step 4  OCR 识别
  [1/5] (20%) 办公费发票.pdf
  [2/5] (40%) 差旅机票.jpg
  ...
✓ 识别完成，共 7 条记录

Step 5  检查重复
✓ 去重完成，7 条记录将继续处理

Step 6  费用分类
  [1/7] 分类: 办公费发票.pdf
  ...
✓ 分类完成

Step 7  汇率换算
✓ 汇率换算完成

Step 8  生成报告和归档文件
✓ 报销报表已生成: output/expense_report.xlsx
✓ 文件已归档: 7 个文件 -> output/renamed_files/Roy

┌──────────────────────────┐
│  报销处理完成             │
└──────────────────────────┘

 报销人           Roy
 报销期间         2025年03月
 发票/账单数量    7
 成功处理         7
 跳过（重复）     0
 待确认          0
 合计金额（CNY）  ¥ 12,345.67

 输出文件：
   报销报表: output/expense_report.xlsx
   归档目录: output/renamed_files/Roy
```

---

## 十七、代码质量要求

1. **模块化**：每个 `.py` 文件职责单一，通过 `main.py` 统一编排
2. **日志**：使用 `logging` 模块，同时输出到终端和 `data/expense_tool.log`
3. **错误处理**：OCR 单个文件失败不应中断整个流程，标记为错误并继续
4. **编码**：所有文件读写统一使用 `utf-8`
5. **类型注解**：使用 Python 3.13 的类型注解（`list[dict]` 而非 `List[Dict]`）
6. **无硬编码路径**：路径通过 `config.yaml` 配置或相对于 `PROJECT_ROOT` 计算
7. **Windows 兼容**：注意路径分隔符、终端编码（chcp 65001）、`\r\n` 问题
