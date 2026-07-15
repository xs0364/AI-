"""
交易时间引擎 — 基金买卖盈利必须卡死的所有时间节点
=================================================
覆盖：场外基金 15:00 分界线 | 场内 ETF | 计息/费率时间 | QDII 时差 | 节假日 | 操作窗口

核心原则：
  1. 所有买卖操作交易日 14:30-14:55 完成，卡死 15 点分界线
  2. 短线务必持有满 7 天再卖，规避 1.5% 高额赎回费
  3. 长假操作一律在节前最后一日 15 点前完成
  4. QDII 看海外收盘时差，利好隔夜消息次日早盘立刻操作
"""

from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

# ═══════════════════════════════════════════════════════════════════════════════
# 一、 中国 A 股交易日历 (2024-2026)
# ═══════════════════════════════════════════════════════════════════════════════

# 法定节假日 → 休市日期范围（包含首尾）
CN_HOLIDAYS: Dict[int, List[Dict[str, str]]] = {
    2024: [
        {"name": "元旦", "start": "2024-01-01", "end": "2024-01-01"},
        {"name": "春节", "start": "2024-02-09", "end": "2024-02-18"},
        {"name": "清明节", "start": "2024-04-04", "end": "2024-04-06"},
        {"name": "劳动节", "start": "2024-05-01", "end": "2024-05-05"},
        {"name": "端午节", "start": "2024-06-08", "end": "2024-06-10"},
        {"name": "中秋节", "start": "2024-09-15", "end": "2024-09-17"},
        {"name": "国庆节", "start": "2024-10-01", "end": "2024-10-07"},
    ],
    2025: [
        {"name": "元旦", "start": "2025-01-01", "end": "2025-01-01"},
        {"name": "春节", "start": "2025-01-28", "end": "2025-02-04"},
        {"name": "清明节", "start": "2025-04-04", "end": "2025-04-06"},
        {"name": "劳动节", "start": "2025-05-01", "end": "2025-05-05"},
        {"name": "端午节", "start": "2025-05-31", "end": "2025-06-02"},
        {"name": "国庆中秋", "start": "2025-10-01", "end": "2025-10-08"},
    ],
    2026: [
        {"name": "元旦", "start": "2026-01-01", "end": "2026-01-01"},
        {"name": "春节", "start": "2026-02-16", "end": "2026-02-24"},
        {"name": "清明节", "start": "2026-04-04", "end": "2026-04-06"},
        {"name": "劳动节", "start": "2026-05-01", "end": "2026-05-05"},
        {"name": "端午节", "start": "2026-06-19", "end": "2026-06-21"},
        {"name": "中秋节", "start": "2026-09-26", "end": "2026-09-28"},
        {"name": "国庆节", "start": "2026-10-01", "end": "2026-10-07"},
    ],
}

# 春节/国庆长假节前最后交易日（用于提示操作窗口）
HOLIDAY_LAST_TRADING_DAYS: Dict[str, str] = {
    "2024-02-08": "2024年春节",
    "2024-09-30": "2024年国庆节",
    "2025-01-27": "2025年春节",
    "2025-09-30": "2025年国庆中秋节",
    "2026-02-13": "2026年春节",
    "2026-09-30": "2026年国庆节",
}


# ═══════════════════════════════════════════════════════════════════════════════
# 二、 核心时间规则常量
# ═══════════════════════════════════════════════════════════════════════════════

class TradeTimeConstants:
    """场外基金交易核心时间节点"""

    # ── 15:00 生死分界线 ──
    CUTOFF_HOUR = 15
    CUTOFF_MINUTE = 0

    # ── 场内 A 股交易时段 ──
    A_MARKET_OPEN = (9, 30)       # 开盘
    A_MARKET_MORNING_CLOSE = (11, 30)  # 午休
    A_MARKET_AFTERNOON_OPEN = (13, 0)  # 下午开盘
    A_MARKET_CLOSE = (15, 0)      # 收盘
    A_MARKET_CALL_AUCTION = (14, 57)   # 尾盘集合竞价开始

    # ── 场内 T+0 品种 ──
    T0_SYMBOLS = ["纳指ETF", "恒生科技", "黄金ETF", "国债ETF",
                  "标普ETF", "日经ETF", "中概互联ETF"]

    # ── 最优操作窗口 ──
    OPTIMAL_BUY_WINDOW_START = (14, 30)
    OPTIMAL_BUY_WINDOW_END = (14, 55)   # 买入/卖出最佳时间
    OPTIMAL_SELL_WINDOW_START = (14, 40)
    OPTIMAL_SELL_WINDOW_END = (14, 55)

    # 早盘利好买入窗口
    MORNING_NEWS_WINDOW_START = (9, 30)
    MORNING_NEWS_WINDOW_END = (10, 0)

    # ── 赎回费率节点（从确认日开始算持有天数）──
    REDEMPTION_FEE_SCHEDULE = [
        (0, 7, 0.015),     # 持有 < 7 天：惩罚性 1.5%（绝对避开）
        (7, 365, 0.005),   # 7 天 – 1 年：0.5%
        (365, 730, 0.0025),# 1 – 2 年：0.25%
        (730, None, 0.0),  # 2 年以上：0%
    ]

    # ── 赎回费率说明（前端展示用）──
    REDEMPTION_FEE_SCHEDULE_DISPLAY = [
        {"minDays": 0, "maxDays": 7, "feeRate": 0.015, "note": "惩罚性1.5%"},
        {"minDays": 7, "maxDays": 365, "feeRate": 0.005, "note": "0.5%"},
        {"minDays": 365, "maxDays": 730, "feeRate": 0.0025, "note": "0.25%"},
        {"minDays": 730, "maxDays": None, "feeRate": 0.0, "note": "0%免费"},
    ]

    # ── QDII 到账周期 ──
    QDII_SETTLEMENT_DAYS = (7, 10)  # T+7 ~ T+10 到账

    # ── 海外市场交易时间（北京时间）──
    US_MARKET_OPEN = (21, 30)      # 夏令时（冬令时 22:30）
    US_MARKET_CLOSE = (4, 0)       # 次日凌晨
    HK_MARKET_OPEN = (9, 30)
    HK_MARKET_CLOSE = (16, 0)      # 港股 16:00 收盘


# ═══════════════════════════════════════════════════════════════════════════════
# 三、 交易日判断
# ═══════════════════════════════════════════════════════════════════════════════

def _date_from_str(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _is_weekend(d: date) -> bool:
    return d.weekday() >= 5  # Saturday=5, Sunday=6


def _in_holiday_range(d: date, holiday: Dict[str, str]) -> bool:
    start = _date_from_str(holiday["start"])
    end = _date_from_str(holiday["end"])
    return start <= d <= end


def is_trading_day(d: date = None) -> bool:
    """判断某日是否为 A 股交易日"""
    if d is None:
        d = date.today()
    if _is_weekend(d):
        return False
    for holidays in CN_HOLIDAYS.values():
        for h in holidays:
            if _in_holiday_range(d, h):
                return False
    return True


def next_trading_day(d: date = None) -> date:
    """获取下个交易日"""
    if d is None:
        d = date.today()
    while True:
        d += timedelta(days=1)
        if is_trading_day(d):
            return d


def prev_trading_day(d: date = None) -> date:
    """获取上个交易日"""
    if d is None:
        d = date.today()
    while True:
        d -= timedelta(days=1)
        if is_trading_day(d):
            return d


def is_last_trading_day_before_holiday(d: date = None) -> Optional[str]:
    """判断当日是否为长假前最后交易日，返回假期名称或 None"""
    if d is None:
        d = date.today()
    d_str = d.strftime("%Y-%m-%d")
    return HOLIDAY_LAST_TRADING_DAYS.get(d_str)


def is_friday_afternoon_warning(dt: datetime = None) -> bool:
    """周五 15:00 后买入警告"""
    if dt is None:
        dt = datetime.now()
    return dt.weekday() == 4 and (dt.hour > 15 or (dt.hour == 15 and dt.minute >= 0))


def is_pre_holiday_warning(dt: datetime = None) -> bool:
    """长假前最后交易日 15:00 后买入警告"""
    if dt is None:
        dt = datetime.now()
    if dt.hour < 15 or (dt.hour == 15 and dt.minute == 0):
        return False
    return is_last_trading_day_before_holiday(dt.date()) is not None


# ═══════════════════════════════════════════════════════════════════════════════
# 四、 场外基金时间校验
# ═══════════════════════════════════════════════════════════════════════════════

def is_before_1500(dt: datetime = None) -> bool:
    """判断当前是否在 15:00 之前（场外核心生死线）"""
    if dt is None:
        dt = datetime.now()
    return dt.hour < TradeTimeConstants.CUTOFF_HOUR or (
        dt.hour == TradeTimeConstants.CUTOFF_HOUR and dt.minute < TradeTimeConstants.CUTOFF_MINUTE
    )


def get_trade_nav_date(buy_time: datetime = None) -> Dict:
    """
    根据买入/卖出时间，返回成交净值日期和确认日期

    返回：
    {
        "tradeDate": "2026-07-13",       # 按哪天的净值成交
        "confirmDate": "2026-07-14",     # 份额确认日（T+1）
        "valueDate": "2026-07-14",       # 开始计息日
        "sameDayConfirm": True/False,     # 是否为 15:00 前
        "warning": "..."                 # 如果有风险则提示
    }
    """
    if buy_time is None:
        buy_time = datetime.now()

    same_day = is_before_1500(buy_time) and is_trading_day(buy_time.date())
    today = buy_time.date()

    if same_day:
        # 15:00 前 + 交易日 → 当天净值，T+1 确认
        trade_date = today
        next_day = next_trading_day(today)
        confirm_date = next_day
        value_date = next_day
    else:
        # 15:00 后 或 非交易日 → 顺延至下一交易日
        next_day = next_trading_day(today)
        trade_date = next_day
        confirm_date = next_trading_day(next_day)
        value_date = confirm_date

    warnings = []
    if buy_time.weekday() == 4 and not same_day:
        warnings.append("⚠️ 周五15点后买入 → 按下周一净值，周末两天上涨完全吃不到")
    if is_last_trading_day_before_holiday(today) and not same_day:
        holiday = is_last_trading_day_before_holiday(today)
        warnings.append(f"⚠️ 长假前最后交易日15点后买入 → 按节后首日净值，假期上涨全部吃不到")
    if buy_time.hour >= 14 and buy_time.hour < 15 and is_trading_day(today):
        if buy_time.hour == 14 and buy_time.minute >= 57:
            warnings.append("⚠️ 尾盘14:57后接近收盘，注意操作时间是否充足")

    # 检查是否为周五
    if buy_time.weekday() >= 5 and not is_trading_day(today):
        warnings.append("ℹ️ 周末/节假日下单 → 归节后第一个交易日T日净值，长假会凭空损失多天行情收益")

    return {
        "tradeDate": trade_date.isoformat(),
        "confirmDate": confirm_date.isoformat(),
        "valueDate": value_date.isoformat(),
        "sameDayConfirm": same_day,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 五、 持有天数计算 & 赎回费
# ═══════════════════════════════════════════════════════════════════════════════

def calc_hold_days(buy_date: date, sell_date: date = None) -> int:
    """
    计算真实持有天数
    从份额确认日（T+1）开始算，到赎回确认日（卖出T+1）结束
    """
    if sell_date is None:
        sell_date = date.today()

    # 买入确认日
    buy_confirm = next_trading_day(buy_date) if is_trading_day(buy_date) else next_trading_day(buy_date)
    # 卖出确认日
    sell_confirm = next_trading_day(sell_date) if is_trading_day(sell_date) else next_trading_day(sell_date)

    return (sell_confirm - buy_confirm).days


def calc_redemption_fee_ratio(hold_days: int) -> float:
    """根据持有天数计算赎回费率"""
    for min_days, max_days, fee in TradeTimeConstants.REDEMPTION_FEE_SCHEDULE:
        if max_days is None:
            if hold_days >= min_days:
                return fee
        elif min_days <= hold_days < max_days:
            return fee
    return 0.015  # 默认最高


def calc_redemption_fee(amount: float, hold_days: int) -> Dict:
    """
    计算赎回费用

    返回：
    {
        "holdDays": 持有天数,
        "feeRatio": 费率,
        "feeAmount": 手续费金额,
        "netAmount": 实际到手,
        "warnings": [],
    }
    """
    fee_ratio = calc_redemption_fee_ratio(hold_days)
    fee_amount = round(amount * fee_ratio, 2)
    net_amount = round(amount - fee_amount, 2)

    warnings = []
    if hold_days < 7:
        warnings.append("🚨 持有不足7天！惩罚性赎回费1.5%，短线频繁买卖直接亏光涨幅，绝对避开")
    elif hold_days < 365:
        warnings.append(f"💡 持有{hold_days}天，费率{fee_ratio*100}%，建议持有满1年降至0.25%")

    return {
        "holdDays": hold_days,
        "feeRatio": fee_ratio,
        "feeAmount": fee_amount,
        "netAmount": net_amount,
        "warnings": warnings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 六、 场内 ETF 时间校验
# ═══════════════════════════════════════════════════════════════════════════════

def is_etf_trading_time(dt: datetime = None) -> bool:
    """判断当前是否在场内 ETF 交易时段内"""
    if dt is None:
        dt = datetime.now()
    if not is_trading_day(dt.date()):
        return False

    h, m = dt.hour, dt.minute
    minutes = h * 60 + m

    morning_start = TradeTimeConstants.A_MARKET_OPEN[0] * 60 + TradeTimeConstants.A_MARKET_OPEN[1]
    morning_end = TradeTimeConstants.A_MARKET_MORNING_CLOSE[0] * 60 + TradeTimeConstants.A_MARKET_MORNING_CLOSE[1]
    afternoon_start = TradeTimeConstants.A_MARKET_AFTERNOON_OPEN[0] * 60 + TradeTimeConstants.A_MARKET_AFTERNOON_OPEN[1]
    afternoon_end = TradeTimeConstants.A_MARKET_CLOSE[0] * 60 + TradeTimeConstants.A_MARKET_CLOSE[1]

    return (morning_start <= minutes < morning_end) or (afternoon_start <= minutes < afternoon_end)


def is_call_auction_time(dt: datetime = None) -> bool:
    """是否为尾盘集合竞价时段（14:57-15:00，不可撤单）"""
    if dt is None:
        dt = datetime.now()
    minutes = dt.hour * 60 + dt.minute
    call_start = TradeTimeConstants.A_MARKET_CALL_AUCTION[0] * 60 + TradeTimeConstants.A_MARKET_CALL_AUCTION[1]
    call_end = TradeTimeConstants.A_MARKET_CLOSE[0] * 60 + TradeTimeConstants.A_MARKET_CLOSE[1]
    return call_start <= minutes < call_end


def get_etf_trade_type(symbol_name: str) -> str:
    """判断 ETF 是否支持 T+0"""
    for t0 in TradeTimeConstants.T0_SYMBOLS:
        if t0 in symbol_name:
            return "T+0"
    return "T+1"


# ═══════════════════════════════════════════════════════════════════════════════
# 七、 QDII 海外时差模块
# ═══════════════════════════════════════════════════════════════════════════════

QDII_US = "us"  # 美股 QDII（纳斯达克、标普等）
QDII_HK = "hk"  # 港股 QDII（恒生、H股等）
QDII_OTHER = "other"


def get_qdii_type(fund_name: str) -> str:
    """根据基金名称判断 QDII 类型"""
    name = fund_name.lower()
    if any(kw in name for kw in ["纳指", "纳斯达克", "标普", "美股", "美国"]):
        return QDII_US
    if any(kw in name for kw in ["恒生", "港股", "h股", "中概互联", "香港"]):
        return QDII_HK
    return QDII_OTHER


def get_qdii_trade_info(fund_name: str, order_time: datetime = None) -> Dict:
    """
    A股下单时间 vs 海外收盘时间的映射

    返回 QDII 成交价格说明
    """
    if order_time is None:
        order_time = datetime.now()

    qdii_type = get_qdii_type(fund_name)
    in_window = is_before_1500(order_time) and is_trading_day(order_time.date())

    if qdii_type == QDII_US:
        description = (
            "按当晚美股收盘价成交（美东时间16:00=北京时间次日凌晨4:00）"
            if in_window else
            "按下一美股交易日收盘价成交"
        )
        risk = "国内白天有利好，当晚美股大涨 → 15点后下单=成本抬高" if in_window else (
            "海外夜间暴跌，国内第二天白天才反应 → 15点前卖出才能锁定损失"
        )
        confirm_days = 2  # T+2
    elif qdii_type == QDII_HK:
        description = (
            "按当天港股收盘价成交（港股16:00收盘，15:00下单时还在交易）"
            if in_window else
            "按下一港股交易日收盘价成交"
        )
        risk = "港股和A股同时段但有午市差异，注意下午突发行情"
        confirm_days = 1  # T+1
    else:
        description = "按海外市场当晚收盘价成交" if in_window else "按下一交易日净值成交"
        confirm_days = 2
        risk = "不同市场清算周期有差异，到账约T+7~T+10"

    return {
        "fundName": fund_name,
        "qdiiType": qdii_type,
        "tradeInWindow": in_window,
        "settlementDescription": description,
        "riskWarning": risk,
        "confirmDays": confirm_days,
        "settlementDays": TradeTimeConstants.QDII_SETTLEMENT_DAYS,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 八、 节假日/长假 买卖策略
# ═══════════════════════════════════════════════════════════════════════════════

def get_holiday_strategy(dt: datetime = None) -> Dict:
    """
    返回针对当前日期的节假日操作策略
    """
    if dt is None:
        dt = datetime.now()
    today = dt.date()

    # 是否是长假前最后交易日
    holiday_name = is_last_trading_day_before_holiday(today)
    is_friday = dt.weekday() == 4

    warnings = []
    actions = []
    counts_down = None

    if holiday_name:
        # 节前最后交易日
        if is_before_1500(dt):
            actions.append("🟢 今日15:00前赎回 → 锁定当日净值，假期涨跌与你无关，落袋为安")
            actions.append("🟢 今日15:00前买入 → 按今日净值成交，可享节后开盘行情（如有）")
        else:
            actions.append("🔴 今日15:00后操作 → 按节后首日净值成交，你要扛整个假期的波动")
        warnings.append(f"⚠️ 今天是 {holiday_name} 前最后一个交易日")

    elif is_friday and is_before_1500(dt):
        warnings.append("💡 周五交易日，操作请在15:00前完成")
    elif is_friday and not is_before_1500(dt):
        warnings.append("⚠️ 周五15点后买入 → 按下周一净值，周末两天上涨完全吃不到")

    # 计算到长假的天数
    for year in [2024, 2025, 2026]:
        for h in CN_HOLIDAYS.get(year, []):
            start = _date_from_str(h["start"])
            if start > today and (start - today).days <= 5:
                counts_down = (start - today).days
                warnings.append(f"📅 距 {h['name']} 还有 {counts_down} 天，提前安排操作")

    return {
        "date": today.isoformat(),
        "isTradingDay": is_trading_day(today),
        "holidayBeforeLastDay": holiday_name is not None,
        "isFriday": is_friday,
        "before1500": is_before_1500(dt),
        "warnings": warnings,
        "actions": actions,
        "countdownDays": counts_down,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 九、 新闻时间匹配 — 判断新闻发生在操作窗口内还是需次日操作
# ═══════════════════════════════════════════════════════════════════════════════

class NewsTimeWindow:
    """新闻时间戳 → 操作窗口映射"""

    # 可操作窗口类型
    IMMEDIATE = "immediate"       # 盘中可操作（交易时段内）
    BEFORE_MARKET = "pre_market"  # 盘前/隔夜利好 → 次日早盘操作
    AFTERNOON = "afternoon"       # 下午可操作（14:30前）
    CLOSE_WINDOW = "close_window"  # 14:30-14:55 最佳窗口
    TOO_LATE = "too_late"         # 15:00后 → 顺延至次日
    WEEKEND = "weekend"           # 周末 → 周一早盘操作
    HOLIDAY = "holiday"           # 节假日 → 节后操作

    @staticmethod
    def classify_news_time(news_time: datetime, detail: str = "") -> Dict:
        """
        根据新闻时间判断操作策略

        Args:
            news_time: 新闻发布时间
            detail: 新闻内容（用于自动判断利好/利空）

        Returns:
            {
                "newsTime": ISO时间,
                "isPositive": True/False (默认True，利好),
                "actionWindow": "immediate|pre_market|afternoon|close_window|too_late|weekend|holiday",
                "actionLabel": 操作建议,
                "actionDeadline": 最晚操作时间,
                "riskNote": 风险提示,
            }
        """
        # 默认利好
        is_positive = not any(kw in detail for kw in ["利空", "减持", "加息", "集采", "辞职", "立案", "退市"])

        now = news_time
        h, m = now.hour, now.minute
        today = now.date()

        if not is_trading_day(today):
            next_day = next_trading_day(today)
            return {
                "newsTime": news_time.isoformat(),
                "isPositive": is_positive,
                "actionWindow": NewsTimeWindow.HOLIDAY if _in_holiday_range(today, {"start": "", "end": ""}) else NewsTimeWindow.WEEKEND,
                "actionLabel": "非交易日 → 节后/周一开盘立刻操作（9:30）",
                "actionDeadline": f"{next_day.isoformat()} 15:00",
                "riskNote": "拖延到下午操作会损失全天时效",
            }

        # 盘前/隔夜新闻（0:00-9:30）
        if h < 9 or (h == 9 and m < 30):
            return {
                "newsTime": news_time.isoformat(),
                "isPositive": is_positive,
                "actionWindow": NewsTimeWindow.BEFORE_MARKET,
                "actionLabel": "隔夜利好 → 今日 9:30 开盘立刻买入，越早成本越低",
                "actionDeadline": f"{today.isoformat()} 10:00",
                "riskNote": "早盘冲高后 10:00 前完成操作，不要拖到 15 点",
            }

        # 早盘期间（9:30-10:00）
        if (9 <= h < 10) and is_etf_trading_time(now):
            return {
                "newsTime": news_time.isoformat(),
                "isPositive": is_positive,
                "actionWindow": NewsTimeWindow.IMMEDIATE,
                "actionLabel": "盘中利好 → 立即买入（早盘窗口），锁定当日最低净值",
                "actionDeadline": f"{today.isoformat()} 10:00",
                "riskNote": "利好出尽可能冲高回落，早盘买入优于午盘追高",
            }

        # 盘中（10:00-14:30）
        morning_minutes = h * 60 + m
        if 10 * 60 <= morning_minutes < 14 * 60 + 30:
            if is_etf_trading_time(now):
                return {
                    "newsTime": news_time.isoformat(),
                    "isPositive": is_positive,
                    "actionWindow": NewsTimeWindow.AFTERNOON,
                    "actionLabel": "盘中突发政策利好 → 14:30 前完成买入，卡死 15:00",
                    "actionDeadline": f"{today.isoformat()} 15:00",
                    "riskNote": "建议 14:30 前建仓完毕，留足操作缓冲时间",
                }
            else:
                return {
                    "newsTime": news_time.isoformat(),
                    "isPositive": is_positive,
                    "actionWindow": NewsTimeWindow.AFTERNOON,
                    "actionLabel": "午休时段出消息 → 下午 13:00 开盘后操作",
                    "actionDeadline": f"{today.isoformat()} 15:00",
                    "riskNote": "下午开盘情绪可能集中释放",
                }

        # 最佳止盈窗口（14:30-14:55）
        if 14 * 60 + 30 <= morning_minutes < 14 * 60 + 55:
            if is_positive:
                label = "尾盘大涨锁利 → 14:40-14:55 分批减仓，锁定当日高点净值"
            else:
                label = "尾盘利空 → 当天 15 点前清仓，规避次日回调"
            return {
                "newsTime": news_time.isoformat(),
                "isPositive": is_positive,
                "actionWindow": NewsTimeWindow.CLOSE_WINDOW,
                "actionLabel": label,
                "actionDeadline": f"{today.isoformat()} 15:00",
                "riskNote": "14:57 后进入集合竞价不可撤单，务必在 14:55 前完成",
            }

        # 14:55-15:00
        if 14 * 60 + 55 <= morning_minutes < 15 * 60:
            return {
                "newsTime": news_time.isoformat(),
                "isPositive": is_positive,
                "actionWindow": NewsTimeWindow.TOO_LATE,
                "actionLabel": "已近收盘 → 今日操作时间不足，建议明日早盘操作",
                "actionDeadline": f"{next_trading_day(today).isoformat()} 10:00",
                "riskNote": "14:57 后不可撤单，强行操作风险极高",
            }

        # 15:00 后
        if h >= 15:
            return {
                "newsTime": news_time.isoformat(),
                "isPositive": is_positive,
                "actionWindow": NewsTimeWindow.TOO_LATE,
                "actionLabel": "15:00 后出消息 → 按次日/下一交易日净值，明日早盘 9:30 操作",
                "actionDeadline": f"{next_trading_day(today).isoformat()} 15:00",
                "riskNote": "今日已无法操作，隔夜夜盘走势不确定",
            }

        return {
            "newsTime": news_time.isoformat(),
            "isPositive": is_positive,
            "actionWindow": NewsTimeWindow.IMMEDIATE,
            "actionLabel": "判断中，请结合交易时段操作",
            "actionDeadline": f"{today.isoformat()} 15:00",
            "riskNote": "",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 十、 综合时间状态 — 全套实时状态快照
# ═══════════════════════════════════════════════════════════════════════════════

def get_current_time_status(dt: datetime = None) -> Dict:
    """返回当前时间状态的完整快照（给前端用）"""
    if dt is None:
        dt = datetime.now()

    today = dt.date()
    trading = is_trading_day(today)
    before_1500 = is_before_1500(dt)

    # 场外交易信息
    trade_info = get_trade_nav_date(dt)

    # 节假日策略
    holiday_info = get_holiday_strategy(dt)

    # 场内时间
    etf_open = is_etf_trading_time(dt)
    call_auction = is_call_auction_time(dt)

    # 最佳操作窗口
    minutes = dt.hour * 60 + dt.minute
    optimal_buy_start = TradeTimeConstants.OPTIMAL_BUY_WINDOW_START[0] * 60 + TradeTimeConstants.OPTIMAL_BUY_WINDOW_START[1]
    optimal_buy_end = TradeTimeConstants.OPTIMAL_BUY_WINDOW_END[0] * 60 + TradeTimeConstants.OPTIMAL_BUY_WINDOW_END[1]
    optimal_sell_start = TradeTimeConstants.OPTIMAL_SELL_WINDOW_START[0] * 60 + TradeTimeConstants.OPTIMAL_SELL_WINDOW_START[1]
    optimal_sell_end = TradeTimeConstants.OPTIMAL_SELL_WINDOW_END[0] * 60 + TradeTimeConstants.OPTIMAL_SELL_WINDOW_END[1]
    morning_news_start = TradeTimeConstants.MORNING_NEWS_WINDOW_START[0] * 60 + TradeTimeConstants.MORNING_NEWS_WINDOW_START[1]
    morning_news_end = TradeTimeConstants.MORNING_NEWS_WINDOW_END[0] * 60 + TradeTimeConstants.MORNING_NEWS_WINDOW_END[1]

    in_optimal_sell = optimal_sell_start <= minutes < optimal_sell_end and trading
    in_optimal_buy = optimal_buy_start <= minutes < optimal_buy_end and trading
    in_morning_news = morning_news_start <= minutes < morning_news_end and trading and etf_open

    # 状态总结
    if not trading:
        next_trade_day = next_trading_day(today)
        days_off = (next_trade_day - today).days
        status = "休市"
        status_label = f"休市（距下一交易日还有 {days_off} 天）"
    elif in_optimal_sell:
        status = "止盈窗口"
        status_label = "🔔 最佳止盈窗口 14:40-14:55 已开启"
    elif in_optimal_buy:
        status = "买入窗口"
        status_label = "🔔 最佳买入窗口 14:30-14:55 已开启"
    elif in_morning_news:
        status = "盘前操作"
        status_label = "🌅 早盘利好窗口 9:30-10:00"
    elif is_etf_trading_time(dt):
        status = "交易中"
        status_label = "✅ 交易时段内"
    elif before_1500:
        status = "可操作"
        status_label = "✅ 场内休市但场外15:00前仍可操作"
    else:
        status = "收盘"
        status_label = "❌ 15:00后，操作已顺延至下一交易日"

    return {
        "currentTime": dt.isoformat(),
        "date": today.isoformat(),
        "isTradingDay": trading,
        "isBefore1500": before_1500,
        "isETFTradingTime": etf_open,
        "isCallAuction": call_auction,
        "inOptimalBuyWindow": in_optimal_buy,
        "inOptimalSellWindow": in_optimal_sell,
        "inMorningNewsWindow": in_morning_news,
        "status": status,
        "statusLabel": status_label,
        "nextTradingDay": next_trading_day(today).isoformat() if not trading else None,
        "tradeInfo": trade_info,
        "holidayStrategy": holiday_info,
        "timeConstants": {
            "cutoffTime": "15:00",
            "morningSession": "9:30-11:30",
            "afternoonSession": "13:00-15:00",
            "callAuction": "14:57-15:00",
            "optimalBuyWindow": "14:30-14:55",
            "optimalSellWindow": "14:40-14:55",
            "morningNewsWindow": "9:30-10:00",
            "t0Symbols": TradeTimeConstants.T0_SYMBOLS,
            "redemptionFeeSchedule": [
                {"minDays": 0, "maxDays": 7, "feeRate": 0.015, "note": "惩罚性1.5%"},
                {"minDays": 7, "maxDays": 365, "feeRate": 0.005, "note": "0.5%"},
                {"minDays": 365, "maxDays": 730, "feeRate": 0.0025, "note": "0.25%"},
                {"minDays": 730, "maxDays": None, "feeRate": 0.0, "note": "0%免费"},
            ],
            "principal4": "14:30-14:55操作，卡死15点分界线",
            "principal7": "短线持有满7天再卖，规避1.5%赎回费",
            "principalHoliday": "长假操作在节前最后一日15点前完成",
            "principalQDII": "QDII看海外收盘时差，隔夜利好次日早盘操作",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 十一、 完整知识库 — 给前端的 JSON 知识页面
# ═══════════════════════════════════════════════════════════════════════════════

def get_knowledge_base() -> Dict:
    """返回完整的基金买卖时间节点知识库"""
    now = datetime.now()
    today = now.date()

    current_status = get_current_time_status(now)

    return {
        "version": "1.0",
        "generatedAt": now.isoformat(),
        "currentStatus": current_status,
        "sections": [
            {
                "id": "cutoff_1500",
                "title": "一、场外基金核心分界线 15:00",
                "icon": "⏰",
                "rules": [
                    {
                        "title": "买入：15:00前 vs 后",
                        "items": [
                            "T日15:00前买入 → 当天收盘净值成交，T+1日确认份额、当天开始算收益",
                            "T日15:00后买入 → 顺延至T+1交易日净值成交，T+2日才计息，少拿1天收益",
                            "周末/节假日下单 → 全部归节后第一个交易日T日净值，长假会损失多天行情收益",
                        ],
                        "warning": "周五15点后买入，按下周一净值，周末两天上涨完全吃不到",
                    },
                    {
                        "title": "卖出：15:00前 vs 后",
                        "items": [
                            "T日15:00前赎回 → 锁定当日净值，T+1起不再承担涨跌",
                            "T日15:00后赎回 → 按次日净值结算，多扛一天波动",
                        ],
                        "warning": "大涨当天拖到3点后卖，第二天回调，到手利润大幅缩水",
                    },
                    {
                        "title": "计息规则",
                        "items": [
                            "15点前赎回 → T日仍享有当天+节前假期全部收益",
                            "15点后赎回 → T日无收益，假期涨跌跟你无关（注意：节前最后交易日15点后赎回=按节后首日净值，扛整个假期波动）",
                            "股票/混合基金：周末、节假日不产生收益",
                            "货币/纯债基金假期计息，但净值节后统一更新",
                        ],
                    },
                ],
            },
            {
                "id": "redemption_fee",
                "title": "二、赎回费率时间节点",
                "icon": "💰",
                "rules": [
                    {
                        "title": "持有天数与费率（从申购确认日开始算，非买入当天）",
                        "items": [
                            "持有 < 7天：惩罚性赎回费 1.5% —— 绝对避开！",
                            "7天 – 1年：0.5% 左右赎回费",
                            "1 – 2年：0.25%",
                            "2年以上：0 赎回费",
                        ],
                        "warning": "短线套利至少拿满7天再卖出；做波段尽量持有满1年再减仓",
                    },
                ],
            },
            {
                "id": "etf_trading",
                "title": "三、场内 ETF/LOF",
                "icon": "📈",
                "rules": [
                    {
                        "title": "交易时段",
                        "items": [
                            "上午 9:30–11:30，下午 13:00–15:00",
                            "14:57–15:00 尾盘集合竞价，不可撤单",
                        ],
                    },
                    {
                        "title": "T+0 / T+1 规则",
                        "items": [
                            "T+1（A股宽基/行业ETF）：当日买入，次交易日才能卖出",
                            "T+0（跨境/黄金/债券ETF）：当日买卖不限次数",
                            f"T+0标的：{'、'.join(TradeTimeConstants.T0_SYMBOLS)}",
                        ],
                    },
                    {
                        "title": "资金到账",
                        "items": [
                            "卖出资金实时可用，可立刻买入其他基金",
                            "转出银行卡需T+1，周末无法提现",
                        ],
                    },
                ],
            },
            {
                "id": "qdii",
                "title": "四、QDII 海外基金时差",
                "icon": "🌍",
                "rules": [
                    {
                        "title": "美股 QDII（纳指/标普）",
                        "items": [
                            "A股15点前下单 → 按当晚美股收盘价成交（美东16:00=北京时间次日4:00）",
                            "A股15点后下单 → 按下一美股交易日价格",
                            "确认周期：T+2确认份额",
                        ],
                        "warning": "国内白天有利好，当晚美股大涨 → 15点后买入=成本抬高",
                    },
                    {
                        "title": "港股 QDII（恒生/H股/中概互联）",
                        "items": [
                            "A股15点前下单 → 按当天港股收盘价成交（港股16:00收盘）",
                            "确认周期：T+1确认",
                        ],
                    },
                    {
                        "title": "资金到账",
                        "items": [
                            "赎回资金 T+7 ~ T+10 到账",
                            "长假前提前3天操作，避免资金长期冻结",
                        ],
                    },
                ],
            },
            {
                "id": "holidays",
                "title": "五、节假日/长假操作",
                "icon": "🎯",
                "rules": [
                    {
                        "title": "买入避坑",
                        "items": [
                            "周五15:00后不买入：按周一净值，错过周末海外利好行情",
                            "长假前最后一日15点后不买入：整个假期上涨全部吃不到",
                        ],
                    },
                    {
                        "title": "卖出锁利",
                        "items": [
                            "想落袋+吃满假期收益：节前最后交易日15:00前赎回",
                            "预判假期外围大跌：节前15点前清仓",
                            "周四15点后不赎回：资金周五确认，周末两天无法取现",
                        ],
                    },
                    {
                        "title": "法定节假日日历",
                        "items": [
                            f"{h['name']}: {h['start']} ~ {h['end']}"
                            for year_holidays in CN_HOLIDAYS.values()
                            for h in year_holidays
                        ],
                    },
                ],
            },
            {
                "id": "operation_windows",
                "title": "六、实操买卖时间策略",
                "icon": "⚡",
                "rules": [
                    {
                        "title": "利好买入窗口",
                        "items": [
                            "早盘9:30-10:00：隔夜国际重大利好，开盘1小时内加仓",
                            "盘中突发政策利好：14:30前完成买入，卡死15:00前",
                            "晚间出利好（20点后）：次日9:30开盘立刻操作",
                        ],
                    },
                    {
                        "title": "止盈卖出窗口",
                        "items": [
                            "单日大涨3%+：14:40-14:55分批减仓，锁当日高点净值",
                            "持仓达到目标收益15%-20%：交易日收盘前完成卖出",
                            "高位出现利空：当天15点前清仓，规避次日回调",
                        ],
                    },
                    {
                        "title": "止损时间规则",
                        "items": [
                            "持仓浮亏超10%+赛道持续利空：当日15点前止损",
                        ],
                    },
                ],
            },
            {
                "id": "golden_rules",
                "title": "七、极简盈利4条",
                "icon": "🏆",
                "rules": [
                    {
                        "title": "记住这4条就够了",
                        "items": [
                            "所有买卖操作交易日14:30-14:55完成，卡死15点分界线",
                            "短线务必持有满7天再卖，规避1.5%高额赎回费",
                            "长假操作一律在节前最后一日15点前完成",
                            "QDII看海外收盘时差，利好隔夜消息次日早盘立刻操作",
                        ],
                    },
                ],
            },
        ],
    }
