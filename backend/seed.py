"""
Seed data generator — populates the database with demo data on first run.
"""
import json
import random
from datetime import datetime, timedelta
from database import get_connection


def seed_database():
    """Insert demo data if the funds table is empty."""
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM funds").fetchone()[0]
        if count > 0:
            return

        now = datetime.now()

        # --- Funds ---
        sample_funds = [
            {"code": "110011", "name": "易方达中小盘混合", "shares": 5000, "cost_price": 1.85, "current_price": 2.12},
            {"code": "005827", "name": "中欧医疗健康混合C", "shares": 3000, "cost_price": 0.82, "current_price": 0.68},
            {"code": "001938", "name": "中欧时代先锋股票A", "shares": 4000, "cost_price": 1.22, "current_price": 1.35},
            {"code": "260108", "name": "景顺长城新兴成长混合", "shares": 2000, "cost_price": 2.05, "current_price": 1.96},
            {"code": "003095", "name": "中欧医疗健康混合A", "shares": 6000, "cost_price": 0.55, "current_price": 0.72},
        ]

        fund_ids = []
        for f in sample_funds:
            cur = conn.execute(
                "INSERT INTO funds (code, name, shares, cost_price, current_price, update_time) VALUES (?,?,?,?,?,?)",
                (f["code"], f["name"], f["shares"], f["cost_price"], f["current_price"], now.isoformat()),
            )
            fund_ids.append(cur.lastrowid)

        # --- Strategies ---
        strategies = [
            {"fund_id": fund_ids[0], "name": "均线趋势策略", "strategy_type": "ma",
             "params": json.dumps({"period": 20, "upper": 105, "lower": 95}), "enabled": 1},
            {"fund_id": fund_ids[2], "name": "网格交易策略", "strategy_type": "grid",
             "params": json.dumps({"upperPrice": 1.50, "lowerPrice": 1.00, "stepCount": 5, "stepSize": 0.10}),
             "enabled": 0},
            {"fund_id": fund_ids[4], "name": "均线网格混合", "strategy_type": "ma",
             "params": json.dumps({"period": 10, "upper": 103, "lower": 97}), "enabled": 1},
        ]

        strategy_ids = []
        for s in strategies:
            cur = conn.execute(
                "INSERT INTO strategies (fund_id, name, strategy_type, params, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (s["fund_id"], s["name"], s["strategy_type"], s["params"], s["enabled"], now.isoformat(), now.isoformat()),
            )
            strategy_ids.append(cur.lastrowid)

        # --- Trades ---
        trade_data = [
            {"fund_id": fund_ids[0], "direction": "buy", "price": 2.10, "shares": 200,
             "strategy": "均线趋势策略", "strategy_id": strategy_ids[0],
             "time": now - timedelta(hours=2)},
            {"fund_id": fund_ids[2], "direction": "sell", "price": 1.36, "shares": 300,
             "strategy": "均线趋势策略", "strategy_id": strategy_ids[0],
             "time": now - timedelta(hours=5)},
            {"fund_id": fund_ids[4], "direction": "buy", "price": 0.71, "shares": 500,
             "strategy": "均线网格混合", "strategy_id": strategy_ids[2],
             "time": now - timedelta(days=1)},
            {"fund_id": fund_ids[0], "direction": "sell", "price": 2.08, "shares": 150,
             "strategy": "均线趋势策略", "strategy_id": strategy_ids[0],
             "time": now - timedelta(days=2)},
            {"fund_id": fund_ids[2], "direction": "buy", "price": 1.32, "shares": 400,
             "strategy": "网格交易策略", "strategy_id": strategy_ids[1],
             "time": now - timedelta(days=3)},
        ]

        for t in trade_data:
            amount = round(t["price"] * t["shares"], 2)
            conn.execute(
                "INSERT INTO trades (fund_id, direction, price, shares, amount, strategy, strategy_id, time, status) VALUES (?,?,?,?,?,?,?,?,?)",
                (t["fund_id"], t["direction"], t["price"], t["shares"], amount,
                 t["strategy"], t["strategy_id"], t["time"].isoformat(), "executed"),
            )

        # --- Daily Values (365 days of history for backtest) ---
        for idx, fund_id in enumerate(fund_ids):
            fund = sample_funds[idx]
            price_start = fund["cost_price"] * 0.9
            price_end = fund["current_price"]

            for day_offset in range(364, -1, -1):
                date = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
                progress = (364 - day_offset) / 364
                price = price_start + (price_end - price_start) * progress
                noise = random.uniform(-0.03, 0.03) * price
                price = price + noise
                total_value = round(fund["shares"] * price, 2)
                conn.execute(
                    "INSERT OR IGNORE INTO daily_values (fund_id, date, total_value) VALUES (?,?,?)",
                    (fund_id, date, total_value),
                )
            # Today's value at exact current price
            today = now.strftime("%Y-%m-%d")
            total_value = round(fund["shares"] * fund["current_price"], 2)
            conn.execute(
                "INSERT OR IGNORE INTO daily_values (fund_id, date, total_value) VALUES (?,?,?)",
                (fund_id, today, total_value),
            )

        conn.commit()
    finally:
        conn.close()


def seed_sim_accounts():
    """创建三个默认模拟账户（如果不存在），每个独立策略配置"""
    conn = get_connection()
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM sim_accounts").fetchone()[0]
        if cnt > 0:
            return

        import json

        accounts = [
            (
                "保守·均线趋势",
                1000,
                json.dumps({
                    "trend": {"enabled": True, "fast": 20, "slow": 60},
                    "grid": {"enabled": False},
                    "market": {"enabled": False},
                    "risk": {"max_position_pct": 0.30, "max_drawdown_pct": 0.10},
                }),
            ),
            (
                "进取·网格增强",
                10000,
                json.dumps({
                    "trend": {"enabled": False},
                    "grid": {"enabled": True, "stepCount": 5, "stepSize": 0.10},
                    "market": {"enabled": True},
                    "risk": {"max_position_pct": 0.50, "max_drawdown_pct": 0.15},
                }),
            ),
            (
                "混合·AI 全开",
                100000,
                json.dumps({
                    "trend": {"enabled": True, "fast": 20, "slow": 60},
                    "grid": {"enabled": True, "stepCount": 5, "stepSize": 0.10},
                    "market": {"enabled": True},
                    "risk": {"max_position_pct": 0.80, "max_drawdown_pct": 0.20},
                }),
            ),
        ]
        now = datetime.now().isoformat()
        for name, cash, cfg in accounts:
            conn.execute(
                "INSERT INTO sim_accounts (name, initial_cash, cash, strategy_config, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (name, cash, cash, cfg, now, now),
            )
        conn.commit()
    finally:
        conn.close()
