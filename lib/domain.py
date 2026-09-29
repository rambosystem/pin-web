"""Advertising-domain context shared by every LLM prompt (translation, PIN
analysis, AI comment drafts, assessment explanations).

Single source of truth for:
  * what Pacvue is and which product modules the Defenders team owns,
  * the terminology the model must keep in English vs. render with a fixed
    Chinese equivalent,
  * the analysis lenses that matter in retail-media advertising tickets.

Bump ``PROMPT_VERSION`` whenever the wording below changes materially: it is
mixed into the translation cache hash so stale translations are redone.
"""

from __future__ import annotations

PROMPT_VERSION = "ads-v1"

# ---------------------------------------------------------------------------
# Business context
# ---------------------------------------------------------------------------

DOMAIN_CONTEXT_ZH = (
    "领域背景：Pacvue 是面向品牌方与代理商的零售媒体（Retail Media）广告 SaaS 平台，"
    "覆盖 Amazon、Walmart（Walmart Connect/WMC）、Instacart、Target、Kroger、DoorDash、Sam's Club、Bol、"
    "Criteo、Citrus 等零售商/渠道的广告投放管理、竞价与预算自动化、分时投放、报表分析和数字货架（SOV，Share of Voice）追踪。"
    "PIN（Product Incoming Need）由 Customer Success / Account Manager 或客户提出，对象是 Pacvue 平台功能。"
    "Defenders 团队负责的模块及含义："
    "My Report（自定义报表：自选指标/维度/筛选，可定时发送与导出）、"
    "Company Board（公司级/跨账号汇总看板，别名 Global Report）、"
    "SOV（数字货架/搜索结果份额追踪：关键词、品牌、商品在搜索结果页 SRP 上的 Paid/Organic/Total 占比，含 Top of Search、SOV Keyword Tag、Shelf View 等）、"
    "Bid Explorer（出价探索：按目标 Top N 排名/曝光份额推荐关键词与商品出价）、"
    "Budget Scheduler（预算排程：按日/周/月自动调整广告活动预算）、"
    "Dayparting Scheduler（分时投放：按小时/星期调整出价或预算，含 Auto Tune）、"
    "Calendar Center（日历中心：定时启停广告活动/广告组/ASIN 等任务）、"
    "Download Center（下载中心：异步导出文件）、"
    "Product Line（产品线：商品分组与汇总口径）、"
    "Message（站内消息/通知）。"
)

DOMAIN_CONTEXT_EN = (
    "Context: Pacvue is a retail-media advertising SaaS platform used by brands "
    "and agencies to manage ads on Amazon, Walmart (Walmart Connect), Instacart, "
    "Target, Kroger, DoorDash, Criteo, Citrus and other retailers: campaign and "
    "bid/budget automation, dayparting, reporting (My Report, Company Board, "
    "Cross Retailer Report) and Share of Voice (SOV) digital-shelf tracking. Use "
    "standard advertising terminology (campaign, ad group, keyword, targeting, "
    "placement, bid, budget, ACOS, ROAS, CTR, CVR, ASIN, SKU, SOV, NTB) and keep "
    "Pacvue module names, retailer names and metric abbreviations exactly as "
    "written in the ticket."
)

# ---------------------------------------------------------------------------
# Terminology
# ---------------------------------------------------------------------------

# Never translate (keep exactly as written in the source).
KEEP_ENGLISH = [
    "零售商/渠道/平台名：Amazon、Amazon DSP、AMC、Walmart、Walmart Connect、WMC、Instacart、Target、Kroger、"
    "DoorDash、Sam's Club、Bol、Costco、CVS、Mediamarkt、Criteo、Citrus、Amazon Now、Sponsored TV",
    "客户/品牌/公司/人名：如 Unilever、Dove Men+Care、Wellpet、Colgate、Publicis、P&G、Acushnet（一律保留原文，不得音译或改写）",
    "Pacvue 及其模块/功能名：Pacvue、PV、My Report、Company Board、Global Report、Cross Retailer Report、Custom Dashboard、"
    "SOV、SOV Keyword Tag、Shelf View、Bid Explorer、Budget Scheduler、Dayparting Scheduler、Auto Tune、Calendar Center、"
    "Download Center、Product Line、Product Center、Campaign Tag、ASIN Tag/SubTag、Share Tag、Rule、Executive Hub、Copilot、Message",
    "广告类型与缩写：SP（Sponsored Products）、SB（Sponsored Brands）、SBV、SD（Sponsored Display）、DSP、Top of Search（TOS）、Display",
    "指标与缩写：ACOS、ROAS、TACOS、CPC、CPM、CTR、CVR、Impressions 可译为曝光、Spend 译为花费、"
    "DPV/DPVR、ATC（Add to Cart）、NTB（New-to-Brand）、SOV、SQP、SRP、PoP、YoY、MoM、Top N、ActBid",
    "标识与数据：ASIN、SKU、UPC、Item ID、Jira 工单号（如 PIN-1234、CP-567）、工单/Case 编号、URL、邮箱、"
    "数字、货币、日期、时区（如 PST/EST/UTC）、版本号一律原样保留",
    "引号中的 UI 文案（按钮、菜单、列名、页签名）保留英文原文，必要时在其后括注中文",
]

# Fixed Chinese renderings for general advertising vocabulary.
FIXED_TERMS = [
    ("campaign", "广告活动"),
    ("ad group", "广告组"),
    ("keyword", "关键词（不要用「关键字」）"),
    ("search term", "搜索词"),
    ("targeting / target（投放对象含义时）", "投放/定向；作为零售商 Target 时保留英文"),
    ("placement", "广告位"),
    ("bid", "出价"),
    ("budget", "预算"),
    ("spend", "花费"),
    ("impressions", "曝光"),
    ("clicks", "点击"),
    ("conversion", "转化"),
    ("add to cart (rate) / ATC", "加购（率），首次可括注 ATC"),
    ("detail page view (rate) / DPV / DPVR", "详情页浏览（率），首次可括注 DPV/DPVR"),
    ("new-to-brand / NTB", "新客（NTB）"),
    ("attribution", "归因"),
    ("match type（exact/phrase/broad）", "匹配类型（精准/词组/广泛）"),
    ("negative keyword", "否定关键词"),
    ("paused / enabled / archived", "已暂停 / 已启用 / 已归档"),
    ("dayparting", "分时投放（模块名 Dayparting Scheduler 保留英文）"),
    ("retailer", "零售商"),
    ("marketplace", "站点"),
    ("advertiser / account / profile", "广告主 / 账号 / Profile"),
    ("brand", "品牌"),
    ("category", "品类"),
    ("organic / paid / total", "自然 / 付费 / 总计"),
    ("share of voice", "SOV（保留缩写）"),
    ("report", "报表"),
    ("metric / dimension / filter / column", "指标 / 维度 / 筛选 / 列"),
    ("export / download", "导出 / 下载"),
    ("scheduled report", "定时报表"),
    ("dashboard / widget", "看板 / 组件"),
    ("tooltip", "提示信息"),
    ("item（Walmart 语境）/ product / listing / PDP", "商品 / 商品 / 商品页（listing）/ 商品详情页"),
    ("rank / top of search", "排名 / Top of Search"),
    ("CSM / AM / MBR / QBR", "保留缩写，可首次括注：客户成功经理 / 客户经理 / 月度业务回顾 / 季度业务回顾"),
    ("retention / churn / upsell", "留存 / 流失 / 增购"),
]

# Lenses that usually explain root cause / impact in retail-media tickets.
ANALYSIS_LENSES_ZH = (
    "广告域分析视角（仅作为归因与影响判断的候选维度，仍须以原文为依据、无依据则不写）："
    "①数据口径：归因窗口（如 7/14 天）、Paid/Organic/Total、时区与货币、数据延迟/回补、聚合层级（账号/广告活动/广告组/关键词/ASIN）；"
    "②零售商能力边界：零售商 Ads API 是否提供该字段/报表类型、各零售商/广告类型（SP/SB/SD/DSP）支持范围不一致；"
    "③自动化规则：Budget Scheduler / Dayparting / Rule 的触发条件、执行时机、对已暂停或超预算对象的处理；"
    "④报表体验：筛选范围与导出结果不一致、列/指标缺失、定时发送、跨零售商口径对齐；"
    "⑤客户价值：影响哪些客户（品牌/代理商）、频率与规模、与留存/续约/竞品对比的关系。"
)


def keep_english_block() -> str:
    return "以下内容保留英文原文、不翻译：" + "；".join(KEEP_ENGLISH) + "。"


def fixed_terms_block() -> str:
    return "通用广告术语固定译法：" + "；".join(f"{en} → {zh}" for en, zh in FIXED_TERMS) + "。"


def translate_system_prompt(target_lang: str) -> str:
    """System prompt for the translation endpoint."""
    return (
        f"你是 Pacvue（零售媒体广告 SaaS）的资深产品经理兼专业译者，请把用户提供的文本完整翻译成{target_lang}。"
        + DOMAIN_CONTEXT_ZH
        + "翻译要求："
        "(1) 完整逐段翻译，不概括、不省略、不添加解释或备注；"
        "(2) 保持原文结构：段落、换行、列表符号、【标题】、Markdown 标记、编号原样保留；"
        "(3) 用产品需求文档的专业口吻，语句通顺自然，不逐字硬译；"
        "(4) 术语一致：同一术语全文用同一译法。"
        + keep_english_block()
        + fixed_terms_block()
        + "只输出译文本身。"
    )


def analysis_domain_block() -> str:
    """Prefix for the PIN analysis system prompt."""
    return (
        DOMAIN_CONTEXT_ZH
        + ANALYSIS_LENSES_ZH
        + "术语规范：" + keep_english_block() + fixed_terms_block()
    )
