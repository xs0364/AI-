"""
Trend Agent — 趋势跟踪 Agent
=============================
定位：纯计算 Agent，不调用 LLM
负责：多指标综合分析 → 趋势判断 → 买卖信号

指标体系（通过 ta 库计算）：
  - MACD(12,26,9)       趋势方向 + 金叉死叉 + 背离
  - RSI(14)               超买超卖
  - BOLL(20,2)           带宽 + 位置
  - ATR(14)               波动率
  - EMA(5,10,20,60)      多周期趋势

输出：统一 AgentSignal 格式
"""
import math
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd
import ta
from loguru import logger

from agent_schema import AgentSignal, SignalType


# ══════════════════════════════════════════════════════════════════
# 指标计算（用 ta 库替代手写）
# ══════════════════════════════════════════════════════════════════

def _to_series(prices: List[float]) -> pd.Series:
    """价格列表 → pandas Series"""
    return pd.Series(prices, dtype=float)


def _macd(prices: List[float]) -> dict:
    """MACD(12,26,9) 用 ta 库"""
    s = _to_series(prices)
    macd = ta.trend.MACD(s, window_slow=26, window_fast=12, window_sign=9)
    dif = macd.macd().values
    dea = macd.macd_signal().values
    hist = macd.macd_diff().values

    last = len(prices) - 1
    cd = float(dif[last]) if not np.isnan(dif[last]) else None
    ce = float(dea[last]) if not np.isnan(dea[last]) else None
    ch = float(hist[last]) if not np.isnan(hist[last]) else None
    pd_ = float(dif[last - 1]) if last > 0 and not np.isnan(dif[last - 1]) else None
    pe = float(dea[last - 1]) if last > 0 and not np.isnan(dea[last - 1]) else None

    signal = "neutral"
    if cd is not None and ce is not None and pd_ is not None and pe is not None:
        if pd_ <= pe and cd > ce:
            signal = "golden_cross"
        elif pd_ >= pe and cd < ce:
            signal = "death_cross"
        # 顶背离
        if last >= 5:
            if prices[last] > prices[last - 5] and (pd_ and cd and cd < pd_):
                signal = "divergence_bearish"
            if prices[last] < prices[last - 5] and (pd_ and cd and cd > pd_):
                signal = "divergence_bullish"

    return {"dif": round(cd, 4) if cd else None, "dea": round(ce, 4) if ce else None,
            "histogram": round(ch, 4) if ch else None, "signal": signal}


def _rsi(prices: List[float]) -> dict:
    """RSI(14) 用 ta 库"""
    if len(prices) < 15:
        return {"value": 50.0, "signal": "neutral"}
    s = _to_series(prices)
    val = float(ta.momentum.RSIIndicator(s, 14).rsi().iloc[-1])
    sig = "overbought" if val >= 70 else ("oversold" if val <= 30 else
                                           ("bullish" if val >= 50 else "bearish"))
    return {"value": round(val, 1), "signal": sig}


def _bollinger(prices: List[float]) -> dict:
    """布林带(20,2) 用 ta 库"""
    if len(prices) < 20:
        return {"upper": None, "mid": None, "lower": None,
                "bandwidth": None, "position": 50, "signal": "neutral"}
    s = _to_series(prices)
    bb = ta.volatility.BollingerBands(s, 20, 2)
    up = float(bb.bollinger_hband().iloc[-1])
    mid = float(bb.bollinger_mavg().iloc[-1])
    lo = float(bb.bollinger_lband().iloc[-1])
    bw = (up - lo) / mid if mid != 0 else 0
    pct = float(bb.bollinger_pband().iloc[-1]) * 100

    last_p = prices[-1]
    sig = "overbought" if last_p >= up else ("oversold" if last_p <= lo else
                                              ("high_volatility" if bw > 0.3 else
                                               ("low_volatility" if bw < 0.1 else "neutral")))
    return {"upper": round(up, 4), "mid": round(mid, 4), "lower": round(lo, 4),
            "bandwidth": round(bw, 4), "position": round(pct, 1), "signal": sig}


def _atr(prices: List[float]) -> dict:
    """ATR(14) 用 ta 库"""
    if len(prices) < 15:
        return {"value": 0, "percent": 0, "signal": "neutral"}
    s = _to_series(prices)
    atr_val = float(ta.volatility.AverageTrueRange(
        pd.Series([0.0] * len(prices)),  # high
        pd.Series([0.0] * len(prices)),  # low
        s, 14
    ).average_true_range().iloc[-1])
    # 用价格变动的平均绝对值近似 ATR
    diffs = np.abs(np.diff(prices[-15:]))
    atr_val = float(np.mean(diffs)) if len(diffs) > 0 else 0
    atr_pct = atr_val / prices[-1] * 100 if prices[-1] != 0 else 0
    sig = "high" if atr_pct > 3 else ("low" if atr_pct < 0.5 else "normal")
    return {"value": round(atr_val, 4), "percent": round(atr_pct, 2), "signal": sig}


def _trend_ema(prices: List[float]) -> dict:
    """多周期 EMA 趋势判断"""
    s = _to_series(prices)
    e5 = float(s.ewm(span=5, adjust=False).mean().iloc[-1])
    e10 = float(s.ewm(span=10, adjust=False).mean().iloc[-1])
    e20 = float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    e60 = float(s.ewm(span=60, adjust=False).mean().iloc[-1]) if len(prices) >= 60 else None

    if e5 and e10 and e20:
        if e60 and e5 > e10 > e20 > e60:
            return {"signal": "strong_bullish", "ema5": e5, "ema10": e10, "ema20": e20, "ema60": e60}
        if e60 and e5 < e10 < e20 < e60:
            return {"signal": "strong_bearish", "ema5": e5, "ema10": e10, "ema20": e20, "ema60": e60}
        if e5 > e10 > e20:
            return {"signal": "bullish", "ema5": e5, "ema10": e10, "ema20": e20, "ema60": e60}
        if e5 < e10 < e20:
            return {"signal": "bearish", "ema5": e5, "ema10": e10, "ema20": e20, "ema60": e60}
    return {"signal": "mixed", "ema5": e5, "ema10": e10, "ema20": e20, "ema60": e60}


def _determine_market_state(macd: dict, rsi_val: float, boll: dict, ema: dict) -> str:
    """综合判断市场状态"""
    bullish, bearish = 0, 0
    s = macd["signal"]
    if s == "golden_cross": bullish += 3
    elif s == "death_cross": bearish += 3
    elif s == "divergence_bullish": bullish += 2
    elif s == "divergence_bearish": bearish += 2

    if rsi_val >= 70: bearish += 1
    elif rsi_val <= 30: bullish += 1
    elif rsi_val >= 55: bullish += 1
    elif rsi_val <= 45: bearish += 1

    if boll["signal"] == "overbought": bearish += 1
    elif boll["signal"] == "oversold": bullish += 1

    es = ema["signal"]
    if es == "strong_bullish": bullish += 3
    elif es == "bullish": bullish += 2
    elif es == "strong_bearish": bearish += 3
    elif es == "bearish": bearish += 2

    diff = bullish - bearish
    if diff >= 4: return "strong_uptrend"
    if diff >= 1: return "uptrend"
    if diff <= -4: return "strong_downtrend"
    if diff <= -1: return "downtrend"
    return "range"


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
    daily_values: Optional[List[dict]] = None,
) -> AgentSignal:
    """
    运行趋势跟踪 Agent

    Args:
        fund_id: 基金ID
        fund_code: 基金代码
        fund_name: 基金名称
        prices: 历史价格序列（越新越靠后）
        current_price: 当前价格
        sentiment_score: Market Agent 传来的情绪分 (0-100)
        daily_values: 每日净值列表

    Returns:
        AgentSignal 统一格式
    """
    if not prices or len(prices) < 20:
        return AgentSignal(
            agent="trend",
            signal=SignalType.HOLD,
            score=50.0,
            confidence=0.0,
            reason=["数据不足（需至少20个价格点）"],
            risk=50.0,
        )

    # 1. 计算各指标
    macd = _macd(prices)
    rsi_data = _rsi(prices)
    boll = _bollinger(prices)
    atr_data = _atr(prices)
    ema_data = _trend_ema(prices)

    rsi_val = rsi_data["value"]

    # 2. 判断市场状态
    state = _determine_market_state(macd, rsi_val, boll, ema_data)

    # 3. 综合评分
    score = 50.0  # 中性基准
    reasoning = []
    weights = []

    # --- MACD 评分 ---
    macd_signal = macd["signal"]
    macd_histogram = macd.get("histogram", 0) or 0

    if macd_signal == "golden_cross":
        score += 20
        reasoning.append(f"📊 MACD金叉(DIF={macd['dif']}↑DEA={macd['dea']}), 买入信号 +20分")
        weights.append(("macd", 20, 0.25))
    elif macd_signal == "death_cross":
        score -= 20
        reasoning.append(f"📊 MACD死叉(DIF={macd['dif']}↓DEA={macd['dea']}), 卖出信号 -20分")
        weights.append(("macd", -20, 0.25))
    elif macd_signal == "divergence_bullish":
        score += 10
        reasoning.append(f"📊 MACD底背离, 可能反转向上 +10分")
        weights.append(("macd", 10, 0.20))
    elif macd_signal == "divergence_bearish":
        score -= 10
        reasoning.append(f"📊 MACD顶背离, 可能反转向下 -10分")
        weights.append(("macd", -10, 0.20))
    else:
        # 柱状图方向
        if macd_histogram > 0:
            score += 5
            reasoning.append(f"📊 MACD柱状图上升(DIF>DEA), 多头占优 +5分")
        elif macd_histogram < 0:
            score -= 5
            reasoning.append(f"📊 MACD柱状图下降(DIF<DEA), 空头占优 -5分")
        else:
            reasoning.append(f"📊 MACD中性")
        weights.append(("macd", 0, 0.20))

    # --- RSI 评分 ---
    if rsi_val >= 70:
        score -= 8
        reasoning.append(f"📊 RSI({rsi_val})超买区, 可能回调 -8分")
        weights.append(("rsi", -8, 0.15))
    elif rsi_val <= 30:
        score += 8
        reasoning.append(f"📊 RSI({rsi_val})超卖区, 可能反弹 +8分")
        weights.append(("rsi", 8, 0.15))
    elif rsi_val >= 55:
        score += 5
        reasoning.append(f"📊 RSI({rsi_val})偏多 +5分")
        weights.append(("rsi", 5, 0.15))
    elif rsi_val <= 45:
        score -= 5
        reasoning.append(f"📊 RSI({rsi_val})偏空 -5分")
        weights.append(("rsi", -5, 0.15))
    else:
        reasoning.append(f"📊 RSI({rsi_val})中性")
        weights.append(("rsi", 0, 0.15))

    # --- 布林带评分 ---
    boll_signal = boll["signal"]
    boll_position = boll.get("position", 50)

    if boll_signal == "overbought":
        score -= 5
        reasoning.append(f"📊 BOLL触及上轨({boll['upper']}), 超买 -5分")
        weights.append(("boll", -5, 0.15))
    elif boll_signal == "oversold":
        score += 5
        reasoning.append(f"📊 BOLL触及下轨({boll['lower']}), 超卖 +5分")
        weights.append(("boll", 5, 0.15))
    elif boll_signal == "high_volatility":
        reasoning.append(f"📊 BOLL带宽({boll['bandwidth']})扩大, 波动加剧")
        weights.append(("boll", 0, 0.12))
    elif boll_signal == "low_volatility":
        reasoning.append(f"📊 BOLL带宽({boll['bandwidth']})收窄, 可能变盘")
        weights.append(("boll", 0, 0.12))
    else:
        reasoning.append(f"📊 BOLL位置{boll_position:.0f}%, 处于中轨附近")
        weights.append(("boll", 0, 0.10))

    # --- EMA 趋势评分 ---
    ema_signal = ema_data["signal"]
    if ema_signal == "strong_bullish":
        score += 15
        reasoning.append(f"📊 EMA多头排列(5>{ema_data['ema5']:.4f}>10>{ema_data['ema10']:.4f}>20>{ema_data['ema20']:.4f}), 上升趋势确认 +15分")
        weights.append(("ema", 15, 0.25))
    elif ema_signal == "bullish":
        score += 8
        reasoning.append(f"📊 EMA短期偏多 +8分")
        weights.append(("ema", 8, 0.20))
    elif ema_signal == "strong_bearish":
        score -= 15
        reasoning.append(f"📊 EMA空头排列, 下降趋势确认 -15分")
        weights.append(("ema", -15, 0.25))
    elif ema_signal == "bearish":
        score -= 8
        reasoning.append(f"📊 EMA短期偏空 -8分")
        weights.append(("ema", -8, 0.20))
    else:
        reasoning.append(f"📊 EMA排列混乱, 趋势不明")
        weights.append(("ema", 0, 0.15))

    # --- ATR 波动率评估 ---
    atr_pct = atr_data["percent"]
    if atr_pct > 3:
        reasoning.append(f"📊 ATR({atr_pct:.1f}%)波动率偏高, 注意风险")
    elif atr_pct < 0.5:
        reasoning.append(f"📊 ATR({atr_pct:.1f}%)波动率偏低, 市场平淡")
    else:
        reasoning.append(f"📊 ATR({atr_pct:.1f}%)波动率正常")

    # --- 情绪分修正 (来自 Market Agent) ---
    if sentiment_score is not None:
        sentiment_delta = (sentiment_score - 50) * 0.15  # 情绪转为±7.5分
        score += sentiment_delta
        direction = "积极" if sentiment_delta > 0 else ("消极" if sentiment_delta < 0 else "中性")
        reasoning.append(f"📰 市场情绪分({sentiment_score}), {direction}, 修正{sentiment_delta:+.1f}分")

    # --- 计算置信度 ---
    # 置信度：指标一致性越高，置信度越高
    pos_weight = sum(w[1] for w in weights if w[1] > 0)
    neg_weight = abs(sum(w[1] for w in weights if w[1] < 0))
    total_magnitude = pos_weight + neg_weight
    net = pos_weight - neg_weight
    if total_magnitude > 0:
        # 一致性 = (强势方 - 弱势方) / 总量，比例越高越一致
        confidence = abs(net) / total_magnitude * 100
    else:
        confidence = 30  # 所有指标中性时，低置信度

    confidence = min(95, max(10, confidence))

    # --- 信号判定 ---
    score = min(100, max(0, score))
    risk = 100 - score if score < 50 else score * 0.4
    risk = min(90, max(5, risk))

    if score >= 75:
        signal = SignalType.STRONG_BUY
    elif score >= 60:
        signal = SignalType.BUY
    elif score >= 45:
        signal = SignalType.HOLD
    elif score >= 30:
        signal = SignalType.LIGHTEN_SELL
    elif score >= 15:
        signal = SignalType.SELL
    else:
        signal = SignalType.STRONG_SELL

    # 超买但趋势强 → 不下卖出指令
    if macd_signal == "golden_cross" and rsi_val > 70:
        if signal in (SignalType.SELL, SignalType.LIGHTEN_SELL):
            signal = SignalType.HOLD
            reasoning.append("⚠️ MACD金叉但RSI超买, 冲突信号→HOLD")

    # 超卖但趋势弱 → 不下买入指令
    if macd_signal == "death_cross" and rsi_val < 30:
        if signal in (SignalType.BUY, SignalType.STRONG_BUY):
            signal = SignalType.HOLD
            reasoning.append("⚠️ MACD死叉但RSI超卖, 冲突信号→HOLD")

    return AgentSignal(
        agent="trend",
        signal=signal,
        score=round(score, 1),
        confidence=round(confidence, 1),
        reason=reasoning,
        risk=round(risk, 1),
        expire_at=datetime.now().replace(hour=15, minute=0, second=0).isoformat(),
        extra={
            "market_state": state,
            "indicators": {
                "macd": macd,
                "rsi": rsi_data,
                "bollinger": boll,
                "atr": atr_data,
                "ema": ema_data,
            },
        },
    )


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import random
    random.seed(42)
    prices = []
    p = 2.0
    for i in range(60):
        p += random.gauss(0.005, 0.02)
        p = max(p, 1.0)
        prices.append(round(p, 4))

    signal = run(
        fund_id=1,
        fund_code="110011",
        fund_name="易方达中小盘混合",
        prices=prices,
        current_price=prices[-1],
        sentiment_score=65,
    )
    print(signal.to_dict())
