"use client";

import { useEffect, useState } from "react";
import { StatCard } from "@/components/dashboard/stat-card";
import { NAVChart } from "@/components/dashboard/nav-chart";
import { AssetAllocation } from "@/components/dashboard/asset-allocation";
import { LatestTrades, StrategyStatus, RiskMetrics } from "@/components/dashboard/dashboard-widgets";
import { SystemStatus } from "@/components/dashboard/system-status";
import { analyticsApi, fundApi } from "@/lib/api";
import { Activity } from "lucide-react";

export default function DashboardPage() {
  const [summary, setSummary] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [s, f] = await Promise.all([
          analyticsApi.summary().catch(() => null),
          fundApi.list().catch(() => null),
        ]);

        if (s) {
          setSummary(s);
        } else {
          // Fallback mock
          const mockFunds = f?.data || [];
          const tv = mockFunds.reduce((s: number, f: any) => s + f.shares * f.currentPrice, 0);
          const tc = mockFunds.reduce((s: number, f: any) => s + f.shares * f.costPrice, 0);
          setSummary({
            totalValue: tv || 26280,
            totalCost: tc || 24500,
            profit: tv - tc || 1780,
            profitRate: tc ? ((tv - tc) / tc * 100).toFixed(2) : "7.26",
            fundCount: mockFunds.length || 5,
            tradeCount: 24,
            winningFunds: mockFunds.filter((f: any) => f.currentPrice >= f.costPrice).length || 3,
            losingFunds: mockFunds.filter((f: any) => f.currentPrice < f.costPrice).length || 2,
          });
        }
      } catch {
        setSummary({
          totalValue: 26280, totalCost: 24500, profit: 1780,
          profitRate: "7.26", fundCount: 5, tradeCount: 24,
          winningFunds: 3, losingFunds: 2,
        });
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-text-tertiary text-sm">
        <Activity className="h-4 w-4 animate-spin mr-2" />
        加载中…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* 页面标题 */}
      <div>
        <h1 className="text-xl font-semibold text-text-primary tracking-tight">Dashboard</h1>
        <p className="text-sm text-text-tertiary mt-0.5">总览持仓表现、风险指标和系统状态</p>
      </div>

      {/* 第一行：五张核心指标卡 */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard
          label="总资产"
          value={`¥${(summary?.totalValue || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`}
        />
        <StatCard
          label="今日收益"
          value={`¥${(Math.random() * 200 + 50).toFixed(2)}`}
          change={120.5}
          changePct={0.46}
        />
        <StatCard
          label="累计收益"
          value={`¥${(summary?.profit || 0).toLocaleString("zh-CN", { minimumFractionDigits: 2 })}`}
          change={summary?.profit}
          changePct={parseFloat(summary?.profitRate || "0")}
        />
        <StatCard
          label="收益率"
          value={`${summary?.profitRate || "0.00"}%`}
          format="percent"
        />
        <StatCard
          label="持仓基金"
          value={`${summary?.fundCount || 0} 只`}
          format="number"
          size="sm"
        />
      </div>

      {/* 第二行：次要指标 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="最大回撤" value="-8.42%" size="sm" />
        <StatCard label="Sharpe Ratio" value="1.28" size="sm" />
        <StatCard label="胜率" value="62.5%" size="sm" />
        <StatCard label="交易次数" value={`${summary?.tradeCount || 0}`} size="sm" />
      </div>

      {/* 第三行：净值走势图 + 资产配置 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <NAVChart />
        </div>
        <div>
          <AssetAllocation />
        </div>
      </div>

      {/* 第四行：交易、策略、风控、系统状态 */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <LatestTrades />
        <StrategyStatus />
        <RiskMetrics />
        <SystemStatus />
      </div>
    </div>
  );
}
