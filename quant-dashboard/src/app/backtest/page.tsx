"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { backtestApi, fundApi, benchmarkApi } from "@/lib/api";
import type { BenchmarkData } from "@/lib/api";
import type {
  BacktestFund, BacktestConfig, BacktestRunResponse,
  EquityPoint, BacktestTrade, BacktestMetrics,
} from "@/lib/api";
import {
  Play, Loader2, TrendingUp, TrendingDown, Activity,
  BarChart3, AlertTriangle, AlertCircle, RefreshCw,
  Calendar, DollarSign, Percent, Pipette,
  Layers, ArrowUpRight, ArrowDownRight, Timer, FlaskConical,
} from "lucide-react";
import { createChart, ColorType, LineStyle, AreaSeries, LineSeries } from "lightweight-charts";
import type { IChartApi, ISeriesApi } from "lightweight-charts";
import { cn } from "@/lib/utils";
import { useTheme } from "next-themes";

const DEFAULT_MA_PARAMS = { period: 20, upper: 105, lower: 95 };
const DEFAULT_GRID_PARAMS = { upperPrice: 1.5, lowerPrice: 1.0, stepCount: 5, stepSize: 0.1 };

export default function BacktestPage() {
  const [funds, setFunds] = useState<BacktestFund[]>([]);
  const [loadingFunds, setLoadingFunds] = useState(true);

  // ── 参数 ──────────────────────────────────────────────────
  const [selectedFund, setSelectedFund] = useState<BacktestFund | null>(null);
  const [strategyType, setStrategyType] = useState<"ma" | "grid">("ma");
  const [maParams, setMaParams] = useState(DEFAULT_MA_PARAMS);
  const [gridParams, setGridParams] = useState(DEFAULT_GRID_PARAMS);
  const [initialCash, setInitialCash] = useState(100000);
  const [buyFeeRate, setBuyFeeRate] = useState(0.15);
  const [maxPositionPct, setMaxPositionPct] = useState(95);
  const [maxDrawdownPct, setMaxDrawdownPct] = useState(25);

  // ── 回测状态 ──────────────────────────────────────────────
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestRunResponse | null>(null);
  const [error, setError] = useState("");

  // ── 部署到模拟盘状态 ──────────────────────────────────────
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState("");

  // ── 加载基金列表 ──────────────────────────────────────────
  useEffect(() => {
    async function load() {
      setLoadingFunds(true);
      try {
        const f = await backtestApi.funds().catch(() => null);
        const dbFunds = await fundApi.list().catch(() => null);
        // 合并：优先用 backtest/funds（带 dataStart/End），缺的从 fund list 补
        const btFunds = f?.funds || [];
        if (dbFunds?.data?.length) {
          const btCodes = new Set(btFunds.map((bf: BacktestFund) => bf.code));
          for (const df of dbFunds.data) {
            if (!btCodes.has(df.code)) {
              btFunds.push({
                id: df.id, code: df.code, name: df.name,
                currentPrice: df.currentPrice,
                dataStart: null, dataEnd: null, dataPoints: 0,
              });
            }
          }
        }
        setFunds(btFunds);
        if (btFunds.length > 0) setSelectedFund(btFunds[0]);
      } catch {
        // fallback mock funds
        const mockFunds: BacktestFund[] = [
          { id: 1, code: "110011", name: "易方达中小盘混合", currentPrice: 2.12, dataStart: null, dataEnd: null, dataPoints: 0 },
          { id: 2, code: "005827", name: "中欧医疗健康混合C", currentPrice: 0.68, dataStart: null, dataEnd: null, dataPoints: 0 },
          { id: 3, code: "001938", name: "中欧时代先锋股票A", currentPrice: 1.35, dataStart: null, dataEnd: null, dataPoints: 0 },
          { id: 4, code: "260108", name: "景顺长城新兴成长混合", currentPrice: 1.96, dataStart: null, dataEnd: null, dataPoints: 0 },
          { id: 5, code: "003095", name: "中欧医疗健康混合A", currentPrice: 0.72, dataStart: null, dataEnd: null, dataPoints: 0 },
        ];
        setFunds(mockFunds);
        setSelectedFund(mockFunds[0]);
      } finally {
        setLoadingFunds(false);
      }
    }
    load();
  }, []);

  // ── 运行回测 ──────────────────────────────────────────────
  const runBacktest = useCallback(async () => {
    if (!selectedFund) return;
    setRunning(true);
    setError("");
    setResult(null);

    try {
      const params: Record<string, any> = {
        fundCode: selectedFund.code,
        fundName: selectedFund.name,
        strategyType,
        strategyParams: strategyType === "ma" ? maParams : gridParams,
        initialCash,
        buyFeeRate: buyFeeRate / 100,
        maxPositionPct: maxPositionPct / 100,
        maxDrawdownPct: maxDrawdownPct / 100,
      };

      const res = await backtestApi.run(params);
      if (res.status === "error") {
        setError(res.message || "回测失败");
      } else {
        setResult(res);
      }
    } catch (e: any) {
      setError(e.message || "请求失败");
    } finally {
      setRunning(false);
    }
  }, [selectedFund, strategyType, maParams, gridParams, initialCash, buyFeeRate, maxPositionPct, maxDrawdownPct]);

  // ── 部署到模拟盘 ──────────────────────────────────────────
  const deployToSim = useCallback(async () => {
    if (!selectedFund) return;
    setDeploying(true);
    setDeployResult("");
    try {
      const res = await backtestApi.deploy({
        fundCode: selectedFund.code,
        strategyType,
        strategyParams: strategyType === "ma" ? maParams : gridParams,
        initialCash,
        name: `回测·${selectedFund.name.slice(0, 8)} ${strategyType.toUpperCase()}`,
        maxPositionPct: maxPositionPct / 100,
        maxDrawdownPct: maxDrawdownPct / 100,
      });
      if (res.status === "ok") {
        setDeployResult(res.message
          ? `⏭ ${res.message} (ID=${res.accountId})`
          : `✅ 已部署到模拟盘: "${res.accountName}" (ID=${res.accountId})`);
      } else {
        setDeployResult(`❌ ${res.message || "部署失败"}`);
      }
    } catch (e: any) {
      setDeployResult(`❌ ${e.message || "请求失败"}`);
    } finally {
      setDeploying(false);
    }
  }, [selectedFund, strategyType, maParams, gridParams, initialCash, maxPositionPct, maxDrawdownPct]);

  // ── 换算参数 ──────────────────────────────────────────────
  const metrics = result?.metrics;
  const equity = result?.equityCurve || [];
  const trades = result?.trades || [];

  return (
    <div className="flex gap-4 h-[calc(100vh-6rem)]">
      {/* ═══ 左侧参数面板 ═══ */}
      <div className="w-72 shrink-0 space-y-4 overflow-y-auto pr-2 scrollbar-thin">
        <div>
          <h1 className="text-xl font-semibold text-text-primary tracking-tight">回测引擎</h1>
          <p className="text-xs text-text-tertiary mt-0.5">策略历史表现验证</p>
        </div>

        {/* 基金选择 */}
        <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3 space-y-3">
          <h3 className="text-xs font-medium text-text-secondary tracking-wide">基金</h3>
          {loadingFunds ? (
            <div className="text-xs text-text-tertiary py-2">加载中…</div>
          ) : (
            <select
              value={selectedFund?.code || ""}
              onChange={(e) => {
                const f = funds.find((ff) => ff.code === e.target.value);
                if (f) setSelectedFund(f);
              }}
              className="w-full text-xs bg-surface-1 border border-border-subtle rounded-lg px-2.5 py-1.5 text-text-primary outline-none focus:border-brand-400/50"
            >
              {funds.map((f) => (
                <option key={f.code} value={f.code}>{f.name} ({f.code})</option>
              ))}
            </select>
          )}
          {selectedFund?.dataPoints ? (
            <div className="text-[10px] text-text-tertiary">
              数据: {selectedFund.dataStart} ~ {selectedFund.dataEnd} ({selectedFund.dataPoints}条)
            </div>
          ) : (
            <div className="text-[10px] text-text-tertiary">数据: 自动从 API 获取</div>
          )}
        </div>

        {/* 策略类型 */}
        <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3 space-y-3">
          <h3 className="text-xs font-medium text-text-secondary tracking-wide">策略</h3>
          <div className="flex gap-2">
            {(["ma", "grid"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setStrategyType(t)}
                className={cn(
                  "flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors",
                  strategyType === t
                    ? "bg-brand-400/20 text-brand-400 border border-brand-400/30"
                    : "bg-surface-1 text-text-tertiary border border-border-subtle hover:text-text-primary"
                )}
              >
                {t === "ma" ? "MA均线" : "网格交易"}
              </button>
            ))}
          </div>
          {strategyType === "ma" ? (
            <div className="space-y-2">
              <LabelInput label="周期(period)" value={maParams.period} onChange={(v) => setMaParams(p => ({ ...p, period: v }))} />
              <LabelInput label="上轨%" value={maParams.upper} onChange={(v) => setMaParams(p => ({ ...p, upper: v }))} />
              <LabelInput label="下轨%" value={maParams.lower} onChange={(v) => setMaParams(p => ({ ...p, lower: v }))} />
            </div>
          ) : (
            <div className="space-y-2">
              <LabelInput label="上界" value={gridParams.upperPrice} step={0.1} onChange={(v) => setGridParams(p => ({ ...p, upperPrice: v }))} />
              <LabelInput label="下界" value={gridParams.lowerPrice} step={0.1} onChange={(v) => setGridParams(p => ({ ...p, lowerPrice: v }))} />
              <LabelInput label="层数" value={gridParams.stepCount} onChange={(v) => setGridParams(p => ({ ...p, stepCount: v }))} />
              <LabelInput label="步距" value={gridParams.stepSize} step={0.01} onChange={(v) => setGridParams(p => ({ ...p, stepSize: v }))} />
            </div>
          )}
        </div>

        {/* 资金 & 风控 */}
        <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3 space-y-2">
          <h3 className="text-xs font-medium text-text-secondary tracking-wide">资金 & 风控</h3>
          <LabelInput label="初始资金" value={initialCash} step={10000} min={1000} prefix="¥" onChange={setInitialCash} />
          <LabelPercent label="申购费率" value={buyFeeRate} onChange={setBuyFeeRate} />
          <LabelPercent label="单次仓位" value={maxPositionPct} onChange={setMaxPositionPct} />
          <LabelPercent label="回撤止损" value={maxDrawdownPct} onChange={setMaxDrawdownPct} />
        </div>

        {/* 运行按钮 */}
        <button
          onClick={runBacktest}
          disabled={running || !selectedFund}
          className={cn(
            "w-full h-9 rounded-xl text-sm font-medium flex items-center justify-center gap-2 transition-all",
            running
              ? "bg-brand-400/10 text-brand-400 cursor-wait"
              : "bg-brand-400/20 text-brand-400 hover:bg-brand-400/30 active:scale-[0.98]"
          )}
        >
          {running ? (
            <><Loader2 className="h-4 w-4 animate-spin" /> 回测中…</>
          ) : (
            <><Play className="h-4 w-4" /> 运行回测</>
          )}
        </button>

        {error && (
          <div className="flex items-start gap-2 text-xs text-negative bg-negative/10 rounded-lg px-3 py-2">
            <AlertCircle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* ═══ 右侧结果面板 ═══ */}
      <div className="flex-1 flex flex-col min-w-0 space-y-4 overflow-y-auto scrollbar-thin">
        {!result && !error && (
          <div className="flex flex-col items-center justify-center h-96 text-text-tertiary space-y-3">
            <BarChart3 className="h-12 w-12" />
            <h2 className="text-lg font-medium text-text-primary">设置参数并运行回测</h2>
            <p className="text-sm">选择基金和策略，点击"运行回测"查看历史表现</p>
          </div>
        )}

        {result && metrics && Object.keys(metrics).length > 0 && (
          <>
            {/* 绩效指标卡片 */}
            <MetricCards metrics={metrics} initialCash={result.config?.initialCash || 100000} />

            {/* 部署到模拟盘 */}
            <div className="flex items-center justify-between rounded-xl bg-card border border-border-subtle shadow-card p-3">
              <div className="text-xs text-text-secondary">
                <span className="font-medium">部署到模拟盘</span>
                <span className="text-text-tertiary ml-2">使用当前参数创建模拟盘账户验证实盘表现</span>
              </div>
              <div className="flex items-center gap-2">
                {deployResult && <span className="text-[10px] text-text-tertiary">{deployResult}</span>}
                <button onClick={deployToSim} disabled={deploying}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                    deploying
                      ? "bg-brand-400/10 text-brand-400 cursor-wait"
                      : "bg-brand-400/20 text-brand-400 hover:bg-brand-400/30 active:scale-[0.98]"
                  )}>
                  {deploying ? <Loader2 className="h-3 w-3 animate-spin" /> : <FlaskConical className="h-3 w-3" />}
                  {deploying ? "部署中…" : "部署到模拟盘"}
                </button>
              </div>
            </div>

            {/* 净值曲线图 */}
            <EquityChart equity={equity} />

            {/* 模拟交易记录 */}
            <TradeTable trades={trades} />
          </>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
// 子组件
// ═══════════════════════════════════════════════════════════════════

function LabelInput({ label, value, onChange, min = 1, max, step = 1, prefix = "" }: {
  label: string; value: number; onChange: (v: number) => void;
  min?: number; max?: number; step?: number; prefix?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-text-tertiary w-16 shrink-0">{label}</span>
      <div className="flex-1 relative">
        {prefix && (
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-[11px] text-text-tertiary">{prefix}</span>
        )}
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            if (!isNaN(v)) onChange(v);
          }}
          className={cn(
            "w-full text-xs bg-surface-1 border border-border-subtle rounded-lg py-1 outline-none focus:border-brand-400/50 text-text-primary",
            prefix ? "pl-5 pr-2" : "px-2"
          )}
        />
      </div>
    </div>
  );
}

function LabelPercent({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-text-tertiary w-16 shrink-0">{label}</span>
      <input
        type="number"
        value={value}
        min={0}
        max={100}
        step={0.05}
        onChange={(e) => {
          const v = parseFloat(e.target.value);
          if (!isNaN(v)) onChange(v);
        }}
        className="flex-1 text-xs bg-surface-1 border border-border-subtle rounded-lg px-2 py-1 outline-none focus:border-brand-400/50 text-text-primary"
      />
      <span className="text-[11px] text-text-tertiary w-4">%</span>
    </div>
  );
}

// ── 绩效指标卡 ─────────────────────────────────────────────

function MetricCards({ metrics, initialCash }: { metrics: BacktestMetrics; initialCash: number }) {
  const profit = metrics.total_profit || 0;
  const isPositive = profit >= 0;

  // 与基准比较
  const vsBenchmark = (metrics.benchmark_return !== undefined && metrics.benchmark_return !== null)
    ? ((metrics.total_return || 0) - metrics.benchmark_return * 100).toFixed(2)
    : null;

  const cards = [
    { label: "总收益", value: `${isPositive ? "+" : ""}${metrics.total_return?.toFixed(2) || "0"}%`, sub: `¥${(profit).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`, color: isPositive ? "text-positive" : "text-negative", icon: TrendingUp },
    { label: "年化收益", value: `${metrics.annual_return?.toFixed(2) || "0"}%`, color: (metrics.annual_return || 0) >= 0 ? "text-positive" : "text-negative", icon: Percent },
    {
      label: "最大回撤", value: `${metrics.max_drawdown_pct?.toFixed(2) || "0"}%`,
      sub: vsBenchmark !== null ? `vs 沪深300 ${vsBenchmark}%` : undefined,
      color: "text-negative", icon: TrendingDown,
    },
    { label: "Sharpe", value: metrics.sharpe_ratio?.toFixed(2) || "-", color: (metrics.sharpe_ratio || 0) >= 1 ? "text-positive" : (metrics.sharpe_ratio || 0) >= 0 ? "text-warning" : "text-negative", icon: Activity },
    { label: "胜率", value: `${metrics.win_rate || "0"}%`, color: (metrics.win_rate || 0) >= 50 ? "text-positive" : "text-negative", icon: Pipette },
    { label: "交易次数", value: `${metrics.total_trades || 0}`, sub: `买${metrics.total_buys || 0} / 卖${metrics.total_sells || 0}`, icon: Layers },
    { label: "Calmar", value: metrics.calmar_ratio?.toFixed(2) || "-", icon: Timer },
    { label: "日均持仓", value: `${metrics.avg_hold_days || "-"}天`, icon: Calendar },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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

// ── 净值曲线图（含基准对比）─────────────────────────────────

function EquityChart({ equity }: { equity: EquityPoint[] }) {
  const chartRef = useRef<IChartApi | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();
  const [benchmarkData, setBenchmarkData] = useState<BenchmarkData | null>(null);
  const [showBenchmark, setShowBenchmark] = useState(true);
  const [benchmarkCode, setBenchmarkCode] = useState("000300");

  // 加载基准指数数据
  useEffect(() => {
    benchmarkApi.history(benchmarkCode, 1095)
      .then(setBenchmarkData)
      .catch(() => setBenchmarkData(null));
  }, [benchmarkCode]);

  // 归一化基准到回测起始
  const normalizedBenchmark = useCallback(() => {
    if (!benchmarkData?.data?.length || !equity.length) return null;
    const firstDate = equity[0].date;
    const startIdx = benchmarkData.data.findIndex(d => d.date >= firstDate);
    if (startIdx < 0) return null;
    const relevant = benchmarkData.data.slice(startIdx);
    if (relevant.length < 2) return null;
    const baseVal = relevant[0].close;
    if (!baseVal || baseVal <= 0) return null;
    return relevant.map(d => ({
      time: d.date as any,
      value: Math.round(d.close / baseVal * (equity[0].totalValue || 100) * 100) / 100,
    }));
  }, [benchmarkData, equity]);

  useEffect(() => {
    if (!containerRef.current || equity.length < 2) return;

    const isDark = resolvedTheme === "dark";
    const textColor = isDark ? "#969cb0" : "#6b6b68";
    const borderColor = isDark ? "#2a2e3e" : "#e6e6e4";
    const gridColor = isDark ? "#2a2e3e" : "#f0f0ef";
    const lineColor = isDark ? "#22c55e" : "#16a34a";

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor,
        fontSize: 11,
        fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", "Geist Mono", monospace',
      },
      grid: {
        vertLines: { color: gridColor, style: LineStyle.Dotted },
        horzLines: { color: gridColor, style: LineStyle.Dotted },
      },
      rightPriceScale: { borderColor, scaleMargins: { top: 0.1, bottom: 0.05 } },
      timeScale: { borderColor, timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
      handleScroll: false,
      handleScale: false,
      autoSize: true,
      crosshair: { mode: 0 },
    });

    // 策略净值（底色区域）
    const areaSeries = chart.addSeries(AreaSeries, {
      lineColor,
      lineWidth: 2,
      topColor: isDark ? "rgba(34, 197, 94, 0.15)" : "rgba(22, 163, 74, 0.10)",
      bottomColor: isDark ? "rgba(34, 197, 94, 0.01)" : "rgba(22, 163, 74, 0.01)",
      priceLineVisible: false,
      crosshairMarkerVisible: false,
      lastValueVisible: true,
      title: "策略",
    });

    const data = equity.filter(e => e.totalValue > 0).map(e => ({
      time: e.date as any,
      value: e.totalValue,
    }));

    areaSeries.setData(data);

    // 基准对比线
    if (showBenchmark) {
      const benchNormalized = normalizedBenchmark();
      if (benchNormalized) {
        const benchSeries = chart.addSeries(LineSeries, {
          color: isDark ? "#eab308" : "#ca8a04",
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: false,
          title: benchmarkData?.name || "沪深300",
        });
        benchSeries.setData(benchNormalized);
      }
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    return () => {
      chart.remove();
    };
  }, [equity, resolvedTheme, showBenchmark, normalizedBenchmark, benchmarkData]);

  if (equity.length < 2) return null;

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-text-tertiary font-medium">净值曲线</div>
        <div className="flex items-center gap-2">
          <select
            value={benchmarkCode}
            onChange={(e) => setBenchmarkCode(e.target.value)}
            className="text-[10px] bg-surface-1 border border-border-subtle rounded px-1.5 py-0.5 text-text-tertiary outline-none"
          >
            <option value="000300">沪深300</option>
            <option value="000905">中证500</option>
            <option value="000922">中证红利</option>
          </select>
          <button onClick={() => setShowBenchmark(v => !v)}
            className={cn("text-[10px] px-1.5 py-0.5 rounded transition-all",
              showBenchmark ? "text-yellow-600 dark:text-yellow-400 bg-yellow-400/10" : "opacity-40 text-text-tertiary")}>
            {benchmarkData?.name || "基准"}
          </button>
        </div>
      </div>
      <div className="h-64" ref={containerRef} />
    </div>
  );
}

// ── 交易记录表 ─────────────────────────────────────────────

function TradeTable({ trades }: { trades: BacktestTrade[] }) {
  const [showAll, setShowAll] = useState(false);
  const display = showAll ? trades : trades.slice(-20);
  const hasMore = trades.length > 20;

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-text-tertiary font-medium">模拟交易记录 ({trades.length}笔)</span>
      </div>

      {trades.length === 0 ? (
        <div className="py-8 text-center text-text-tertiary text-sm">无交易记录</div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border-subtle text-[10px] text-text-tertiary">
                  <th className="text-left py-2 pr-2 font-medium">日期</th>
                  <th className="text-left py-2 px-2 font-medium">方向</th>
                  <th className="text-right py-2 px-2 font-medium">价格</th>
                  <th className="text-right py-2 px-2 font-medium">份额</th>
                  <th className="text-right py-2 px-2 font-medium">金额</th>
                  <th className="text-right py-2 px-2 font-medium">手续费</th>
                  <th className="text-left py-2 pl-2 font-medium">原因</th>
                </tr>
              </thead>
              <tbody>
                {display.map((t, i) => (
                  <tr key={i} className="border-b border-border-subtle/50 hover:bg-surface-2/30">
                    <td className="py-1.5 pr-2 tabular-nums text-text-primary">{t.date}</td>
                    <td className="py-1.5 px-2">
                      <span className={cn("inline-flex items-center gap-1 font-medium", t.action === "buy" ? "text-positive" : "text-negative")}>
                        {t.action === "buy" ? <ArrowUpRight className="h-2.5 w-2.5" /> : <ArrowDownRight className="h-2.5 w-2.5" />}
                        {t.action === "buy" ? "买入" : "卖出"}
                      </span>
                    </td>
                    <td className="py-1.5 px-2 text-right tabular-nums text-text-primary">{t.price.toFixed(4)}</td>
                    <td className="py-1.5 px-2 text-right tabular-nums text-text-primary">{t.shares.toFixed(2)}</td>
                    <td className="py-1.5 px-2 text-right tabular-nums text-text-primary font-medium">¥{t.amount.toFixed(2)}</td>
                    <td className="py-1.5 px-2 text-right tabular-nums text-text-tertiary">{t.fee.toFixed(2)}</td>
                    <td className="py-1.5 pl-2 text-text-tertiary max-w-[160px] truncate" title={t.reason}>{t.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {hasMore && (
            <button
              onClick={() => setShowAll(!showAll)}
              className="w-full mt-2 py-1.5 text-[11px] text-text-tertiary hover:text-text-primary text-center transition-colors"
            >
              {showAll ? "收起" : `查看全部 ${trades.length} 笔 >`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
