"use client";

import { useEffect, useState } from "react";
import { strategyApi, fundApi } from "@/lib/api";
import { Play, Pause, Trash2, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Strategy, Fund } from "@/lib/types";

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [funds, setFunds] = useState<Fund[]>([]);
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    try {
      const [s, f] = await Promise.all([
        strategyApi.list().catch(() => ({ data: [] })),
        fundApi.list().catch(() => ({ data: [] })),
      ]);
      if (s.data?.length) setStrategies(s.data);
      else fallbackStrategies();
      if (f.data?.length) setFunds(f.data);
    } catch {
      fallbackStrategies();
    } finally {
      setLoading(false);
    }
  }

  function fallbackStrategies() {
    setStrategies([
      { id: 1, fundId: 1, name: "均线趋势策略", type: "ma", params: { period: 20, upper: 105, lower: 95 }, enabled: true, createdAt: "", updatedAt: "" },
      { id: 2, fundId: 3, name: "网格交易策略", type: "grid", params: { upperPrice: 1.5, lowerPrice: 1, stepCount: 5, stepSize: 0.1 }, enabled: false, createdAt: "", updatedAt: "" },
      { id: 3, fundId: 5, name: "均线网格混合", type: "ma", params: { period: 10, upper: 103, lower: 97 }, enabled: true, createdAt: "", updatedAt: "" },
    ]);
  }

  useEffect(() => { load(); }, []);

  function fundName(id: number) {
    const f = funds.find(f => f.id === id);
    return f?.name || `基金#${id}`;
  }

  async function toggle(s: Strategy) {
    try {
      await strategyApi.toggle(s.id, !s.enabled);
      setStrategies(prev => prev.map(st => st.id === s.id ? { ...st, enabled: !st.enabled } : st));
    } catch {}
  }

  async function remove(id: number) {
    if (!confirm("确定删除该策略？")) return;
    try { await strategyApi.remove(id); setStrategies(prev => prev.filter(s => s.id !== id)); } catch {}
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">策略</h1>
          <p className="text-sm text-text-tertiary mt-0.5">管理和配置交易策略</p>
        </div>
        <Button size="sm" disabled>
          <Plus className="h-3.5 w-3.5 mr-1" /> 新增策略
        </Button>
      </div>

      <div className="grid gap-3">
        {strategies.map((s) => (
          <div key={s.id} className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Badge variant="outline" className={cn("h-6 text-[11px]", s.type === "ma" ? "text-brand-400 border-brand-400/30" : "text-warning border-warning/30")}>
                  {s.type === "ma" ? "MA均线" : "网格交易"}
                </Badge>
                <div>
                  <span className="text-sm font-medium text-text-primary">{s.name}</span>
                  <span className="text-xs text-text-tertiary ml-2">{fundName(s.fundId)}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className={cn("h-6 text-[11px]", s.enabled ? "text-positive border-positive/30" : "text-text-tertiary")}>
                  {s.enabled ? "运行中" : "已暂停"}
                </Badge>
                <button onClick={() => toggle(s)} className="p-1.5 rounded-md text-text-tertiary hover:text-text-primary hover:bg-surface-2 transition-colors">
                  {s.enabled ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                </button>
                <button onClick={() => remove(s.id)} className="p-1.5 rounded-md text-text-tertiary hover:text-negative hover:bg-negative/10 transition-colors">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            {/* 策略参数 */}
            <div className="mt-3 flex flex-wrap gap-2">
              {Object.entries(s.params).map(([key, val]) => (
                <Badge key={key} variant="outline" className="text-[11px] font-normal bg-surface-2">
                  {key}: {String(val)}
                </Badge>
              ))}
            </div>
          </div>
        ))}

        {!strategies.length && !loading && (
          <div className="py-16 text-center text-text-tertiary text-sm">暂无策略</div>
        )}
      </div>
    </div>
  );
}
