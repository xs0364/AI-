"""
基金回测引擎 — 分层架构，策略复用现有引擎
======================================
设计：

  DataProvider → SimulationClock → [Strategy → OrderManager → ExecutionSimulator → FeeEngine] → Portfolio → Metrics

原则：
  - 复用 strategy_engine.py 的策略逻辑
  - 复用 trading_time_engine.py 的费率/时间规则
  - 回测和实盘共用一套流程
  - 输出 equity_curve + trades + metrics
"""
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from loguru import logger
from database import get_connection
from market_data_fetcher import fetch_fund_history
from trading_time_engine import (
    is_trading_day,
    calc_redemption_fee,
    calc_redemption_fee_ratio,
    is_before_1500,
    TradeTimeConstants,
)


# ═══════════════════════════════════════════════════════════════════
# 配置 & 结果类型
# ═══════════════════════════════════════════════════════════════════

@dataclass
class BacktestConfig:
    """回测参数配置"""
    fund_code: str                     # 基金代码
    fund_name: str                     # 基金名称
    strategy_type: str = "ma"          # "ma" | "grid"
    strategy_params: Dict[str, Any] = field(default_factory=lambda: {
        "period": 20, "upper": 105, "lower": 95,
    })

    initial_cash: float = 100000.0
    start_date: str = ""               # 空则取最早可用数据
    end_date: str = ""                 # 空则取今天

    buy_fee_rate: float = 0.0015       # 申购费率（默认0.15%）
    sell_fee_rate: Optional[float] = None  # 赎回费率（None 则按持有天数计算）
    min_fee: float = 1.0               # 最低手续费（元）
    slippage: float = 0.0              # 滑点（占净值比例, 0=无）

    max_position_pct: float = 0.95     # 单次最大仓位占比
    max_drawdown_pct: float = 0.25     # 最大回撤止损（0=不启用）


@dataclass
class BacktestTrade:
    """模拟交易记录"""
    date: str
    action: str           # "buy" | "sell"
    price: float
    shares: float
    amount: float
    fee: float
    reason: str = ""


@dataclass
class EquityPoint:
    """每日权益快照"""
    date: str
    total_value: float    # 总资产 = 现金 + 持仓市值
    cash: float
    shares: float
    price: float          # 当日净值
    action: str = ""      # 当日是否有交易


@dataclass
class BacktestResult:
    """回测结果"""
    config: BacktestConfig
    equity_curve: List[EquityPoint]
    trades: List[BacktestTrade]
    metrics: Dict[str, Any]
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════════
# 绩效指标计算
# ═══════════════════════════════════════════════════════════════════

def _calc_metrics(equity: List[EquityPoint], trades: List[BacktestTrade],
                  config: BacktestConfig) -> Dict[str, Any]:
    """计算全套绩效指标"""
    if len(equity) < 2:
        return {"error": "数据不足"}

    start_val = equity[0].total_value
    end_val = equity[-1].total_value
    total_return = (end_val - start_val) / start_val if start_val > 0 else 0

    # 年化收益（按日计算）
    days = max((datetime.fromisoformat(equity[-1].date) -
                datetime.fromisoformat(equity[0].date)).days, 1)
    years = days / 365.0
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # 最大回撤
    peak = equity[0].total_value
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    for ep in equity:
        if ep.total_value > peak:
            peak = ep.total_value
        dd = peak - ep.total_value
        dd_pct = dd / peak if peak > 0 else 0
        if dd_pct > max_drawdown_pct:
            max_drawdown = dd
            max_drawdown_pct = dd_pct

    # 日收益率序列（用于 Sharpe / Sortino）
    daily_returns = []
    for i in range(1, len(equity)):
        prev = equity[i - 1].total_value
        if prev > 0:
            daily_returns.append((equity[i].total_value - prev) / prev)

    # Sharpe Ratio (假设无风险利率 = 0.02)
    if daily_returns:
        avg_daily = sum(daily_returns) / len(daily_returns)
        variance = sum((r - avg_daily) ** 2 for r in daily_returns) / len(daily_returns)
        std_daily = math.sqrt(variance) if variance > 0 else 0.0001
        sharpe = (avg_daily - 0.02 / 365) / std_daily * math.sqrt(365)
    else:
        sharpe = 0

    # Sortino (只考虑下行波动)
    negative_returns = [r for r in daily_returns if r < 0]
    if negative_returns:
        avg_neg = sum(negative_returns) / len(negative_returns)
        neg_var = sum((r - avg_neg) ** 2 for r in negative_returns) / len(negative_returns)
        downside_std = math.sqrt(neg_var) if neg_var > 0 else 0.0001
        sortino = (avg_daily - 0.02 / 365) / downside_std * math.sqrt(365)
    else:
        sortino = sharpe

    # Calmar Ratio = 年化收益 / |最大回撤|
    calmar = annual_return / max_drawdown_pct if max_drawdown_pct > 0 else 0

    # 胜率 & 盈亏比
    wins = [t for t in trades if t.action == "sell" and t.amount > 0]  # simplified
    total_closed = len([t for t in trades if t.action == "sell"])

    # 从 equity curve 计算：每笔卖出后剩余收益
    profit_trades = 0
    total_win = 0.0
    total_loss = 0.0
    closed_trades = 0
    for i in range(1, len(trades)):
        if trades[i].action == "sell":
            closed_trades += 1
            pnl = trades[i].amount - trades[i].fee
            # 粗略计算买入成本
            buy_idx = -1
            for j in range(i - 1, -1, -1):
                if trades[j].action == "buy":
                    buy_idx = j
                    break
            if buy_idx >= 0:
                cost = trades[buy_idx].amount + trades[buy_idx].fee
                pnl = trades[i].amount - trades[i].fee - cost
            if pnl > 0:
                profit_trades += 1
                total_win += pnl
            else:
                total_loss += abs(pnl)

    win_rate = profit_trades / closed_trades if closed_trades > 0 else 0
    profit_loss_ratio = total_win / total_loss if total_loss > 0 else (total_win if total_win > 0 else 0)

    # 换手率
    total_turnover = sum(t.amount for t in trades)
    turnover_rate = total_turnover / start_val if start_val > 0 else 0

    # 最大连续亏损
    max_consecutive_loss = 0
    current_loss_streak = 0
    for t in trades:
        if t.action == "sell":
            b_idx = -1
            for j in range(len(trades)):
                if trades[j].action == "buy" and trades[j].date <= t.date:
                    b_idx = j
                    break
            if b_idx >= 0:
                cost = trades[b_idx].amount + trades[b_idx].fee
                pnl = t.amount - t.fee - cost
                if pnl < 0:
                    current_loss_streak += 1
                    max_consecutive_loss = max(max_consecutive_loss, current_loss_streak)
                else:
                    current_loss_streak = 0

    # 最大连续盈利
    max_consecutive_profit = 0
    current_profit_streak = 0
    for t in trades:
        if t.action == "sell":
            b_idx = -1
            for j in range(len(trades)):
                if trades[j].action == "buy" and trades[j].date <= t.date:
                    b_idx = j
                    break
            if b_idx >= 0:
                cost = trades[b_idx].amount + trades[b_idx].fee
                pnl = t.amount - t.fee - cost
                if pnl > 0:
                    current_profit_streak += 1
                    max_consecutive_profit = max(max_consecutive_profit, current_profit_streak)
                else:
                    current_profit_streak = 0

    # 平均持仓天数
    hold_days_list = []
    for i in range(len(trades)):
        if trades[i].action == "buy":
            for j in range(i + 1, len(trades)):
                if trades[j].action == "sell":
                    d1 = datetime.fromisoformat(trades[i].date)
                    d2 = datetime.fromisoformat(trades[j].date)
                    hold_days_list.append((d2 - d1).days)
                    break
    avg_hold_days = sum(hold_days_list) / len(hold_days_list) if hold_days_list else 0

    # 月度/年度收益
    monthly_returns = {}
    yearly_returns = {}
    for i in range(1, len(equity)):
        month_key = equity[i].date[:7]
        year_key = equity[i].date[:4]
        prev_val = equity[i - 1].total_value
        if prev_val > 0:
            r = (equity[i].total_value - prev_val) / prev_val
            monthly_returns.setdefault(month_key, 0)
            monthly_returns[month_key] += r
        # yearly: last day of each year
        if i == len(equity) - 1 or equity[i].date[:4] != equity[i + 1].date[:4]:
            first_day_of_year = None
            for ep in equity:
                if ep.date[:4] == year_key:
                    first_day_of_year = ep
                    break
            if first_day_of_year and first_day_of_year.total_value > 0:
                yearly_returns[year_key] = (equity[i].total_value - first_day_of_year.total_value) / first_day_of_year.total_value

    return {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown_pct * 100, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "calmar_ratio": round(calmar, 2),
        "win_rate": round(win_rate * 100, 1),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "total_trades": len(trades),
        "total_buys": len([t for t in trades if t.action == "buy"]),
        "total_sells": len([t for t in trades if t.action == "sell"]),
        "max_consecutive_loss": max_consecutive_loss,
        "max_consecutive_profit": max_consecutive_profit,
        "avg_hold_days": round(avg_hold_days, 1),
        "turnover_rate": round(turnover_rate * 100, 1),
        "start_date": equity[0].date,
        "end_date": equity[-1].date,
        "total_days": days,
        "trading_days": len(equity),
        "final_value": round(end_val, 2),
        "total_profit": round(end_val - start_val, 2),
    }


# ═══════════════════════════════════════════════════════════════════
# 回测引擎主类
# ═══════════════════════════════════════════════════════════════════

class BacktestEngine:
    """单基金回测引擎"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.price_data: List[Dict] = []  # [{date, price}, ...]
        self._price_map: Dict[str, float] = {}  # date → price 快速查找
        self.cash: float = config.initial_cash
        self.shares: float = 0.0
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[EquityPoint] = []
        self.peak_value: float = config.initial_cash
        self._pending_order: Optional[Dict] = None  # T日下单,T+1确认
        self._hold_days_cache: Dict[str, int] = {}  # fund_id_fund_code → hold_days

    # ── DataProvider ──────────────────────────────────────────

    def _load_data(self) -> bool:
        """加载历史净值数据（优先 DB daily_values，其次 API，最后模拟数据）"""
        import random as _random
        from datetime import timedelta as _td

        # 从 DB daily_values 加载
        conn = get_connection()
        fund = conn.execute(
            "SELECT id, code, name, current_price, shares FROM funds WHERE code = ?",
            (self.config.fund_code,),
        ).fetchone()
        if fund:
            rows = conn.execute(
                "SELECT date, total_value FROM daily_values "
                "WHERE fund_id = ? ORDER BY date ASC",
                (fund["id"],),
            ).fetchall()
            shares = fund["shares"] if fund["shares"] and fund["shares"] > 0 else 1
            for r in rows:
                # daily_values 存的是 total_value = shares * price
                avg_price = r["total_value"] / shares if shares > 0 else 0
                self.price_data.append({"date": r["date"], "price": avg_price})
        conn.close()

        # 如果 DB 数据不足，走 API 获取历史净值
        if len(self.price_data) < 20:
            api_data = fetch_fund_history(self.config.fund_code, page=1, per=500)
            if api_data and not api_data.get("error") and api_data.get("records"):
                self.price_data = []
                for rec in api_data["records"]:
                    dwjz = rec.get("dwjz")
                    if dwjz:
                        try:
                            price = float(dwjz)
                            self.price_data.append({
                                "date": rec["date"],
                                "price": price,
                            })
                        except (ValueError, TypeError):
                            continue
                # 去重 + 排序
                seen = set()
                deduped = []
                for p in self.price_data:
                    if p["date"] not in seen:
                        seen.add(p["date"])
                        deduped.append(p)
                deduped.sort(key=lambda x: x["date"])
                self.price_data = deduped

        # 如果仍然不足，生成模拟数据（至少 365 天）
        if len(self.price_data) < 30:
            logger.info(f"[Backtest] 数据不足，生成模拟数据 ({self.config.fund_code})")
            current_price = fund["current_price"] if fund else 1.0
            self.price_data = []
            start = datetime.now() - _td(days=365)
            price = current_price * 0.85
            for i in range(365):
                d = (start + _td(days=i)).strftime("%Y-%m-%d")
                drift = (current_price - price) / max(365 - i, 1) * 0.3
                noise = _random.gauss(0, 1) * price * 0.015
                price = price + drift + noise
                price = max(price, current_price * 0.4)
                self.price_data.append({"date": d, "price": round(price, 4)})
            # 最后一天对齐到 current_price
            if self.price_data:
                self.price_data[-1]["price"] = current_price

        if len(self.price_data) < 10:
            logger.warning(f"[Backtest] 数据不足: {self.config.fund_code}, 仅{len(self.price_data)}条")
            return False

        if len(self.price_data) < 10:
            logger.warning(f"[Backtest] 数据不足: {self.config.fund_code}, 仅{len(self.price_data)}条")
            return False

        # 构建快速查找表
        self._price_map = {p["date"]: p["price"] for p in self.price_data}

        # 按日期范围过滤
        if self.config.start_date:
            self.price_data = [p for p in self.price_data if p["date"] >= self.config.start_date]
        if self.config.end_date:
            self.price_data = [p for p in self.price_data if p["date"] <= self.config.end_date]

        if len(self.price_data) < 2:
            logger.warning(f"[Backtest] 过滤后数据不足")
            return False

        return True

    def _get_price(self, dt_str: str) -> Optional[float]:
        """获取某日净值"""
        return self._price_map.get(dt_str)

    def _next_trading_day(self, dt_str: str) -> Optional[str]:
        """获取下一个交易日"""
        found = False
        for p in self.price_data:
            if found:
                return p["date"]
            if p["date"] == dt_str:
                found = True
        return None

    # ── Strategy ──────────────────────────────────────────────

    def _check_strategy(self, date_str: str, price: float) -> Optional[Dict]:
        """
        检查策略是否产生交易信号
        复用 strategy_engine 的逻辑思路

        返回: {"action": "buy"|"sell", "reason": "..."} 或 None
        """
        # 找当前日期在价格序列中的位置
        idx = -1
        for i, p in enumerate(self.price_data):
            if p["date"] == date_str:
                idx = i
                break

        if idx < 0:
            return None

        # 需要足够的历史数据计算指标
        typ = self.config.strategy_type
        params = self.config.strategy_params

        if typ == "ma":
            period = int(params.get("period", 20))
            upper_pct = float(params.get("upper", 105))
            lower_pct = float(params.get("lower", 95))

            if idx < period:
                return None

            # 计算 SMA
            prices_window = [self.price_data[j]["price"] for j in range(idx - period + 1, idx + 1)]
            sma = sum(prices_window) / period

            # 前一日 SMA
            prev_prices = [self.price_data[j]["price"] for j in range(idx - period, idx)]
            prev_sma = sum(prev_prices) / period if len(prev_prices) == period else sma

            upper_band = sma * upper_pct / 100
            lower_band = sma * lower_pct / 100
            prev_upper = prev_sma * upper_pct / 100
            prev_lower = prev_sma * lower_pct / 100
            prev_price = self.price_data[idx - 1]["price"]

            # 上穿：昨日 <= 上轨 → 今日 > 上轨 → 卖出
            if prev_price <= prev_upper and price > upper_band and self.shares > 0:
                return {"action": "sell", "reason": f"MA{period}上穿{upper_pct}%上轨"}
            # 下穿：昨日 >= 下轨 → 今日 < 下轨 → 买入
            if prev_price >= prev_lower and price < lower_band:
                return {"action": "buy", "reason": f"MA{period}下穿{lower_pct}%下轨"}

        elif typ == "grid":
            upper_price = float(params.get("upperPrice", price * 1.3))
            lower_price = float(params.get("lowerPrice", price * 0.7))
            step_count = int(params.get("stepCount", 5))

            if upper_price <= lower_price or step_count < 1:
                return None

            step_height = (upper_price - lower_price) / step_count
            current_step = math.floor((price - lower_price) / step_height) if upper_price > lower_price else 0
            current_step = max(0, min(current_step, step_count - 1))

            # 根据当前价格在网格中的位置判断
            prev_price = self.price_data[idx - 1]["price"] if idx > 0 else price
            prev_step = math.floor((prev_price - lower_price) / step_height) if upper_price > lower_price else 0
            prev_step = max(0, min(prev_step, step_count - 1))

            if current_step < prev_step and self.shares > 0:
                return {"action": "sell", "reason": f"网格{current_step + 1}/{step_count}层卖出"}
            if current_step > prev_step:
                return {"action": "buy", "reason": f"网格{current_step + 1}/{step_count}层买入"}

        return None

    # ── Execution Simulator ───────────────────────────────────

    def _execute_trade(self, date_str: str, price: float,
                       action: str, reason: str) -> None:
        """执行一笔交易（含费率计算）"""
        params = self.config.strategy_params
        amount_per_trade = self.cash * self.config.max_position_pct

        if action == "buy":
            cash_available = self.cash * self.config.max_position_pct
            fee_rate = self.config.buy_fee_rate
            # 计算可买份额（含申购费）
            invest_amount = cash_available
            fee = max(invest_amount * fee_rate, self.config.min_fee)
            actual_invest = invest_amount - fee
            if actual_invest <= 0:
                return
            shares_bought = round(actual_invest / price, 2)

            if shares_bought <= 0:
                return

            self.cash -= invest_amount
            self.shares += shares_bought
            self.trades.append(BacktestTrade(
                date=date_str, action="buy", price=price,
                shares=shares_bought, amount=invest_amount,
                fee=fee, reason=reason,
            ))

        elif action == "sell" and self.shares > 0:
            shares_sold = self.shares
            gross_amount = shares_sold * price
            fee = max(gross_amount * self.config.sell_fee_rate, self.config.min_fee) \
                if self.config.sell_fee_rate else 0
            # 如果未指定卖出费率，按持有天数计算赎回费
            if not self.config.sell_fee_rate:
                # 计算持有天数（取最近买入日期）
                hold_days = 0
                for t in reversed(self.trades):
                    if t.action == "buy":
                        d1 = datetime.fromisoformat(t.date)
                        d2 = datetime.fromisoformat(date_str)
                        hold_days = (d2 - d1).days
                        break
                fee_rate = calc_redemption_fee_ratio(hold_days)
                fee = max(gross_amount * fee_rate, self.config.min_fee)

            net_amount = gross_amount - fee
            if net_amount <= 0:
                return

            self.cash += net_amount
            self.shares = 0
            self.trades.append(BacktestTrade(
                date=date_str, action="sell", price=price,
                shares=shares_sold, amount=gross_amount,
                fee=fee, reason=reason,
            ))

    # ── 风控检查 ─────────────────────────────────────────────

    def _check_risk(self, date_str: str, total_value: float) -> bool:
        """风控: 最大回撤止损"""
        if self.config.max_drawdown_pct <= 0:
            return True  # 未启用
        if total_value > self.peak_value:
            self.peak_value = total_value
            return True
        drawdown_pct = (self.peak_value - total_value) / self.peak_value
        if drawdown_pct >= self.config.max_drawdown_pct:
            # 触发止损，强制清仓
            if self.shares > 0:
                price = self._get_price(date_str)
                if price:
                    self._execute_trade(date_str, price, "sell", f"止损(回撤{drawdown_pct * 100:.1f}%)")
            return False
        return True

    # ── 主循环 ───────────────────────────────────────────────

    def run(self) -> BacktestResult:
        """运行回测"""
        try:
            # 1. 加载数据
            if not self._load_data():
                return BacktestResult(
                    config=self.config, equity_curve=[], trades=[],
                    metrics={},
                    error=f"历史净值数据不足，无法回测 {self.config.fund_code}",
                )

            # 2. 按日期逐日推进
            for i, dp in enumerate(self.price_data):
                date_str = dp["date"]
                price = dp["price"]
                action_taken = ""

                # 只在交易日产生信号
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                if not is_trading_day(dt.date()):
                    # 非交易日：只记录权益
                    self.equity_curve.append(EquityPoint(
                        date=date_str,
                        total_value=round(self.cash + self.shares * price, 2),
                        cash=round(self.cash, 2),
                        shares=self.shares,
                        price=price,
                    ))
                    continue

                # 只有有足够数据后才开始交易（前 period 天预热）
                signal = self._check_strategy(date_str, price)

                if signal:
                    self._execute_trade(date_str, price, signal["action"], signal["reason"])
                    action_taken = signal["action"]

                # 更新权益快照
                total_value = self.cash + self.shares * price

                # 风控检查
                if not self._check_risk(date_str, total_value):
                    action_taken = "stop_loss"

                # 重新计算
                total_value = self.cash + self.shares * price
                self.equity_curve.append(EquityPoint(
                    date=date_str,
                    total_value=round(total_value, 2),
                    cash=round(self.cash, 2),
                    shares=self.shares,
                    price=price,
                    action=action_taken,
                ))

            logger.info(
                f"[Backtest] {self.config.fund_code} 完成: "
                f"{self.price_data[0]['date']} → {self.price_data[-1]['date']}, "
                f"{len(self.trades)}笔交易"
            )

            # 3. 计算绩效
            metrics = _calc_metrics(self.equity_curve, self.trades, self.config)

            return BacktestResult(
                config=self.config,
                equity_curve=self.equity_curve,
                trades=self.trades,
                metrics=metrics,
            )

        except Exception as e:
            logger.error(f"[Backtest] 运行异常: {e}")
            return BacktestResult(
                config=self.config, equity_curve=[], trades=[],
                metrics={}, error=str(e),
            )


# ── 快捷测试 ─────────────────────────────────────────────────

if __name__ == "__main__":
    config = BacktestConfig(
        fund_code="110011",
        fund_name="易方达中小盘混合",
        strategy_type="ma",
        strategy_params={"period": 20, "upper": 105, "lower": 95},
        initial_cash=100000,
        buy_fee_rate=0.0015,
        max_position_pct=0.95,
    )
    engine = BacktestEngine(config)
    result = engine.run()

    if result.error:
        print(f"❌ {result.error}")
    else:
        print(f"✅ 回测完成")
        print(f"   总收益: {result.metrics.get('total_return', 'N/A')}%")
        print(f"   年化: {result.metrics.get('annual_return', 'N/A')}%")
        print(f"   最大回撤: {result.metrics.get('max_drawdown_pct', 'N/A')}%")
        print(f"   Sharpe: {result.metrics.get('sharpe_ratio', 'N/A')}")
        print(f"   交易: {result.metrics.get('total_trades', 'N/A')}笔")
        print(f"   胜率: {result.metrics.get('win_rate', 'N/A')}%")
