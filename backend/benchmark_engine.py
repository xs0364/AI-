"""
Benchmark Engine — 基准指数数据引擎
====================================
数据源：东方财富指数 K 线 API
支持指数：
  000300 — 沪深300
  000905 — 中证500
  000922 — 中证红利
  000016 — 上证50

用法：
  history = get_benchmark("000300", days=365)
  history 含原始收盘价和归一化净值（base=100）
"""
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger
from database import get_connection

# ── 指数代码配置 ──────────────────────────────────────────────────

BENCHMARK_INDICES = {
    "000300": {"name": "沪深300", "market": 1},
    "000905": {"name": "中证500", "market": 1},
    "000922": {"name": "中证红利", "market": 1},
    "000016": {"name": "上证50", "market": 1},
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _http_get(url: str, timeout: int = 10) -> Optional[str]:
    """GET 请求"""
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _USER_AGENT,
            "Referer": "https://quote.eastmoney.com/",
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("[Benchmark] HTTP 请求失败 {}: {}", url, e)
        return None


def _fetch_eastmoney_kline(code: str, market: int, days: int = 500) -> List[dict]:
    """
    从东方财富 K 线接口获取指数历史数据

    secid 格式: market.code
    上海(market=1): 1.000300
    深圳(market=0): 0.399001
    """
    secid = f"{market}.{code}"
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6&"
        f"fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&"
        f"klt=101&fqt=1&end=20500101&lmt={days}"
    )
    text = _http_get(url)
    if not text:
        return []

    try:
        data = json.loads(text)
        klines = data.get("data", {}).get("klines", [])
    except (json.JSONDecodeError, AttributeError, TypeError):
        return []

    results = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            results.append({
                "date": parts[0],
                "open": float(parts[1]),
                "close": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
            })
        except (ValueError, IndexError):
            continue

    return results


def _store_benchmark_data(code: str, records: List[dict]):
    """写入 daily_benchmark 表（UPSERT）"""
    conn = get_connection()
    inserted = 0
    for r in records:
        try:
            conn.execute("""
                INSERT INTO daily_benchmark (index_code, date, close)
                VALUES (?, ?, ?)
                ON CONFLICT(index_code, date) DO UPDATE SET
                    close = excluded.close
            """, (code, r["date"], r["close"]))
            inserted += 1
        except Exception as e:
            logger.warning("[Benchmark] 写入失败 {} {}: {}", code, r.get("date"), e)
    conn.commit()
    conn.close()
    logger.info("[Benchmark] {} 已存入 {} 条数据", code, inserted)


def ensure_benchmark_data(code: str, days: int = 365) -> bool:
    """
    确保指数数据已缓存到 DB。
    如果 DB 中最新的数据超过 3 天旧（非交易日），则重新拉取。
    """
    market = BENCHMARK_INDICES.get(code, {}).get("market")
    if market is None:
        logger.warning("[Benchmark] 不支持的指数代码: {}", code)
        return False

    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(date) as last_date FROM daily_benchmark WHERE index_code = ?",
        (code,),
    ).fetchone()
    conn.close()

    now = datetime.now()
    need_fetch = True

    if row and row["last_date"]:
        try:
            last = datetime.strptime(row["last_date"], "%Y-%m-%d")
            # 如果数据不足 days 天，或最后日期超过 5 天前（考虑节假日），重新拉取
            if (now - last).days <= 5:
                # 检查数量是否足够
                conn = get_connection()
                count = conn.execute(
                    "SELECT COUNT(*) as cnt FROM daily_benchmark WHERE index_code = ?",
                    (code,),
                ).fetchone()["cnt"]
                conn.close()
                if count >= days * 0.8:
                    need_fetch = False
        except ValueError:
            pass

    if need_fetch:
        records = _fetch_eastmoney_kline(code, market, max(days, 500))
        if records:
            _store_benchmark_data(code, records)
            return True
        return False

    return True


def get_benchmark_history(code: str, days: int = 365) -> dict:
    """
    获取基准指数历史数据（含归一化净值）

    返回:
    {
        "code": "000300",
        "name": "沪深300",
        "data": [
            {"date": "2026-01-01", "close": 3800.12, "nav": 100.0},
            {"date": "2026-01-02", "close": 3850.34, "nav": 101.32},
            ...
        ]
    }
    """
    # 先确保数据已拉取
    ensure_benchmark_data(code, days)

    conn = get_connection()
    rows = conn.execute("""
        SELECT date, close FROM daily_benchmark
        WHERE index_code = ?
        ORDER BY date DESC
        LIMIT ?
    """, (code, days)).fetchall()
    conn.close()

    data = [{"date": r["date"], "close": r["close"]} for r in rows]
    data.reverse()  # 按日期升序

    # 归一化：base = 100，以第一个数据点为基准
    base_nav = 100.0
    result_data = []
    if data:
        first_close = data[0]["close"]
        if first_close and first_close > 0:
            for d in data:
                result_data.append({
                    "date": d["date"],
                    "close": d["close"],
                    "nav": round(d["close"] / first_close * base_nav, 4),
                })

    return {
        "code": code,
        "name": BENCHMARK_INDICES.get(code, {}).get("name", code),
        "data": result_data,
        "total": len(result_data),
    }


def get_all_benchmarks(days: int = 365) -> list:
    """获取所有已配置指数的历史数据"""
    results = []
    for code in BENCHMARK_INDICES:
        try:
            results.append(get_benchmark_history(code, days))
        except Exception as e:
            logger.warning("[Benchmark] 获取 {} 失败: {}", code, e)
    return results


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    data = get_benchmark_history("000300", 30)
    print(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
