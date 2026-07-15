"""
Market Intelligence Agent
=========================
定位：全市场情报分析 Agent（LLM 驱动）
负责所有影响基金持仓的外部信息分析

当前能力：
  - 新闻语义理解（LLM）→ 情绪/影响/置信度/推理链
  - 持仓关键词快速预检（兜底）
  - 结果缓存（同篇新闻不重复调 LLM）
  - 统一 AgentSignal 格式输出

未来扩展（预留接口）：
  - 龙虎榜资金流向
  - 北向资金/ETF 资金流
  - 宏观指标（CPI/PMI/利率/汇率）
  - 社交媒体热度（雪球/微博）
  - 大宗商品/VIX/美元指数

设计原则：
  1. LLM 优先，关键词兜底
  2. 缓存降低 Token 消耗
  3. 不影响 15:00 前交易窗口（超时 10s 自动降级）
  4. 不直接调用其他 Agent（只输出数据供调度器分发）
"""
import json
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from loguru import logger

from database import get_connection
from agent_schema import AgentSignal, SignalType
from llm_service import chat_json, MODELS
from market_data_fetcher import fetch_all_news
from news_engine import build_holdings_keywords, classify_sentiment as keyword_classify
from trading_time_engine import NewsTimeWindow


# ══════════════════════════════════════════════════════════════════
# 缓存（同一新闻不重复分析）
# ══════════════════════════════════════════════════════════════════

class NewsCache:
    """新闻分析结果缓存 key=md5(title+content[:100])"""

    def __init__(self, ttl_minutes: int = 480):
        self._cache: Dict[str, Tuple[dict, datetime]] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    def get(self, title: str, content: str) -> Optional[dict]:
        key = hashlib.md5(f"{title}|{content[:100]}".encode()).hexdigest()
        entry = self._cache.get(key)
        if entry:
            val, ts = entry
            if datetime.now() - ts < self._ttl:
                return val
            del self._cache[key]
        return None

    def set(self, title: str, content: str, result: dict):
        key = hashlib.md5(f"{title}|{content[:100]}".encode()).hexdigest()
        self._cache[key] = (result, datetime.now())

    def clear(self):
        self._cache.clear()


_news_cache = NewsCache()

# 全局运行结果缓存（避免重复网络 + LLM 调用）
_run_cache: Optional[Tuple[List[dict], datetime]] = None
_RUN_CACHE_TTL = timedelta(minutes=10)


# ══════════════════════════════════════════════════════════════════
# 持仓上下文构建
# ══════════════════════════════════════════════════════════════════

def _build_holdings_context() -> str:
    """构建持仓基金+重仓股的文本描述（给 LLM 的上下文）"""
    conn = get_connection()
    rows = conn.execute("SELECT code, name, shares, current_price FROM funds").fetchall()
    conn.close()
    if not rows:
        return "当前无持仓"

    lines = [f"{r['code']} {r['name']} 持有{r['shares']}份 现价{r['current_price']}" for r in rows]
    try:
        kw = build_holdings_keywords()
        for code in kw.get("by_fund", {}):
            stocks = kw["by_fund"][code][:5]
            stock_str = "、".join(f"{s['word']}({s['ratio']}%)" for s in stocks if s['ratio'] > 0)
            if stock_str:
                lines.append(f"  → 重仓: {stock_str}")
    except Exception:
        pass
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════
# 核心分析函数
# ══════════════════════════════════════════════════════════════════

def analyze_news_item(title: str, content: str, source: str,
                      news_time: Optional[str] = None) -> dict:
    """
    分析单条新闻 → 返回统一结构
    策略：缓存→LLM→关键词兜底
    """
    cached = _news_cache.get(title, content)
    if cached:
        logger.info("MI cache hit '{}'", title[:30])
        return cached

    holdings_ctx = _build_holdings_context()
    llm_result = _llm_analyze(title, content, holdings_ctx)
    if llm_result:
        result = _parse_llm_result(llm_result, title, content, source, news_time)
    else:
        logger.info("MI LLM failed, fallback to keyword for '{}'", title[:30])
        result = _keyword_fallback(title, content, source, news_time)

    _news_cache.set(title, content, result)
    return result


def _llm_analyze(title: str, content: str, holdings_ctx: str) -> Optional[dict]:
    """调用 LLM 分析新闻"""
    system_prompt = """你是一个专业的量化交易新闻分析助手。

对每条新闻，你需要分析：

1. **情绪判断**：positive / negative / neutral
2. **影响评分** (impact_score 0-100)
3. **置信度** (confidence 0-100)
4. **受影响基金**：列出受影响的基金代码及原因

输出严格 JSON 格式：
{
    "sentiment": "positive|negative|neutral",
    "impact_score": 0-100,
    "confidence": 0-100,
    "affected_funds": [{"code": "基金代码", "reason": "..."}],
    "summary": "一句话结论",
    "reasoning": ["推理点1", "推理点2"]
}

注意：不确定时宁可 neutral + 低置信度，不要过度解读。"""

    return chat_json(
        messages=[{"role": "user", "content": f"【新闻标题】\n{title}\n\n【新闻内容】\n{content}\n\n【当前持仓】\n{holdings_ctx}\n\n请分析这条新闻。"}],
        model=MODELS["market_intelligence"],
        system_prompt=system_prompt,
        temperature=0.1,
        timeout=45,
    )


def _parse_llm_result(llm_result: dict, title: str, content: str,
                      source: str, news_time: Optional[str] = None) -> dict:
    sentiment = llm_result.get("sentiment", "neutral")
    impact_score = min(100, max(0, llm_result.get("impact_score", 50)))
    confidence = min(100, max(0, llm_result.get("confidence", 50)))
    affected = llm_result.get("affected_funds", [])
    summary = llm_result.get("summary", "")
    reasoning = llm_result.get("reasoning", [])

    signal = {"positive": "POSITIVE", "negative": "NEGATIVE"}.get(sentiment, "NEUTRAL")
    score = 50 + impact_score * 0.5 if signal == "POSITIVE" else (50 - impact_score * 0.5 if signal == "NEGATIVE" else 50)
    risk = impact_score * 0.8 if signal == "NEGATIVE" else (impact_score * 0.2 if signal == "POSITIVE" else impact_score * 0.4)

    fund_codes = []
    for a in (affected if isinstance(affected, list) else []):
        fund_codes.append(str(a.get("code", "")) if isinstance(a, dict) else str(a))

    return {"signal": signal, "score": round(score, 1), "confidence": round(confidence, 1),
            "reason": reasoning if reasoning else [summary], "risk": round(risk, 1),
            "affected_funds": fund_codes, "summary": summary, "source": source,
            "time": news_time or datetime.now().isoformat(), "method": "llm"}


def _keyword_fallback(title: str, content: str, source: str,
                      news_time: Optional[str] = None) -> dict:
    text = f"{title} {content}"
    sentiment, conf = keyword_classify(text)
    signal = sentiment.upper()
    score = 70.0 if signal == "POSITIVE" else (30.0 if signal == "NEGATIVE" else 50.0)
    risk = 15.0 if signal == "POSITIVE" else (60.0 if signal == "NEGATIVE" else 30.0)
    return {"signal": signal, "score": score, "confidence": round(conf * 100, 1),
            "reason": [f"关键词匹配: {sentiment}"], "risk": risk,
            "affected_funds": [], "summary": text[:80], "source": source,
            "time": news_time or datetime.now().isoformat(), "method": "keyword"}


def scan_all_news() -> List[dict]:
    """扫描所有新闻源 → 逐条分析 → 返回分析结果列表"""
    raw = fetch_all_news()
    items = raw.get("items", []) if not raw.get("error") else []

    results = []
    for item in items[:20]:
        try:
            r = analyze_news_item(title=item.get("title", ""), content=item.get("content", ""),
                                  source=item.get("source", "unknown"), news_time=item.get("time"))
            results.append(r)
        except Exception as e:
            logger.warning("MI analyze error: {}", e)
    return results


def run(fund_id: int = None, fund_code: str = None, fund_name: str = None) -> List[dict]:
    """Decision Orchestrator 调用的主入口（带全局缓存，10 分钟有效期）"""
    global _run_cache

    now = datetime.now()
    if _run_cache and (now - _run_cache[1]) < _RUN_CACHE_TTL:
        logger.info("MI run cache hit (age={:.0f}s)", (now - _run_cache[1]).total_seconds())
        results = _run_cache[0]
    else:
        results = scan_all_news()
        _run_cache = (results, now)

    if fund_code:
        filtered = [r for r in results if fund_code in r.get("affected_funds", [])]
        return filtered if filtered else results[:3]
    return results[:5]


if __name__ == "__main__":
    results = scan_all_news()
    print(json.dumps(results, ensure_ascii=False, indent=2))
