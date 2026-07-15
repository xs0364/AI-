"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { simApi, benchmarkApi } from "@/lib/api";
import type { SimAccount, BenchmarkData } from "@/lib/api";
import {
  Play, Loader2, TrendingUp, TrendingDown,
  DollarSign, BarChart3, ArrowLeftRight,
  Coins, PiggyBank, Landmark, Activity,
  Percent, Timer, PieChart, Brain,
} from "lucide-react";
import { createChart, ColorType, LineStyle, LineSeries } from "lightweight-charts";
import type { IChartApi } from "lightweight-charts";
import { cn } from "@/lib/utils";
import { useTheme } from "next-themes";

const ACCOUNT_ICONS = [Coins, PiggyBank, Landmark];
const ACCOUNT_COLORS = ["#22c55e", "#3b82f6", "#a855f7"];

interface EquityData {
  accounts: {
    accountId: number;
    accountName: string;
    initialCash: number;
    equity: { date: string; nav: number; totalValue: number }[];
  }[];
  benchmark?: {
    code: string;
    name: string;
    data: { date: string; close: number; nav: number }[];
  } | null;
}

export default function SimulationPage() {
  const [accounts, setAccounts] = useState<SimAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [execResult, setExecResult] = useState("");
  const [equityData, setEquityData] = useState<EquityData | null>(null);
  const [metrics, setMetrics] = useState<Record<string, any> | null>(null);
  const [attribution, setAttribution] = useState<any[]>([]);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);

  // ── 启动时加载 ──────────────────────────────────────────────
  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [acctRes, eqRes] = await Promise.all([
        simApi.accounts(),
        simApi.equity().catch(() => null),
      ]);
      setAccounts(acctRes.accounts || []);
      setEquityData(eqRes);
      if (acctRes.accounts?.length && !selectedId) {
        setSelectedId(acctRes.accounts[0].id);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [selectedId]);

  useEffect(() => { loadAll(); }, [loadAll]);

  // ── 选中账户时加载详情 + 分析数据 ──────────────────────────
  useEffect(() => {
    if (!selectedId) return;
    setDetailLoading(true);
    setAnalyticsLoading(true);
    Promise.all([
      simApi.detail(selectedId),
      simApi.metrics(selectedId).catch(() => null),
      simApi.attribution(selectedId).catch(() => ({ data: [] })),
    ]).then(([d, m, a]) => {
      setDetail(d);
      setMetrics(m?.metrics || null);
      setAttribution(a?.data || []);
    }).catch(() => {
      setDetail(null);
    }).finally(() => {
      setDetailLoading(false);
      setAnalyticsLoading(false);
    });
  }, [selectedId]);

  // ── 执行 ────────────────────────────────────────────────────
  const execute = useCallback(async () => {
    setExecuting(true);
    setExecResult("");
    try {
      const res = await simApi.execute();
      const totalTrades = res.results?.reduce((s: number, r: any) => s + (r.trades?.length || 0), 0) || 0;
      setExecResult(`执行完成: ${totalTrades} 笔交易`);
      loadAll();
      if (selectedId) {
        simApi.detail(selectedId).then(setDetail);
        simApi.metrics(selectedId).then(m => setMetrics(m?.metrics || null)).catch(() => {});
        simApi.attribution(selectedId).then(a => setAttribution(a?.data || [])).catch(() => {});
      }
    } catch (e: any) {
      setExecResult("执行失败: " + (e.message || ""));
    } finally { setExecuting(false); }
  }, [selectedId, loadAll]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary tracking-tight">量化策略实验室</h1>
          <p className="text-xs text-text-tertiary mt-0.5">三个独立策略配置 · 实时对比验证</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={execute} disabled={executing}
            className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium bg-brand-400/20 text-brand-400 hover:bg-brand-400/30 disabled:opacity-50 transition-all">
            {executing ? <><Loader2 className="h-4 w-4 animate-spin" /> 执行中…</>
              : <><Play className="h-4 w-4" /> 运行 Agent 扫描</>}
          </button>
        </div>
      </div>
      {execResult && <div className="text-xs text-text-tertiary bg-surface-2 rounded-lg px-3 py-2">{execResult}</div>}

      {/* ── 模拟盘总览卡片 ──────────────────────────────────── */}
      {loading ? (
        <div className="flex items-center justify-center h-32 text-text-tertiary"><Loader2 className="h-5 w-5 animate-spin mr-2" />加载中…</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {accounts.map((acct, idx) => {
            const Icon = ACCOUNT_ICONS[idx] || DollarSign;
            const totalReturn = acct.initialCash > 0 ? ((acct.totalValue - acct.initialCash) / acct.initialCash * 100) : 0;
            const isPositive = totalReturn >= 0;

            // 从 equityData 取最近两日算今日涨跌
            const acctEquity = equityData?.accounts.find(a => a.accountId === acct.id)?.equity || [];
            const lastVal = acctEquity.length >= 1 ? acctEquity[acctEquity.length - 1].totalValue : null;
            const prevVal = acctEquity.length >= 2 ? acctEquity[acctEquity.length - 2].totalValue : null;
            const dailyChange = (lastVal !== null && prevVal !== null && prevVal > 0)
              ? ((lastVal - prevVal) / prevVal * 100) : null;

            const cashRatio = acct.totalValue > 0 ? (acct.cash / acct.totalValue * 100) : 100;

            const strategyLabels: string[] = [];
            const sc = acct.strategyConfig || {};
            if (sc.trend?.enabled) strategyLabels.push("均线");
            if (sc.grid?.enabled) strategyLabels.push("网格");
            if (sc.market?.enabled) strategyLabels.push("舆情");

            return (
              <button key={acct.id} onClick={() => setSelectedId(acct.id)}
                className={cn(
                  "rounded-xl border p-4 text-left transition-all",
                  selectedId === acct.id ? "bg-card border-brand-400/40 shadow-card" : "bg-card border-border-subtle shadow-card hover:border-brand-400/20"
                )}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center",
                      idx === 0 ? "bg-emerald-400/20 text-emerald-400" : idx === 1 ? "bg-blue-400/20 text-blue-400" : "bg-purple-400/20 text-purple-400")}>
                      <Icon className="h-4 w-4" />
                    </div>
                    <div className="text-left">
                      <div className="text-sm font-medium text-text-primary">{acct.name}</div>
                      <div className="text-[10px] text-text-tertiary flex gap-1">
                        {strategyLabels.map(s => <span key={s} className="bg-surface-2 px-1 rounded">{s}</span>)}
                      </div>
                    </div>
                  </div>
                  {/* 今日涨跌 */}
                  {dailyChange !== null && (
                    <span className={cn("text-xs font-semibold font-mono tabular-nums", dailyChange >= 0 ? "text-positive" : "text-negative")}>
                      {dailyChange >= 0 ? "+" : ""}{dailyChange.toFixed(2)}%
                    </span>
                  )}
                </div>
                <div className="flex items-end justify-between">
                  <div>
                    <div className="text-2xl font-bold font-mono tabular-nums text-text-primary">
                      ¥{acct.totalValue.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}
                    </div>
                    <div className="flex items-center gap-2 mt-1">
                      <span className="text-[10px] text-text-tertiary">本金 ¥{acct.initialCash.toLocaleString()}</span>
                      <span className={cn("text-[11px] font-medium font-mono", isPositive ? "text-positive" : "text-negative")}>
                        {isPositive ? "+" : ""}{totalReturn.toFixed(1)}%
                      </span>
                    </div>
                  </div>
                  {/* 现金比例小标 */}
                  <div className="text-right">
                    <div className="text-[10px] text-text-tertiary">现金占比</div>
                    <div className="text-xs font-mono tabular-nums text-text-primary">{cashRatio.toFixed(0)}%</div>
                    <div className="w-16 h-1 bg-surface-2 rounded-full mt-1 overflow-hidden">
                      <div className={cn(
                        "h-full rounded-full transition-all",
                        cashRatio > 60 ? "bg-emerald-400/40" : cashRatio > 30 ? "bg-amber-400/40" : "bg-brand-400/40"
                      )} style={{ width: `${Math.max(4, Math.min(100, cashRatio))}%` }} />
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 mt-2 pt-2 border-t border-border-subtle/50 text-[10px] text-text-tertiary">
                  <span>{acct.holdingCount || 0} 只持仓</span>
                  <span>¥{acct.positionValue.toLocaleString()} 市值</span>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {/* ── 净值对比曲线 ─────────────────────────────────────── */}
      {equityData && equityData.accounts.some(a => a.equity.length > 1) && (
        <EquityChart equityData={equityData} />
      )}

      {/* ── 选中账户分析面板 ─────────────────────────────────── */}
      {selectedId && (
        analyticsLoading ? (
          <div className="flex items-center justify-center h-24 text-text-tertiary"><Loader2 className="h-4 w-4 animate-spin mr-2" />加载分析…</div>
        ) : (
          <div className="space-y-4">
            {/* 绩效指标 */}
            {metrics && <MetricCards metrics={metrics} />}
            {/* 收益归因 */}
            {attribution.length > 0 && <AttributionCard data={attribution} />}
          </div>
        )
      )}

      {/* ── 选中账户详情（持仓 + 交易） ─────────────────────── */}
      {selectedId && (
        detailLoading ? (
          <div className="flex items-center justify-center h-32 text-text-tertiary"><Loader2 className="h-5 w-5 animate-spin mr-2" />加载详情…</div>
        ) : detail ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* 持仓 */}
            <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
              <div className="text-xs font-medium text-text-secondary mb-3 flex items-center gap-1.5">
                <BarChart3 className="h-3.5 w-3.5" /> 持仓 ({detail.positions?.length || 0})
              </div>
              {!detail.positions?.length ? (
                <div className="text-xs text-text-tertiary py-4 text-center">暂无持仓</div>
              ) : (
                <div className="space-y-2">
                  {detail.positions.map((p: any) => {
                    const pnl = (p.currentPrice - p.costPrice) * p.shares;
                    const pnlPct = p.costPrice > 0 ? (p.currentPrice - p.costPrice) / p.costPrice * 100 : 0;
                    return (
                      <div key={p.id} className="flex items-center justify-between py-1.5 border-b border-border-subtle/50 last:border-0">
                        <div className="min-w-0 text-left">
                          <div className="text-xs text-text-primary truncate">{p.fundName}</div>
                          <div className="text-[10px] text-text-tertiary">{p.fundCode} · {p.shares.toFixed(2)}份</div>
                        </div>
                        <div className="text-right">
                          <div className="text-xs font-mono tabular-nums text-text-primary">¥{(p.shares * p.currentPrice).toFixed(2)}</div>
                          <div className={cn("text-[10px] font-mono", pnl >= 0 ? "text-positive" : "text-negative")}>
                            {pnl >= 0 ? "+" : ""}{pnl.toFixed(2)} ({pnlPct >= 0 ? "+" : ""}{pnlPct.toFixed(2)}%)
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* 交易记录 */}
            <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
              <div className="text-xs font-medium text-text-secondary mb-3 flex items-center gap-1.5">
                <ArrowLeftRight className="h-3.5 w-3.5" /> 最近交易 ({detail.trades?.length || 0})
              </div>
              {!detail.trades?.length ? (
                <div className="text-xs text-text-tertiary py-4 text-center">暂无交易</div>
              ) : (
                <div className="space-y-1.5 max-h-64 overflow-y-auto scrollbar-thin">
                  {detail.trades.map((t: any) => (
                    <div key={t.id} className="flex items-center justify-between py-1 text-xs border-b border-border-subtle/30 last:border-0">
                      <div className="flex items-center gap-2 min-w-0 text-left">
                        <span className={cn("shrink-0 w-12 text-center text-[10px] font-medium rounded px-1",
                          t.direction === "buy" ? "bg-positive/10 text-positive" : "bg-negative/10 text-negative")}>
                          {t.direction === "buy" ? "买入" : "卖出"}
                        </span>
                        <div className="min-w-0 truncate">
                          <span className="text-text-primary truncate">{t.fundName}</span>
                          <span className="text-text-tertiary ml-1">{t.shares?.toFixed(2)}份</span>
                        </div>
                      </div>
                      <div className="text-right shrink-0 ml-2">
                        <div className="tabular-nums text-text-primary">¥{t.amount?.toFixed(2)}</div>
                        <div className="text-[10px] text-text-tertiary">费{t.fee?.toFixed(2)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  净值对比曲线
// ═══════════════════════════════════════════════════════════════════

function EquityChart({ equityData }: { equityData: EquityData }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  const [benchmarkCode, setBenchmarkCode] = useState("000300");
  const [benchmarkData, setBenchmarkData] = useState<BenchmarkData | null>(
    equityData.benchmark ? { ...equityData.benchmark, total: equityData.benchmark.data?.length || 0 } : null
  );

  // 切换基准指数时重新拉取
  useEffect(() => {
    benchmarkApi.history(benchmarkCode, 730)
      .then(setBenchmarkData)
      .catch(() => setBenchmarkData(null));
  }, [benchmarkCode]);

  useEffect(() => {
    if (!containerRef.current) return;
    const isDark = resolvedTheme === "dark";
    const textColor = isDark ? "#969cb0" : "#6b6b68";
    const borderColor = isDark ? "#2a2e3e" : "#e6e6e4";
    const gridColor = isDark ? "#2a2e3e" : "#f0f0ef";
    const BENCHMARK_COLOR = isDark ? "#eab308" : "#ca8a04";

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor, fontSize: 11,
        fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", "Geist Mono", monospace' },
      grid: { vertLines: { color: gridColor, style: LineStyle.Dotted }, horzLines: { color: gridColor, style: LineStyle.Dotted } },
      rightPriceScale: { borderColor, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor, fixLeftEdge: true, fixRightEdge: true },
      handleScroll: false, handleScale: false,
      autoSize: true, crosshair: { mode: 0 },
    });

    equityData.accounts.forEach((acct, idx) => {
      if (hidden[`acct_${acct.accountId}`]) return;
      if (acct.equity.length < 2) return;

      const color = ACCOUNT_COLORS[idx % ACCOUNT_COLORS.length];
      const lineSeries = chart.addSeries(LineSeries, {
        color, lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: false,
        title: acct.accountName,
      });

      lineSeries.setData(acct.equity.map(e => ({
        time: e.date as any,
        value: e.nav,
      })));
    });

    // 基准指数叠加线
    const bench = benchmarkData;
    if (bench?.data?.length && !hidden.benchmark) {
      const benchSeries = chart.addSeries(LineSeries, {
        color: BENCHMARK_COLOR,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        priceLineVisible: false,
        lastValueVisible: true,
        crosshairMarkerVisible: false,
        title: bench.name,
      });
      benchSeries.setData(bench.data.map(d => ({
        time: d.date as any,
        value: d.nav,
      })));
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [equityData, benchmarkData, resolvedTheme, hidden]);

  if (!equityData.accounts.some(a => a.equity.length > 1)) return null;

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
          <TrendingUp className="h-3.5 w-3.5" /> 净值对比（归一化至 100）
        </div>
        <div className="flex gap-2 flex-wrap">
          {equityData.accounts.map((acct, idx) => (
            <button key={acct.accountId}
              onClick={() => setHidden(prev => ({ ...prev, [`acct_${acct.accountId}`]: !prev[`acct_${acct.accountId}`] }))}
              className={cn("flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded transition-all", hidden[`acct_${acct.accountId}`] ? "opacity-30" : "")}
              style={{ color: ACCOUNT_COLORS[idx % ACCOUNT_COLORS.length] }}>
              <span className="w-2 h-2 rounded-full inline-block" style={{ backgroundColor: ACCOUNT_COLORS[idx % ACCOUNT_COLORS.length] }} />
              {acct.accountName}
            </button>
          ))}
          <select
            value={benchmarkCode}
            onChange={(e) => setBenchmarkCode(e.target.value)}
            className="text-[10px] bg-surface-1 border border-border-subtle rounded px-1.5 py-0.5 text-text-tertiary outline-none"
          >
            <option value="000300">沪深300</option>
            <option value="000905">中证500</option>
            <option value="000922">中证红利</option>
            <option value="000016">上证50</option>
          </select>
          {benchmarkData?.data?.length ? (
            <button onClick={() => setHidden(prev => ({ ...prev, benchmark: !prev.benchmark }))}
              className={cn("flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded transition-all",
                hidden.benchmark ? "opacity-30" : "", "text-yellow-600 dark:text-yellow-400")}>
              <span className="w-2 h-2 rounded-full inline-block bg-yellow-600 dark:bg-yellow-400" />
              {benchmarkData.name}
            </button>
          ) : null}
        </div>
      </div>
      <div className="h-72" ref={containerRef} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  绩效指标卡
// ═══════════════════════════════════════════════════════════════════

function MetricCards({ metrics }: { metrics: Record<string, any> }) {
  const profit = metrics.total_profit || 0;
  const isPositive = profit >= 0;

  const cards = [
    { label: "总收益", value: `${isPositive ? "+" : ""}${(metrics.total_return || 0).toFixed(2)}%`, sub: `¥${profit.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`, color: isPositive ? "text-positive" : "text-negative", icon: TrendingUp },
    { label: "年化收益", value: `${(metrics.annual_return || 0).toFixed(2)}%`, color: (metrics.annual_return || 0) >= 0 ? "text-positive" : "text-negative", icon: Percent },
    { label: "最大回撤", value: `${(metrics.max_drawdown_pct || 0).toFixed(2)}%`, color: "text-negative", icon: TrendingDown },
    { label: "Sharpe", value: (metrics.sharpe_ratio || 0).toFixed(2), color: (metrics.sharpe_ratio || 0) >= 1 ? "text-positive" : (metrics.sharpe_ratio || 0) >= 0 ? "text-warning" : "text-negative", icon: Activity },
    { label: "波动率", value: `${(metrics.volatility || 0).toFixed(2)}%`, color: (metrics.volatility || 0) > 20 ? "text-negative" : "text-text-primary", icon: Activity },
    { label: "Calmar", value: (metrics.calmar_ratio || 0).toFixed(2), color: (metrics.calmar_ratio || 0) >= 1 ? "text-positive" : "text-text-primary", icon: Timer },
    { label: "上涨日", value: `${metrics.win_days || 0}`, sub: `${(metrics.win_rate_days || 0).toFixed(1)}%胜率`, color: "text-positive", icon: TrendingUp },
    { label: "下跌日", value: `${metrics.loss_days || 0}`, color: "text-negative", icon: TrendingDown },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
      {cards.map((c) => (
        <div key={c.label} className="rounded-xl bg-card border border-border-subtle shadow-card p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] text-text-tertiary font-medium">{c.label}</span>
            <c.icon className={cn("h-3 w-3", c.color || "text-text-tertiary")} />
          </div>
          <div className={cn("text-sm font-semibold font-mono tabular-nums", c.color || "text-text-primary")}>
            {c.value}
          </div>
          {c.sub && (
            <div className="text-[10px] text-text-tertiary mt-0.5">{c.sub}</div>
          )}
        </div>
      ))}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  收益归因卡
// ═══════════════════════════════════════════════════════════════════

function AttributionCard({ data }: { data: { agent_name: string; total_pnl: number; pnl_share_pct: number; total_trades: number; avg_confidence: number }[] }) {
  const AGENT_LABELS: Record<string, string> = { trend: "趋势策略", grid: "网格策略", market: "舆情策略" };
  const AGENT_COLORS: Record<string, string> = { trend: "text-emerald-400", grid: "text-blue-400", market: "text-purple-400" };
  const AGENT_BG: Record<string, string> = { trend: "bg-emerald-400/10", grid: "bg-blue-400/10", market: "bg-purple-400/10" };

  // 以最大的 abs(pnl_share_pct) 为基准缩放宽度
  const maxAbs = Math.max(...data.map(d => Math.abs(d.pnl_share_pct)), 1);

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="flex items-center gap-1.5 mb-3">
        <PieChart className="h-3.5 w-3.5 text-text-tertiary" />
        <span className="text-xs font-medium text-text-secondary">收益来源归因</span>
      </div>
      <div className="space-y-3">
        {data.map((d) => {
          const label = AGENT_LABELS[d.agent_name] || d.agent_name;
          const color = AGENT_COLORS[d.agent_name] || "text-text-primary";
          const bg = AGENT_BG[d.agent_name] || "bg-surface-2";
          const isPositive = d.total_pnl >= 0;
          const barWidth = Math.max(4, Math.abs(d.pnl_share_pct) / maxAbs * 100);
          return (
              <div key={d.agent_name}>
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-1.5">
                    <Brain className={cn("h-3 w-3", color)} />
                    <span className="text-xs text-text-primary font-medium">{label}</span>
                    <span className="text-[10px] text-text-tertiary">({d.total_trades}笔)</span>
                  </div>
                  <span className={cn("text-xs font-mono tabular-nums font-medium", isPositive ? "text-positive" : "text-negative")}>
                    {isPositive ? "+" : ""}¥{d.total_pnl.toFixed(2)} ({d.pnl_share_pct.toFixed(1)}%)
                  </span>
                </div>
                {/* 条形图 — 按最大值为基准缩放 */}
                <div className="h-2 bg-surface-2 rounded-full overflow-hidden">
                  <div
                    className={cn("h-full rounded-full transition-all", bg)}
                    style={{ width: `${barWidth}%` }}
                  />
              </div>
              <div className="text-[10px] text-text-tertiary mt-0.5">
                平均置信度 {d.avg_confidence.toFixed(0)}%
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
