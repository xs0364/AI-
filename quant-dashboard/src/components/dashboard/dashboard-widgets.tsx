"use client";

import { useEffect, useState } from "react";
import { tradeApi, analyticsApi } from "@/lib/api";
import { format } from "date-fns";
import {
  ArrowUpRight, ArrowDownRight, Activity, TrendingUp, TrendingDown,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { Trade } from "@/lib/types";

export function LatestTrades() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const res = await tradeApi.list({ limit: 10 });
        if (res.data?.length) {
          setTrades(res.data);
        } else {
          fallbackMock();
        }
      } catch {
        fallbackMock();
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  function fallbackMock() {
    const now = new Date();
    setTrades([
      { id: 7, fundId: 1, direction: "buy", price: 2.15, shares: 200, amount: 430, strategy: "均线趋势", strategyId: 1, time: new Date(now.getTime() - 7200000).toISOString(), status: "executed" },
      { id: 6, fundId: 3, direction: "sell", price: 1.38, shares: 300, amount: 414, strategy: "均线趋势", strategyId: 1, time: new Date(now.getTime() - 18000000).toISOString(), status: "executed" },
      { id: 5, fundId: 4, direction: "buy", price: 0.72, shares: 500, amount: 360, strategy: "均线网格", strategyId: 2, time: new Date(now.getTime() - 86400000).toISOString(), status: "executed" },
      { id: 4, fundId: 2, direction: "sell", price: 0.68, shares: 150, amount: 102, strategy: "均线网格", strategyId: 2, time: new Date(now.getTime() - 172800000).toISOString(), status: "executed" },
    ]);
  }

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-text-tertiary font-medium">最新交易</span>
        <Badge variant="outline" className="h-5 text-[10px] font-normal">
          <Activity className="h-3 w-3 mr-1" />
          实时
        </Badge>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-32 text-text-tertiary text-sm">
          加载中…
        </div>
      ) : trades.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-text-tertiary text-sm">
          暂无交易
        </div>
      ) : (
        <div className="space-y-1">
          {trades.map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-3 p-2 rounded-lg hover:bg-surface-2 transition-colors"
            >
              {/* 方向图标 */}
              <div
                className={cn(
                  "w-7 h-7 rounded-lg flex items-center justify-center shrink-0",
                  t.direction === "buy"
                    ? "bg-positive/10 text-positive"
                    : "bg-negative/10 text-negative"
                )}
              >
                {t.direction === "buy" ? (
                  <ArrowUpRight className="h-3.5 w-3.5" />
                ) : (
                  <ArrowDownRight className="h-3.5 w-3.5" />
                )}
              </div>

              {/* 详情 */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-text-primary">
                    {t.direction === "buy" ? "买入" : "卖出"}
                  </span>
                  <span className="text-xs text-text-secondary tabular-nums">
                    {t.shares} 份 @ ¥{t.price.toFixed(4)}
                  </span>
                  {t.strategy && (
                    <Badge variant="outline" className="h-5 text-[10px] font-normal">
                      {t.strategy}
                    </Badge>
                  )}
                </div>
                <div className="text-[11px] text-text-tertiary">
                  {t.time ? format(new Date(t.time), "MM-dd HH:mm") : "-"}
                  <span className="mx-1">·</span>
                  ¥{t.amount.toFixed(2)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function StrategyStatus() {
  const [strategies, setStrategies] = useState<any[]>([]);

  useEffect(() => {
    async function load() {
      try {
        const res = await import("@/lib/api").then((m) => m.strategyApi.list());
        if (res.data?.length) {
          setStrategies(res.data);
        } else {
          setStrategies([
            { id: 1, name: "均线趋势 - 易方达中小盘", type: "ma", enabled: true },
            { id: 2, name: "网格交易 - 中欧医疗A", type: "grid", enabled: true },
            { id: 3, name: "均线网格混合", type: "ma", enabled: false },
          ]);
        }
      } catch {
        setStrategies([
          { id: 1, name: "均线趋势 - 易方达中小盘", type: "ma", enabled: true },
          { id: 2, name: "网格交易 - 中欧医疗A", type: "grid", enabled: true },
          { id: 3, name: "均线网格混合", type: "ma", enabled: false },
        ]);
      }
    }
    load();
  }, []);

  const active = strategies.filter((s) => s.enabled).length;

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-text-tertiary font-medium">策略运行状态</span>
        <Badge variant="outline" className="h-5 text-[10px] font-normal text-positive border-positive/30">
          <span className="w-1.5 h-1.5 rounded-full bg-positive mr-1" />
          {active}/{strategies.length}
        </Badge>
      </div>

      <div className="space-y-1.5">
        {strategies.map((s) => (
          <div key={s.id} className="flex items-center justify-between py-1">
            <div className="flex items-center gap-2 text-sm text-text-primary">
              <TrendingUp className="h-3.5 w-3.5 text-text-tertiary" />
              <span>{s.name}</span>
            </div>
            <span
              className={cn(
                "text-[11px] font-medium",
                s.enabled ? "text-positive" : "text-text-tertiary"
              )}
            >
              {s.enabled ? "运行中" : "已暂停"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function RiskMetrics() {
  const metrics = [
    { label: "最大回撤", value: "-8.42%" },
    { label: "Sharpe Ratio", value: "1.28" },
    { label: "年化波动率", value: "15.3%" },
    { label: "胜率", value: "62.5%" },
    { label: "总交易次数", value: "24" },
  ];

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="text-xs text-text-tertiary font-medium mb-3">风险指标</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2">
        {metrics.map((m) => (
          <div key={m.label} className="flex items-center justify-between">
            <span className="text-xs text-text-tertiary">{m.label}</span>
            <span className="text-sm font-mono tabular-nums font-semibold text-text-primary">
              {m.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
