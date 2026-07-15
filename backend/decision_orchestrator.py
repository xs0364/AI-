"""
Decision Orchestrator — 决策调度器
====================================
定位：纯调度器，不调用 LLM，不参与智能判断
任务：
  1. 从数据库读取基金列表 + 历史价格
  2. 采集交易时间状态
  3. 调度 Market Agent → 情绪分
  4. 分发数据到 Trend / Grid Agent（不互相调用）
  5. 收集所有 Agent 输出 → 传给 Signal Merge Engine
  6. 返回融合决策

数据流：
  Orchestrator
    ├─→ Market Agent → sentiment_score
    ├─→ Trend Agent  → trend_signal
    ├─→ Grid Agent   → grid_signal
    └─→ Merge Engine → final_decision
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger

from database import get_connection
from agent_schema import AgentSignal, SignalType, MergedDecision
from signal_merge_engine import merge as merge_signals
from risk_engine import RiskEngine, load_risk_config

# 全局风控实例（惰性初始化）
_risk_engine: Optional[RiskEngine] = None

def _get_risk_engine() -> RiskEngine:
    global _risk_engine
    if _risk_engine is None:
        cfg = load_risk_config()
        _risk_engine = RiskEngine(cfg.__dict__)
    return _risk_engine


# ══════════════════════════════════════════════════════════════════
# 数据采集
# ══════════════════════════════════════════════════════════════════

def _get_all_funds() -> List[dict]:
    """读取所有基金列表"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, code, name, shares, cost_price, current_price, update_time
        FROM funds ORDER BY id
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_price_history(fund_code: str, days: int = 90) -> List[float]:
    """
    从 daily_values 或基金历史净值构建价格序列

    优先使用 daily_values 的净值推算价格，
    如果没有则使用 seed 方式生成模拟序列。
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT date, total_value FROM daily_values
        WHERE fund_id = (SELECT id FROM funds WHERE code = ?)
        ORDER BY date
    """, (fund_code,)).fetchall()
    conn.close()

    if rows and len(rows) >= 20:
        # 从 daily_values 反向推算价格
        conn2 = get_connection()
        shares = conn2.execute(
            "SELECT shares FROM funds WHERE code = ?", (fund_code,)
        ).fetchone()
        conn2.close()

        if shares and shares["shares"] > 0:
            prices = [r["total_value"] / shares["shares"] for r in rows]
            return prices

    # 兜底：从 current_price 生成随机序列
    conn3 = get_connection()
    fund = conn3.execute(
        "SELECT current_price FROM funds WHERE code = ?", (fund_code,)
    ).fetchone()
    conn3.close()

    if not fund:
        return []

    import random
    random.seed(hash(fund_code) % (2**31))
    prices = []
    price = fund["current_price"] * 0.85
    for i in range(days):
        drift = (fund["current_price"] - price) / max(days, 1) * 0.3
        noise = random.gauss(0, 1) * price * 0.015
        price = price + drift + noise
        price = max(price, fund["current_price"] * 0.4)
        prices.append(round(price, 4))
    prices[-1] = fund["current_price"]
    return prices


def _get_strategy_for_fund(fund_id: int) -> Optional[dict]:
    """获取基金启用的策略"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM strategies WHERE fund_id = ? AND enabled = 1 LIMIT 1",
        (fund_id,),
    ).fetchone()
    conn.close()
    if row:
        params = json.loads(row["params"]) if isinstance(row["params"], str) else row["params"]
        return {"id": row["id"], "type": row["strategy_type"], "params": params}
    return None


def _get_time_status() -> dict:
    """获取当前交易时间状态"""
    try:
        from trading_time_engine import get_current_time_status
        return get_current_time_status()
    except Exception as e:
        logger.warning("获取时间状态失败: {}", e)
        return {"isTradingDay": True, "isBefore1500": True}


# ══════════════════════════════════════════════════════════════════
# 核心：处理单个基金
# ══════════════════════════════════════════════════════════════════

def process_fund(
    fund: dict,
    time_status: dict,
    market_results: Optional[List[dict]] = None,
) -> MergedDecision:
    """
    对单只基金运行所有 Agent → 输出最终决策

    Args:
        fund: 基金信息 { id, code, name, current_price, ... }
        time_status: 交易时间状态
        market_results: Market Agent 的批量分析结果（可选，避免重复调用）

    Returns:
        MergedDecision
    """
    fund_id = fund["id"]
    fund_code = fund["code"]
    fund_name = fund["name"]
    current_price = fund.get("current_price", 0) or 0

    # 1. 获取价格历史
    prices = _get_price_history(fund_code)

    if not prices or len(prices) < 5:
        logger.warning("基金 {} 数据不足，跳过", fund_code)
        return _empty_decision("数据不足", fund_code, fund_name)

    # 2. 获取策略
    strategy = _get_strategy_for_fund(fund_id)

    # 3. 获取情绪分（从 Market Agent 结果中筛选）
    sentiment_score = None
    market_signal = None
    if market_results:
        relevant = [
            r for r in market_results
            if fund_code in r.get("affected_funds", [])
        ]
        if relevant:
            # 取影响最大的一条
            relevant.sort(key=lambda r: abs(r.get("score", 50) - 50), reverse=True)
            top = relevant[0]
            sentiment_score = top.get("score")
            # 构建 Market AgentSignal 供融合用
            sig_map = {
                "POSITIVE": SignalType.POSITIVE,
                "NEGATIVE": SignalType.NEGATIVE,
            }
            market_signal = AgentSignal(
                agent="market",
                signal=sig_map.get(top.get("signal", "NEUTRAL"), SignalType.NEUTRAL),
                score=top.get("score", 50),
                confidence=top.get("confidence", 50),
                reason=top.get("reason", [top.get("summary", "")]),
                risk=top.get("risk", 30),
                affected_funds=[fund_code],
            )

    # 4. 运行 Trend Agent
    from agent_trend import run as run_trend
    trend_signal = run_trend(
        fund_id=fund_id,
        fund_code=fund_code,
        fund_name=fund_name,
        prices=prices,
        current_price=current_price,
        sentiment_score=sentiment_score,
    )

    # 5. 运行 Grid Agent
    from agent_grid import run as run_grid
    grid_signal = run_grid(
        fund_id=fund_id,
        fund_code=fund_code,
        fund_name=fund_name,
        prices=prices,
        current_price=current_price,
        sentiment_score=sentiment_score,
        strategy_params=strategy["params"] if strategy else None,
        time_status=time_status,
    )

    # 6. 收集所有信号 → 融合
    all_signals: List[AgentSignal] = [trend_signal, grid_signal]
    if market_signal:
        all_signals.append(market_signal)

    decision = merge_signals(all_signals)
    decision.trade_price = current_price

    # 计算建议交易量（简单比例）
    if strategy:
        if strategy["type"] == "ma":
            decision.trade_quantity = round(500 / max(current_price, 0.01), 2)
        elif strategy["type"] == "grid":
            params = strategy["params"]
            step_size = float(params.get("stepSize", 0.10))
            decision.trade_quantity = round(step_size * 100 / max(current_price, 0.01), 2)
    else:
        decision.trade_quantity = round(500 / max(current_price, 0.01), 2)

    # 7. 风控引擎检查
    try:
        risk_engine = _get_risk_engine()

        # 获取持仓天数
        hold_days = 0
        try:
            conn = get_connection()
            last_buy = conn.execute(
                "SELECT time FROM trades WHERE fund_id = ? AND direction = 'buy' AND status = 'executed' ORDER BY time DESC LIMIT 1",
                (fund_id,),
            ).fetchone()
            conn.close()
            if last_buy:
                buy_time = datetime.fromisoformat(last_buy["time"])
                hold_days = (datetime.now() - buy_time).days
        except Exception:
            pass

        # 判断是否为开仓信号
        is_open = decision.signal in (
            SignalType.STRONG_BUY, SignalType.BUY,
            SignalType.LIGHTEN_BUY, SignalType.INCREASE,
        )

        # 获取所有基金信息（用于资金风控）
        all_funds = _get_all_funds()

        # 获取 daily_values（用于回撤计算）
        dv_prices = []
        try:
            conn = get_connection()
            rows = conn.execute("""
                SELECT date, total_value, fund_id FROM daily_values
                WHERE fund_id = ?
                ORDER BY date
            """, (fund_id,)).fetchall()
            conn.close()
            dv_prices = [dict(r) for r in rows]
        except Exception:
            pass

        risk_verdict = risk_engine.check(
            fund=fund,
            decision_score=decision.score,
            decision_signal=decision.signal.value,
            context={
                "prices": prices,
                "daily_values": dv_prices,
                "sentiment_score": sentiment_score or 50,
                "all_funds": all_funds,
                "hold_days": hold_days,
                "is_open": is_open,
            },
        )

        decision.risk_verdict = risk_verdict

        # 如果风控不允许执行，覆盖 should_execute
        if not risk_verdict.allow:
            decision.should_execute = False

        # 如果风控建议的仓位更低，缩小交易量
        if risk_verdict.max_position < 1.0 and decision.trade_quantity > 0:
            decision.trade_quantity = round(decision.trade_quantity * risk_verdict.max_position, 2)

        logger.info("[Risk] 基金 {} 风控评分: {}, 等级: {}, 允许执行: {}",
                    fund_code, risk_verdict.risk_score, risk_verdict.risk_level, risk_verdict.allow)

    except Exception as e:
        logger.warning("[Risk] 风控检查失败: {}", e)

    return decision


def _empty_decision(reason: str, code: str = "", name: str = "") -> MergedDecision:
    """数据不足时的空决策"""
    return MergedDecision(
        signal="HOLD",
        score=50,
        confidence=0,
        reasons=[f"{reason} | {code} {name}"],
        risk=50,
        expire_at=None,
        should_execute=False,
    )


# ══════════════════════════════════════════════════════════════════
# 批量扫描（主入口）
# ══════════════════════════════════════════════════════════════════

def scan_all() -> List[dict]:
    """
    扫描所有基金 → 运行全 Agent 流程 → 返回决策列表

    此函数被 app.py 的 /api/agents/scan 端点调用。

    Returns:
        [
            {
                "fund_id": 1,
                "fund_code": "110011",
                "fund_name": "易方达中小盘混合",
                "decision": { MergedDecision.to_dict() },
            },
            ...
        ]
    """
    logger.info("Orchestrator: 开始全量扫描")
    t0 = datetime.now()

    # 1. 采集全局数据
    funds = _get_all_funds()
    time_status = _get_time_status()

    if not funds:
        logger.warning("Orchestrator: 无基金数据")
        return []

    # 2. 运行 Market Agent（全局新闻分析，所有基金共享）
    logger.info("Orchestrator: 运行 Market Intelligence Agent...")
    try:
        from agent_market import run as run_market
        market_results = run_market()
    except Exception as e:
        logger.warning("Orchestrator: Market Agent 失败: {}", e)
        market_results = None

    # 3. 逐个处理基金
    results = []
    for fund in funds:
        try:
            decision = process_fund(fund, time_status, market_results)
            results.append({
                "fund_id": fund["id"],
                "fund_code": fund["code"],
                "fund_name": fund["name"],
                "current_price": fund.get("current_price", 0),
                "decision": decision.to_dict(),
            })
        except Exception as e:
            logger.warning("Orchestrator: 处理基金 {} 失败: {}", fund['code'], e)
            results.append({
                "fund_id": fund["id"],
                "fund_code": fund["code"],
                "fund_name": fund.get("name", ""),
                "current_price": fund.get("current_price", 0),
                "decision": _empty_decision(f"处理出错: {e}").to_dict(),
            })

    elapsed = (datetime.now() - t0).total_seconds()
    logger.info("Orchestrator: 扫描完成, {}/{} 只基金, 耗时{:.1f}s",
                len(results), len(funds), elapsed)

    return results


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    results = scan_all()
    print(json.dumps(results, ensure_ascii=False, indent=2))
