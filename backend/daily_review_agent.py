"""
AI Daily Review Agent — 每日收盘复盘报告
========================================
调度时间：交易日 15:10（收盘后）
数据来源：
  - simulation_runs（输入快照 + 决策 + 结果各账户）
  - sim_agent_attribution（各Agent贡献）
  - sim_daily_values（净值）
  - daily_benchmark（基准指数）
  - risk_config + risk engine 日志

输出：Markdown 格式报告 → daily_reports 表
"""
import json
from datetime import datetime
from typing import Dict, List, Optional

from loguru import logger
from database import get_connection

from llm_service import chat


# ── 数据采集函数 ────────────────────────────────────────────────

def _get_accounts() -> List[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM sim_accounts ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_daily_runs(account_id: int, days: int = 5) -> List[dict]:
    """获取最近几天的 simulation_runs 记录"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM simulation_runs
        WHERE account_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (account_id, days)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_attribution(account_id: int, days: int = 1) -> List[dict]:
    """获取最近归因数据"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT agent_name, SUM(trade_count) as total_trades,
               AVG(avg_confidence) as avg_confidence,
               SUM(pnl_contribution) as total_pnl,
               SUM(weighted_share) as total_weight
        FROM sim_agent_attribution
        WHERE account_id = ? AND date >= date('now', ?)
        GROUP BY agent_name
    """, (account_id, f'-{days} days')).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_nav_data(account_id: int, days: int = 30) -> List[dict]:
    """获取近期净值数据"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT date, total_value FROM sim_daily_values
        WHERE account_id = ?
        ORDER BY date DESC
        LIMIT ?
    """, (account_id, days)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_benchmark_return(days: int = 30) -> Optional[float]:
    """计算基准指数近期收益率"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT date, close FROM daily_benchmark
        WHERE index_code = '000300'
        ORDER BY date DESC
        LIMIT ?
    """, (days,)).fetchall()
    conn.close()
    if len(rows) < 2:
        return None
    first_close = rows[-1]["close"]
    last_close = rows[0]["close"]
    if first_close and first_close > 0:
        return round((last_close - first_close) / first_close * 100, 2)
    return None


def _get_recent_trades(account_id: int, limit: int = 5) -> List[dict]:
    conn = get_connection()
    rows = conn.execute("""
        SELECT fund_code, direction, price, shares, amount, reason, created_at
        FROM sim_trades
        WHERE account_id = ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (account_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Prompt 构建 ─────────────────────────────────────────────────

REPORT_SYSTEM_PROMPT = """你是一个量化策略复盘分析师。你的任务是根据系统提供的今日量化数据，生成一份结构化的中文日度复盘报告。

报告格式要求（必须用 Markdown）：

# 📊 量化日报 — {date}

## 📈 市场概况
- 沪深300 当日/近一月涨跌（如有数据）
- 简要市场判断（一句话）

## 🏦 账户表现总览
各账户表格：
| 账户 | 当日收益 | 累计收益 | 策略配置 |
每个账户一段简评。

## 🤖 Agent 贡献
各账户下表格：
| Agent | 笔数 | 收益贡献 | 权重 |
简要说明哪个Agent贡献最大。

## ⚠️ 风险提示
- 基于风控规则的预警
- 基于数据的前瞻性提示

## 📌 明日关注
3-5 条具体关注事项（MACD状态、仓位、新闻等）

## 💡 综合建议
一段总结性建议，中性专业视角。

规则：
1. 不要说"根据提供的数据"这种废话
2. 数字精确到两位小数
3. 累计收益用 total_return_pct
4. 保守为主，不要给出具体的交易指令
5. 如果数据不足，诚实说明"""


def _build_payload(account_id: int, account: dict, days: int = 30) -> str:
    """为某个账户构建 LLM 输入数据"""
    runs = _get_daily_runs(account_id, days)
    attribution = _get_attribution(account_id, 1)
    nav = _get_nav_data(account_id, days)
    trades = _get_recent_trades(account_id, 5)

    sc = account.get("strategy_config", "{}")
    if isinstance(sc, str):
        try:
            sc = json.loads(sc)
        except (json.JSONDecodeError, TypeError):
            sc = {}

    # 计算累计收益
    total_return_pct = 0
    if account.get("initialCash", 0) > 0:
        total_return_pct = round(
            (account.get("totalValue", 0) - account["initialCash"]) / account["initialCash"] * 100, 2
        )

    lines = [f"【账户】{account.get('name', f'Account #{account_id}')}"]
    lines.append(f"初始资金: ¥{account.get('initialCash', 0):.2f}")
    lines.append(f"当前总资产: ¥{account.get('totalValue', 0):.2f}")
    lines.append(f"累计收益: {total_return_pct}%")
    lines.append(f"策略配置: {json.dumps(sc, ensure_ascii=False)}")

    if runs:
        lines.append(f"\n近期执行记录 ({len(runs)}条):")
        for r in runs[:7]:
            lines.append(
                f"  {r['created_at'][:10]} | ma20={r.get('ma20','-')} "
                f"rsi={r.get('rsi','-')} atr={r.get('atr','-')} "
                f"信号={r['signal']} 分数={r['score']} "
                f"P&L={r.get('pnl',0):+.2f}"
            )

    if attribution:
        lines.append(f"\nAgent归因 (今日):")
        for a in attribution:
            lines.append(f"  {a['agent_name']}: {a['total_trades']}笔 "
                         f"P&L={a['total_pnl']:+.2f} "
                         f"置信度={a.get('avg_confidence', 0):.1f}%")

    if nav and len(nav) >= 2:
        first_nav = nav[-1]["total_value"]
        last_nav = nav[0]["total_value"]
        nav_return = (last_nav - first_nav) / first_nav * 100 if first_nav > 0 else 0
        lines.append(f"\n近{min(len(nav), days)}天净值收益: {nav_return:+.2f}%")

    if trades:
        lines.append(f"\n最近交易 ({len(trades)}笔):")
        for t in trades[:5]:
            lines.append(f"  {t['direction']} {t['fund_code']} "
                         f"¥{t['price']:.2f}×{t['shares']:.2f} "
                         f"[{t.get('reason','')[:40]}]")

    return "\n".join(lines)


# ── 报告生成 ───────────────────────────────────────────────────

def generate_daily_review() -> Optional[dict]:
    """
    生成今日复盘报告

    Returns:
        {"date": "2026-07-15", "content": "# 完整 Markdown 报告", "account_reports": [...]}
        失败返回 None
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # 检查今天是否已生成（避免重复执行）
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM daily_reports WHERE date = ? AND report_type = 'daily'",
        (today,),
    ).fetchone()
    if existing:
        logger.info("[DAILY_REVIEW] 今日报告已存在 (id={})", existing["id"])
        conn.close()
        return None

    # 采集全局数据
    accounts = _get_accounts()
    if not accounts:
        logger.warning("[DAILY_REVIEW] 无模拟账户数据")
        conn.close()
        return None

    benchmark_return = _get_benchmark_return(30)

    # 构建各账户数据描述
    account_payloads = []
    for acct in accounts:
        try:
            payload = _build_payload(acct["id"], acct)
            account_payloads.append(payload)
        except Exception as e:
            logger.warning("[DAILY_REVIEW] 账户 {} 数据构建失败: {}", acct.get("id"), e)

    if not account_payloads:
        conn.close()
        logger.warning("[DAILY_REVIEW] 无有效账户数据")
        return None

    # 构建用户消息
    user_message = "【全局概览】\n"
    user_message += f"日期: {today}\n"
    user_message += f"账户数: {len(accounts)}\n"
    if benchmark_return is not None:
        user_message += f"沪深300近30日涨跌: {benchmark_return:+.2f}%\n"

    user_message += "\n\n【各账户详情】\n" + "\n---\n".join(account_payloads)

    user_message += "\n\n请根据以上数据生成今日量化复盘报告。"

    # 调用 LLM
    logger.info("[DAILY_REVIEW] 调用 LLM 生成报告...")
    content = chat(
        messages=[{"role": "user", "content": user_message}],
        system_prompt=REPORT_SYSTEM_PROMPT,
        temperature=0.3,
        max_tokens=4096,
        timeout=120,  # 复盘不急，给 2 分钟
    )

    if not content:
        logger.error("[DAILY_REVIEW] LLM 报告生成失败")
        conn.close()
        return None

    # 持久化
    conn.execute("""
        INSERT INTO daily_reports (date, report_type, content, accounts_summary)
        VALUES (?, 'daily', ?, ?)
    """, (
        today,
        content,
        json.dumps([{"id": a["id"], "name": a.get("name", "")} for a in accounts], ensure_ascii=False),
    ))
    conn.commit()
    report_id = conn.execute("SELECT last_insert_rowid() as rid").fetchone()["rid"]
    conn.close()

    logger.info("[DAILY_REVIEW] 报告已生成 id={}, length={}", report_id, len(content))

    return {
        "id": report_id,
        "date": today,
        "content": content,
        "report_type": "daily",
    }


def get_recent_reports(limit: int = 10) -> List[dict]:
    """获取最近报告列表"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, date, report_type, accounts_summary, created_at
        FROM daily_reports
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_report(report_id: int) -> Optional[dict]:
    """获取单条报告完整内容"""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM daily_reports WHERE id = ?", (report_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    from loguru import logger
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="INFO")

    result = generate_daily_review()
    if result:
        print("\n" + "=" * 60)
        print(result["content"][:2000])
        print("\n…" if len(result["content"]) > 2000 else "")
    else:
        print("生成失败或今日已存在")
