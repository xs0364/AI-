"""
新闻舆情引擎 — 持仓关键词匹配 + 利好利空分类
=============================================
流程：
  1. 从数据库读取当前持仓基金列表
  2. 拉取每只基金的重仓股 → 构建"持仓关键词库"
  3. 抓取新闻源 → 正文/标题匹配关键词 → 标记【持仓利好/利空】
  4. 输出结构化舆情报告给前端

核心原则：只在 A 股交易时段（9:30-15:00）内判定"可操作"，
          非交易时段给出"隔夜/盘前/盘后"操作策略标签
"""

import re
import json
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from database import get_connection
from market_data_fetcher import (
    fetch_fund_holdings,
    fetch_all_news,
    batch_fetch_holdings,
)
from trading_time_engine import (
    is_trading_day,
    is_before_1500,
    is_etf_trading_time,
    NewsTimeWindow,
)


# ── 中文停用词（过滤干扰匹配）──────────────────────────────────────────────
_STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这", "他", "她",
    "它", "们", "那", "些", "什么", "吗", "吧", "啊", "呢", "哦",
    "进行", "可以", "应该", "可能", "已经", "通过", "成为",  # 新闻虚词
    "公司", "中国", "市场", "亿元", "美元", "全球",  # 过于宽泛
}

# ── 行业板块分级定义 ─────────────────────────────────────────────
# 一级板块 → 二级细分（用于关键词匹配 + 前端展示）
SECTOR_DEFINITIONS = {
    "医药": ["创新药", "中药", "医疗器械", "CXO", "生物医药", "医美", "医疗服务", "医药商业"],
    "消费": ["白酒", "食品饮料", "家电", "零售", "旅游", "免税", "服装", "美妆"],
    "科技": ["半导体", "AI", "软件", "算力", "通信", "信创", "消费电子", "芯片", "数字经济"],
    "新能源": ["光伏", "锂电", "储能", "风电", "新能源车", "氢能", "充电桩", "钠离子"],
    "金融": ["银行", "证券", "保险", "券商", "信托", "金融科技"],
    "周期": ["有色", "煤炭", "钢铁", "化工", "建材", "石油", "天然气", "稀土"],
    "制造": ["机器人", "高端制造", "军工", "机械", "工业母机", "航空航天", "船舶"],
    "地产": ["房地产", "物业", "建筑", "建材", "基建"],
    "公用事业": ["电力", "燃气", "水务", "环保", "交通"],
    "TMT": ["传媒", "互联网", "游戏", "影视", "广告", "元宇宙"],
    "农业": ["种植", "养殖", "农产品", "种业", "畜牧", "渔业"],
    "港股/海外": ["恒生科技", "美股科技", "中概股", "港股", "纳斯达克"],
    "红利/策略": ["高股息", "央企红利", "红利低波", "价值"],
    "宽基指数": ["沪深300", "中证500", "中证1000", "创业板", "科创50", "上证50"],
}

# 所有二级板块扁平化列表（用于从基金名称匹配）
SECTOR_FLAT = []
for parent, children in SECTOR_DEFINITIONS.items():
    for child in children:
        if child not in SECTOR_FLAT:
            SECTOR_FLAT.append(child)
    # 一级板块关键词也加入
    if parent not in SECTOR_FLAT:
        SECTOR_FLAT.append(parent)

# 一级板块列表（给前端用）
SECTOR_PARENTS = list(SECTOR_DEFINITIONS.keys())

# 利好关键词（权重可累加）
_POSITIVE_KEYWORDS = [
    "大涨", "涨停", "暴涨", "飙升", "利好", "政策", "降息", "降准",
    "放宽", "刺激", "扶持", "补贴", "资金流入", "北上", "主力",
    "放量", "突破", "新高", "业绩", "预增", "中标", "回购",
    "增持", "分红", "派息", "重组", "注入", "资产",
    "利好出尽",  # 中性偏利好
]
# 利空关键词
_NEGATIVE_KEYWORDS = [
    "大跌", "跌停", "暴跌", "利空", "加息", "缩表", "收紧",
    "资金流出", "北上流出", "缩量", "破位", "新低",
    "减持", "立案", "退市", "ST", "亏损", "暴雷", "违约",
    "倒闭", "裁员", "下调", "处罚", "调查", "集采",
    "辞职", "战争", "制裁", "封锁", "疫情",
]


def build_holdings_keywords() -> Dict[str, List[Dict]]:
    """
    从数据库读取持仓基金，拉取重仓股，构建关键词映射

    Returns:
        {
            "by_fund": {
                "110011": [{ "word":"贵州茅台", "ratio":9.85, "type":"stock" }, ...],
                "005827": [{ "word":"医疗服务", "ratio":15.2, "type":"industry" }, ...]
            },
            "all_keywords": ["贵州茅台", "医疗服务", "新能源", ...],
            "stock_names": ["贵州茅台", "药明康德", ...]
        }
    """
    conn = get_connection()
    rows = conn.execute("SELECT code, name FROM funds").fetchall()
    conn.close()

    fund_codes = [row["code"] for row in rows]
    fund_names = {row["code"]: row["name"] for row in rows}

    # 2. 拉取每只基金的重仓股
    holdings_map = batch_fetch_holdings(fund_codes)

    # 3. 构建关键词
    result = {"by_fund": {}, "all_keywords": set(), "stock_names": set()}

    for code, stocks in holdings_map.items():
        fund_result = []
        for s in stocks:
            word = s.get("stockName", "")
            if word and len(word) >= 2 and word not in _STOP_WORDS:
                ratio = s.get("ratio", 0)
                fund_result.append({
                    "word": word,
                    "ratio": ratio,
                    "type": "stock",
                })
                result["all_keywords"].add(word)
                result["stock_names"].add(word)

        # 从基金名称提取赛道关键词（完整板块列表）
        fname = fund_names.get(code, "")
        for kw in SECTOR_FLAT:
            if kw in fname and kw not in _STOP_WORDS and len(kw) >= 2:
                fund_result.append({"word": kw, "ratio": 0, "type": "sector"})
                result["all_keywords"].add(kw)

        result["by_fund"][code] = fund_result

    return {
        "by_fund": result["by_fund"],
        "all_keywords": sorted(result["all_keywords"]),
        "stock_names": sorted(result["stock_names"]),
    }


def classify_sentiment(text: str) -> Tuple[str, float]:
    """
    判断新闻情感倾向

    Returns:
        (sentiment, confidence)
        sentiment: "positive" | "negative" | "neutral"
        confidence: 0~1
    """
    text_lower = text.lower()
    pos_score = 0
    neg_score = 0

    for kw in _POSITIVE_KEYWORDS:
        if kw in text:
            pos_score += 1
    for kw in _NEGATIVE_KEYWORDS:
        if kw in text:
            neg_score += 1

    # 否定词反转
    negation_patterns = [
        r"(不|没有|未|否)(会|能|是)?\s?.{0,8}(大涨|涨停|利好|突破|新高)",
        r"(难|无法|难以).{0,4}(利好|突破|新高)",
    ]
    for pat in negation_patterns:
        if re.search(pat, text):
            pos_score -= 1

    total = pos_score + neg_score
    if total == 0:
        return ("neutral", 0.5)

    if pos_score > neg_score:
        return ("positive", round(pos_score / (pos_score + neg_score), 2))
    elif neg_score > pos_score:
        return ("negative", round(neg_score / (total), 2))
    else:
        return ("neutral", 0.5)


def match_news_to_portfolio(news_items: List[Dict]) -> List[Dict]:
    """
    将新闻列表逐一匹配持仓关键词

    Args:
        news_items: [{ "title", "content", "source", "time", "tags" }, ...]

    Returns:
        [
            {
                "matched": True/False,
                "fundCodes": ["110011", ...],
                "matchedKeywords": ["贵州茅台", ...],
                "sentiment": "positive|negative|neutral",
                "sentimentScore": 0~1,
                "actionWindow": operation window label,
                ...
            },
            ...
        ]
    """
    keywords_data = build_holdings_keywords()
    by_fund = keywords_data["by_fund"]
    stock_names = keywords_data["stock_names"]

    # 构建关键词→基金映射（倒排索引）
    word_to_funds: Dict[str, List[str]] = {}
    for code, words in by_fund.items():
        for w in words:
            word = w["word"]
            if word not in word_to_funds:
                word_to_funds[word] = []
            word_to_funds[word].append(code)

    results = []
    for item in news_items:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        sentiment, score = classify_sentiment(text)

        # 匹配关键词
        matched_keywords = []
        matched_funds = set()

        for word in stock_names:
            if word in text:
                matched_keywords.append(word)
                # 找到持有这只股票的基金
                fund_codes = word_to_funds.get(word, [])
                for fc in fund_codes:
                    matched_funds.add(fc)

        # 赛道关键词匹配
        if not matched_keywords:
            # 宽泛匹配赛道
            for code, words in by_fund.items():
                for w in words:
                    if w["type"] == "sector" and w["word"] in text and len(text) > 10:
                        matched_keywords.append(w["word"])
                        matched_funds.add(code)

        # 匹配新闻时间 → 操作窗口
        news_dt = None
        time_str = item.get("time", "")
        if time_str:
            try:
                news_dt = datetime.fromisoformat(time_str)
            except (ValueError, TypeError):
                try:
                    news_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
                except (ValueError, TypeError):
                    pass

        window_info = {}
        if matched_funds and news_dt:
            window_info = NewsTimeWindow.classify_news_time(news_dt, text)

        result = {
            "matched": len(matched_funds) > 0,
            "matchedFunds": list(matched_funds),
            "matchedKeywords": matched_keywords[:5],
            "sentiment": sentiment,
            "sentimentScore": score,
            "actionWindow": window_info.get("actionWindow", ""),
            "actionLabel": window_info.get("actionLabel", ""),
            "actionDeadline": window_info.get("actionDeadline", ""),
            "riskNote": window_info.get("riskNote", ""),
        }
        # 合并原始新闻信息
        result.update(item)
        results.append(result)

    return results


def get_portfolio_news() -> Dict:
    """
    完整链路：抓新闻 → 匹配持仓 → 输出舆情报告

    返回:
    {
        "matchedNews": [ ... ],        # 与持仓相关的新闻
        "unmatchedNews": [ ... ],      # 不相关的新闻
        "matchedCount": 5,
        "totalCount": 60,
        "holdingsKeywords": { "110011": [...] },
        "updateTime": "2026-07-13T...",
    }
    """
    # 1. 抓取所有新闻
    all_news = fetch_all_news()
    if all_news.get("error"):
        return {"error": all_news["error"], "matchedNews": [], "unmatchedNews": []}

    items = all_news.get("items", [])

    # 2. 匹配
    matched_results = match_news_to_portfolio(items)

    matched = [r for r in matched_results if r.get("matched")]
    unmatched = [r for r in matched_results if not r.get("matched")]

    # 3. 关键词库
    keywords_data = build_holdings_keywords()

    return {
        "matchedNews": matched,
        "unmatchedNews": unmatched[:20],  # 截断
        "matchedCount": len(matched),
        "totalCount": len(items),
        "holdingsKeywords": keywords_data["by_fund"],
        "allKeywords": keywords_data["all_keywords"],
        "updateTime": datetime.now().isoformat(),
    }
