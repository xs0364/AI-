"use client";

import { useEffect, useState } from "react";
import { fundApi, marketApi } from "@/lib/api";
import { Pencil, Trash2, Plus, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { Fund, RealtimeQuote } from "@/lib/types";

export default function HoldingsPage() {
  const [funds, setFunds] = useState<Fund[]>([]);
  const [realtime, setRealtime] = useState<Record<string, RealtimeQuote>>({});
  const [loading, setLoading] = useState(true);
  const [rtLoading, setRtLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [editing, setEditing] = useState<Fund | null>(null);
  const [form, setForm] = useState({ code: "", name: "", shares: 0, costPrice: 0, currentPrice: 0 });
  const [estimateTime, setEstimateTime] = useState("");

  async function loadFunds() {
    setLoading(true);
    try {
      const res = await fundApi.list();
      const f = res.data || [];
      if (f.length) {
        setFunds(f);
      } else {
        fallbackFunds();
      }
    } catch {
      fallbackFunds();
    } finally {
      setLoading(false);
    }
  }

  function fallbackFunds() {
    setFunds([
      { id: 1, code: "110011", name: "易方达中小盘混合", shares: 5000, costPrice: 1.85, currentPrice: 2.12, updateTime: "" },
      { id: 2, code: "005827", name: "中欧医疗健康混合C", shares: 3000, costPrice: 0.82, currentPrice: 0.68, updateTime: "" },
      { id: 3, code: "001938", name: "中欧时代先锋股票A", shares: 4000, costPrice: 1.22, currentPrice: 1.35, updateTime: "" },
      { id: 4, code: "260108", name: "景顺长城新兴成长混合", shares: 2000, costPrice: 2.05, currentPrice: 1.96, updateTime: "" },
      { id: 5, code: "003095", name: "中欧医疗健康混合A", shares: 6000, costPrice: 0.55, currentPrice: 0.72, updateTime: "" },
    ]);
  }

  async function refreshRealtime() {
    const codes = funds.map(f => f.code).filter(Boolean);
    if (!codes.length) return;
    setRtLoading(true);
    try {
      const res = await marketApi.batchRealtime(codes.join(","));
      const map: Record<string, RealtimeQuote> = {};
      for (const item of res.data || []) {
        if (item.code && !item.error) map[item.code] = item;
      }
      setRealtime(map);
      for (const item of res.data || []) {
        if (item.gztime) { setEstimateTime(item.gztime); break; }
      }
    } catch {}
    setRtLoading(false);
  }

  useEffect(() => { loadFunds(); }, []);
  useEffect(() => { if (funds.length) refreshRealtime(); }, [funds.length]);

  function calcProfit(f: Fund) {
    const price = realtime[f.code]?.gsz ?? f.currentPrice;
    return (price - f.costPrice) * f.shares;
  }

  function openAdd() {
    setEditing(null);
    setForm({ code: "", name: "", shares: 0, costPrice: 0, currentPrice: 0 });
    setShowModal(true);
  }

  function openEdit(f: Fund) {
    setEditing(f);
    setForm({ code: f.code, name: f.name, shares: f.shares, costPrice: f.costPrice, currentPrice: f.currentPrice });
    setShowModal(true);
  }

  async function save() {
    try {
      if (editing) {
        await fundApi.update(editing.id, form);
      } else {
        await fundApi.create(form);
      }
      setShowModal(false);
      loadFunds();
    } catch (e) { alert(e); }
  }

  async function remove(id: number) {
    if (!confirm("确定删除？")) return;
    try { await fundApi.remove(id); loadFunds(); } catch {}
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">持仓</h1>
          <p className="text-sm text-text-tertiary mt-0.5">管理基金持仓和实时估值</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={refreshRealtime} disabled={rtLoading}>
            <RefreshCw className={cn("h-3.5 w-3.5 mr-1", rtLoading && "animate-spin")} />
            {rtLoading ? "更新中" : "更新估值"}
          </Button>
          <Button size="sm" onClick={openAdd}>
            <Plus className="h-3.5 w-3.5 mr-1" /> 新增
          </Button>
        </div>
      </div>

      {estimateTime && (
        <p className="text-xs text-text-tertiary">估值时间: {estimateTime}</p>
      )}

      <div className="rounded-xl bg-card border border-border-subtle shadow-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-xs text-text-tertiary">
                <th className="text-left py-2.5 px-3 font-medium">代码</th>
                <th className="text-left py-2.5 px-3 font-medium">名称</th>
                <th className="text-right py-2.5 px-3 font-medium">份额</th>
                <th className="text-right py-2.5 px-3 font-medium">成本价</th>
                <th className="text-right py-2.5 px-3 font-medium">持仓价</th>
                <th className="text-right py-2.5 px-3 font-medium">实时估值</th>
                <th className="text-right py-2.5 px-3 font-medium">估算涨跌</th>
                <th className="text-right py-2.5 px-3 font-medium">市值</th>
                <th className="text-right py-2.5 px-3 font-medium">盈亏</th>
                <th className="text-right py-2.5 px-3 font-medium w-20">操作</th>
              </tr>
            </thead>
            <tbody>
              {funds.map((f) => {
                const rt = realtime[f.code];
                const price = rt?.gsz ?? f.currentPrice;
                const changePct = rt?.gszzl ?? 0;
                const profitVal = calcProfit(f);
                return (
                  <tr key={f.id} className="border-b border-border-subtle hover:bg-surface-2/50 transition-colors">
                    <td className="py-2.5 px-3 font-mono text-text-primary font-medium">{f.code}</td>
                    <td className="py-2.5 px-3 text-text-primary">{f.name}</td>
                    <td className="py-2.5 px-3 text-right tabular-nums text-text-primary">{f.shares}</td>
                    <td className="py-2.5 px-3 text-right tabular-nums text-text-primary">{f.costPrice.toFixed(4)}</td>
                    <td className="py-2.5 px-3 text-right tabular-nums text-text-tertiary">{f.currentPrice.toFixed(4)}</td>
                    <td className={cn("py-2.5 px-3 text-right tabular-nums font-semibold", rt ? (changePct > 0 ? "text-positive" : changePct < 0 ? "text-negative" : "text-text-primary") : "text-text-tertiary")}>
                      {rt ? price.toFixed(4) : "-"}
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <span className={cn("tabular-nums", changePct > 0 ? "text-positive" : changePct < 0 ? "text-negative" : "text-text-tertiary")}>
                        {changePct >= 0 ? "+" : ""}{changePct}%
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right tabular-nums text-text-primary font-medium">
                      ¥{(f.shares * price).toFixed(2)}
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <span className={cn("tabular-nums font-semibold", profitVal >= 0 ? "text-positive" : "text-negative")}>
                        {profitVal >= 0 ? "+" : ""}{profitVal.toFixed(2)}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => openEdit(f)} className="p-1 rounded text-text-tertiary hover:text-text-primary hover:bg-surface-2"><Pencil className="h-3.5 w-3.5" /></button>
                        <button onClick={() => remove(f.id)} className="p-1 rounded text-text-tertiary hover:text-negative hover:bg-negative/10"><Trash2 className="h-3.5 w-3.5" /></button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!funds.length && !loading && (
                <tr><td colSpan={10} className="py-12 text-center text-text-tertiary text-sm">暂无持仓，点击"新增"添加基金</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Dialog open={showModal} onOpenChange={setShowModal}>
        <DialogContent>
          <DialogHeader><DialogTitle>{editing ? "编辑基金" : "新增基金"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs text-text-secondary">基金代码</label>
                <Input value={form.code} onChange={e => setForm({...form, code: e.target.value})} placeholder="110011" />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs text-text-secondary">基金名称</label>
                <Input value={form.name} onChange={e => setForm({...form, name: e.target.value})} placeholder="易方达中小盘混合" />
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="space-y-1.5">
                <label className="text-xs text-text-secondary">持仓份额</label>
                <Input type="number" value={form.shares} onChange={e => setForm({...form, shares: +e.target.value})} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs text-text-secondary">成本价</label>
                <Input type="number" step="0.0001" value={form.costPrice} onChange={e => setForm({...form, costPrice: +e.target.value})} />
              </div>
              <div className="space-y-1.5">
                <label className="text-xs text-text-secondary">现价</label>
                <Input type="number" step="0.0001" value={form.currentPrice} onChange={e => setForm({...form, currentPrice: +e.target.value})} />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowModal(false)}>取消</Button>
            <Button onClick={save}>{editing ? "保存" : "新增"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
