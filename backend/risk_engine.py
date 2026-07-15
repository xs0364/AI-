"""
Risk Engine — 六层风控系统
============================
定位：纯规则引擎，不调用 LLM
位置：Signal Merge Engine → Risk Engine → Trade Executor

职责：
  1. 资金风控   — 单笔/单基金仓位上限、现金保留
  2. 仓位管理   — 根据趋势评分/ATR 动态调整仓位
  3. 止损系统   — 固定止损/ATR止损/Trailing Stop/时间止损
  4. 回撤控制   — 账户回撤分级降仓
  5. 市场状态   — 情绪分数档过滤
  6. 综合评分   — 加权产生 0-100 风险评分 + 最终决策

数据流：
  Orchestrator → merge_signals(all_signals) → decision(MergedDecision)
                                              → RiskEngine.check(decision, context)
                                              → enriched_decision(MergedDecision + RiskVerdict)
"""
import json
import math
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from loguru import logger

from database import get_connection
from agent_schema import RiskConfig, RiskVerdict


class RiskEngine:
    """
    六层风控引擎 — 线程安全，所有方法纯函数/实例级

    用法：
        engine = RiskEngine(config_override=None)  # 使用默认配置
        verdict = engine.check(fund, current_decision, context)
    """

    def __init__(self, config_override: Optional[dict] = None):
        """初始化，config_override 可覆盖默认 RiskConfig 的字段"""
        self.config = RiskConfig()
        if config_override:
            for k, v in config_override.items():
                if hasattr(self.config, k):
                    setattr(self.config, k, v)

    # ══════════════════════════════════════════════════════════════════
    #  主入口
    # ══════════════════════════════════════════════════════════════════

    def check(
        self,
        fund: dict,
        decision_score: float,
        decision_signal: str,
        context: dict,
    ) -> RiskVerdict:
        """
        运行完整六层风控 → 返回 RiskVerdict

        Args:
            fund:           基金信息 { id, code, name, current_price, shares, cost_price, ... }
            decision_score: 当前决策的融合评分 0-100
            decision_signal: 当前决策信号 (STRONG_BUY, BUY, ..., HOLD, ...)
            context:        上下文数据 {
                "prices": [...],           # 历史价格序列
                "daily_values": [...],     # 每日净值 [{date, total_value}, ...]
                "sentiment_score": float,  # Market Agent 情绪分 0-100
                "all_funds": [...],        # 所有基金信息（用于计算总仓位）
                "hold_days": int,          # 当前持仓天数
                "is_open": bool,           # 是否为开仓方向信号
            }

        Returns:
            RiskVerdict
        """
        prices = context.get("prices", [])
        daily_values = context.get("daily_values", [])
        sentiment = context.get("sentiment_score", 50.0)
        all_funds = context.get("all_funds", [])
        hold_days = context.get("hold_days", 0)
        is_open = context.get("is_open", False)

        current_price = fund.get("current_price", 0) or 0
        fund_shares = fund.get("shares", 0) or 0
        total_position_value = current_price * fund_shares  # 当前持仓市值

        # 各层独立计算
        layer_scores = {}
        all_reasons = []

        # 1. 资金风控
        cap_risk, cap_reason = self._check_capital_risk(
            fund, total_position_value, decision_score, all_funds
        )
        layer_scores["capital"] = cap_risk
        if cap_reason:
            all_reasons.append(cap_reason)

        # 2. 仓位管理
        position_factor, pos_reason = self._check_position_sizing(
            decision_score, current_price, fund_shares, total_position_value
        )
        pos_risk = self._factor_to_risk_score(position_factor)
        layer_scores["position"] = pos_risk
        if pos_reason:
            all_reasons.append(pos_reason)

        # 3. 止损系统
        stop_loss_price, sl_risk, sl_reason = self._check_stop_loss(
            prices, current_price, fund_shares, hold_days
        )
        layer_scores["stop_loss"] = sl_risk
        if sl_reason:
            all_reasons.append(sl_reason)

        # 4. 回撤控制
        dd_risk, dd_factor, dd_reason = self._check_drawdown(daily_values)
        layer_scores["drawdown"] = dd_risk
        if dd_reason:
            all_reasons.append(dd_reason)

        # 5. 市场状态
        market_risk, market_reason = self._check_market_regime(
            sentiment, is_open
        )
        layer_scores["market"] = market_risk
        if market_reason:
            all_reasons.append(market_reason)

        # 6. 综合评分
        final_score, risk_level = self._calculate_combined_score(layer_scores)
        allow = risk_level not in ("critical",)

        # 如果是开仓信号且风控不允许 → 改 allow=False
        if is_open and not allow:
            all_reasons.append(f"⛔ 风控综合评分 {final_score:.0f}，禁止开新仓")
        elif is_open and position_factor < 0.01:
            allow = False
            all_reasons.append("⛔ 仓位系数为 0，禁止开仓")

        # 止损价格随 trailing stop 更新
        final_stop = stop_loss_price

        # 取 profit target = cost_price * 1.15（简化止盈）
        take_profit = None
        cost_price = fund.get("cost_price", 0) or 0
        if cost_price > 0 and fund_shares > 0:
            take_profit = round(cost_price * 1.15, 4)

        return RiskVerdict(
            allow=allow,
            risk_score=round(final_score, 1),
            risk_level=risk_level,
            max_position=round(position_factor, 4),
            stop_loss_price=round(final_stop, 4) if final_stop else None,
            take_profit=round(take_profit, 4) if take_profit else None,
            layer_scores=layer_scores,
            reasons=all_reasons,
        )

    # ══════════════════════════════════════════════════════════════════
    #  1. 资金风控
    # ══════════════════════════════════════════════════════════════════

    def _check_capital_risk(
        self,
        fund: dict,
        total_position_value: float,
        decision_score: float,
        all_funds: List[dict],
    ) -> Tuple[float, str]:
        """
        资金风控检查

        检查项：
        - 单笔交易金额 ≤ 总资产 × single_trade_cap_pct
        - 单基金持仓 ≤ 总资产 × single_fund_cap_pct
        - 现金留存 ≥ 总资产 × cash_reserve_pct

        Returns:
            (risk_score 0-100, reason_string)
        """
        cfg = self.config
        total_assets = self._calc_total_assets(all_funds, total_position_value)
        if total_assets <= 0:
            return 0, ""

        reasons = []
        max_penalty = 0.0  # 0-1 额外惩罚

        # 单基金持仓比例
        current_fund_pct = total_position_value / total_assets if total_assets > 0 else 0
        if current_fund_pct > cfg.single_fund_cap_pct:
            over = (current_fund_pct - cfg.single_fund_cap_pct) / cfg.single_fund_cap_pct
            max_penalty = max(max_penalty, min(1.0, over))
            reasons.append(
                f"⚠️ 单基金仓位 {current_fund_pct:.1%} 超限 {cfg.single_fund_cap_pct:.0%}"
            )

        # 现金留存检查（通过 all_funds 中 shares=0 推算）
        cash_pct = self._calc_cash_pct(all_funds, total_assets)
        if cash_pct < cfg.cash_reserve_pct:
            shortage = (cfg.cash_reserve_pct - cash_pct) / cfg.cash_reserve_pct
            max_penalty = max(max_penalty, min(0.5, shortage * 0.5))
            reasons.append(
                f"⚠️ 现金留存 {cash_pct:.1%} 低于要求 {cfg.cash_reserve_pct:.0%}"
            )

        # 开仓信号且现金不足 → 高惩罚
        if max_penalty > 0:
            score = min(100, max_penalty * 100)
            return score, " | ".join(reasons)

        return 0, ""

    def _calc_total_assets(
        self, all_funds: List[dict], current_position: float
    ) -> float:
        """计算总资产（所有基金持仓市值 + 现金估算）"""
        if not all_funds:
            return current_position + 100000  # 兜底
        total = 0.0
        conn = get_connection()
        for f in all_funds:
            shares = f.get("shares", 0) or 0
            price = f.get("current_price", 0) or 0
            total += shares * price
        conn.close()
        # 现金：初始资金 100000 - 已投入
        invested = total
        cash = max(0, 100000 - invested)  # 简化：初始 10 万
        return total + cash

    def _calc_cash_pct(self, all_funds: List[dict], total_assets: float) -> float:
        """计算现金占总资产比例"""
        if total_assets <= 0:
            return 1.0
        invested = 0.0
        for f in all_funds:
            shares = f.get("shares", 0) or 0
            price = f.get("current_price", 0) or 0
            invested += shares * price
        cash = max(0, total_assets - invested)
        return cash / total_assets

    # ══════════════════════════════════════════════════════════════════
    #  2. 仓位管理
    # ══════════════════════════════════════════════════════════════════

    def _check_position_sizing(
        self,
        decision_score: float,
        current_price: float,
        current_shares: float,
        total_position_value: float,
    ) -> Tuple[float, str]:
        """
        动态仓位管理

        根据融合决策的 score 确定建议仓位比例。
        使用 config.position_tiers 的分档映射。

        Returns:
            (position_factor 0.0-1.0, reason_string)
        """
        cfg = self.config

        # 按 score 查找对应档位
        factor = 0.0
        for threshold, pct in sorted(cfg.position_tiers, key=lambda x: -x[0]):
            if decision_score >= threshold:
                factor = pct
                break

        # 如果已有持仓但 score 很低，不清仓仅减仓（保留观察仓）
        if factor == 0.0 and current_shares > 0:
            factor = 0.1  # 保留 10% 观察仓
            return factor, f"📊 趋势评分 {decision_score:.0f}，保留 10% 观察仓"

        if factor >= 1.0:
            return factor, f"📊 趋势评分 {decision_score:.0f}，允许满仓"
        elif factor > 0.5:
            return factor, f"📊 趋势评分 {decision_score:.0f}，仓位 {factor:.0%}"
        elif factor > 0:
            return factor, f"📊 趋势评分 {decision_score:.0f}，轻仓 {factor:.0%}"
        else:
            return 0.0, f"📊 趋势评分 {decision_score:.0f}，禁止建仓"

    # ══════════════════════════════════════════════════════════════════
    #  3. 止损系统
    # ══════════════════════════════════════════════════════════════════

    def _check_stop_loss(
        self,
        prices: List[float],
        current_price: float,
        current_shares: float,
        hold_days: int,
    ) -> Tuple[Optional[float], float, str]:
        """
        四层止损检查

        1. 固定止损: 当前价格 < 买入均价 × (1 - fixed_pct)
        2. ATR 止损: 当前价格 < max(近期最高价 - ATR × atr_multiple)
        3. 移动止损: 已盈利且回撤从高点超过 trailing_distance
        4. 时间止损: 持仓超过 time_days 天且未盈利

        Returns:
            (stop_loss_price, risk_score 0-100, reason_string)
        """
        cfg = self.config

        if current_shares <= 0 or current_price <= 0:
            return None, 0, ""

        # 获取买入均价
        avg_cost = self._get_avg_cost()
        if not avg_cost or avg_cost <= 0:
            return None, 0, ""

        pnl_pct = (current_price - avg_cost) / avg_cost * 100
        reasons = []
        risk_score = 0
        stop_price = None

        # 3a. 固定止损
        fixed_stop = avg_cost * (1 - cfg.stop_loss_fixed_pct)
        if current_price <= fixed_stop:
            risk_score = max(risk_score, 90)
            reasons.append(f"🛑 固定止损触发: {current_price:.4f} ≤ {fixed_stop:.4f} ({cfg.stop_loss_fixed_pct:.0%})")
            stop_price = fixed_stop

        # 3b. ATR 止损（简化：用过去 14 天的平均波动）
        if len(prices) >= 14:
            atr = self._calc_atr(prices, 14)
            recent_high = max(prices[-14:])
            atr_stop = recent_high - atr * cfg.stop_loss_atr_multiple
            if current_price <= atr_stop:
                risk_score = max(risk_score, 80)
                reasons.append(f"🛑 ATR止损触发: {current_price:.4f} ≤ {atr_stop:.4f}")
                if stop_price is None or atr_stop < stop_price:
                    stop_price = atr_stop
            else:
                # ATR stop 作为动态止损参考
                if stop_price is None or atr_stop < stop_price:
                    stop_price = atr_stop

        # 3c. 移动止损 (Trailing Stop)
        if pnl_pct >= cfg.stop_loss_trailing_activate_pct * 100:
            trailing_stop = current_price * (1 - cfg.stop_loss_trailing_distance_pct)
            if stop_price is None or trailing_stop > stop_price:
                stop_price = trailing_stop
            reasons.append(
                f"📈 移动止损激活: 盈利 {pnl_pct:.1f}%, trailing @ {trailing_stop:.4f}"
            )
            risk_score = max(risk_score, 20)  # 正常预警

        # 3d. 时间止损
        if hold_days >= cfg.stop_loss_time_days and pnl_pct < 0:
            risk_score = max(risk_score, 60)
            reasons.append(
                f"⏰ 时间止损: 持仓 {hold_days} 天 ≥ {cfg.stop_loss_time_days} 天, 亏损 {pnl_pct:.1f}%"
            )

        if not reasons:
            return stop_price, 0, ""

        return stop_price, min(100, risk_score), " | ".join(reasons)

    def _calc_atr(self, prices: List[float], period: int = 14) -> float:
        """简化 ATR 计算：过去 period 天的平均日波动"""
        if len(prices) < 2:
            return 0.0
        ranges = []
        for i in range(1, min(len(prices), period + 1)):
            ranges.append(abs(prices[-i] - prices[-i - 1]))
        return sum(ranges) / len(ranges) if ranges else 0.0

    def _get_avg_cost(self) -> Optional[float]:
        """从数据库获取最近持仓的买入均价"""
        try:
            conn = get_connection()
            row = conn.execute("""
                SELECT price FROM trades
                WHERE direction = 'buy' AND status = 'executed'
                ORDER BY time DESC LIMIT 1
            """).fetchone()
            conn.close()
            return row["price"] if row else None
        except Exception:
            return None

    # ══════════════════════════════════════════════════════════════════
    #  4. 回撤控制
    # ══════════════════════════════════════════════════════════════════

    def _check_drawdown(
        self, daily_values: List[dict]
    ) -> Tuple[float, float, str]:
        """
        账户回撤检查

        从 daily_values 计算当前回撤，按 drawdown_tiers 分级降仓。

        Returns:
            (risk_score 0-100, drawdown_factor 0.0-1.0, reason_string)
        """
        cfg = self.config

        if not daily_values or len(daily_values) < 2:
            return 0, 1.0, ""

        # 从 daily_values 计算总市值序列
        # 聚合所有基金在同一天的总净值
        values = self._aggregate_portfolio_values(daily_values)

        if len(values) < 2:
            return 0, 1.0, ""

        # 计算最大回撤
        peak = 0
        current_dd_pct = 0
        for v in values:
            if v > peak:
                peak = v
            if peak > 0:
                dd = (peak - v) / peak * 100
                if dd > current_dd_pct:
                    current_dd_pct = dd

        # 按回撤档位判断
        factor = 1.0
        risk_score = 0
        reason = ""
        for threshold, pct in sorted(cfg.drawdown_tiers, key=lambda x: x[0]):
            if current_dd_pct < threshold:
                factor = pct
                break

        if factor < 1.0:
            risk_score = min(100, current_dd_pct * 5)  # 回撤 5% → 25分, 20% → 100分
            reason = f"📉 当前回撤 {current_dd_pct:.1f}%, 仓位限制 {factor:.0%}"
        else:
            risk_score = current_dd_pct * 2  # 小回撤也轻度预警
            if current_dd_pct > 0:
                reason = f"📉 当前回撤 {current_dd_pct:.1f}%"

        return min(100, risk_score), factor, reason

    def _aggregate_portfolio_values(self, daily_values: List[dict]) -> List[float]:
        """
        从 daily_values 聚合每日总市值

        daily_values 结构: [{date, total_value, fund_id}, ...]
        按 date 分组求和。
        """
        grouped = {}
        for row in daily_values:
            date = row.get("date", "")
            tv = row.get("total_value", 0) or 0
            grouped[date] = grouped.get(date, 0) + tv

        # 按日期排序
        return [v for _, v in sorted(grouped.items())]

    # ══════════════════════════════════════════════════════════════════
    #  5. 市场状态滤网
    # ══════════════════════════════════════════════════════════════════

    def _check_market_regime(
        self, sentiment_score: float, is_open: bool
    ) -> Tuple[float, str]:
        """
        市场状态滤网

        基于 Market Agent 的情绪分做过滤:
        - sentiment ≥ good_min: 允许正常交易
        - good_min > sentiment ≥ bad_max: 仅允许减仓/止损
        - sentiment < bad_max: 禁止任何新操作（仅止损）

        Returns:
            (risk_score 0-100, reason_string)
        """
        cfg = self.config

        if sentiment_score >= cfg.sentiment_good_min:
            return 0, f"🌤️ 市场情绪 {sentiment_score:.0f}, 正常交易"

        if sentiment_score >= cfg.sentiment_bad_max:
            if is_open:
                return 50, f"🌥️ 市场情绪 {sentiment_score:.0f}, 仅允许减仓/止损"
            else:
                return 20, f"🌥️ 市场情绪 {sentiment_score:.0f}, 减仓操作允许"

        # 情绪极差
        return 80, f"🌧️ 市场情绪 {sentiment_score:.0f}, 仅允许止损, 禁止新操作"

    # ══════════════════════════════════════════════════════════════════
    #  6. 综合评分
    # ══════════════════════════════════════════════════════════════════

    def _calculate_combined_score(
        self, layer_scores: dict
    ) -> Tuple[float, str]:
        """
        加权综合风险评分

        权重配比:
        - 资金风控 20%
        - 仓位管理 20%
        - 止损系统 20%
        - 回撤控制 25%
        - 市场状态 15%

        → risk_level: normal(0-30) / caution(31-60) / danger(61-80) / critical(81-100)
        """
        cfg = self.config
        weights = {
            "capital": cfg.risk_weight_capital,
            "position": cfg.risk_weight_position,
            "stop_loss": cfg.risk_weight_stop_loss,
            "drawdown": cfg.risk_weight_drawdown,
            "market": cfg.risk_weight_market,
        }

        weighted_sum = 0.0
        total_w = 0.0
        for layer, score in layer_scores.items():
            w = weights.get(layer, 0.1)
            weighted_sum += score * w
            total_w += w

        final_score = weighted_sum / total_w if total_w > 0 else 0

        # 风险等级
        if final_score <= 30:
            level = "normal"
        elif final_score <= 60:
            level = "caution"
        elif final_score <= 80:
            level = "danger"
        else:
            level = "critical"

        return min(100, final_score), level

    # ══════════════════════════════════════════════════════════════════
    #  便捷方法：因式 → 风险分
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _factor_to_risk_score(factor: float) -> float:
        """仓位因子 [0-1] → 风险分 [0-100]"""
        return round((1.0 - factor) * 80, 1)


# ══════════════════════════════════════════════════════════════════
#  便捷函数：从数据库读取风控配置
# ══════════════════════════════════════════════════════════════════

def load_risk_config() -> RiskConfig:
    """从 risk_config.json 加载风控配置（如存在），否则返回默认"""
    import os
    config_path = os.path.join(os.path.dirname(__file__), "risk_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return RiskConfig(**data)
        except Exception as e:
            logger.warning("加载风控配置文件失败: {}, 使用默认配置", e)
    return RiskConfig()


def save_risk_config(config: RiskConfig) -> None:
    """保存风控配置到 risk_config.json"""
    import os
    config_path = os.path.join(os.path.dirname(__file__), "risk_config.json")
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config.__dict__, f, ensure_ascii=False, indent=2)
        logger.info("风控配置已保存到 {}", config_path)
    except Exception as e:
        logger.error("保存风控配置失败: {}", e)


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    engine = RiskEngine()
    fund = {"id": 1, "code": "110011", "name": "易方达中小盘混合",
            "current_price": 2.12, "shares": 5000, "cost_price": 1.85}
    context = {
        "prices": [1.8 + i * 0.01 for i in range(90)],
        "daily_values": [{"date": f"2025-{m:02d}-{d:02d}", "total_value": 10000 + i * 50}
                         for i, (m, d) in enumerate([(1, i+1) for i in range(30)] + [(2, i+1) for i in range(28)])],
        "sentiment_score": 55.0,
        "all_funds": [fund],
        "hold_days": 30,
        "is_open": True,
    }
    verdict = engine.check(fund, decision_score=72, decision_signal="BUY", context=context)
    print(verdict.to_dict())
