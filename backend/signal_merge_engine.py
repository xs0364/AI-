"""
Signal Merge Engine — 多 Agent 信号融合
==========================================
定位：纯规则引擎，不调用 LLM
负责：接收多个 AgentSignal，按优先级+权重融合为统一决策

融合规则：
  1. 否决制：任何人打出 STRONG_SELL / STOP_LOSS → 采纳
  2. 强买保护：STRONG_BUY 除非有 SELL 以上对冲 → 采纳
  3. 加权平均：其余情况按权重加权
  4. 风险上限：风险评分 > 80 → 强制 HOLD
  5. 过期检查：expire_at 过期的信号被忽略
  6. 最早过期时间作为最终 expire_at
"""
from datetime import datetime
from typing import List

from loguru import logger

from agent_schema import AgentSignal, SignalType, MergedDecision

# ── Agent 权重（经验值，可调） ─────────────────────────────────────

AGENT_WEIGHTS = {
    "trend": 0.40,
    "grid": 0.25,
    "market": 0.35,
}

# 信号强度映射（用于排序）
SIGNAL_STRENGTH = {
    SignalType.STRONG_SELL: -100,
    SignalType.STOP_LOSS:   -90,
    SignalType.SELL:         -60,
    SignalType.LIGHTEN_SELL: -40,
    SignalType.REDUCE:       -30,
    SignalType.PAUSE_GRID:   -20,
    SignalType.ADJUST_GRID:  -10,
    SignalType.HOLD:           0,
    SignalType.NEUTRAL:        0,
    SignalType.ENABLE_GRID:   10,
    SignalType.SWITCH_TREND:  15,
    SignalType.INCREASE:      20,
    SignalType.LIGHTEN_BUY:   30,
    SignalType.BUY:           60,
    SignalType.STRONG_BUY:    80,
    SignalType.ALERT:          0,
    SignalType.POSITIVE:      20,
    SignalType.NEGATIVE:     -20,
}


def _score_to_signal(score: float) -> SignalType:
    """将融合后的分数转为信号枚举"""
    if score >= 80:
        return SignalType.STRONG_BUY
    elif score >= 65:
        return SignalType.BUY
    elif score >= 45:
        return SignalType.HOLD
    elif score >= 30:
        return SignalType.LIGHTEN_SELL
    elif score >= 15:
        return SignalType.SELL
    else:
        return SignalType.STRONG_SELL


def merge(signals: List[AgentSignal]) -> MergedDecision:
    """
    融合多个 Agent 信号 → 输出最终决策

    Args:
        signals: AgentSignal 列表（可含 None，会被过滤）

    Returns:
        MergedDecision
    """
    date_begin = datetime.now()

    # 过滤无效信号
    valid = [
        s for s in signals
        if s is not None and s.signal is not None
    ]
    if not valid:
        return MergedDecision(
            signal=SignalType.HOLD,
            score=50,
            confidence=0,
            reasons=["无有效信号"],
            risk=50,
            expire_at=None,
            should_execute=False,
        )

    # ── 第一关：否决制检查 ──────────────────────────────────────

    has_stop_loss = any(s.signal == SignalType.STOP_LOSS for s in valid)
    has_strong_sell = any(s.signal == SignalType.STRONG_SELL for s in valid)

    if has_stop_loss:
        return MergedDecision(
            signal=SignalType.STOP_LOSS,
            score=0,
            confidence=100,
            reasons=["🛑 风控止损信号触发"],
            risk=100,
            expire_at=_earliest_expire(valid),
            agents_contributions=[s.to_dict() for s in valid],
            should_execute=True,
        )

    if has_strong_sell:
        # 检查是否有 STRONG_BUY 对冲
        has_strong_buy = any(s.signal == SignalType.STRONG_BUY for s in valid)
        if not has_strong_buy:
            return MergedDecision(
                signal=SignalType.STRONG_SELL,
                score=10,
                confidence=90,
                reasons=["🔴 趋势Agent强烈卖出建议"],
                risk=85,
                expire_at=_earliest_expire(valid),
                agents_contributions=[s.to_dict() for s in valid],
                should_execute=True,
            )

    # ── 第二关：强买保护 ────────────────────────────────────────
    has_strong_buy = any(s.signal == SignalType.STRONG_BUY for s in valid)
    has_sell_or_worse = any(
        s.signal in (SignalType.SELL, SignalType.STRONG_SELL, SignalType.STOP_LOSS)
        for s in valid
    )
    if has_strong_buy and not has_sell_or_worse:
        # 采纳强买
        return _build_merged(
            valid, SignalType.STRONG_BUY, expire=_earliest_expire(valid)
        )

    # ── 第三关：风险检查 ────────────────────────────────────────
    max_risk = max(s.risk for s in valid)
    if max_risk > 80:
        reasons = [f"⚠️ 风险评估={max_risk:.0f}, 超过80上限, 强制持有"]
        reasons.extend(s.reason[0] if s.reason else "" for s in valid[:3])
        return MergedDecision(
            signal=SignalType.HOLD,
            score=50,
            confidence=60,
            reasons=reasons,
            risk=max_risk,
            expire_at=_earliest_expire(valid),
            agents_contributions=[s.to_dict() for s in valid],
            should_execute=False,
        )

    # ── 第四关：加权平均融合 ────────────────────────────────────
    weighted_score = 0.0
    weighted_conf = 0.0
    total_weight = 0.0
    merged_reasons = []
    contributions = []

    for s in valid:
        weight = AGENT_WEIGHTS.get(s.agent, 0.33)
        if s.confidence > 0:
            # 高置信度的信号权重更大
            effective_weight = weight * (s.confidence / 50)
        else:
            effective_weight = weight * 0.5

        weighted_score += s.score * effective_weight
        weighted_conf += s.confidence * effective_weight
        total_weight += effective_weight
        contributions.append({
            "agent": s.agent,
            "signal": s.signal.value,
            "score": s.score,
            "confidence": s.confidence,
            "weight": round(effective_weight, 3),
            "extra": s.extra,
        })

        # 取每个 Agent 的第一条原因
        if s.reason:
            merged_reasons.append(f"[{s.agent}] {s.reason[0]}")

    if total_weight > 0:
        final_score = weighted_score / total_weight
        final_conf = weighted_conf / total_weight
    else:
        final_score = 50.0
        final_conf = 50.0

    # 分数 → 信号
    final_signal = _score_to_signal(final_score)

    # 加权风险
    final_risk = sum(s.risk * AGENT_WEIGHTS.get(s.agent, 0.33) for s in valid)
    final_risk = min(100, max(0, final_risk))

    # 过期时间
    expire = _earliest_expire(valid)

    # 是否执行交易
    should_execute = final_signal in (
        SignalType.STRONG_BUY, SignalType.BUY,
        SignalType.SELL, SignalType.STRONG_SELL,
        SignalType.LIGHTEN_BUY, SignalType.LIGHTEN_SELL,
        SignalType.STOP_LOSS, SignalType.REDUCE, SignalType.INCREASE,
    )

    return MergedDecision(
        signal=final_signal,
        score=round(final_score, 1),
        confidence=round(final_conf, 1),
        reasons=merged_reasons[:5],
        risk=round(final_risk, 1),
        expire_at=expire,
        agents_contributions=contributions,
        should_execute=should_execute,
    )


def _earliest_expire(signals: List[AgentSignal]) -> str:
    """取所有信号中最早的过期时间"""
    times = []
    for s in signals:
        if s.expire_at:
            try:
                t = datetime.fromisoformat(s.expire_at)
                times.append(t)
            except (ValueError, TypeError):
                continue

    if not times:
        return datetime.now().replace(hour=15, minute=0, second=0).isoformat()

    earliest = min(times)
    return earliest.isoformat()


def _build_merged(
    signals: List[AgentSignal],
    signal: SignalType,
    expire: str,
) -> MergedDecision:
    """快速构建融合结果（否决/强买保护时用）"""
    signals_sorted = sorted(
        signals,
        key=lambda s: SIGNAL_STRENGTH.get(s.signal, 0),
        reverse=(signal in (SignalType.STRONG_BUY, SignalType.BUY)),
    )

    top = signals_sorted[0] if signals_sorted else None
    score = top.score if top else 50
    confidence = max(s.confidence for s in signals) if signals else 50
    risk = top.risk if top else 50
    reasons = []
    for s in signals[:3]:
        if s.reason:
            reasons.append(f"[{s.agent}] {s.reason[0]}")

    return MergedDecision(
        signal=signal,
        score=round(score, 1),
        confidence=round(confidence, 1),
        reasons=reasons,
        risk=round(risk, 1),
        expire_at=expire,
        agents_contributions=[dict(s.to_dict(), extra=s.extra) for s in signals],
        should_execute=True,
    )


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":

    from agent_schema import AgentSignal, SignalType

    signals = [
        AgentSignal(
            agent="trend", signal=SignalType.BUY, score=72, confidence=80,
            reason=["MACD金叉"], risk=25,
        ),
        AgentSignal(
            agent="grid", signal=SignalType.HOLD, score=48, confidence=60,
            reason=["震荡市"], risk=30,
        ),
        AgentSignal(
            agent="market", signal=SignalType.NEGATIVE, score=35, confidence=75,
            reason=["集采利空"], risk=60, affected_funds=["005827"],
        ),
    ]

    decision = merge(signals)
    print(decision.to_dict())
