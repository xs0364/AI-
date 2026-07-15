"""
Grid Agent — 网格增强 Agent
============================
定位：纯计算 Agent，不调用 LLM
负责：动态网格参数调整 + 波动率自适应 + 突破检测 + 舆情感知

核心逻辑：
  1. ATR 计算最佳网格间距
  2. 波动率变化时自动调整上下界/层数
  3. 价格持续突破网格边界 → 暂停网格
  4. 接收 Market Agent 情绪分 → 调整网格位置（恐慌时下移）
  5. QDII 基金自动延后操作窗口

输出：统一 AgentSignal 格式
"""
import math
from datetime import datetime
from typing import List, Optional

from loguru import logger

from agent_schema import AgentSignal, SignalType

# ── 网格默认参数 ──────────────────────────────────────────────────

DEFAULT_GRID_CONFIG = {
    "initial_capital_ratio": 0.5,     # 初始资金分配比例（网格部分占总资金）
    "base_layer_count": 8,            # 基础网格层数
    "min_layer_count": 4,             # 最小网格层数
    "max_layer_count": 16,            # 最大网格层数
    "volatility_adjust_factor": 1.5,  # 波动率放大时网格间距乘数
    "breakout_days": 3,               # 连续突破 N 天判定为趋势
    "sentiment_offset_max": 0.15,     # 情绪偏移最大比例（恐慌时下移网格）
    "profit_take_layers": 0.3,        # 盈利达到 30% 层数时缩减中间层
}


# ══════════════════════════════════════════════════════════════════
# 指标计算
# ══════════════════════════════════════════════════════════════════

def _atr(prices: List[float], period: int = 14) -> float:
    """简化 ATR 计算"""
    if len(prices) < period + 1:
        return 0
    tr_sum = 0
    for i in range(max(1, len(prices) - period), len(prices)):
        tr_sum += abs(prices[i] - prices[i - 1])
    return tr_sum / min(period, len(prices) - 1)


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    result: List[Optional[float]] = [None] * len(values)
    valid = [v for v in values if v is not None]
    if len(valid) < period:
        return result
    multiplier = 2 / (period + 1)
    result[period - 1] = sum(valid[:period]) / period
    for i in range(period, len(values)):
        result[i] = (values[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


# ══════════════════════════════════════════════════════════════════
# 网格计算
# ══════════════════════════════════════════════════════════════════

def _calculate_grid_params(
    current_price: float,
    atr_value: float,
    volatility_pct: float,
    config: dict,
    sentiment_score: Optional[float] = None,
) -> dict:
    """
    根据波动率和情绪计算最佳网格参数

    Returns:
        {
            "upper_price": 网格上界,
            "lower_price": 网格下界,
            "step_count": 网格层数,
            "step_height": 每格间距,
            "adjusted": True/False (是否有调整),
            "reason": 调整原因,
        }
    """
    base_layers = config["base_layer_count"]
    min_layers = config["min_layer_count"]
    max_layers = config["max_layer_count"]
    volatility_factor = config["volatility_adjust_factor"]

    # 波动率自适应网格层数
    if volatility_pct > 3:
        # 高波动 → 减少层数、加大间距
        layer_count = max(min_layers, base_layers - int((volatility_pct - 3) * 2))
        grid_range_pct = volatility_pct * 3  # 网格范围 = 3倍ATR%
        adjusted = True
        reason = f"高波动({volatility_pct:.1f}%), 减少网格层数至{layer_count}"
    elif volatility_pct < 0.8:
        # 低波动 → 增加层数、缩窄间距
        layer_count = min(max_layers, base_layers + int((0.8 - volatility_pct) * 5))
        grid_range_pct = volatility_pct * 5
        adjusted = True
        reason = f"低波动({volatility_pct:.1f}%), 增加网格层数至{layer_count}"
    else:
        # 正常波动
        layer_count = base_layers
        grid_range_pct = volatility_pct * 4
        adjusted = False
        reason = "波动正常, 保持默认网格"

    # 情绪偏移（恐慌时下移网格，乐观时上移）
    sentiment_offset = 0
    if sentiment_score is not None:
        # sentiment_score 0=极负面 50=中性 100=极正面
        offset_ratio = config["sentiment_offset_max"]
        if sentiment_score < 40:
            # 恐慌 → 下移网格（降低买入价）
            sentiment_offset = -(40 - sentiment_score) / 40 * offset_ratio
            reason += f", 情绪偏空({sentiment_score}), 网格下移{abs(sentiment_offset)*100:.0f}%"
            adjusted = True
        elif sentiment_score > 60:
            # 乐观 → 上移网格（提高卖出目标）
            sentiment_offset = (sentiment_score - 60) / 40 * offset_ratio
            reason += f", 情绪偏多({sentiment_score}), 网格上移{sentiment_offset*100:.0f}%"
            adjusted = True

    if not adjusted:
        reason = "参数维持不变"

    # 计算上下界
    half_range = current_price * grid_range_pct / 100
    upper = current_price + half_range * (1 + sentiment_offset)
    lower = current_price - half_range * (1 - sentiment_offset)

    # 确保下界 > 0
    lower = max(lower, current_price * 0.3)

    # 每格间距
    step_height = (upper - lower) / layer_count if layer_count > 0 else 0

    # 检查价格是否在网格范围内
    price_position = (current_price - lower) / (upper - lower) if upper != lower else 0.5

    return {
        "upper_price": round(upper, 4),
        "lower_price": round(lower, 4),
        "step_count": layer_count,
        "step_height": round(step_height, 4),
        "adjusted": adjusted,
        "reason": reason,
        "price_position": round(price_position, 2),
    }


def _detect_breakout(
    prices: List[float],
    upper: float,
    lower: float,
    breakout_days: int,
) -> dict:
    """
    检测价格是否突破网格范围

    Returns:
        { "breakout": True/False, "direction": "up"/"down"/None,
          "duration": 突破持续天数, "reason": "" }
    """
    if len(prices) < breakout_days:
        return {"breakout": False, "direction": None, "duration": 0, "reason": "数据不足"}

    # 检查最近 N 天价格是否在网格范围外
    recent = prices[-breakout_days:]
    above_count = sum(1 for p in recent if p > upper)
    below_count = sum(1 for p in recent if p < lower)

    if above_count >= breakout_days:
        return {
            "breakout": True,
            "direction": "up",
            "duration": above_count,
            "reason": f"连续{above_count}天突破上界{upper}",
        }
    elif below_count >= breakout_days:
        return {
            "breakout": True,
            "direction": "down",
            "duration": below_count,
            "reason": f"连续{below_count}天跌破下界{lower}",
        }

    return {"breakout": False, "direction": None, "duration": 0, "reason": "价格在网格范围内"}


# ══════════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════════

def run(
    fund_id: int,
    fund_code: str,
    fund_name: str,
    prices: List[float],
    current_price: float,
    sentiment_score: Optional[float] = None,
    strategy_params: Optional[dict] = None,
    time_status: Optional[dict] = None,
) -> AgentSignal:
    """
    运行网格增强 Agent

    Args:
        fund_id: 基金ID
        fund_code: 基金代码
        fund_name: 基金名称
        prices: 历史价格序列
        current_price: 当前价
        sentiment_score: Market Agent 情绪分
        strategy_params: 当前策略参数
        time_status: 交易时间状态

    Returns:
        AgentSignal
    """
    if not prices or len(prices) < 14:
        return AgentSignal(
            agent="grid",
            signal=SignalType.HOLD,
            score=50.0,
            confidence=30.0,
            reason=["数据不足，至少需要14个价格点"],
            risk=50.0,
        )

    reasoning = []
    config = dict(DEFAULT_GRID_CONFIG)

    # 1. 计算波动率指标
    atr_value = _atr(prices, 14)
    volatility_pct = atr_value / current_price * 100 if current_price > 0 else 0

    reasoning.append(f"📊 ATR={atr_value:.4f}, 波动率={volatility_pct:.2f}%")

    # 2. 读取当前网格参数（如果已有）
    current_grid = strategy_params or {}

    # 3. 计算最优网格参数
    grid_params = _calculate_grid_params(
        current_price=current_price,
        atr_value=atr_value,
        volatility_pct=volatility_pct,
        config=config,
        sentiment_score=sentiment_score,
    )

    if grid_params["adjusted"]:
        reasoning.append(f"⚙️ {grid_params['reason']}")
    else:
        reasoning.append(f"⚙️ {grid_params['reason']}")

    reasoning.append(
        f"  网格范围: {grid_params['lower_price']} ~ {grid_params['upper_price']}, "
        f"{grid_params['step_count']}层, 间距{grid_params['step_height']}"
    )

    # 4. 突破检测
    breakout = _detect_breakout(
        prices,
        grid_params["upper_price"],
        grid_params["lower_price"],
        config["breakout_days"],
    )

    if breakout["breakout"]:
        direction_cn = "向上" if breakout["direction"] == "up" else "向下"
        reasoning.append(f"🚨 趋势突破! {breakout['reason']}")
        reasoning.append(f"  建议暂停网格, 考虑切换{direction_cn}趋势模式")
    else:
        reasoning.append(f"✅ 价格在网格范围内, {breakout['reason']}")

    # 5. 综合决策
    score = 50.0  # 中性

    if breakout["breakout"]:
        if breakout["direction"] == "up":
            score = 35  # 突破上界 → 暂停买入，观察是否真趋势
            signal = SignalType.PAUSE_GRID
            reasoning.append("📈 建议: 暂停网格, 等待趋势确认后再决定")
        else:
            score = 65  # 跌破下界 → 暂停卖出，等待反弹
            signal = SignalType.PAUSE_GRID
            reasoning.append("📉 建议: 暂停网格, 不接飞刀, 等待企稳")
    elif grid_params["adjusted"]:
        if "高波动" in grid_params["reason"]:
            score = 45
            signal = SignalType.ADJUST_GRID
            reasoning.append("🔄 建议: 按新参数调整网格")
        elif "低波动" in grid_params["reason"]:
            score = 55
            signal = SignalType.ADJUST_GRID
            reasoning.append("🔄 建议: 按新参数调整网格, 利用低波动套利")
        else:
            if sentiment_score is not None and sentiment_score < 40:
                score = 40
                signal = SignalType.ADJUST_GRID
            elif sentiment_score is not None and sentiment_score > 60:
                score = 60
                signal = SignalType.ADJUST_GRID
            else:
                score = 50
                signal = SignalType.HOLD
            reasoning.append("🔄 按情绪偏移调整网格位置")
    else:
        # 正常运行网格
        score = 65  # 震荡市网格策略置信度较高
        signal = SignalType.ENABLE_GRID
        reasoning.append("✅ 建议: 维持网格运行, 等待震荡套利")

    # 6. 风险评分
    risk = 0
    if volatility_pct > 3:
        risk += 30
    if breakout["breakout"]:
        risk += 25
    if sentiment_score is not None and sentiment_score < 30:
        risk += 20
    risk = min(90, risk + 10)

    # 置信度
    if breakout["breakout"]:
        confidence = 85  # 突破检测准确度高
    elif grid_params["adjusted"]:
        confidence = 70
    else:
        confidence = 60

    # QDII 检查
    qdii_note = ""
    if time_status:
        trade_info = time_status.get("tradeInfo", {})
        if trade_info.get("warnings"):
            qdii_warnings = [
                w for w in trade_info["warnings"]
                if "QDII" in w or "周五" in w or "长假" in w
            ]
            if qdii_warnings:
                reasoning.append(f"⏰ {'; '.join(qdii_warnings[:2])}")

    return AgentSignal(
        agent="grid",
        signal=signal,
        score=round(score, 1),
        confidence=round(confidence, 1),
        reason=reasoning,
        risk=round(risk, 1),
        expire_at=datetime.now().replace(hour=15, minute=0, second=0).isoformat(),
        extra={
            "grid_params": grid_params,
            "breakout": breakout,
            "volatility_pct": round(volatility_pct, 2),
            "atr_value": round(atr_value, 4),
        },
    )


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":

    # 模拟震荡行情
    import random
    random.seed(42)
    prices = []
    p = 1.5
    for i in range(60):
        p += random.uniform(-0.03, 0.03)
        p = max(p, 1.2)
        p = min(p, 1.8)
        prices.append(round(p, 4))

    signal = run(
        fund_id=3,
        fund_code="001938",
        fund_name="中欧时代先锋股票A",
        prices=prices,
        current_price=prices[-1],
        sentiment_score=45,
        strategy_params={"upperPrice": 1.50, "lowerPrice": 1.00, "stepCount": 5, "stepSize": 0.10},
    )
    print(signal.to_dict())
