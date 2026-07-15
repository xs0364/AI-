"""
Strategy engine — generates buy/sell signals from configured strategies.
"""
import json
import math
import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from database import get_connection


def _generate_price_history(
    current_price: float, days: int = 60
) -> List[float]:
    """Generate a simulated daily price series using a mean-reverting random walk."""
    prices = []
    price = current_price * 0.85  # start lower
    for _ in range(days):
        drift = (current_price - price) / max(days, 1) * 0.3
        noise = random.gauss(0, 1) * price * 0.015
        price = price + drift + noise
        price = max(price, current_price * 0.6)
        prices.append(round(price, 4))
    # ensure the last price is close to current_price
    prices[-1] = current_price
    return prices


def _sma(prices: List[float], period: int) -> List[Optional[float]]:
    """Simple moving average."""
    result = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        result[i] = sum(prices[i - period + 1 : i + 1]) / period
    return result


def run_ma_strategy(
    fund_id: int,
    strategy_id: int,
    params: Dict[str, Any],
    fund_code: str,
    fund_name: str,
    current_price: float,
) -> List[Dict[str, Any]]:
    """
    Moving Average strategy:
    - Generates a simulated price history
    - Calculates SMA
    - Buy when price drops below lower% of SMA
    - Sell when price rises above upper% of SMA
    """
    period = int(params.get("period", 20))
    upper_pct = float(params.get("upper", 105))
    lower_pct = float(params.get("lower", 95))

    prices = _generate_price_history(current_price, days=period + 20)
    sma_values = _sma(prices, period)

    signals: List[Dict[str, Any]] = []
    for i in range(period, len(prices)):
        sma_val = sma_values[i]
        if sma_val is None:
            continue
        price = prices[i]
        upper_band = sma_val * upper_pct / 100
        lower_band = sma_val * lower_pct / 100

        # Previous price for crossover detection
        prev_price = prices[i - 1] if i > 0 else price
        prev_upper = sma_values[i - 1] * upper_pct / 100 if sma_values[i - 1] else upper_band
        prev_lower = sma_values[i - 1] * lower_pct / 100 if sma_values[i - 1] else lower_band

        signal_type = None
        if prev_price <= prev_upper and price > upper_band:
            signal_type = "sell"
        elif prev_price >= prev_lower and price < lower_band:
            signal_type = "buy"

        if signal_type:
            signals.append({
                "fund_id": fund_id,
                "strategy_id": strategy_id,
                "signal_type": signal_type,
                "price": price,
                "quantity": round(1000 / price, 2),  # fixed amount per trade
                "generated_at": (
                    datetime.now() - timedelta(days=len(prices) - 1 - i)
                ).isoformat(),
                "fund_code": fund_code,
                "fund_name": fund_name,
                "strategy_name": f"MA({period}) {fund_name}",
            })

    return signals


def run_grid_strategy(
    fund_id: int,
    strategy_id: int,
    params: Dict[str, Any],
    fund_code: str,
    fund_name: str,
    current_price: float,
) -> List[Dict[str, Any]]:
    """
    Grid trading strategy:
    - Defines upper/lower price range
    - Divides into steps
    - Buy at lower grid levels, sell at upper grid levels
    """
    upper_price = float(params.get("upperPrice", 1.50))
    lower_price = float(params.get("lowerPrice", 1.00))
    step_count = int(params.get("stepCount", 5))
    step_size = float(params.get("stepSize", 0.10))

    if upper_price <= lower_price or step_count < 1:
        return []

    step_height = (upper_price - lower_price) / step_count
    current_step = math.floor((current_price - lower_price) / step_height)
    current_step = max(0, min(current_step, step_count - 1))

    signals: List[Dict[str, Any]] = []
    base_qty = round(500 / current_price, 2)

    for step in range(step_count):
        grid_price = lower_price + step * step_height + step_height / 2
        if grid_price >= upper_price:
            continue
        signal_type = "sell" if step > current_step else ("buy" if step < current_step else None)
        if signal_type:
            signals.append({
                "fund_id": fund_id,
                "strategy_id": strategy_id,
                "signal_type": signal_type,
                "price": round(grid_price, 4),
                "quantity": base_qty,
                "generated_at": datetime.now().isoformat(),
                "fund_code": fund_code,
                "fund_name": fund_name,
                "strategy_name": f"Grid {fund_name}",
            })

    return signals


STRATEGY_RUNNERS = {
    "ma": run_ma_strategy,
    "grid": run_grid_strategy,
}


def scan_all_strategies() -> List[Dict[str, Any]]:
    """
    Scan all enabled strategies and generate trade signals.
    Returns list of signal dicts.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.id, s.fund_id, s.strategy_type, s.params,
               f.code AS fund_code, f.name AS fund_name, f.current_price
        FROM strategies s
        JOIN funds f ON f.id = s.fund_id
        WHERE s.enabled = 1
    """).fetchall()
    conn.close()

    all_signals: List[Dict[str, Any]] = []
    for row in rows:
        params = json.loads(row["params"]) if isinstance(row["params"], str) else row["params"]
        runner = STRATEGY_RUNNERS.get(row["strategy_type"])
        if runner:
            signals = runner(
                fund_id=row["fund_id"],
                strategy_id=row["id"],
                params=params,
                fund_code=row["fund_code"],
                fund_name=row["fund_name"],
                current_price=row["current_price"],
            )
            all_signals.extend(signals)

    return all_signals


def run_strategy(strategy_id: int) -> List[Dict[str, Any]]:
    """Run a single strategy and return generated signals."""
    conn = get_connection()
    row = conn.execute("""
        SELECT s.id, s.fund_id, s.strategy_type, s.params,
               f.code AS fund_code, f.name AS fund_name, f.current_price
        FROM strategies s
        JOIN funds f ON f.id = s.fund_id
        WHERE s.id = ?
    """, (strategy_id,)).fetchone()
    conn.close()

    if not row:
        return []

    params = json.loads(row["params"]) if isinstance(row["params"], str) else row["params"]
    runner = STRATEGY_RUNNERS.get(row["strategy_type"])
    if not runner:
        return []

    return runner(
        fund_id=row["fund_id"],
        strategy_id=row["id"],
        params=params,
        fund_code=row["fund_code"],
        fund_name=row["fund_name"],
        current_price=row["current_price"],
    )
