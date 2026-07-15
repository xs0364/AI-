"""
FastAPI backend for the Fund Manager application.

Endpoints:
  /api/funds/*              — Fund CRUD
  /api/strategies/*         — Strategy CRUD + run + toggle
  /api/trades/*             — Trade records + scan + execute
  /api/analytics/*          — Portfolio value, trade analytics, summary
  /api/portfolio/reset      — Reset all data
"""
import json
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from loguru import logger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 全局调度器（lifespan 内初始化，health check 读取）
scheduler: BackgroundScheduler = None

from database import get_connection, init_db
from models import (FundCreate, FundUpdate, StrategyCreate, StrategyUpdate,
                     TradeCreate, ListResponse, MessageResponse, SignalResponse)
from strategy_engine import scan_all_strategies, run_strategy
from seed import seed_database
from trading_time_engine import (
    get_current_time_status,
    get_knowledge_base,
    get_trade_nav_date,
    calc_hold_days,
    calc_redemption_fee,
    is_trading_day,
    is_before_1500,
    is_etf_trading_time,
    get_qdii_trade_info,
    NewsTimeWindow,
)
from market_data_fetcher import (
    fetch_fund_realtime,
    fetch_fund_history,
    fetch_etf_trend,
    fetch_fund_holdings,
    fetch_fund_code_list,
    fetch_all_news,
    batch_fetch_funds_realtime,
)
from news_engine import get_portfolio_news, match_news_to_portfolio


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    init_db()
    seed_database()
    from seed import seed_sim_accounts
    seed_sim_accounts()

    # ── APScheduler 定时任务 ────────────────────────────────────
    scheduler = BackgroundScheduler()

    def scheduled_agent_scan():
        """定时运行 Agent 全量扫描"""
        try:
            from decision_orchestrator import scan_all
            logger.info("[Scheduler] Agent 定时扫描开始...")
            results = scan_all()
            # 如果有可执行的交易信号，自动执行
            executable = [
                r for r in results
                if r.get("decision", {}).get("should_execute")
            ]
            if executable:
                logger.info("[Scheduler] {} 个可执行信号，自动提交交易", len(executable))
                for item in executable:
                    _execute_agent_trade(item)
            logger.info("[Scheduler] Agent 定时扫描完成 ({} 只基金, {} 个信号)",
                        len(results), len(executable))
        except Exception as e:
            logger.error("[Scheduler] 定时扫描失败: {}", e)

    def _execute_agent_trade(item: dict):
        """执行 Agent 的交易信号"""
        dec = item.get("decision", {})
        signal, fund_id = dec.get("signal"), item.get("fund_id")
        if not signal or not fund_id:
            return
        conn = get_connection()
        fund = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
        if not fund:
            conn.close()
            return
        direction = "buy" if signal in ("STRONG_BUY", "BUY", "LIGHTEN_BUY") else "sell"
        price = dec.get("trade_price") or fund["current_price"]
        qty = dec.get("trade_quantity", 0)
        if qty <= 0:
            conn.close()
            return
        amount = round(price * qty, 2)
        conn.execute(
            "INSERT INTO trades (fund_id, direction, price, shares, amount, strategy, time, status) VALUES (?,?,?,?,?,?,?,?)",
            (fund_id, direction, price, qty, amount, "Agent自动", datetime.now().isoformat(), "executed"),
        )
        conn.commit()
        conn.close()
        logger.info("[Scheduler] 自动交易: {} {} {}份 @{}",
                    fund["name"], direction, qty, price)

    # ── 交易日 5 步流水线调度 ──────────────────────────────────
    # 14:30 Market Data / 新闻 / 基准指数更新 + 基金价格刷新
    def scheduled_market_update():
        try:
            logger.info("[Scheduler] 14:30 市场数据更新开始...")
            # 1. 基准指数更新
            from benchmark_engine import ensure_benchmark_data
            for code in ("000300", "000905"):
                ok = ensure_benchmark_data(code)
                logger.info("[Scheduler] 基准指数 {} 更新: {}", code, "成功" if ok else "失败")

            # 2. 基金实时价格刷新
            conn = get_connection()
            try:
                funds = conn.execute("SELECT id, code, name FROM funds").fetchall()
                codes = [f["code"] for f in funds]
                if codes:
                    from market_data_fetcher import batch_fetch_funds_realtime
                    quotes = batch_fetch_funds_realtime(codes)
                    today = datetime.now().strftime("%Y-%m-%d")
                    updated = 0
                    for q in quotes:
                        if q.get("error") or not q.get("gsz"):
                            continue
                        code = q["code"]
                        gsz = float(q["gsz"])
                        dwjz = float(q["dwjz"]) if q.get("dwjz") else None
                        gszzl = q.get("gszzl")
                        change_pct = float(gszzl) if gszzl else None

                        # 更新 funds.current_price
                        conn.execute(
                            "UPDATE funds SET current_price = ?, update_time = datetime('now','localtime') WHERE code = ?",
                            (gsz, code),
                        )
                        # 写入 fund_prices 历史表
                        conn.execute("""
                            INSERT OR REPLACE INTO fund_prices (fund_code, date, nav, estimate_nav, change_pct, source)
                            VALUES (?, ?, ?, ?, ?, 'realtime')
                        """, (code, today, dwjz or gsz, gsz, change_pct))
                        updated += 1
                    conn.commit()
                    logger.info("[Scheduler] 基金价格刷新: {}/{} 只成功", updated, len(codes))
            finally:
                conn.close()

            logger.info("[Scheduler] 14:30 数据更新完成")
        except Exception as e:
            logger.error("[Scheduler] 14:30 数据更新失败: {}", e)

    scheduler.add_job(
        scheduled_market_update,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=30),
        id="market_update_1430",
        name="数据更新 14:30",
        replace_existing=True,
    )
    # 14:40 Agent 扫描 + 实盘交易
    scheduler.add_job(
        scheduled_agent_scan,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=40),
        id="agent_scan_1440",
        name="Agent 扫描 14:40",
        replace_existing=True,
    )
    # 14:55 Agent 二次扫描（实盘补充）
    scheduler.add_job(
        scheduled_agent_scan,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=55),
        id="agent_scan_1455",
        name="Agent 扫描 14:55",
        replace_existing=True,
    )
    # 14:50 模拟盘执行
    def scheduled_simulate():
        try:
            from sim_engine import execute_for_all_accounts, record_daily_snapshot_now
            logger.info("[Scheduler] 模拟盘定时执行开始...")
            results = execute_for_all_accounts()
            record_daily_snapshot_now()
            total_trades = sum(len(r.get("trades", [])) for r in results)
            logger.info("[Scheduler] 模拟盘执行完成: {} 个账户, {} 笔交易", len(results), total_trades)
        except Exception as e:
            logger.error("[Scheduler] 模拟盘执行失败: {}", e)

    scheduler.add_job(
        scheduled_simulate,
        CronTrigger(day_of_week="mon-fri", hour=14, minute=50),
        id="sim_execute_1450",
        name="模拟盘执行 14:50",
        replace_existing=True,
    )
    # 15:05 收盘净值快照
    def scheduled_snapshot():
        try:
            from sim_engine import record_daily_snapshot_now
            record_daily_snapshot_now()
            logger.info("[Scheduler] 收盘净值快照已记录")
        except Exception as e:
            logger.error("[Scheduler] 收盘净值快照失败: {}", e)

    scheduler.add_job(
        scheduled_snapshot,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=5),
        id="snapshot_1505",
        name="收盘净值快照 15:05",
        replace_existing=True,
    )

    # 15:10 AI 复盘日报生成
    def scheduled_daily_review():
        try:
            from daily_review_agent import generate_daily_review
            result = generate_daily_review()
            if result:
                logger.info("[Scheduler] AI 复盘报告已生成 (id={})", result.get("id"))
            else:
                logger.info("[Scheduler] AI 复盘报告跳过（今日已存在或数据不足）")
        except Exception as e:
            logger.error("[Scheduler] AI 复盘报告失败: {}", e)

    scheduler.add_job(
        scheduled_daily_review,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=10),
        id="daily_review_1510",
        name="AI 复盘报告 15:10",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] 交易日流水线已启动: 14:30数据→14:40Agent→14:50模拟盘→14:55Agent→15:05快照→15:10AI复盘")

    yield
    scheduler.shutdown(wait=False)


# ── App ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Fund Manager API",
    description="基金持仓管理与策略回测系统",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def row_to_dict(row) -> dict:
    """Convert sqlite3.Row to dict."""
    return dict(row) if row else None


# ── Helpers ──────────────────────────────────────────────────────────────

def _build_fund(row) -> dict:
    """Row → camelCase fund dict."""
    r = row_to_dict(row)
    return {
        "id": r["id"],
        "code": r["code"],
        "name": r["name"],
        "shares": r["shares"],
        "costPrice": r["cost_price"],
        "currentPrice": r["current_price"],
        "updateTime": r["update_time"],
    }


def _build_strategy(row) -> dict:
    """Row → camelCase strategy dict."""
    r = row_to_dict(row)
    params = json.loads(r["params"]) if isinstance(r["params"], str) else r["params"]
    return {
        "id": r["id"],
        "fundId": r["fund_id"],
        "name": r["name"],
        "type": r["strategy_type"],
        "params": params,
        "enabled": bool(r["enabled"]),
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }


def _build_trade(row) -> dict:
    """Row → camelCase trade dict."""
    r = row_to_dict(row)
    return {
        "id": r["id"],
        "fundId": r["fund_id"],
        "direction": r["direction"],
        "price": r["price"],
        "shares": r["shares"],
        "amount": r["amount"],
        "strategy": r["strategy"],
        "strategyId": r["strategy_id"],
        "time": r["time"],
        "status": r["status"],
    }


# ══════════════════════════════════════════════════════════════════════════
#  FUNDS
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/funds", response_model=ListResponse)
def list_funds():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM funds ORDER BY code").fetchall()
    conn.close()
    data = [_build_fund(r) for r in rows]
    return {"data": data, "total": len(data)}


@app.get("/api/funds/{fund_id}", response_model=dict)
def get_fund(fund_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "基金不存在")
    return _build_fund(row)


@app.post("/api/funds", response_model=dict, status_code=201)
def create_fund(body: FundCreate):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO funds (code, name, shares, cost_price, current_price, update_time) VALUES (?,?,?,?,?,?)",
            (body.code, body.name, body.shares, body.cost_price, body.current_price, datetime.now().isoformat()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM funds WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()
    return _build_fund(row)


@app.put("/api/funds/{fund_id}", response_model=dict)
def update_fund(fund_id: int, body: FundUpdate):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "基金不存在")

    updates = {}
    if body.code is not None:
        updates["code"] = body.code
    if body.name is not None:
        updates["name"] = body.name
    if body.shares is not None:
        updates["shares"] = body.shares
    if body.cost_price is not None:
        updates["cost_price"] = body.cost_price
    if body.current_price is not None:
        updates["current_price"] = body.current_price
    updates["update_time"] = datetime.now().isoformat()

    if len(updates) > 1:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [fund_id]
        conn.execute(f"UPDATE funds SET {set_clause} WHERE id = ?", values)
        conn.commit()

    row = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
    conn.close()
    return _build_fund(row)


@app.delete("/api/funds/{fund_id}", response_model=MessageResponse)
def delete_fund(fund_id: int):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "基金不存在")
    conn.execute("DELETE FROM funds WHERE id = ?", (fund_id,))
    conn.commit()
    conn.close()
    return {"message": "已删除"}


# ══════════════════════════════════════════════════════════════════════════
#  STRATEGIES
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/strategies", response_model=ListResponse)
def list_strategies():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM strategies ORDER BY id").fetchall()
    conn.close()
    data = [_build_strategy(r) for r in rows]
    return {"data": data, "total": len(data)}


@app.post("/api/strategies", response_model=dict, status_code=201)
def create_strategy(body: StrategyCreate):
    conn = get_connection()
    fund = conn.execute("SELECT id FROM funds WHERE id = ?", (body.fund_id,)).fetchone()
    if not fund:
        conn.close()
        raise HTTPException(400, "关联的基金不存在")
    try:
        params_str = json.dumps(body.params, ensure_ascii=False)
        cur = conn.execute(
            "INSERT INTO strategies (fund_id, name, strategy_type, params, enabled, created_at, updated_at) VALUES (?,?,?,?,1,?,?)",
            (body.fund_id, body.name, body.strategy_type, params_str, datetime.now().isoformat(), datetime.now().isoformat()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM strategies WHERE id = ?", (cur.lastrowid,)).fetchone()
    finally:
        conn.close()
    return _build_strategy(row)


@app.put("/api/strategies/{strategy_id}", response_model=dict)
def update_strategy(strategy_id: int, body: StrategyUpdate):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "策略不存在")

    updates = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.fund_id is not None:
        # Verify fund exists
        fund = conn.execute("SELECT id FROM funds WHERE id = ?", (body.fund_id,)).fetchone()
        if not fund:
            conn.close()
            raise HTTPException(400, "关联的基金不存在")
        updates["fund_id"] = body.fund_id
    if body.strategy_type is not None:
        updates["strategy_type"] = body.strategy_type
    if body.params is not None:
        updates["params"] = json.dumps(body.params, ensure_ascii=False)
    if body.enabled is not None:
        updates["enabled"] = 1 if body.enabled else 0
    updates["updated_at"] = datetime.now().isoformat()

    if len(updates) > 1:
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [strategy_id]
        conn.execute(f"UPDATE strategies SET {set_clause} WHERE id = ?", values)
        conn.commit()

    row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    conn.close()
    return _build_strategy(row)


@app.delete("/api/strategies/{strategy_id}", response_model=MessageResponse)
def delete_strategy(strategy_id: int):
    conn = get_connection()
    existing = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "策略不存在")
    conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
    conn.commit()
    conn.close()
    return {"message": "已删除"}


@app.patch("/api/strategies/{strategy_id}/toggle", response_model=dict)
def toggle_strategy(strategy_id: int, body: dict = None):
    enabled = body.get("enabled", True) if body else True
    conn = get_connection()
    existing = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    if not existing:
        conn.close()
        raise HTTPException(404, "策略不存在")
    conn.execute(
        "UPDATE strategies SET enabled = ?, updated_at = ? WHERE id = ?",
        (1 if enabled else 0, datetime.now().isoformat(), strategy_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    conn.close()
    return _build_strategy(row)


@app.post("/api/strategies/{strategy_id}/run", response_model=SignalResponse)
def run_strategy_endpoint(strategy_id: int):
    """Run backtest on a single strategy and return generated signals."""
    conn = get_connection()
    strategy = conn.execute("SELECT * FROM strategies WHERE id = ?", (strategy_id,)).fetchone()
    conn.close()
    if not strategy:
        raise HTTPException(404, "策略不存在")

    signals = run_strategy(strategy_id)
    return {"signals": signals, "total": len(signals)}


@app.get("/api/strategies/{strategy_id}/signals", response_model=SignalResponse)
def get_strategy_signals(strategy_id: int):
    """Get all saved trade signals for a strategy (from trade_signals table)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM trade_signals WHERE strategy_id = ? ORDER BY generated_at DESC",
        (strategy_id,),
    ).fetchall()
    conn.close()
    signals = [dict(r) for r in rows]
    return {"signals": signals, "total": len(signals)}


# ══════════════════════════════════════════════════════════════════════════
#  TRADES
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/trades", response_model=ListResponse)
def list_trades(
    direction: Optional[str] = Query(None),
    strategy_id: Optional[int] = Query(None, alias="strategyId"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
):
    conn = get_connection()
    conditions = []
    params = []
    if direction:
        conditions.append("direction = ?")
        params.append(direction)
    if strategy_id is not None:
        conditions.append("strategy_id = ?")
        params.append(strategy_id)

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = conn.execute(
        f"SELECT * FROM trades WHERE {where} ORDER BY time DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    total = conn.execute(
        f"SELECT COUNT(*) FROM trades WHERE {where}", params
    ).fetchone()[0]
    conn.close()
    data = [_build_trade(r) for r in rows]
    return {"data": data, "total": total}


@app.post("/api/trades", response_model=dict, status_code=201)
def create_trade(body: TradeCreate):
    """Execute a trade manually."""
    conn = get_connection()
    fund = conn.execute("SELECT * FROM funds WHERE id = ?", (body.fund_id,)).fetchone()
    if not fund:
        conn.close()
        raise HTTPException(400, "基金不存在")

    amount = round(body.price * body.shares, 2)

    # Update fund holdings
    if body.direction == "buy":
        new_shares = fund["shares"] + body.shares
        new_cost = ((fund["shares"] * fund["cost_price"]) + amount) / new_shares if new_shares > 0 else body.price
        new_price = body.price
    else:  # sell
        new_shares = max(0, fund["shares"] - body.shares)
        new_cost = fund["cost_price"]
        new_price = body.price

    conn.execute(
        "UPDATE funds SET shares = ?, cost_price = ?, current_price = ?, update_time = ? WHERE id = ?",
        (new_shares, round(new_cost, 4), new_price, datetime.now().isoformat(), body.fund_id),
    )

    cur = conn.execute(
        "INSERT INTO trades (fund_id, direction, price, shares, amount, strategy, strategy_id, time, status) VALUES (?,?,?,?,?,?,?,?,?)",
        (body.fund_id, body.direction, body.price, body.shares, amount,
         body.strategy, body.strategy_id, datetime.now().isoformat(), "executed"),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM trades WHERE id = ?", (cur.lastrowid,)).fetchone()
    conn.close()
    return _build_trade(row)


@app.post("/api/trades/scan", response_model=SignalResponse)
def scan_trades():
    """
    Scan all enabled strategies, generate signals, save to trade_signals,
    auto-execute signals (update fund prices + create trade records).
    """
    signals = scan_all_strategies()
    executed_signals = []

    conn = get_connection()
    try:
        for sig in signals:
            # Save to trade_signals table
            cur = conn.execute(
                "INSERT INTO trade_signals (fund_id, strategy_id, signal_type, price, quantity, generated_at) VALUES (?,?,?,?,?,?)",
                (sig["fund_id"], sig["strategy_id"], sig["signal_type"], sig["price"], sig["quantity"], sig["generated_at"]),
            )
            signal_id = cur.lastrowid

            # Auto-execute: update fund current_price + create trade record
            fund = conn.execute("SELECT * FROM funds WHERE id = ?", (sig["fund_id"],)).fetchone()
            if not fund:
                continue

            qty = sig["quantity"]
            amount = round(sig["price"] * qty, 2)

            if sig["signal_type"] == "buy":
                new_shares = fund["shares"] + qty
                new_cost = round(((fund["shares"] * fund["cost_price"]) + amount) / new_shares, 4) if new_shares > 0 else sig["price"]
            else:  # sell
                new_shares = max(0, fund["shares"] - qty)
                new_cost = fund["cost_price"]

            conn.execute(
                "UPDATE funds SET shares = ?, cost_price = ?, update_time = ? WHERE id = ?",
                (new_shares, new_cost, datetime.now().isoformat(), sig["fund_id"]),
            )

            trade_time = datetime.now().isoformat()
            conn.execute(
                "INSERT INTO trades (fund_id, direction, price, shares, amount, strategy, strategy_id, time, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (sig["fund_id"], sig["signal_type"], sig["price"], qty, amount,
                 sig.get("strategy_name"), sig["strategy_id"], trade_time, "executed"),
            )

            conn.execute(
                "UPDATE trade_signals SET executed = 1, executed_at = ? WHERE id = ?",
                (trade_time, signal_id),
            )

            sig["id"] = signal_id
            sig["executed"] = True
            sig["executed_at"] = trade_time
            executed_signals.append(sig)

        conn.commit()
    finally:
        conn.close()

    return {"signals": executed_signals, "total": len(executed_signals)}


# ══════════════════════════════════════════════════════════════════════════
#  ANALYTICS
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/analytics/portfolio", response_model=ListResponse)
def analytics_portfolio(days: int = Query(30, le=365)):
    """Aggregated daily portfolio value over time."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT date, SUM(total_value) AS total_value
        FROM daily_values
        WHERE date >= date('now', ?)
        GROUP BY date
        ORDER BY date
    """, (f"-{days} days",)).fetchall()
    conn.close()
    data = [{"date": r["date"], "totalValue": r["total_value"]} for r in rows]
    return {"data": data, "total": len(data)}


@app.get("/api/analytics/trades", response_model=ListResponse)
def analytics_trades(days: int = Query(30, le=365)):
    """Trade statistics aggregated by day."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT date(time) AS date,
               COUNT(*) AS trade_count,
               SUM(CASE WHEN direction='buy' THEN 1 ELSE 0 END) AS buy_count,
               SUM(CASE WHEN direction='sell' THEN 1 ELSE 0 END) AS sell_count,
               SUM(amount) AS total_amount
        FROM trades
        WHERE time >= datetime('now', ?)
        GROUP BY date(time)
        ORDER BY date
    """, (f"-{days} days",)).fetchall()
    conn.close()
    data = [dict(r) for r in rows]
    return {"data": data, "total": len(data)}


@app.get("/api/analytics/summary", response_model=dict)
def analytics_summary():
    """Portfolio summary statistics."""
    conn = get_connection()
    funds = conn.execute("SELECT * FROM funds").fetchall()
    trade_count = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    total_value = 0
    total_cost = 0
    for f in funds:
        total_value += f["shares"] * f["current_price"]
        total_cost += f["shares"] * f["cost_price"]

    profit = total_value - total_cost
    profit_rate = (profit / total_cost * 100) if total_cost > 0 else 0

    # Winners vs losers
    winners = sum(1 for f in funds if f["current_price"] >= f["cost_price"])
    losers = sum(1 for f in funds if f["current_price"] < f["cost_price"])

    conn.close()
    return {
        "totalValue": round(total_value, 2),
        "totalCost": round(total_cost, 2),
        "profit": round(profit, 2),
        "profitRate": round(profit_rate, 2),
        "fundCount": len(funds),
        "tradeCount": trade_count,
        "winningFunds": winners,
        "losingFunds": losers,
    }


def _calc_risk_metrics() -> dict:
    """
    从 daily_values + trades 表计算风控指标：
    - 最大回撤
    - Sharpe Ratio（假设无风险利率 2%）
    - 年化波动率
    - 胜率
    """
    conn = get_connection()

    # 获取每日总市值
    rows = conn.execute("""
        SELECT date, SUM(total_value) AS tv
        FROM daily_values
        GROUP BY date
        ORDER BY date
    """).fetchall()

    values = [{"date": r["date"], "value": r["tv"]} for r in rows]

    max_drawdown = 0
    max_drawdown_pct = 0
    daily_returns = []
    peak = 0

    for i, v in enumerate(values):
        if v["value"] > peak:
            peak = v["value"]
        dd = peak - v["value"]
        dd_pct = dd / peak * 100 if peak > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd
            max_drawdown_pct = dd_pct

        if i > 0 and values[i-1]["value"] > 0:
            daily_ret = (v["value"] - values[i-1]["value"]) / values[i-1]["value"]
            daily_returns.append(daily_ret)

    # Sharpe Ratio（年化）
    if len(daily_returns) > 1:
        avg_daily_return = sum(daily_returns) / len(daily_returns)
        daily_std = (sum((r - avg_daily_return) ** 2 for r in daily_returns) / (len(daily_returns) - 1)) ** 0.5
        annual_return = avg_daily_return * 252
        annual_vol = daily_std * (252 ** 0.5)
        risk_free = 0.02
        sharpe = (annual_return - risk_free) / annual_vol if annual_vol > 0 else None
        volatility = annual_vol * 100
    else:
        sharpe = None
        volatility = None

    # 胜率
    trades = conn.execute(
        "SELECT direction, price, shares FROM trades ORDER BY time"
    ).fetchall()
    conn.close()

    wins = 0
    total_traded = len(trades)
    # 简化：卖出价 > 前一次同基金的买入均价视为胜
    buy_prices = {}
    for t in trades:
        if t["direction"] == "buy":
            buy_prices[t["fund_id"]] = t["price"]
        elif t["direction"] == "sell":
            buy_price = buy_prices.get(t["fund_id"])
            if buy_price and t["price"] > buy_price:
                wins += 1
    win_rate = (wins / total_traded * 100) if total_traded > 0 else 0

    return {
        "maxDrawdown": round(max_drawdown, 2),
        "maxDrawdownPct": round(max_drawdown_pct, 2),
        "sharpeRatio": round(sharpe, 2) if sharpe is not None else None,
        "volatility": round(volatility, 2) if volatility is not None else None,
        "winRate": round(win_rate, 2),
        "totalTrades": total_traded,
    }


@app.get("/api/analytics/risk", response_model=dict)
def analytics_risk():
    """风控指标：最大回撤、Sharpe、波动率、胜率"""
    return _calc_risk_metrics()


# ══════════════════════════════════════════════════════════════════════════
#  TRADING TIME ENGINE
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/time/status", response_model=dict)
def time_status():
    """Get current trading time status snapshot (实时交易时间状态)."""
    return get_current_time_status()


@app.get("/api/time/knowledge", response_model=dict)
def time_knowledge():
    """Get full trading time knowledge base (基金买卖时间节点知识库)."""
    return get_knowledge_base()


@app.get("/api/time/trade-info", response_model=dict)
def trade_time_info(time: Optional[str] = None):
    """Get NAV trade info for a given time (buy/sell time analysis).

    Query param: time= ISO datetime, defaults to now.
    """
    if time:
        try:
            dt = datetime.fromisoformat(time)
        except ValueError:
            raise HTTPException(400, "时间格式错误，请使用 ISO 格式 (YYYY-MM-DDTHH:MM:SS)")
    else:
        dt = datetime.now()
    return get_trade_nav_date(dt)


@app.get("/api/time/redemption-fee", response_model=dict)
def redemption_fee(
    buy_date: str = Query(..., description="买入日期 YYYY-MM-DD"),
    sell_date: Optional[str] = Query(None, description="卖出日期 YYYY-MM-DD，默认今天"),
    amount: float = Query(..., description="赎回金额"),
):
    """Calculate redemption fee based on holding days."""
    try:
        buy = datetime.strptime(buy_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "买入日期格式错误")

    sell = None
    if sell_date:
        try:
            sell = datetime.strptime(sell_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "卖出日期格式错误")

    hold_days = calc_hold_days(buy, sell)
    return calc_redemption_fee(amount, hold_days)


@app.get("/api/time/qdii", response_model=dict)
def qdii_info(
    fund_name: str = Query(..., description="基金名称"),
    order_time: Optional[str] = Query(None, description="下单时间 ISO格式"),
):
    """Get QDII time-zone trade info."""
    dt = datetime.fromisoformat(order_time) if order_time else datetime.now()
    return get_qdii_trade_info(fund_name, dt)


@app.get("/api/time/news-window", response_model=dict)
def news_window(
    news_time: str = Query(..., description="新闻发布时间 ISO格式"),
    detail: Optional[str] = Query("", description="新闻内容"),
):
    """Classify news and recommend operation window."""
    try:
        dt = datetime.fromisoformat(news_time)
    except ValueError:
        raise HTTPException(400, "新闻时间格式错误")
    return NewsTimeWindow.classify_news_time(dt, detail)


# ══════════════════════════════════════════════════════════════════════════
#  MARKET DATA — 实时行情 / 基金数据
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/market/fund/{code}/realtime", response_model=dict)
def market_fund_realtime(code: str):
    """单只场外基金实时估值（fundgz 极速接口）"""
    return fetch_fund_realtime(code)


@app.get("/api/market/fund/{code}/history", response_model=dict)
def market_fund_history(code: str, page: int = 1, per: int = 200):
    """基金历史净值"""
    return fetch_fund_history(code, page, per)


@app.get("/api/market/etf/{etf_code}/trend", response_model=dict)
def market_etf_trend(etf_code: str, market: int = 1):
    """场内 ETF 实时分时行情"""
    return fetch_etf_trend(etf_code, market)


@app.get("/api/market/fund/{code}/holdings", response_model=dict)
def market_fund_holdings(code: str):
    """基金前十大重仓股"""
    return fetch_fund_holdings(code)


@app.get("/api/market/fund-list", response_model=dict)
def market_fund_list():
    """全基金基础列表（初始化持仓池）"""
    return fetch_fund_code_list()


@app.post("/api/market/batch-realtime", response_model=dict)
def market_batch_realtime(codes: str = Query(..., description="基金代码逗号分隔")):
    """批量拉取多只基金实时估值"""
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        raise HTTPException(400, "请提供至少一个基金代码")
    results = batch_fetch_funds_realtime(code_list)
    return {"data": results, "total": len(results)}


@app.get("/api/benchmark/history", response_model=dict)
def benchmark_history(
    code: str = Query("000300", description="指数代码"),
    days: int = Query(365, le=1095),
):
    """获取基准指数历史净值（含归一化 nav）"""
    from benchmark_engine import get_benchmark_history
    return get_benchmark_history(code, days)


@app.get("/api/benchmark/list", response_model=dict)
def benchmark_list():
    """获取所有支持的基准指数列表"""
    from benchmark_engine import BENCHMARK_INDICES
    return {
        "indices": [
            {"code": k, "name": v["name"]}
            for k, v in BENCHMARK_INDICES.items()
        ],
        "total": len(BENCHMARK_INDICES),
    }


@app.get("/api/fund-prices/history", response_model=dict)
def fund_prices_history(
    code: str = Query(..., description="基金代码"),
    days: int = Query(30, le=365),
):
    """获取基金的历史净值记录"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT date, nav, estimate_nav, change_pct, source
            FROM fund_prices
            WHERE fund_code = ?
            ORDER BY date DESC
            LIMIT ?
        """, (code, days)).fetchall()
        data = [dict(r) for r in rows]
        data.reverse()
        return {"code": code, "data": data, "total": len(data)}
    finally:
        conn.close()


@app.get("/api/fund-prices/latest", response_model=dict)
def fund_prices_latest():
    """获取所有基金的最新 fund_prices 记录"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT fp.fund_code, f.name, fp.date, fp.nav, fp.estimate_nav, fp.change_pct
            FROM fund_prices fp
            JOIN funds f ON f.code = fp.fund_code
            WHERE fp.date = ?
            ORDER BY fp.fund_code
        """, (today,)).fetchall()
        return {"data": [dict(r) for r in rows], "total": len(rows), "date": today}
    finally:
        conn.close()


@app.post("/api/market/refresh-prices", response_model=dict)
def market_refresh_prices():
    """手动触发基金价格刷新（测试用，等效于 14:30 调度器）"""
    conn = get_connection()
    try:
        funds = conn.execute("SELECT id, code, name FROM funds").fetchall()
        codes = [f["code"] for f in funds]
        if not codes:
            return {"status": "error", "message": "无基金数据"}
        from market_data_fetcher import batch_fetch_funds_realtime
        quotes = batch_fetch_funds_realtime(codes)
        today = datetime.now().strftime("%Y-%m-%d")
        updated = 0
        errors = []
        for q in quotes:
            if q.get("error") or not q.get("gsz"):
                errors.append(f"{q.get('code')}: {q.get('error', '无估值数据')}")
                continue
            code = q["code"]
            gsz = float(q["gsz"])
            dwjz = float(q["dwjz"]) if q.get("dwjz") else None
            gszzl = q.get("gszzl")
            change_pct = float(gszzl) if gszzl else None
            conn.execute(
                "UPDATE funds SET current_price = ?, update_time = datetime('now','localtime') WHERE code = ?",
                (gsz, code),
            )
            conn.execute("""
                INSERT OR REPLACE INTO fund_prices (fund_code, date, nav, estimate_nav, change_pct, source)
                VALUES (?, ?, ?, ?, ?, 'realtime')
            """, (code, today, dwjz or gsz, gsz, change_pct))
            updated += 1
        conn.commit()
        return {
            "status": "ok",
            "updated": updated,
            "total": len(codes),
            "errors": errors,
            "date": today,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════
#  NEWS / SENTIMENT — 新闻舆情 & 持仓匹配
# ══════════════════════════════════════════════════════════════════════════

@app.get("/api/news/latest", response_model=dict)
def news_latest():
    """聚合多源最新新闻快讯"""
    return fetch_all_news()


@app.get("/api/news/portfolio", response_model=dict)
def news_portfolio():
    """持仓舆情 — 新闻匹配持仓关键词，标记利好利空"""
    return get_portfolio_news()


@app.get("/api/news/sectors", response_model=dict)
def news_sectors():
    """获取行业板块分级列表"""
    from news_engine import SECTOR_DEFINITIONS, SECTOR_PARENTS
    return {"sectors": SECTOR_DEFINITIONS, "parents": SECTOR_PARENTS}


@app.get("/api/news/holdings-keywords", response_model=dict)
def news_holdings_keywords():
    """当前持仓基金的关键词库（重仓股+赛道）"""
    from news_engine import build_holdings_keywords
    return build_holdings_keywords()


# ══════════════════════════════════════════════════════════════════════════
#  PORTFOLIO RESET
# ══════════════════════════════════════════════════════════════════════════

@app.post("/api/portfolio/reset", response_model=MessageResponse)
def reset_portfolio():
    """Delete all data and re-seed."""
    try:
        conn = get_connection()
        conn.execute("PRAGMA journal_mode=DELETE")
        for table in ("daily_values", "trades", "trade_signals", "strategies", "funds"):
            conn.execute(f"DELETE FROM {table}")
        # Reset autoincrement counters
        conn.execute("DELETE FROM sqlite_sequence")
        conn.commit()
    finally:
        conn.close()

    # Re-seed using its own connection
    seed_database()
    return {"message": "模拟数据已重置"}


# ══════════════════════════════════════════════════════════════════
#  AGENT ENDPOINTS — 多 Agent 决策系统
# ══════════════════════════════════════════════════════════════════

@app.get("/api/agents/scan", response_model=dict)
def agents_scan():
    """
    全量 Agent 扫描：
    1. Market Intelligence Agent（新闻分析）
    2. Trend Agent（趋势跟踪）
    3. Grid Agent（网格增强）
    4. Signal Merge Engine（融合决策）
    5. 自动生成买卖信号

    返回每只基金的融合决策结果。
    """
    from decision_orchestrator import scan_all
    try:
        results = scan_all()
        return {
            "data": results,
            "total": len(results),
            "timestamp": datetime.now().isoformat(),
            "status": "ok",
        }
    except Exception as e:
        raise HTTPException(500, f"Agent扫描失败: {str(e)}")


@app.get("/api/agents/fund/{fund_id}", response_model=dict)
def agents_scan_fund(fund_id: int):
    """
    单只基金 Agent 决策：
    运行 Market + Trend + Grid + Merge，返回该基金的融合决策详情。

    包含：
      - 各 Agent 独立信号
      - 融合决策结果
      - 推理链
    """
    from decision_orchestrator import process_fund, _get_all_funds, _get_time_status
    try:
        time_status = _get_time_status()
        from agent_market import run as run_market

        conn = get_connection()
        fund = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
        conn.close()
        if not fund:
            raise HTTPException(404, "基金不存在")

        fund_dict = dict(fund)
        market_results = run_market(
            fund_id=fund_id,
            fund_code=fund_dict["code"],
            fund_name=fund_dict["name"],
        )

        decision = process_fund(fund=fund_dict, time_status=time_status, market_results=market_results)

        return {
            "fund": {
                "id": fund_dict["id"],
                "code": fund_dict["code"],
                "name": fund_dict["name"],
                "currentPrice": fund_dict["current_price"],
            },
            "decision": decision.to_dict(),
            "timestamp": datetime.now().isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Agent分析失败: {str(e)}")


@app.get("/api/agents/market-news", response_model=dict)
def agents_market_news():
    """
    运行 Market Intelligence Agent，返回最新的新闻分析结果。
    不涉及策略决策，仅展示市场情报。
    """
    from agent_market import scan_all_news
    try:
        results = scan_all_news()
        return {
            "data": results,
            "total": len(results),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(500, f"Market分析失败: {str(e)}")


# ══════════════════════════════════════════════════════════════════
#  AI CHAT — 前台对话接口（圆宝）
# ══════════════════════════════════════════════════════════════════

from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"

class ChatHistoryRequest(BaseModel):
    session_id: str = "default"
    limit: int = 50
    offset: int = 0

@app.post("/api/chat", response_model=dict)
def ai_chat(body: ChatRequest):
    """
    圆宝聊天接口 — 自动持久化对话历史

    前端调用:
        POST /api/chat  { "message": "...", "session_id": "default" }
    返回:
        { "reply": "...", "status": "ok", "session_id": "default" }
    """
    from llm_service import chat, MODELS
    from chat_history import save_user_message, save_assistant_message, get_llm_context
    from rag_engine import SimpleRAGEngine

    try:
        session_id = body.session_id or "default"

        # 1. 保存用户消息
        save_user_message(session_id, body.message)

        # 2. 加载历史上下文
        history = get_llm_context(session_id)

        # 3. RAG 检索知识库
        rag_context = SimpleRAGEngine.get_chat_context(body.message)

        # 4. 构建 system prompt（带 RAG 上下文）
        system_prompt = """你是一个专业的量化交易 AI 助手，名叫"圆宝"（一只可爱的小博美犬在守护这个交易系统）。

你可以帮助用户：
1. 🐾 分析账户持仓和收益状况
2. 🤖 解释交易策略逻辑（趋势跟踪/网格增强）
3. 📈 提供市场分析观点（注意：不构成投资建议）
4. ❓ 回答关于基金、交易时间、费率等知识问题

请注意：
- 你背后连接的是一个 Python 量化交易系统，有趋势策略和网格策略在运行
- 数据会被 Agent 系统定期扫描和分析
- 你的名字叫圆宝，回答时可以用"圆宝"自称，温暖而专业
- 如果用户问持仓数据，引导用户在页面上查看，因为你看不到实时持仓
- 回答要简洁、专业、数据驱动，可以使用 **粗体** 强调重点
- 你的回答结合自身知识 + 下方提供的知识库内容，如果知识库提供了相关信息，优先参考它

""" + (rag_context if rag_context else "")

        reply = chat(
            messages=history,
            model=MODELS.get("chat", "qwen/qwen3.5-397b-a17b"),
            system_prompt=system_prompt,
            temperature=0.3,
            timeout=30,
        )

        if not reply:
            return {"reply": "圆宝暂时开小差了，请稍后再试 🐾", "status": "error", "session_id": session_id}

        # 4. 保存回复
        save_assistant_message(session_id, reply)

        return {"reply": reply, "status": "ok", "session_id": session_id}

    except Exception as e:
        logger = __import__("logging").getLogger("ai_chat")
        logger.warning(f"圆宝 chat error: {e}")
        return {"reply": "圆宝遇到了一点问题，请稍后再试 🐾", "status": "error", "session_id": body.session_id}


@app.get("/api/chat/history", response_model=dict)
def chat_history(session_id: str = "default", limit: int = 50, offset: int = 0):
    """
    获取历史对话记录
    前端首次加载时调用，恢复对话上下文

    返回:
        { "messages": [...], "total": N, "session_id": "default" }
    """
    from chat_history import get_history, count_messages
    messages = get_history(session_id, limit=limit, offset=offset)
    total = count_messages(session_id)
    return {"messages": messages, "total": total, "session_id": session_id}


@app.delete("/api/chat/history", response_model=dict)
def chat_history_clear(session_id: str = "default"):
    """清空历史对话"""
    from chat_history import clear_history
    clear_history(session_id)
    return {"message": "已清空", "session_id": session_id}


@app.post("/api/chat/session/delete")
def chat_session_delete(body: dict):
    """删除一个 session"""
    session_id = body.get("session_id", "")
    if not session_id:
        raise HTTPException(400, "session_id 不能为空")
    if session_id == "default":
        raise HTTPException(400, "默认 session 不能删除")
    from chat_history import delete_session
    delete_session(session_id)
    return {"message": "已删除", "session_id": session_id}


@app.get("/api/chat/sessions", response_model=dict)
def chat_sessions():
    """列出所有 session"""
    from chat_history import list_sessions
    sessions = list_sessions()
    return {"sessions": sessions, "total": len(sessions)}


# ── Backtest Endpoints ───────────────────────────────────────────

BACKTEST_CACHE: Dict[str, dict] = {}


@app.get("/api/backtest/funds", response_model=dict)
def backtest_funds():
    """获取可用于回测的基金列表（有历史净值数据的）
    返回：每个基金附带 DB 中的 daily_values 起止日期
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT f.id, f.code, f.name, f.current_price,
               MIN(dv.date) AS data_start, MAX(dv.date) AS data_end,
               COUNT(dv.id) AS data_points
        FROM funds f
        LEFT JOIN daily_values dv ON dv.fund_id = f.id
        GROUP BY f.id
        ORDER BY f.name
    """).fetchall()
    conn.close()

    funds = []
    for r in rows:
        funds.append({
            "id": r["id"],
            "code": r["code"],
            "name": r["name"],
            "currentPrice": r["current_price"],
            "dataStart": r["data_start"],
            "dataEnd": r["data_end"],
            "dataPoints": r["data_points"],
        })
    return {"funds": funds, "total": len(funds)}


@app.post("/api/backtest/run", response_model=dict)
def backtest_run(body: dict):
    """运行回测

    请求:
    {
        "fundCode": "110011",
        "fundName": "易方达中小盘混合",
        "strategyType": "ma",         # "ma" | "grid"
        "strategyParams": {"period": 20, "upper": 105, "lower": 95},
        "initialCash": 100000,
        "startDate": "",              # 空=自动
        "endDate": "",
        "buyFeeRate": 0.0015,
        "maxPositionPct": 0.95,
        "maxDrawdownPct": 0.25,
    }
    """
    from backtest_engine import BacktestEngine, BacktestConfig

    try:
        config = BacktestConfig(
            fund_code=body.get("fundCode", ""),
            fund_name=body.get("fundName", ""),
            strategy_type=body.get("strategyType", "ma"),
            strategy_params=body.get("strategyParams", {}),
            initial_cash=float(body.get("initialCash", 100000)),
            start_date=body.get("startDate", ""),
            end_date=body.get("endDate", ""),
            buy_fee_rate=float(body.get("buyFeeRate", 0.0015)),
            max_position_pct=float(body.get("maxPositionPct", 0.95)),
            max_drawdown_pct=float(body.get("maxDrawdownPct", 0.25)),
        )

        if not config.fund_code:
            raise HTTPException(400, "fundCode 不能为空")

        engine = BacktestEngine(config)
        result = engine.run()

        if result.error:
            return {"status": "error", "message": result.error}

        # 序列化结果
        response = {
            "status": "ok",
            "config": {
                "fundCode": config.fund_code,
                "fundName": config.fund_name,
                "strategyType": config.strategy_type,
                "strategyParams": config.strategy_params,
                "initialCash": config.initial_cash,
                "buyFeeRate": config.buy_fee_rate,
                "maxPositionPct": config.max_position_pct,
                "maxDrawdownPct": config.max_drawdown_pct,
            },
            "equityCurve": [
                {"date": ep.date, "totalValue": ep.total_value,
                 "cash": ep.cash, "shares": ep.shares, "price": ep.price,
                 "action": ep.action}
                for ep in result.equity_curve
            ],
            "trades": [
                {"date": t.date, "action": t.action, "price": t.price,
                 "shares": t.shares, "amount": round(t.amount, 2),
                 "fee": round(t.fee, 2), "reason": t.reason}
                for t in result.trades
            ],
            "metrics": result.metrics,
        }

        # 持久化到 DB
        try:
            conn = get_connection()
            # 获取基准指数同期收益率
            benchmark_return = None
            try:
                from benchmark_engine import get_benchmark_history
                bench = get_benchmark_history("000300", 730)
                if bench.get("data") and config.start_date:
                    # 找起止日期对应的指数收盘价
                    first_idx, last_idx = None, None
                    for d in bench["data"]:
                        if d["date"] == config.start_date:
                            first_idx = d["close"]
                        if d["date"] == config.end_date:
                            last_idx = d["close"]
                    if first_idx and last_idx and first_idx > 0:
                        benchmark_return = round((last_idx - first_idx) / first_idx, 4)
            except Exception:
                pass

            metrics = result.metrics
            conn.execute("""
                INSERT INTO backtest_results
                    (fund_code, fund_name, strategy_type, strategy_params,
                     initial_cash, start_date, end_date,
                     total_return, annual_return, max_drawdown_pct,
                     sharpe_ratio, sortino_ratio, calmar_ratio,
                     win_rate, total_trades, final_value, total_profit,
                     benchmark_code, benchmark_return)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                config.fund_code, config.fund_name, config.strategy_type,
                json.dumps(config.strategy_params),
                config.initial_cash, config.start_date or result.metrics.get("start_date"),
                config.end_date or result.metrics.get("end_date"),
                metrics.get("total_return"), metrics.get("annual_return"),
                metrics.get("max_drawdown_pct"),
                metrics.get("sharpe_ratio"), metrics.get("sortino_ratio"),
                metrics.get("calmar_ratio"),
                metrics.get("win_rate"), metrics.get("total_trades"),
                metrics.get("final_value"), metrics.get("total_profit"),
                "000300", benchmark_return,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("[Backtest] 持久化失败: {}", e)

        # 缓存（按 fundCode + strategyType）
        cache_key = f"{config.fund_code}_{config.strategy_type}"
        BACKTEST_CACHE[cache_key] = response

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Backtest] 运行异常: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/backtest/results", response_model=dict)
def backtest_results(limit: int = Query(20, le=100)):
    """获取历史回测结果（从 DB 读取）"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM backtest_results
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    results = []
    for r in rows:
        row = dict(r)
        # 反序列化 strategy_params
        if isinstance(row.get("strategy_params"), str):
            try:
                row["strategy_params"] = json.loads(row["strategy_params"])
            except (json.JSONDecodeError, TypeError):
                row["strategy_params"] = {}
        results.append(row)

    return {"results": results, "total": len(results)}


@app.post("/api/backtest/deploy", response_model=dict)
def backtest_deploy(body: dict):
    """将回测结果部署到新的模拟账户

    请求:
    {
        "backtestResultId": 123,    # backtest_results 的 ID，二选一
        "fundCode": "110011",       # 或直接传策略参数
        "strategyType": "ma",
        "strategyParams": {"period": 20, "upper": 105, "lower": 95},
        "initialCash": 100000,      # 模拟盘初始资金
        "name": "MA20 回测部署",     # 账户名（可选，自动生成）
    }

    响应:
    {
        "status": "ok",
        "accountId": 4,
        "accountName": "MA20 回测部署",
    }
    """
    from sim_engine import list_accounts

    try:
        # 1. 解析参数
        result_id = body.get("backtestResultId")
        fund_code = body.get("fundCode", "")
        strategy_type = body.get("strategyType", "ma")
        strategy_params = body.get("strategyParams", {})
        initial_cash = float(body.get("initialCash", 100000))
        custom_name = body.get("name", "")

        # 如果提供了 backtestResultId，从 DB 读取
        if result_id:
            conn = get_connection()
            row = conn.execute(
                "SELECT * FROM backtest_results WHERE id = ?", (result_id,)
            ).fetchone()
            conn.close()
            if not row:
                raise HTTPException(404, "回测结果不存在")
            fund_code = row["fund_code"]
            strategy_type = row["strategy_type"]
            if isinstance(row["strategy_params"], str):
                try:
                    strategy_params = json.loads(row["strategy_params"])
                except (json.JSONDecodeError, TypeError):
                    strategy_params = {}
            if not custom_name:
                custom_name = f"回测·{row.get('fund_name','')[:8]} {strategy_type.upper()}"
            if not initial_cash or initial_cash <= 0:
                initial_cash = row["initial_cash"]
        else:
            if not fund_code:
                raise HTTPException(400, "fundCode 或 backtestResultId 必填一个")
            if not custom_name:
                custom_name = f"回测·{fund_code} {strategy_type.upper()}"

        # 2. 查重：同名账户不重复创建
        existing_accounts = list_accounts()
        for acct in existing_accounts:
            if acct.get("name") == custom_name:
                return {"status": "ok", "accountId": acct["id"], "accountName": custom_name, "message": "账户已存在"}

        # 3. 构建策略配置
        strategy_config = {
            "trend": {"enabled": strategy_type == "ma"},
            "grid": {"enabled": strategy_type == "grid"},
            "market": {"enabled": False},
            "risk": {"max_position_pct": body.get("maxPositionPct", 0.30), "max_drawdown_pct": body.get("maxDrawdownPct", 0.20)},
        }
        if strategy_type == "ma":
            strategy_config["trend"]["period"] = strategy_params.get("period", 20)
            strategy_config["trend"]["upper"] = strategy_params.get("upper", 105)
            strategy_config["trend"]["lower"] = strategy_params.get("lower", 95)
        elif strategy_type == "grid":
            strategy_config["grid"]["stepCount"] = strategy_params.get("stepCount", 5)
            strategy_config["grid"]["stepSize"] = strategy_params.get("stepSize", 0.10)

        # 4. 创建账户
        now = datetime.now().isoformat()
        conn = get_connection()
        conn.execute("""
            INSERT INTO sim_accounts (name, initial_cash, cash, strategy_config, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            custom_name,
            initial_cash, initial_cash,
            json.dumps(strategy_config, ensure_ascii=False),
            now, now,
        ))
        conn.commit()
        account_id = conn.execute("SELECT last_insert_rowid() as rid").fetchone()["rid"]
        conn.close()

        logger.info("[Backtest] 部署回测到模拟盘: account_id={} name={}", account_id, custom_name)

        return {
            "status": "ok",
            "accountId": account_id,
            "accountName": custom_name,
            "strategyConfig": strategy_config,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[Backtest] 部署失败: {}", e)
        return {"status": "error", "message": str(e)}


# ══════════════════════════════════════════════════════════════════
#  RISK ENGINE — 风控系统 API
# ══════════════════════════════════════════════════════════════════

from risk_engine import RiskEngine, load_risk_config, save_risk_config

# 全局风控实例
_risk_engine_instance: Optional[RiskEngine] = None

def _get_risk_engine_instance() -> RiskEngine:
    global _risk_engine_instance
    if _risk_engine_instance is None:
        cfg = load_risk_config()
        _risk_engine_instance = RiskEngine(cfg.__dict__)
    return _risk_engine_instance


@app.get("/api/risk/config", response_model=dict)
def risk_get_config():
    """获取风控系统当前配置"""
    cfg = load_risk_config()
    # 把 dataclass 的 field 转为可序列化格式
    result = {}
    for k, v in cfg.__dict__.items():
        if isinstance(v, list):
            result[k] = v
        else:
            result[k] = v
    return result


@app.post("/api/risk/config", response_model=dict)
def risk_update_config(body: dict):
    """更新风控配置

    请求：部分或全部 RiskConfig 字段
    {
        "single_trade_cap_pct": 0.05,
        "stop_loss_fixed_pct": 0.08,
        ...
    }
    """
    try:
        cfg = load_risk_config()
        for k, v in body.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        save_risk_config(cfg)
        # 重置全局实例
        global _risk_engine_instance
        _risk_engine_instance = RiskEngine(cfg.__dict__)
        return {"status": "ok", "message": "风控配置已更新"}
    except Exception as e:
        raise HTTPException(500, f"更新风控配置失败: {str(e)}")


@app.post("/api/risk/check", response_model=dict)
def risk_check(body: dict):
    """对指定基金运行风控检查

    请求:
    {
        "fundCode": "110011",
        "decisionScore": 72,
        "decisionSignal": "BUY"
    }

    返回: RiskVerdict
    """
    fund_code = body.get("fundCode", "")
    if not fund_code:
        raise HTTPException(400, "fundCode 不能为空")

    try:
        from decision_orchestrator import _get_price_history

        conn = get_connection()
        fund = conn.execute(
            "SELECT * FROM funds WHERE code = ?", (fund_code,)
        ).fetchone()
        if not fund:
            raise HTTPException(404, f"基金 {fund_code} 不存在")

        fund_dict = dict(fund)
        prices = _get_price_history(fund_code)

        # 获取 daily_values
        dv_rows = conn.execute("""
            SELECT date, total_value, fund_id FROM daily_values
            WHERE fund_id = ? ORDER BY date
        """, (fund_dict["id"],)).fetchall()
        conn.close()

        # 获取情绪分 — 从 Agent Market 缓存读取，不触发网络/LLM
        sentiment = 50.0
        try:
            from agent_market import _run_cache
            if _run_cache and (datetime.now() - _run_cache[1]).total_seconds() < 600:
                for r in _run_cache[0]:
                    if fund_code in r.get("affected_funds", []):
                        sentiment = r.get("score", 50)
                        break
        except Exception:
            pass

        # 获取持仓天数
        hold_days = 0
        try:
            conn2 = get_connection()
            last_buy = conn2.execute(
                "SELECT time FROM trades WHERE fund_id = ? AND direction = 'buy' AND status = 'executed' ORDER BY time DESC LIMIT 1",
                (fund_dict["id"],),
            ).fetchone()
            conn2.close()
            if last_buy:
                from datetime import datetime as dt
                buy_time = dt.fromisoformat(last_buy["time"])
                hold_days = (dt.now() - buy_time).days
        except Exception:
            pass

        # 获取所有基金
        from decision_orchestrator import _get_all_funds
        all_funds = _get_all_funds()

        engine = _get_risk_engine_instance()
        verdict = engine.check(
            fund=fund_dict,
            decision_score=float(body.get("decisionScore", 50)),
            decision_signal=body.get("decisionSignal", "HOLD"),
            context={
                "prices": prices,
                "daily_values": [dict(r) for r in dv_rows],
                "sentiment_score": sentiment,
                "all_funds": all_funds,
                "hold_days": hold_days,
                "is_open": body.get("decisionSignal", "").upper()
                          in ("STRONG_BUY", "BUY", "LIGHTEN_BUY", "INCREASE", "ENABLE_GRID"),
            },
        )

        return verdict.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"风控检查失败: {str(e)}")


# ══════════════════════════════════════════════════════════════════
#  SIMULATION ENGINE — 模拟盘 API
# ══════════════════════════════════════════════════════════════════

from sim_engine import (
    list_accounts, get_account, get_positions, get_trades,
    execute_for_all_accounts, get_daily_values,
    update_account_config, record_daily_snapshot_now,
)


@app.get("/api/sim/accounts", response_model=dict)
def sim_accounts():
    """获取所有模拟账户"""
    accounts = list_accounts()
    return {"accounts": accounts, "total": len(accounts)}


@app.get("/api/sim/accounts/{account_id}", response_model=dict)
def sim_account_detail(account_id: int):
    """获取单个模拟账户详情（含持仓、交易、净值曲线）"""
    acct = get_account(account_id)
    if not acct:
        raise HTTPException(404, "账户不存在")
    positions = get_positions(account_id)
    trades = get_trades(account_id, 20)
    daily_values = get_daily_values(account_id)
    return {
        "account": acct,
        "positions": positions,
        "trades": trades,
        "dailyValues": daily_values,
    }


@app.post("/api/sim/execute", response_model=dict)
def sim_execute():
    """运行 Agent 扫描并将信号应用到所有模拟账户"""
    try:
        results = execute_for_all_accounts()
        return {
            "status": "ok",
            "results": results,
            "total": len(results),
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        raise HTTPException(500, f"模拟盘执行失败: {str(e)}")


@app.get("/api/sim/trades/{account_id}", response_model=dict)
def sim_trades_list(account_id: int, limit: int = 50):
    """获取账户交易记录"""
    trades = get_trades(account_id, limit)
    return {"trades": trades, "total": len(trades)}


@app.get("/api/sim/equity", response_model=dict)
def sim_equity():
    """获取所有模拟账户的净值曲线（归一化到初始 100）"""
    accounts = list_accounts()
    result = []
    for acct in accounts:
        dv = get_daily_values(acct["id"])
        base = acct.get("initialCash", 1000) or 1000
        normalized = []
        for row in dv:
            normalized.append({
                "date": row["date"],
                "nav": round(row["total_value"] / base * 100, 4),
                "totalValue": row["total_value"],
            })
        result.append({
            "accountId": acct["id"],
            "accountName": acct["name"],
            "initialCash": acct["initialCash"],
            "equity": normalized,
        })

    # 附加基准指数（沪深300用于对比）
    benchmark_data = None
    try:
        from benchmark_engine import get_benchmark_history
        bench = get_benchmark_history("000300", 730)
        benchmark_data = bench
    except Exception:
        pass

    return {"accounts": result, "total": len(result), "benchmark": benchmark_data}


@app.post("/api/sim/accounts/{account_id}/config", response_model=dict)
def sim_update_config(account_id: int, body: dict):
    """更新模拟账户策略配置"""
    config = body.get("config", {})
    if not config:
        raise HTTPException(400, "config 不能为空")
    ok = update_account_config(account_id, config)
    if not ok:
        raise HTTPException(500, "更新配置失败")
    return {"status": "ok", "message": "策略配置已更新"}


@app.post("/api/sim/snapshot", response_model=dict)
def sim_snapshot():
    """手动记录当日净值快照"""
    record_daily_snapshot_now()
    return {"status": "ok", "message": "净值快照已记录"}


# ── 模拟盘分析 API ─────────────────────────────────────────────

@app.get("/api/sim/runs", response_model=dict)
def sim_analysis_runs(account_id: int = 0, limit: int = 50):
    """获取模拟执行记录（输入快照 + 决策 + 结果）"""
    from sim_analytics import get_simulation_runs
    aid = account_id if account_id > 0 else None
    runs = get_simulation_runs(aid, limit)
    return {"runs": runs, "total": len(runs)}


@app.get("/api/sim/attribution", response_model=dict)
def sim_analysis_attribution(account_id: int = 0, days: int = 30):
    """获取收益归因（按 Agent 维度）"""
    from sim_analytics import get_attribution_summary
    aid = account_id if account_id > 0 else None
    if not aid:
        return {"error": "account_id required", "data": []}
    data = get_attribution_summary(aid, days)
    return {"data": data, "total": len(data)}


@app.get("/api/sim/attribution/detail", response_model=dict)
def sim_analysis_attribution_detail(account_id: int = 0, days: int = 30):
    """获取归因详情（每日每条记录）"""
    from sim_analytics import get_attribution
    aid = account_id if account_id > 0 else None
    data = get_attribution(aid, days)
    return {"data": data, "total": len(data)}


@app.get("/api/sim/metrics", response_model=dict)
def sim_analysis_metrics(account_id: int):
    """获取账户绩效指标，基于 daily_values 计算"""
    from sim_analytics import calc_performance_metrics
    dv = get_daily_values(account_id)
    if not dv or len(dv) < 2:
        return {"error": "数据不足"}
    metrics = calc_performance_metrics(dv)
    return {"account_id": account_id, "metrics": metrics}


# ══════════════════════════════════════════════════════════════════
#  AI DAILY REVIEW — 每日复盘 API
# ══════════════════════════════════════════════════════════════════

@app.get("/api/reports", response_model=dict)
def reports_list(limit: int = Query(10, le=50)):
    """获取最近复盘报告列表"""
    from daily_review_agent import get_recent_reports
    reports = get_recent_reports(limit)
    return {"reports": reports, "total": len(reports)}


@app.get("/api/reports/{report_id}", response_model=dict)
def reports_detail(report_id: int):
    """获取完整复盘报告内容"""
    from daily_review_agent import get_report
    report = get_report(report_id)
    if not report:
        raise HTTPException(404, "报告不存在")
    return report


@app.post("/api/reports/generate", response_model=dict)
def reports_generate():
    """手动触发当日复盘报告生成（用于调试/补生成）"""
    from daily_review_agent import generate_daily_review
    result = generate_daily_review()
    if result:
        return {"status": "ok", "reportId": result.get("id"), "date": result.get("date")}
    return {"status": "skipped", "message": "今日报告已存在或数据不足"}


@app.get("/api/health", response_model=dict)
def health_check():
    """系统健康检查"""
    status = "ok"
    checks = {}

    # 1. Database
    try:
        conn = get_connection()
        tables_info = {}
        for t in ["funds", "sim_accounts", "simulation_runs", "daily_benchmark",
                   "backtest_results", "daily_reports"]:
            row = conn.execute(f"SELECT COUNT(*) as cnt FROM {t}").fetchone()
            tables_info[t] = row["cnt"] if row else 0
        conn.close()
        checks["database"] = {"status": "ok", "tables": tables_info}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}
        status = "degraded"

    # 2. Market data source
    try:
        from market_data_fetcher import fetch_fund_realtime
        resp = fetch_fund_realtime("110011")
        if resp and resp.get("error") is None:
            checks["market_data"] = {"status": "ok", "sample": f"{resp.get('name','')} ¥{resp.get('price',0)}"}
        else:
            checks["market_data"] = {"status": "warning", "detail": resp.get("error", "无响应") if resp else "无响应"}
            status = "degraded"
    except Exception as e:
        checks["market_data"] = {"status": "error", "detail": str(e)}
        status = "degraded"

    # 3. Benchmark data
    try:
        conn = get_connection()
        bench_row = conn.execute(
            "SELECT MAX(date) as last_date, COUNT(*) as cnt FROM daily_benchmark WHERE index_code='000300'"
        ).fetchone()
        conn.close()
        if bench_row and bench_row["cnt"] > 0:
            checks["benchmark"] = {"status": "ok", "last_date": bench_row["last_date"], "count": bench_row["cnt"]}
        else:
            checks["benchmark"] = {"status": "warning", "detail": "基准指数数据为空"}
            status = "degraded"
    except Exception as e:
        checks["benchmark"] = {"status": "error", "detail": str(e)}
        status = "degraded"

    # 4. Scheduler
    try:
        if scheduler is None:
            checks["scheduler"] = {"status": "warning", "detail": "调度器未初始化"}
        else:
            scheduler_jobs = scheduler.get_jobs()
            checks["scheduler"] = {
                "status": "ok",
                "jobs": [
                    {"id": j.id, "name": j.name, "next_run": str(j.next_run_time)}
                    for j in scheduler_jobs
                ],
            }
    except Exception as e:
        checks["scheduler"] = {"status": "warning", "detail": str(e)}

    return {"status": status, "timestamp": datetime.now().isoformat(), "checks": checks}


# ── Entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=3000, reload=True)
