"""
模拟盘分析模块
===============
1. simulation_runs 记录 — 每次执行的输入快照 + 决策 + 结果
2. 收益归因 — 按 Agent 维度拆解 PnL
3. 绩效指标 — 基于每日净值的全套绩效计算
"""
from datetime import date, datetime
from typing import Dict, List, Optional

from loguru import logger

from database import get_connection

_RUN_VERSION = "1.0"


# ═══════════════════════════════════════════════════════════════════
# 1. 输入快照提取
# ═══════════════════════════════════════════════════════════════════

def extract_input_snapshot(decisions_by_code: Dict[str, dict]) -> dict:
    """
    从 Agent 决策字典中提取全局输入快照。

    取第一只基金的 trend/market Agent 的指标数据作为代表。
    所有基金共享同一全局情绪分；市场指标取代表性值。
    """
    snapshot = {"ma20": None, "rsi": None, "atr": None, "news_score": None}

    for code, decision in decisions_by_code.items():
        contributions = decision.get("agents_contributions", [])
        for c in contributions:
            extra = c.get("extra") or {}
            indicators = extra.get("indicators") or {}

            if c.get("agent") == "trend":
                rsi_data = indicators.get("rsi") or {}
                snapshot["rsi"] = rsi_data.get("value")

                atr_data = indicators.get("atr") or {}
                snapshot["atr"] = atr_data.get("percent")

                ema_data = indicators.get("ema") or {}
                snapshot["ma20"] = ema_data.get("ema20")

            if c.get("agent") == "market":
                snapshot["news_score"] = c.get("score")

        # 一只基金足矣
        break

    return snapshot


# ═══════════════════════════════════════════════════════════════════
# 2. simulation_runs 写入
# ═══════════════════════════════════════════════════════════════════

def record_simulation_run(
    account_id: int,
    input_snapshot: dict,
    decision: dict,
    total_value_before: float,
    total_value_after: float,
    trades_count: int,
    pnl: float,
) -> int:
    """记录一次执行到 simulation_runs 表"""
    conn = get_connection()
    try:
        cur = conn.execute("""
            INSERT INTO simulation_runs
                (account_id, run_version, created_at,
                 ma20, rsi, atr, news_score,
                 signal, score, confidence,
                 trades_count, pnl, total_value_before, total_value_after)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            account_id, _RUN_VERSION, datetime.now().isoformat(),
            input_snapshot.get("ma20"), input_snapshot.get("rsi"),
            input_snapshot.get("atr"), input_snapshot.get("news_score"),
            decision.get("signal"), decision.get("score"),
            decision.get("confidence"),
            trades_count, round(pnl, 2),
            round(total_value_before, 2), round(total_value_after, 2),
        ))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 3. 收益归因 — 按 Agent 维度写入
# ═══════════════════════════════════════════════════════════════════

def record_agent_attribution(
    account_id: int,
    dt_str: str,
    contributions: List[dict],
    total_pnl: float,
):
    """
    按 Agent 权重比例拆分收益归因并写入 sim_agent_attribution。

    Args:
        account_id: 模拟账户 ID
        dt_str: 日期字符串 (YYYY-MM-DD)
        contributions: 来自 MergedDecision.agents_contributions
                      或 account_results.trades 中提取的贡献数据
        total_pnl: 本次执行总盈亏（含未实现浮盈浮亏）
    """
    conn = get_connection()
    try:
        for c in contributions:
            agent = c.get("agent")
            score = c.get("score", 50)
            confidence = c.get("confidence", 50)
            weight = c.get("weight", 0.33)

            # PnL 按融合权重比例归因
            pnl_share = round(total_pnl * weight, 2)

            conn.execute("""
                INSERT INTO sim_agent_attribution
                    (account_id, date, agent_name, trade_count, total_score,
                     avg_confidence, weighted_share, pnl_contribution)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id, date, agent_name) DO UPDATE SET
                    trade_count = trade_count + excluded.trade_count,
                    total_score = excluded.total_score,
                    avg_confidence = (avg_confidence + excluded.avg_confidence) / 2,
                    weighted_share = excluded.weighted_share,
                    pnl_contribution = pnl_contribution + excluded.pnl_contribution
            """, (
                account_id, dt_str, agent,
                1 if weight > 0 else 0,
                score, confidence, round(weight, 4), pnl_share,
            ))

        conn.commit()
    except Exception as e:
        logger.error("[Attribution] 写入归因失败: {}", e)
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 4. 读取归因数据
# ═══════════════════════════════════════════════════════════════════

def get_attribution(
    account_id: Optional[int] = None,
    days: int = 30,
) -> List[dict]:
    """获取归因数据，可选按账户筛选"""
    conn = get_connection()
    try:
        if account_id:
            rows = conn.execute("""
                SELECT aa.*, a.name AS account_name
                FROM sim_agent_attribution aa
                JOIN sim_accounts a ON a.id = aa.account_id
                WHERE aa.account_id = ?
                  AND aa.date >= date('now', '-' || ? || ' days')
                ORDER BY aa.date DESC, aa.agent_name
            """, (account_id, days)).fetchall()
        else:
            rows = conn.execute("""
                SELECT aa.*, a.name AS account_name
                FROM sim_agent_attribution aa
                JOIN sim_accounts a ON a.id = aa.account_id
                WHERE aa.date >= date('now', '-' || ? || ' days')
                ORDER BY aa.date DESC, aa.agent_name
            """, (days,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_attribution_summary(
    account_id: int,
    days: int = 30,
) -> List[dict]:
    """按 Agent 维度汇总 — 每个 Agent 的总贡献"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                agent_name,
                SUM(trade_count) AS total_trades,
                AVG(avg_confidence) AS avg_confidence,
                SUM(pnl_contribution) AS total_pnl,
                ROUND(SUM(pnl_contribution) * 100.0 / NULLIF(SUM(SUM(pnl_contribution)) OVER (), 0), 1) AS pnl_share_pct
            FROM sim_agent_attribution
            WHERE account_id = ?
              AND date >= date('now', '-' || ? || ' days')
            GROUP BY agent_name
            ORDER BY total_pnl DESC
        """, (account_id, days)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 5. 读取运行记录
# ═══════════════════════════════════════════════════════════════════

def get_simulation_runs(
    account_id: Optional[int] = None,
    limit: int = 50,
) -> List[dict]:
    """获取运行历史"""
    conn = get_connection()
    try:
        if account_id:
            rows = conn.execute("""
                SELECT sr.*, a.name AS account_name
                FROM simulation_runs sr
                JOIN sim_accounts a ON a.id = sr.account_id
                WHERE sr.account_id = ?
                ORDER BY sr.id DESC LIMIT ?
            """, (account_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT sr.*, a.name AS account_name
                FROM simulation_runs sr
                JOIN sim_accounts a ON a.id = sr.account_id
                ORDER BY sr.id DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════
# 6. 绩效指标（基于每日净值序列）
# ═══════════════════════════════════════════════════════════════════

def calc_performance_metrics(daily_values: List[dict]) -> dict:
    """
    基于 daily_values 序列计算绩效指标。
    复用回测引擎的 _calc_metrics() 逻辑思路。

    Returns:
        { total_return, annual_return, max_drawdown_pct,
          sharpe_ratio, sortino_ratio, calmar_ratio,
          volatility, win_days, loss_days, ... }
    """
    if not daily_values or len(daily_values) < 2:
        return {"error": "数据不足", "total_return": 0}

    vals = [d["total_value"] for d in daily_values]
    start_val = vals[0]
    end_val = vals[-1]
    total_return = (end_val - start_val) / start_val if start_val > 0 else 0

    # 时间段
    days = max(
        (datetime.fromisoformat(daily_values[-1]["date"]) -
         datetime.fromisoformat(daily_values[0]["date"])).days,
        1,
    )
    years = days / 365.0
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # 最大回撤
    peak = vals[0]
    max_drawdown_pct = 0.0
    for v in vals:
        if v > peak:
            peak = v
        dd_pct = (peak - v) / peak if peak > 0 else 0
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct

    # 日收益率序列
    daily_returns = [(vals[i] - vals[i - 1]) / vals[i - 1]
                     for i in range(1, len(vals)) if vals[i - 1] > 0]

    # Sharpe
    import math
    if daily_returns:
        avg_daily = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_daily) ** 2 for r in daily_returns) / len(daily_returns)
        std_daily = math.sqrt(variance) if variance > 0 else 0.0001
        sharpe = (avg_daily - 0.02 / 365) / std_daily * math.sqrt(365)
    else:
        sharpe = 0

    # Sortino
    neg_returns = [r for r in daily_returns if r < 0]
    if neg_returns:
        avg_neg = sum(neg_returns) / len(neg_returns)
        neg_var = sum((r - avg_neg) ** 2 for r in neg_returns) / len(neg_returns)
        downside_std = math.sqrt(neg_var) if neg_var > 0 else 0.0001
        sortino = (avg_daily - 0.02 / 365) / downside_std * math.sqrt(365)
    else:
        sortino = sharpe

    # Calmar
    calmar = annual_return / max_drawdown_pct if max_drawdown_pct > 0 else 0

    # 波动率
    volatility = math.sqrt(variance) * math.sqrt(365) if daily_returns else 0 if "variance" in dir() else 0
    if daily_returns and "variance" not in dir():
        avg_d = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_d) ** 2 for r in daily_returns) / len(daily_returns)
        volatility = math.sqrt(variance) * math.sqrt(365)

    # 上涨/下跌天数
    win_days = sum(1 for r in daily_returns if r > 0)
    loss_days = sum(1 for r in daily_returns if r < 0)
    win_rate = win_days / len(daily_returns) * 100 if daily_returns else 0

    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "max_drawdown_pct": round(max_drawdown_pct * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "volatility": round(volatility * 100, 2),
        "win_rate_days": round(win_rate, 1),
        "win_days": win_days,
        "loss_days": loss_days,
        "total_days": days,
        "trading_days": len(vals),
        "final_value": round(end_val, 2),
        "total_profit": round(end_val - start_val, 2),
    }
