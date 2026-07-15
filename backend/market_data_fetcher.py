"""
市场数据获取层 — 零依赖纯 urllib 实现
======================================
数据源分级（按你给的清单）：
  1 级：东财逆向 HTTP（实时估值 / ETF 行情 / 历史净值 / 重仓）
  2 级：选股宝 Flash / TerminalFeed（新闻快讯）
  3 级：Mediastack、Finnhub、AKShare（备用兜底）

所有函数均返回统一 Dict 格式，含 error 字段标记失败
"""

import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Dict, List, Optional

# ── 通用工具 ──────────────────────────────────────────────────────────────

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://fund.eastmoney.com/",
}


def _http_get(url: str, timeout: int = 8) -> Optional[str]:
    """GET 请求 + 通用异常处理"""
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # 自动编码检测
            encoding = resp.headers.get_content_charset() or "utf-8"
            return raw.decode(encoding, errors="replace")
    except urllib.error.HTTPError as e:
        return json.dumps({"error": f"HTTP {e.code}", "detail": str(e)})
    except urllib.error.URLError as e:
        return json.dumps({"error": "连接失败", "detail": str(e.reason)})
    except Exception as e:
        return json.dumps({"error": "请求异常", "detail": str(e)})


def _clean_json(text: str) -> Optional[Dict]:
    """尝试解析 JSON，失败返回 None"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# 一、基金数据接口
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_fund_realtime(code: str) -> Dict:
    """
    单只场外基金实时估值（fundgz 极速 JS 接口）

    返回:
    {
        "code": "000001",
        "name": "基金名称",
        "dwjz": 昨日净值,
        "gsz": 实时估算净值,
        "gszzl": 估算涨跌幅%,
        "gztime": 估值时间,
        "error": None
    }
    """
    url = f"http://fundgz.1234567.com.cn/js/{code}.js"
    text = _http_get(url)

    if not text:
        return {"error": "无响应", "code": code}

    # 返回格式: jsonpgz({...});
    try:
        if text.startswith("jsonpgz("):
            text = text[8:-2]  # 去掉 jsonpgz( 和 );
        data = json.loads(text)
        return {
            "code": data.get("fundcode", code),
            "name": data.get("name", ""),
            "dwjz": data.get("dwjz"),
            "gsz": data.get("gsz"),
            "gszzl": data.get("gszzl"),
            "gztime": data.get("gztime", ""),
            "error": None,
        }
    except (json.JSONDecodeError, IndexError) as e:
        return {"error": f"解析失败: {e}", "code": code}


def fetch_fund_detail_api(code: str) -> Dict:
    """
    基金详情 / 申赎状态（东财 F10DataApi）
    """
    url = (
        f"http://fund.eastmoney.com/f10/F10DataApi.aspx?"
        f"type=gsz&code={code}"
    )
    text = _http_get(url)
    if not text:
        return {"error": "无响应", "code": code}
    return {
        "code": code,
        "raw": text[:500],  # 截断，主要是 HTML 表格
        "error": None,
    }


def fetch_fund_history(code: str, page: int = 1, per: int = 200) -> Dict:
    """
    基金历史净值（回测 / 定投演算用）

    返回:
    {
        "code": "000001",
        "records": [{ "date":"2026-07-10", "dwjz":"2.1234", "ljjz":"3.4567" }, ...],
        "total": 200,
        "error": None
    }
    """
    url = (
        f"http://fund.eastmoney.com/f10/F10DataApi.aspx?"
        f"type=lsjz&code={code}&page={page}&per={per}"
    )
    text = _http_get(url)
    if not text:
        return {"error": "无响应", "code": code}

    # 返回 HTML + JS 混合，尝试解析 JSONP 中的 records
    try:
        # 提取 records 数组
        import re
        records = _parse_f10_history(text)
        return {
            "code": code,
            "records": records[:per],
            "total": len(records),
            "page": page,
            "error": None,
        }
    except Exception as e:
        return {"error": f"解析历史净值失败: {e}", "code": code}


def _parse_f10_history(text: str) -> List[Dict]:
    """从 F10DataApi 的 HTML/JS 混合输出中提取历史净值记录"""
    import re

    records = []

    # 尝试提取 JSON 结构: var apidata={ content:"...", record:5, pages:1, curpage:1 }
    # content 里是 <tr> 表格行
    content_match = re.search(r'content:"(.*?)"', text, re.DOTALL)
    if not content_match:
        return records

    content = content_match.group(1)
    # 转义还原
    content = content.replace(r"\r\n", "\n").replace(r"\t", "")

    # 解析 <tr><td>date</td><td>dwjz</td><td>ljjz</td>...
    rows = re.findall(
        r"<tr>(.*?)</tr>", content, re.DOTALL
    )
    for row in rows:
        cells = re.findall(r"<td>(.*?)</td>", row, re.DOTALL)
        if len(cells) >= 4:
            records.append({
                "date": cells[0].strip(),
                "dwjz": cells[1].strip(),
                "ljjz": cells[2].strip(),
            })

    return records


def fetch_etf_trend(etf_code: str, market: int = 1) -> Dict:
    """
    场内 ETF 实时分时行情

    Args:
        etf_code: ETF 代码，如 159915（创业板 ETF）
        market: 市场代码 1=深交所 0=上交所

    返回:
    {
        "code": "159915",
        "name": "...",
        "price": 现价,
        "high": 最高,
        "low": 最低,
        "volume": 成交量,
        "change": 涨跌额,
        "changePct": 涨跌幅%,
        "trend": [ { "time":"09:31", "price":1.23 }, ... ],
        "error": None
    }
    """
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/trends2/get?"
        f"secid={market}.{etf_code}&fields1=f1,f2,f3,f4,f5&"
        f"fields2=f51,f52,f53,f54,f55&ut=fa5fd1943c7b386f172d6893dbfd32bb"
    )
    text = _http_get(url)
    data = _clean_json(text)
    if not data or data.get("data") is None:
        return {"error": "ETF 行情获取失败", "code": etf_code}

    d = data["data"]
    trends = d.get("trends", [])
    trend_points = []
    for t in trends[:242]:  # 最多 242 个分时点 (4*60+2)
        parts = t.split(",")
        if len(parts) >= 2:
            trend_points.append({
                "time": parts[0],
                "price": float(parts[1]) if parts[1] else 0,
            })

    return {
        "code": d.get("code", etf_code),
        "name": d.get("name", ""),
        "price": d.get("prePrice", 0),
        "high": d.get("high", 0),
        "low": d.get("low", 0),
        "volume": d.get("volume", 0),
        "amount": d.get("amount", 0),
        "change": d.get("rise", 0),
        "changePct": d.get("risePct", 0),
        "trend": trend_points,
        "error": None,
    }


def fetch_fund_holdings(fund_code: str) -> Dict:
    """
    基金前十大重仓股 / 行业

    返回:
    {
        "code": "110011",
        "holdings": [
            { "stockName":"贵州茅台", "ratio":9.85, "industry":"食品饮料" },
            ...
        ],
        "error": None
    }
    """
    url = (
        "https://datacenter-web.eastmoney.com/api/data/v1/get?"
        f"reportName=RPT_FUND_HOLD_STOCK&filter=(FUND_CODE='{fund_code}')&"
        "pageSize=10&pageNumber=1&sortTypes=-1&sortColumns=HOLD_MARKET_CAP&"
        "columns=STOCK_CODE,STOCK_NAME,HOLD_MARKET_CAP,HOLD_MARKET_CAP_RATIO&source=WEB"
    )
    text = _http_get(url)
    data = _clean_json(text)
    if not data or data.get("result") is None or data["result"].get("data") is None:
        return {"error": "重仓数据获取失败", "code": fund_code}

    stocks = []
    for item in data["result"]["data"]:
        stocks.append({
            "stockName": item.get("STOCK_NAME", ""),
            "stockCode": item.get("STOCK_CODE", ""),
            "ratio": item.get("HOLD_MARKET_CAP_RATIO", 0),
        })

    return {
        "code": fund_code,
        "holdings": stocks,
        "error": None,
    }


def fetch_fund_code_list() -> Dict:
    """
    全基金基础列表（初始化模拟持仓池）

    返回:
    {
        "total": 10000,
        "funds": [ { "code":"000001", "name":"...", "type":"..." }, ... ],
        "error": None
    }
    """
    url = "http://fund.eastmoney.com/js/fundcode_search.js"
    text = _http_get(url)

    if not text:
        return {"error": "基金列表获取失败"}

    # 格式: var r = [[code, name, type_id, type_name, pinyin], ...]
    try:
        import re
        match = re.search(r"var r = (\[.*?\]);", text, re.DOTALL)
        if not match:
            return {"error": "解析列表失败"}

        raw = json.loads(match.group(1))
        funds = [
            {"code": item[0], "name": item[2], "type": item[3]}
            for item in raw
        ]
        return {
            "total": len(funds),
            "funds": funds[:5000],  # 截断避免过大
            "error": None,
        }
    except Exception as e:
        return {"error": f"解析基金列表失败: {e}"}


# ═══════════════════════════════════════════════════════════════════════════════
# 二、新闻 / 快讯接口
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_eastmoney_news() -> Dict:
    """
    东财全市场快讯（A股/基金实时利好）

    返回:
    {
        "news": [
            {
                "title": "...",
                "time": "2026-07-13 09:35",
                "summary": "...",
                "tag": 行业标签,
                "url": "..."
            },
            ...
        ],
        "error": None
    }
    """
    url = (
        "https://push.eastmoney.com/api/qt/stock/notice/get?"
        "cb=jsonp_notice&sact=notice&reportid=1&pageindex=1&pagesize=20"
    )
    text = _http_get(url)

    if not text:
        return {"error": "东财快讯获取失败"}

    try:
        if text.startswith("jsonp_notice("):
            text = text[len("jsonp_notice("):-1]
        data = json.loads(text)

        items = []
        for item in data.get("data", {}).get("list", []):
            items.append({
                "title": item.get("title", ""),
                "time": item.get("showDate", ""),
                "summary": item.get("content", item.get("summary", "")),
                "tag": item.get("column", ""),
            })

        return {"news": items, "error": None}
    except Exception as e:
        return {"error": f"解析东财快讯失败: {e}"}


def fetch_xuangubao_flash(limit: int = 60) -> Dict:
    """
    选股宝 7×24 极速快讯（突发消息延迟最低）

    返回:
    {
        "messages": [
            {
                "content": "...",
                "time_ms": 时间戳毫秒,
                "type": "macro|a_stock|commodity|us_stock",
                "urgent": bool
            },
            ...
        ],
        "error": None
    }
    """
    url = f"https://flash-api.xuangubao.cn/api/flash?limit={limit}"
    text = _http_get(url)

    if not text:
        return {"error": "选股宝快讯获取失败"}

    try:
        data = json.loads(text)
        messages = []
        for item in data.get("data", {}).get("items", []):
            messages.append({
                "content": item.get("content", ""),
                "time_ms": item.get("created_at", 0),
                "type": _map_xuangubao_type(item.get("type", "")),
                "urgent": item.get("important", False),
            })
        return {"messages": messages, "error": None}
    except Exception as e:
        return {"error": f"解析选股宝快讯失败: {e}"}


def _map_xuangubao_type(t: str) -> str:
    """映射选股宝消息类型"""
    mapping = {
        "1": "macro",     # 宏观
        "2": "a_stock",   # A股
        "3": "commodity", # 商品
        "4": "us_stock",  # 美股
    }
    return mapping.get(t, "other")


def fetch_terminalfeed_briefing() -> Dict:
    """
    TerminalFeed 全球简报（零 Key 国际宏观快讯）

    返回:
    {
        "briefing": "...",
        "source": "TerminalFeed",
        "error": None
    }
    """
    url = "https://terminalfeed.io/api/briefing"
    text = _http_get(url, timeout=5)

    if not text:
        return {"error": "TerminalFeed 获取失败"}

    try:
        data = json.loads(text)
        return {
            "briefing": data.get("briefing", data.get("content", text[:500])),
            "source": "TerminalFeed",
            "error": None,
        }
    except json.JSONDecodeError:
        # 可能是纯文本
        return {
            "briefing": text[:500],
            "source": "TerminalFeed",
            "error": None,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 三、批量获取 — 根据持仓基金列表一次性拉取全部实时数据
# ═══════════════════════════════════════════════════════════════════════════════

def batch_fetch_funds_realtime(fund_codes: List[str]) -> List[Dict]:
    """
    批量拉取多只基金实时估值（自动限流 0.5s 间隔）

    Args:
        fund_codes: 基金代码列表 ["110011", "005827", ...]

    Returns:
        [ { code, name, dwjz, gsz, gszzl, gztime }, ... ]
    """
    results = []
    for code in fund_codes:
        result = fetch_fund_realtime(code)
        results.append(result)
        time.sleep(0.5)  # 限流：单 IP 1s≤2 次
    return results


def batch_fetch_holdings(fund_codes: List[str]) -> Dict[str, List[Dict]]:
    """
    批量拉取多只基金重仓股（构建关键词库用）

    Returns:
        { "110011": [{ stockName, ratio }, ...], ... }
    """
    holdings_map = {}
    for code in fund_codes:
        result = fetch_fund_holdings(code)
        if result["holdings"]:
            holdings_map[code] = result["holdings"]
        time.sleep(0.3)
    return holdings_map


# ═══════════════════════════════════════════════════════════════════════════════
# 四、聚合新闻源（合并多源去重）
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_all_news() -> Dict:
    """
    聚合所有新闻源，去重后返回统一列表

    返回:
    {
        "items": [{ "title", "content", "source", "time", "tags", "urgent" }, ...],
        "sources": ["eastmoney", "xuangubao", "terminalfeed"],
        "error": None
    }
    """
    items = []

    # 1. 东财快讯
    em = fetch_eastmoney_news()
    if not em.get("error"):
        for n in em.get("news", []):
            items.append({
                "title": n["title"],
                "content": n["summary"],
                "source": "eastmoney",
                "time": n["time"],
                "tags": [n["tag"]] if n["tag"] else [],
                "urgent": False,
            })

    # 2. 选股宝 Flash（延迟最低）
    xb = fetch_xuangubao_flash()
    if not xb.get("error"):
        for m in xb.get("messages", []):
            items.append({
                "title": "",
                "content": m["content"],
                "source": "xuangubao",
                "time": datetime.fromtimestamp(m["time_ms"]).isoformat() if m["time_ms"] else "",
                "tags": [m["type"]],
                "urgent": m["urgent"],
            })

    # 3. TerminalFeed 全球简报
    tf = fetch_terminalfeed_briefing()
    if not tf.get("error") and tf.get("briefing"):
        items.append({
            "title": "全球市场简报",
            "content": tf["briefing"],
            "source": "terminalfeed",
            "time": datetime.now().isoformat(),
            "tags": ["global", "macro"],
            "urgent": False,
        })

    return {
        "items": items,
        "sources": ["eastmoney", "xuangubao", "terminalfeed"],
        "total": len(items),
        "error": None,
    }
