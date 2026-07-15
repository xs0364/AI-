"""
模拟盘执行引擎
===============
职责：基于 Agent 融合决策，按各账户策略配置 + 现金/仓位独立执行买卖

流程：
  1. scan_all() 先运行 Agent 全量扫描
  2. 每个模拟账户读取自己的 strategy_config → 筛选适用的决策
  3. 按 MergedDecision + RiskVerdict 计算可执行数量
  4. 写入 sim_trades + 更新 sim_positions + cash
  5. 记录每日净值快照至 sim_daily_values

设计原则：
  - Agent 分析跑一次，各账户按各自策略配置筛选信号
  - 不重复调 API，不查 daily_values
  - 风控按账户配置的阈值算
"""
import json
from datetime import datetime, date
from typing import List, Optional

from loguru import logger

from database import get_connection


# ══════════════════════════════════════════════════════════════════
# 策略配置解析
# ══════════════════════════════════════════════════════════════════

def parse_strategy_config(config_json: str) -> dict:
    """解析账户的 strategy_config JSON → dict"""
    if not config_json:
        return {}
    try:
        return json.loads(config_json) if isinstance(config_json, str) else config_json
    except json.JSONDecodeError:
        return {}


def should_act_on_signal(decision: dict, config: dict) -> bool:
    """
    根据账户的策略配置判断是否响应某个信号。

    Agent 信号映射：
      - trend 信号: 来自 agent_trend → 走 trend 策略
      - grid 信号: 来自 agent_grid → 走 grid 策略
      - market 信号: 来自 agent_market → 走 market 策略
      - 融合信号: 综合判断
    """
    signal = decision.get("signal", "HOLD")
    contributions = decision.get("agents_contributions", [])

    # 检查是否有任何 Agent 给出了交易信号
    has_trend_signal = any(
        c.get("agent") == "trend" and c.get("signal") not in ("HOLD", "NEUTRAL")
        for c in contributions
    )
    has_grid_signal = any(
        c.get("agent") == "grid" and c.get("signal") not in ("HOLD", "NEUTRAL")
        for c in contributions
    )

    trend_cfg = config.get("trend", {})
    grid_cfg = config.get("grid", {})
    market_cfg = config.get("market", {})

    # 强信号（清仓/止损）直接执行，不受配置限制
    if signal in ("STOP_LOSS", "STRONG_SELL", "STRONG_BUY"):
        return True

    # 趋势信号 → 账户开启了 trend 才响应
    if has_trend_signal and not trend_cfg.get("enabled", False):
        return False

    # 网格信号 → 账户开启了 grid 才响应
    if has_grid_signal and not grid_cfg.get("enabled", False):
        return False

    # HOLD 不执行交易
    if signal == "HOLD":
        return False

    return True


# ══════════════════════════════════════════════════════════════════
# 账户管理
# ══════════════════════════════════════════════════════════════════

def list_accounts() -> List[dict]:
    """列出所有模拟账户及其资产概况"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT a.*,
            COALESCE(SUM(p.shares * f.current_price), 0) AS position_value,
            COUNT(DISTINCT p.fund_code) AS holding_count
        FROM sim_accounts a
        LEFT JOIN sim_positions p ON p.account_id = a.id
        LEFT JOIN funds f ON f.code = p.fund_code
        GROUP BY a.id
        ORDER BY a.id
    """).fetchall()
    conn.close()
    return [_acct_row(r) for r in rows]


def get_account(account_id: int) -> Optional[dict]:
    """获取单个账户详情"""
    conn = get_connection()
    row = conn.execute("""
        SELECT a.*,
            COALESCE(SUM(p.shares * f.current_price), 0) AS position_value,
            COUNT(DISTINCT p.fund_code) AS holding_count
        FROM sim_accounts a
        LEFT JOIN sim_positions p ON p.account_id = a.id
        LEFT JOIN funds f ON f.code = p.fund_code
        WHERE a.id = ?
        GROUP BY a.id
    """, (account_id,)).fetchone()
    conn.close()
    return _acct_row(row) if row else None


def get_positions(account_id: int) -> List[dict]:
    """获取账户持仓"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*, f.name AS fund_name, f.current_price
        FROM sim_positions p
        JOIN funds f ON f.code = p.fund_code
        WHERE p.account_id = ?
        ORDER BY p.shares * f.current_price DESC
    """, (account_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trades(account_id: int, limit: int = 50) -> List[dict]:
    """获取账户交易记录"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.*, f.name AS fund_name
        FROM sim_trades t
        JOIN funds f ON f.code = t.fund_code
        WHERE t.account_id = ?
        ORDER BY t.id DESC LIMIT ?
    """, (account_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_daily_values(account_id: int) -> List[dict]:
    """获取账户每日净值序列"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT date, total_value, cash, position_value
        FROM sim_daily_values
        WHERE account_id = ?
        ORDER BY date ASC
    """, (account_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _acct_row(r) -> dict:
    return {
        "id": r["id"],
        "name": r["name"],
        "initialCash": r["initial_cash"],
        "cash": r["cash"],
        "positionValue": round(r["position_value"], 2),
        "totalValue": round(r["cash"] + r["position_value"], 2),
        "holdingCount": r["holding_count"],
        "strategyConfig": parse_strategy_config(r["strategy_config"]),
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }


# ══════════════════════════════════════════════════════════════════
# 账户配置更新
# ══════════════════════════════════════════════════════════════════

def update_account_config(account_id: int, config: dict) -> bool:
    """更新账户策略配置"""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE sim_accounts SET strategy_config = ?, updated_at = ? WHERE id = ?",
            (json.dumps(config, ensure_ascii=False), datetime.now().isoformat(), account_id),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("[Sim] 更新配置失败: {}", e)
        return False
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════
# 核心：执行 Agent 信号到所有模拟账户
# ══════════════════════════════════════════════════════════════════

def execute_for_all_accounts() -> List[dict]:
    """
    运行 Agent 扫描 → 将信号应用到每个模拟账户

    Returns:
        [{ account_id, account_name, trades: [...], errors: [...] }, ...]
    """
    from decision_orchestrator import scan_all as agent_scan_all

    # 1. 跑一次 Agent 全量扫描
    agent_results = agent_scan_all()
    decisions_by_code = {}
    for r in agent_results:
        decisions_by_code[r["fund_code"]] = r["decision"]

    if not decisions_by_code:
        logger.warning("[Sim] Agent 扫描无结果")
        return []

    # 1b. 提取全局输入快照（用于 simulation_runs 记录）
    from sim_analytics import extract_input_snapshot
    input_snapshot = extract_input_snapshot(decisions_by_code)
    today_str = date.today().isoformat()

    # 2. 获取所有模拟账户
    accounts = list_accounts()
    if not accounts:
        logger.warning("[Sim] 无模拟账户")
        return []

    # 3. 逐个账户执行
    results = []
    for acct in accounts:
        config = acct.get("strategyConfig", {})
        trades = []
        errors = []

        total_before = acct.get("totalValue", acct.get("cash", 0))
        contributions = []

        for fund_code, decision_dict in decisions_by_code.items():
            try:
                # 按策略配置筛选信号
                if not should_act_on_signal(decision_dict, config):
                    continue
                trade = _execute_one(acct["id"], fund_code, decision_dict, config)
                if trade:
                    trades.append(trade)
            except Exception as e:
                errors.append(f"{fund_code}: {e}")

        # 3b. 收集本次决策的 Agent 贡献
        for fund_code, decision_dict in decisions_by_code.items():
            for c in decision_dict.get("agents_contributions", []):
                existing = next(
                    (x for x in contributions if x["agent"] == c.get("agent")),
                    None,
                )
                if existing:
                    existing["score"] = (existing["score"] + c.get("score", 50)) / 2
                    existing["confidence"] = (existing["confidence"] + c.get("confidence", 50)) / 2
                    existing["weight"] = c.get("weight", 0.33)
                else:
                    contributions.append({
                        "agent": c.get("agent"),
                        "score": c.get("score", 50),
                        "confidence": c.get("confidence", 50),
                        "weight": c.get("weight", 0.33),
                    })

        # 3c. 计算执行后的总资产
        total_after = _calc_account_total(acct["id"])

        # 3d. 记录 simulation_run
        try:
            from sim_analytics import record_simulation_run, record_agent_attribution
            record_simulation_run(
                account_id=acct["id"],
                input_snapshot=input_snapshot,
                decision=next(iter(decisions_by_code.values()), {}),
                total_value_before=total_before,
                total_value_after=total_after,
                trades_count=len(trades),
                pnl=total_after - total_before,
            )
            # 归因
            if contributions:
                record_agent_attribution(
                    account_id=acct["id"],
                    dt_str=today_str,
                    contributions=contributions,
                    total_pnl=total_after - total_before,
                )
        except Exception as e:
            logger.warning("[Sim] 记录分析数据失败: {}", e)

        results.append({
            "account_id": acct["id"],
            "account_name": acct["name"],
            "trades": trades,
            "errors": errors,
        })

    # 4. 记录当日净值快照
    _record_daily_snapshots()

    return results


def _calc_account_total(account_id: int) -> float:
    """计算某账户当前总资产"""
    conn = get_connection()
    try:
        acct = conn.execute("SELECT cash FROM sim_accounts WHERE id = ?", (account_id,)).fetchone()
        if not acct:
            return 0
        pos = conn.execute("""
            SELECT COALESCE(SUM(p.shares * f.current_price), 0) AS pos_val
            FROM sim_positions p
            JOIN funds f ON f.code = p.fund_code
            WHERE p.account_id = ?
        """, (account_id,)).fetchone()
        return round(acct["cash"] + (pos["pos_val"] if pos else 0), 2)
    finally:
        conn.close()


def _execute_one(account_id: int, fund_code: str, decision_dict: dict,
                 config: dict) -> Optional[dict]:
    """
    对单个账户执行一条决策

    规则：
      - 买入：检查现金是否足够
      - 卖出：检查持仓是否足够
      - 受风控 verdict 和账户 risk 配置限制
    """
    conn = get_connection()

    acct = conn.execute("SELECT cash FROM sim_accounts WHERE id = ?", (account_id,)).fetchone()
    if not acct:
        conn.close()
        return None
    cash = acct["cash"]

    pos = conn.execute(
        "SELECT shares, cost_price FROM sim_positions WHERE account_id = ? AND fund_code = ?",
        (account_id, fund_code),
    ).fetchone()
    shares = pos["shares"] if pos else 0
    cost_price = pos["cost_price"] if pos else 0

    signal = decision_dict.get("signal", "HOLD")
    should_execute = decision_dict.get("should_execute", False)
    trade_qty = decision_dict.get("trade_quantity", 0)
    trade_price = decision_dict.get("trade_price", 0)

    # 风控裁决
    verdict = decision_dict.get("risk_verdict") or {}
    allow = verdict.get("allow", True)
    risk_max_pos = verdict.get("max_position", 1.0)

    # 账户自身 risk 配置覆盖
    risk_cfg = config.get("risk", {})
    acct_max_pos = risk_cfg.get("max_position_pct", risk_max_pos)
    # 取更保守的那个
    max_position = min(risk_max_pos, acct_max_pos)

    if not should_execute or not allow:
        conn.close()
        return None

    fund = conn.execute("SELECT current_price, name FROM funds WHERE code = ?", (fund_code,)).fetchone()
    if not fund:
        conn.close()
        return None
    current_price = trade_price or fund["current_price"]
    fund_name = fund["name"]

    buy_rate = 0.0015
    sell_rate = 0.005
    if cash < 5000:
        sell_rate = 0.015

    trade = None

    if signal in ("STRONG_BUY", "BUY", "LIGHTEN_BUY", "INCREASE"):
        price = current_price
        base_qty = max(1, int(trade_qty * max_position))
        max_can_buy = max(0, int((cash - 1) / (price * (1 + buy_rate))))
        buy_shares = min(base_qty, max_can_buy)

        if buy_shares >= 1:
            amount = round(price * buy_shares, 2)
            fee = round(amount * buy_rate, 2)
            total_cost = amount + fee

            if total_cost <= cash:
                new_cash = round(cash - total_cost, 2)
                conn.execute("UPDATE sim_accounts SET cash = ?, updated_at = ? WHERE id = ?",
                             (new_cash, datetime.now().isoformat(), account_id))

                if shares > 0:
                    total_shares = shares + buy_shares
                    total_cost_basis = shares * cost_price + amount + fee
                    new_cost = round(total_cost_basis / total_shares, 4)
                    conn.execute(
                        "UPDATE sim_positions SET shares = ?, cost_price = ? WHERE account_id = ? AND fund_code = ?",
                        (total_shares, new_cost, account_id, fund_code),
                    )
                else:
                    conn.execute(
                        "INSERT INTO sim_positions (account_id, fund_code, shares, cost_price) VALUES (?,?,?,?)",
                        (account_id, fund_code, buy_shares, round(price + fee / buy_shares, 4)),
                    )

                trade = _write_trade(conn, account_id, fund_code, "buy", price, buy_shares, fee,
                                     f"Agent:{signal} score:{decision_dict.get('score', 50)} pos:{max_position:.0%}")
        else:
            logger.debug("[Sim] 账户{} {} 现金不足: cash={}", account_id, fund_code, cash)

    elif signal in ("SELL", "STRONG_SELL", "LIGHTEN_SELL", "REDUCE", "STOP_LOSS"):
        if shares <= 0:
            conn.close()
            return None

        if signal in ("STRONG_SELL", "STOP_LOSS"):
            sell_shares = int(shares)
        else:
            sell_pct = 0.5 if signal in ("REDUCE",) else 0.3
            sell_shares = max(1, int(shares * sell_pct))

        price = current_price
        amount = round(price * sell_shares, 2)
        fee = round(amount * sell_rate, 2)
        net_proceeds = round(amount - fee, 2)

        new_cash = round(cash + net_proceeds, 2)
        conn.execute("UPDATE sim_accounts SET cash = ?, updated_at = ? WHERE id = ?",
                     (new_cash, datetime.now().isoformat(), account_id))

        remaining = round(shares - sell_shares, 2)
        if remaining <= 0:
            conn.execute("DELETE FROM sim_positions WHERE account_id = ? AND fund_code = ?",
                         (account_id, fund_code))
        else:
            conn.execute("UPDATE sim_positions SET shares = ? WHERE account_id = ? AND fund_code = ?",
                         (remaining, account_id, fund_code))

        trade = _write_trade(conn, account_id, fund_code, "sell", price, sell_shares, fee,
                             f"Agent:{signal} score:{decision_dict.get('score', 50)}")

    conn.commit()
    conn.close()
    return trade


def _write_trade(conn, account_id, fund_code, direction, price, shares, fee, reason=""):
    """写入交易记录"""
    amount = round(price * shares, 2)
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO sim_trades (account_id, fund_code, direction, price, shares, amount, fee, reason, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (account_id, fund_code, direction, price, shares, amount, fee, reason, now),
    )
    return {
        "account_id": account_id,
        "fund_code": fund_code,
        "direction": direction,
        "price": round(price, 4),
        "shares": round(shares, 2),
        "amount": round(amount, 2),
        "fee": round(fee, 2),
        "reason": reason,
        "created_at": now,
    }


# ══════════════════════════════════════════════════════════════════
# 每日净值快照
# ══════════════════════════════════════════════════════════════════

def _record_daily_snapshots():
    """
    记录所有账户的当日总资产到 sim_daily_values

    每日一次（不会重复写入同一天的数据）
    """
    conn = get_connection()
    try:
        today = date.today().isoformat()
        accounts = conn.execute(
            "SELECT id, cash FROM sim_accounts"
        ).fetchall()

        for acct in accounts:
            # 计算持仓市值
            positions = conn.execute("""
                SELECT p.shares, f.current_price
                FROM sim_positions p
                JOIN funds f ON f.code = p.fund_code
                WHERE p.account_id = ?
            """, (acct["id"],)).fetchall()

            pos_value = sum(p["shares"] * (p["current_price"] or 0) for p in positions)
            total_value = round(acct["cash"] + pos_value, 2)
            cash = round(acct["cash"], 2)
            pos_value = round(pos_value, 2)

            # INSERT OR IGNORE — 同天不重复写入
            conn.execute("""
                INSERT OR IGNORE INTO sim_daily_values
                    (account_id, date, total_value, cash, position_value)
                VALUES (?,?,?,?,?)
            """, (acct["id"], today, total_value, cash, pos_value))

        conn.commit()
    finally:
        conn.close()


def record_daily_snapshot_now():
    """供外部调用（APScheduler）—— 记录当日净值"""
    _record_daily_snapshots()
    logger.info("[Sim] 每日净值快照已记录")
