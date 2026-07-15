"""
统一 Agent Schema — 所有 Agent 输出格式契约
===========================================
确保任意 Agent 可插拔，Signal Merge Engine 零改动接收

原理：
  - 所有 Agent 输出同一 Schema，永不互相调用
  - score 总在 [0-100] 范围
  - signal 统一枚举，Merge Engine 据此融合
  - reason 每条 < 80 字，Markdown 符号开头
"""
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from enum import Enum


# ═══════════════════════════════════════════════════════════════════
# 信号枚举
# ═══════════════════════════════════════════════════════════════════

class SignalType(str, Enum):
    """统一信号类型枚举 — 所有 Agent 共用"""

    # ── 资金动作 ──
    STRONG_BUY    = "STRONG_BUY"     # 强烈买入（多指标共振+高置信度）
    BUY           = "BUY"            # 买入
    LIGHTEN_BUY   = "LIGHTEN_BUY"    # 轻仓试仓
    HOLD          = "HOLD"           # 持仓不动
    LIGHTEN_SELL  = "LIGHTEN_SELL"   # 减仓观察
    SELL          = "SELL"           # 卖出
    STRONG_SELL   = "STRONG_SELL"    # 清仓离场

    # ── 策略状态切换 ──
    ENABLE_GRID   = "ENABLE_GRID"    # 启用网格策略
    PAUSE_GRID    = "PAUSE_GRID"     # 暂停网格（趋势来临/波动异常）
    ADJUST_GRID   = "ADJUST_GRID"   # 调整网格参数
    SWITCH_TREND  = "SWITCH_TREND"  # 切换到趋势模式

    # ── 信息/情绪 ──
    POSITIVE      = "POSITIVE"       # 正面情绪/利好
    NEUTRAL       = "NEUTRAL"        # 中性
    NEGATIVE      = "NEGATIVE"       # 负面情绪/利空
    ALERT         = "ALERT"          # 告警

    # ── 风控 ──
    REDUCE        = "REDUCE"         # 降低仓位
    STOP_LOSS     = "STOP_LOSS"      # 止损
    INCREASE      = "INCREASE"       # 加仓


# ═══════════════════════════════════════════════════════════════════
# 统一输出 Schema
# ═══════════════════════════════════════════════════════════════════

@dataclass
class AgentSignal:
    """
    每个 Agent 的输出数据包

    Field             说明
    ─────             ────
    agent             Agent 标识: "trend" / "grid" / "market"
    signal            枚举信号
    score             综合评分 0-100 (越高越看多)
    confidence        置信度 0-100 (本Agent对自己的判断有多确信)
    reason            推理链，每条中文字符串
    risk              风险评分 0-100 (0=无风险, 100=极高风险)
    expire_at         信号过期时间 (ISO格式)，默认当日 15:00
    affected_funds    仅 Market Agent 使用：受影响的基金ID列表
    extra             Agent 特有的额外数据 (如指示器详细值)
    """
    agent: str
    signal: SignalType
    score: float
    confidence: float
    reason: List[str]
    risk: float = 0.0
    expire_at: Optional[str] = None
    affected_funds: Optional[List[int]] = None
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        """转成 dict（枚举转字符串）"""
        d = asdict(self)
        d["signal"] = self.signal.value
        return d


@dataclass
class AgentInput:
    """
    每个 Agent 收到的统一输入

    Field             说明
    ─────             ────
    fund_id           基金ID
    fund_code         基金代码 (如 110011)
    fund_name         基金名称
    prices            历史价格序列 [p0, p1, ..., pN] (N=最新)
    current_price     当前价格
    sentiment_score   Market Agent 输出的情绪分 (0=极负面, 100=极正面),
                      未分析时为 None
    strategy_params   当前策略参数 dict
    strategy_type     "ma" / "grid" / None
    time_status       交易时间状态快照 (from trading_time_engine)
    daily_values      每日净值列表 [{date, totalValue}, ...]
    """
    fund_id: int
    fund_code: str
    fund_name: str
    prices: List[float]
    current_price: float
    sentiment_score: Optional[float] = None
    strategy_params: Optional[dict] = None
    strategy_type: Optional[str] = None
    time_status: Optional[dict] = None
    daily_values: Optional[List[dict]] = None


# ═══════════════════════════════════════════════════════════════════
# 风控系统类型
# ═══════════════════════════════════════════════════════════════════

@dataclass
class RiskConfig:
    """
    风控系统全局配置

    层级含义：
      1. 资金风控 — 单笔/单基金/单行业仓位上限、现金保留
      2. 仓位管理 — 动态仓位系数（Trend Score → 仓位比例映射）
      3. 止损系统 — 固定/ATR/Trailing/时间止损参数
      4. 回撤控制 — 账户回撤分级降仓阈值
      5. 市场状态 — 情绪分数档过滤
      6. 综合风控 — 评分权重配置
    """
    # ── 1. 资金风控 ──
    single_trade_cap_pct: float = 0.05       # 单笔交易最大仓位比例 (5%)
    single_fund_cap_pct: float = 0.15        # 单基金最大持仓 (15%)
    cash_reserve_pct: float = 0.20           # 最低现金留存 (20%)

    # ── 2. 仓位管理 ──
    # Trend Score → 仓位比例映射: [(score_threshold, position_pct), ...]
    # score 0-100, position 0.0-1.0
    position_tiers: list = field(default_factory=lambda: [
        (80, 1.0),    # score ≥ 80: 满仓 (≤ single_fund_cap)
        (60, 0.75),   # score ≥ 60: 75%
        (40, 0.50),   # score ≥ 40: 50%
        (20, 0.25),   # score ≥ 20: 25%
        (0,  0.0),    # score < 20: 不建仓
    ])

    # ── 3. 止损系统 ──
    stop_loss_fixed_pct: float = 0.08        # 固定止损 8%
    stop_loss_atr_multiple: float = 2.0      # ATR 倍数止损
    stop_loss_trailing_activate_pct: float = 0.10  # 盈利 10% 启动 trailing
    stop_loss_trailing_distance_pct: float = 0.05  # trailing 回撤 5% 触发
    stop_loss_time_days: int = 30            # 持仓超过 30 天无条件评估

    # ── 4. 回撤控制 ──
    drawdown_tiers: list = field(default_factory=lambda: [
        (5,  1.0),    # 回撤 < 5%: 正常
        (10, 0.50),   # 回撤 5-10%: 减半仓
        (15, 0.20),   # 回撤 10-15%: 仅保留 20%
        (100, 0.0),   # 回撤 > 15%: 清仓
    ])

    # ── 5. 市场状态滤网 ──
    sentiment_good_min: float = 40.0         # 情绪分 ≥ 40 可正常交易
    sentiment_bad_max: float = 20.0          # 情绪分 < 20 禁止开新仓

    # ── 6. 综合评分权重 ──
    risk_weight_capital: float = 0.20
    risk_weight_position: float = 0.20
    risk_weight_stop_loss: float = 0.20
    risk_weight_drawdown: float = 0.25
    risk_weight_market: float = 0.15


@dataclass
class RiskVerdict:
    """
    风控引擎统一输出

    Field            说明
    ─────            ────
    allow            是否允许执行交易
    risk_score       综合风险评分 0-100 (0=无风险, 100=极高风险)
    risk_level       风险等级: "normal" / "caution" / "danger" / "critical"
    max_position     建议最大仓位比例 0.0-1.0
    stop_loss_price  建议止损价格 (None=不触发)
    take_profit      建议止盈价格 (None=不触发)
    layer_scores     各层独立评分 dict
    reasons          风控理由列表
    """
    allow: bool = True
    risk_score: float = 0.0
    risk_level: str = "normal"
    max_position: float = 1.0
    stop_loss_price: Optional[float] = None
    take_profit: Optional[float] = None
    layer_scores: dict = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════
# 融合结果
# ═══════════════════════════════════════════════════════════════════

@dataclass
class MergedDecision:
    """
    Signal Merge Engine 输出

    信号融合规则：
      1. 任何人打出 STRONG_SELL / STOP_LOSS → 一律采纳
      2. 任何人打出 STRONG_BUY → 除非有 SELL 对冲否则采纳
      3. 其余取加权平均，阈值参照全局权重
      4. 风险评分 > 80 无论信号方向一律 HOLD
      5. expire_at 取所有信号中最早的那个
    """
    signal: SignalType
    score: float
    confidence: float
    reasons: List[str]
    risk: float
    expire_at: Optional[str]
    agents_contributions: List[dict] = field(default_factory=list)
    should_execute: bool = False
    trade_quantity: float = 0.0
    trade_price: float = 0.0
    risk_verdict: Optional[RiskVerdict] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signal"] = self.signal.value
        d["agents_contributions"] = [
            {k: v.value if isinstance(v, SignalType) else v
             for k, v in c.items()}
            for c in d["agents_contributions"]
        ]
        if d.get("risk_verdict") and isinstance(d["risk_verdict"], dict):
            d["risk_verdict"] = {
                k: v for k, v in d["risk_verdict"].items()
                if v is not None
            }
        return d
