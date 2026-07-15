"use client";

import { useState, useEffect, useCallback } from "react";
import { riskApi, fundApi } from "@/lib/api";
import type { RiskVerdict, RiskConfigData } from "@/lib/api";
import {
  ShieldAlert, ShieldCheck, Shield, ShieldOff,
  Save, Loader2, RefreshCw, AlertTriangle, AlertCircle,
  DollarSign, BarChart3, TrendingDown, Activity,
  BrainCircuit, Gauge, Settings, ChevronDown, ChevronUp,
  CheckCircle2, XCircle, Siren,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface FundOption {
  id: number;
  code: string;
  name: string;
  currentPrice: number;
}

const DEFAULT_CONFIG: RiskConfigData = {
  singleTradeCapPct: 0.05,
  singleFundCapPct: 0.15,
  cashReservePct: 0.20,
  positionTiers: [[80, 1.0], [60, 0.75], [40, 0.50], [20, 0.25], [0, 0.0]],
  stopLossFixedPct: 0.08,
  stopLossAtrMultiple: 2.0,
  stopLossTrailingActivatePct: 0.10,
  stopLossTrailingDistancePct: 0.05,
  stopLossTimeDays: 30,
  drawdownTiers: [[5, 1.0], [10, 0.50], [15, 0.20], [100, 0.0]],
  sentimentGoodMin: 40.0,
  sentimentBadMax: 20.0,
  riskWeightCapital: 0.20,
  riskWeightPosition: 0.20,
  riskWeightStopLoss: 0.20,
  riskWeightDrawdown: 0.25,
  riskWeightMarket: 0.15,
};

const RISK_LEVEL_INFO: Record<string, { label: string; color: string; icon: typeof Shield }> = {
  normal: { label: "正常", color: "text-positive", icon: ShieldCheck },
  caution: { label: "关注", color: "text-warning", icon: Shield },
  danger: { label: "危险", color: "text-negative", icon: ShieldAlert },
  critical: { label: "极危", color: "text-negative", icon: ShieldOff },
};

export default function RiskPage() {
  // Tab state
  const [tab, setTab] = useState<"dashboard" | "config">("dashboard");

  // Dashboard state
  const [funds, setFunds] = useState<FundOption[]>([]);
  const [selectedFund, setSelectedFund] = useState<string>("");
  const [checking, setChecking] = useState(false);
  const [verdict, setVerdict] = useState<RiskVerdict | null>(null);
  const [config, setConfig] = useState<RiskConfigData>(DEFAULT_CONFIG);
  const [loadingConfig, setLoadingConfig] = useState(true);
  const [savingConfig, setSavingConfig] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // ── Load data ─────────────────────────────────────────────
  useEffect(() => {
    async function load() {
      try {
        const f = await fundApi.list().catch(() => null);
        if (f?.data?.length) {
          setFunds(f.data.map((ff: any) => ({
            id: ff.id, code: ff.code, name: ff.name,
            currentPrice: ff.currentPrice || ff.current_price || 0,
          })));
          setSelectedFund(f.data[0].code);
        }
      } catch { /* ignore */ }

      try {
        const c = await riskApi.config();
        setConfig(c);
      } catch { /* use default */ }
      setLoadingConfig(false);
    }
    load();
  }, []);

  // ── Run risk check ────────────────────────────────────────
  const runCheck = useCallback(async () => {
    if (!selectedFund) return;
    setChecking(true);
    try {
      const v = await riskApi.check({
        fundCode: selectedFund,
        decisionScore: 50,
        decisionSignal: "BUY",
      });
      setVerdict(v);
    } catch {
      setVerdict({
        allow: false, riskScore: 100, riskLevel: "critical",
        maxPosition: 0, stopLossPrice: null, takeProfit: null,
        layerScores: {}, reasons: ["风控检查请求失败"],
      });
    } finally {
      setChecking(false);
    }
  }, [selectedFund]);

  // Auto-run on fund change
  useEffect(() => {
    if (selectedFund && funds.length > 0) {
      runCheck();
    }
  }, [selectedFund, funds.length, runCheck]);

  // ── Save config ───────────────────────────────────────────
  const saveConfig = useCallback(async () => {
    setSavingConfig(true);
    setSaveMsg("");
    try {
      const r = await riskApi.updateConfig(config);
      setSaveMsg(r.message || "已保存");
      setTimeout(() => setSaveMsg(""), 3000);
    } catch (e: any) {
      setSaveMsg("保存失败: " + (e.message || ""));
    } finally {
      setSavingConfig(false);
    }
  }, [config]);

  // ── Risk level display ────────────────────────────────────
  const levelInfo = RISK_LEVEL_INFO[verdict?.riskLevel || "normal"] || RISK_LEVEL_INFO.normal;
  const LevelIcon = levelInfo.icon;
  const riskScore = verdict?.riskScore ?? 0;
  const riskAngle = (riskScore / 100) * 180 - 90; // -90° (left) to +90° (right)

  return (
    <div className="space-y-4">
      {/* Header + Tabs */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary tracking-tight">风控中心</h1>
          <p className="text-xs text-text-tertiary mt-0.5">六层风控引擎 · 实时风险评估</p>
        </div>
        <div className="flex gap-1 bg-surface-2 rounded-lg p-0.5">
          <button
            onClick={() => setTab("dashboard")}
            className={cn(
              "px-3 py-1.5 rounded-md text-xs font-medium transition-all",
              tab === "dashboard"
                ? "bg-card text-text-primary shadow-sm"
                : "text-text-tertiary hover:text-text-primary"
            )}
          >
            <Gauge className="h-3.5 w-3.5 inline mr-1.5" />
            仪表盘
          </button>
          <button
            onClick={() => setTab("config")}
            className={cn(
              "px-3 py-1.5 rounded-md text-xs font-medium transition-all",
              tab === "config"
                ? "bg-card text-text-primary shadow-sm"
                : "text-text-tertiary hover:text-text-primary"
            )}
          >
            <Settings className="h-3.5 w-3.5 inline mr-1.5" />
            配置
          </button>
        </div>
      </div>

      {tab === "dashboard" ? (
        <>
          {/* ═══ 基金选择 + 检查按钮 ═══ */}
          <div className="flex items-center gap-3">
            <div className="flex-1 max-w-xs">
              {funds.length === 0 ? (
                <div className="text-xs text-text-tertiary py-1">加载基金列表…</div>
              ) : (
                <select
                  value={selectedFund}
                  onChange={(e) => setSelectedFund(e.target.value)}
                  className="w-full text-xs bg-surface-1 border border-border-subtle rounded-lg px-2.5 py-1.5 text-text-primary outline-none focus:border-brand-400/50"
                >
                  {funds.map((f) => (
                    <option key={f.code} value={f.code}>{f.name} ({f.code})</option>
                  ))}
                </select>
              )}
            </div>
            <button
              onClick={runCheck}
              disabled={checking || !selectedFund}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-brand-400/20 text-brand-400 hover:bg-brand-400/30 disabled:opacity-50 transition-all"
            >
              {checking ? (
                <><Loader2 className="h-3 w-3 animate-spin" /> 检查中…</>
              ) : (
                <><RefreshCw className="h-3 w-3" /> 刷新检查</>
              )}
            </button>
          </div>

          {verdict ? (
            <>
              {/* ═══ 风险概览 ═══ */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* 风险仪表 */}
                <div className="rounded-xl bg-card border border-border-subtle shadow-card p-5 flex flex-col items-center">
                  <div className="relative w-36 h-24 overflow-hidden mb-2">
                    {/* 半圆仪表 */}
                    <svg viewBox="0 0 200 120" className="w-36 h-24">
                      {/* 背景弧 */}
                      <path
                        d="M 20 100 A 80 80 0 0 1 180 100"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="14"
                        strokeLinecap="round"
                        className="text-surface-2"
                      />
                      {/* 彩色分段 */}
                      <path
                        d="M 20 100 A 80 80 0 0 1 180 100"
                        fill="none"
                        stroke="url(#riskGradient)"
                        strokeWidth="14"
                        strokeLinecap="round"
                        strokeDasharray={`${riskScore * 1.6} 1000`}
                        className="transition-all duration-500"
                      />
                      <defs>
                        <linearGradient id="riskGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                          <stop offset="0%" stopColor="#22c55e" />
                          <stop offset="40%" stopColor="#eab308" />
                          <stop offset="70%" stopColor="#f97316" />
                          <stop offset="100%" stopColor="#ef4444" />
                        </linearGradient>
                      </defs>
                      {/* 指针 */}
                      <line
                        x1="100" y1="100"
                        x2={100 + 65 * Math.cos(riskAngle * Math.PI / 180)}
                        y2={100 + 65 * Math.sin(riskAngle * Math.PI / 180)}
                        stroke="currentColor"
                        strokeWidth="2"
                        className="text-text-primary transition-all duration-500"
                      />
                      <circle cx="100" cy="100" r="4" className="fill-text-primary" />
                      {/* 刻度标签 */}
                      <text x="25" y="112" className="fill-text-tertiary" fontSize="8">0</text>
                      <text x="188" y="112" className="fill-text-tertiary text-anchor-end" fontSize="8">100</text>
                    </svg>
                  </div>
                  <div className={cn("text-2xl font-bold font-mono tabular-nums", levelInfo.color)}>
                    {riskScore.toFixed(0)}
                  </div>
                  <div className={cn("flex items-center gap-1 text-xs mt-1 font-medium", levelInfo.color)}>
                    <LevelIcon className="h-3.5 w-3.5" />
                    {levelInfo.label}
                  </div>
                  <div className={cn(
                    "flex items-center gap-1 mt-2 text-xs rounded-full px-2.5 py-0.5 font-medium",
                    verdict?.allow
                      ? "bg-positive/10 text-positive"
                      : "bg-negative/10 text-negative"
                  )}>
                    {verdict?.allow ? (
                      <><CheckCircle2 className="h-3 w-3" /> 允许执行</>
                    ) : (
                      <><XCircle className="h-3 w-3" /> 禁止执行</>
                    )}
                  </div>
                </div>

                {/* 仓位限制 */}
                <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4 space-y-3">
                  <div className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
                    <BarChart3 className="h-3.5 w-3.5" /> 仓位限制
                  </div>
                  <div className="space-y-2">
                    <RiskStat label="建议仓位" value={`${((verdict?.maxPosition ?? 0) * 100).toFixed(0)}%`}
                      color={(verdict?.maxPosition ?? 0) >= 0.5 ? "text-positive" : "text-warning"} />
                    <RiskStat label="止损价格" value={verdict?.stopLossPrice ? `¥${verdict.stopLossPrice.toFixed(4)}` : "未触发"}
                      color={verdict?.stopLossPrice ? "text-negative" : "text-text-tertiary"} />
                    <RiskStat label="止盈价格" value={verdict?.takeProfit ? `¥${verdict.takeProfit.toFixed(4)}` : "未设置"}
                      color={verdict?.takeProfit ? "text-positive" : "text-text-tertiary"} />
                  </div>
                </div>

                {/* 风控理由 */}
                <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4 space-y-2">
                  <div className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
                    <Siren className="h-3.5 w-3.5" /> 风控理由
                  </div>
                  <div className="space-y-1 max-h-32 overflow-y-auto scrollbar-thin">
                    {(verdict?.reasons?.length ?? 0) > 0 ? (
                      verdict!.reasons.map((r, i) => (
                        <div key={i} className="text-[11px] text-text-tertiary leading-relaxed">{r}</div>
                      ))
                    ) : (
                      <div className="text-[11px] text-text-tertiary">无风控警告</div>
                    )}
                  </div>
                </div>
              </div>

              {/* ═══ 各层评分 ═══ */}
              <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
                <div className="text-xs font-medium text-text-secondary mb-3">各层风控评分</div>
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  <LayerCard name="资金风控" key="capital" score={verdict?.layerScores?.capital ?? 0} icon={DollarSign} />
                  <LayerCard name="仓位管理" key="position" score={verdict?.layerScores?.position ?? 0} icon={BarChart3} />
                  <LayerCard name="止损系统" key="stop_loss" score={verdict?.layerScores?.stop_loss ?? 0} icon={TrendingDown} />
                  <LayerCard name="回撤控制" key="drawdown" score={verdict?.layerScores?.drawdown ?? 0} icon={Activity} />
                  <LayerCard name="市场状态" key="market" score={verdict?.layerScores?.market ?? 0} icon={BrainCircuit} />
                </div>
              </div>
            </>
          ) : (
            /* Empty state */
            <div className="flex flex-col items-center justify-center h-72 text-text-tertiary space-y-3">
              <Gauge className="h-12 w-12" />
              <h2 className="text-lg font-medium text-text-primary">选择基金查看风险评估</h2>
              <p className="text-sm">风控引擎将检查资金、仓位、止损、回撤、市场状态五层</p>
            </div>
          )}
        </>
      ) : (
        <>
          {/* ═══ 配置面板 ═══ */}
          {loadingConfig ? (
            <div className="flex items-center justify-center h-48 text-text-tertiary text-sm">
              <Loader2 className="h-4 w-4 animate-spin mr-2" /> 加载配置…
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* 资金风控配置 */}
              <ConfigSection title="资金风控" icon={DollarSign}>
                <ConfigField label="单笔仓位上限" value={config.singleTradeCapPct} unit="%"
                  onChange={(v) => setConfig((p) => ({ ...p, singleTradeCapPct: v }))}
                  min={0} max={1} step={0.01} factor={100} />
                <ConfigField label="单基金上限" value={config.singleFundCapPct} unit="%"
                  onChange={(v) => setConfig((p) => ({ ...p, singleFundCapPct: v }))}
                  min={0} max={1} step={0.01} factor={100} />
                <ConfigField label="现金留存" value={config.cashReservePct} unit="%"
                  onChange={(v) => setConfig((p) => ({ ...p, cashReservePct: v }))}
                  min={0} max={1} step={0.01} factor={100} />
              </ConfigSection>

              {/* 止损配置 */}
              <ConfigSection title="止损系统" icon={TrendingDown}>
                <ConfigField label="固定止损" value={config.stopLossFixedPct} unit="%"
                  onChange={(v) => setConfig((p) => ({ ...p, stopLossFixedPct: v }))}
                  min={0} max={0.5} step={0.01} factor={100} />
                <ConfigField label="ATR倍数" value={config.stopLossAtrMultiple}
                  onChange={(v) => setConfig((p) => ({ ...p, stopLossAtrMultiple: v }))}
                  min={0.5} max={5} step={0.1} factor={1} />
                <ConfigField label="Trailing激活盈利" value={config.stopLossTrailingActivatePct} unit="%"
                  onChange={(v) => setConfig((p) => ({ ...p, stopLossTrailingActivatePct: v }))}
                  min={0} max={0.5} step={0.01} factor={100} />
                <ConfigField label="Trailing回撤距离" value={config.stopLossTrailingDistancePct} unit="%"
                  onChange={(v) => setConfig((p) => ({ ...p, stopLossTrailingDistancePct: v }))}
                  min={0} max={0.3} step={0.01} factor={100} />
                <ConfigField label="时间止损" value={config.stopLossTimeDays} unit="天"
                  onChange={(v) => setConfig((p) => ({ ...p, stopLossTimeDays: v }))}
                  min={1} max={365} step={1} factor={1} />
              </ConfigSection>

              {/* 回撤控制 */}
              <ConfigSection title="回撤控制" icon={Activity}>
                <ConfigField label="正常回撤阈值" value={config.drawdownTiers[0][0]} unit="%"
                  onChange={(v) => {
                    const newTiers = [...config.drawdownTiers] as [number, number][];
                    newTiers[0] = [v, newTiers[0][1]];
                    setConfig((p) => ({ ...p, drawdownTiers: newTiers }));
                  }}
                  min={1} max={20} step={1} factor={1} />
                <ConfigField label="减半仓阈值" value={config.drawdownTiers[1][0]} unit="%"
                  onChange={(v) => {
                    const newTiers = [...config.drawdownTiers] as [number, number][];
                    newTiers[1] = [v, newTiers[1][1]];
                    setConfig((p) => ({ ...p, drawdownTiers: newTiers }));
                  }}
                  min={1} max={30} step={1} factor={1} />
                <ConfigField label="清仓阈值" value={config.drawdownTiers[2][0]} unit="%"
                  onChange={(v) => {
                    const newTiers = [...config.drawdownTiers] as [number, number][];
                    newTiers[2] = [v, newTiers[2][1]];
                    setConfig((p) => ({ ...p, drawdownTiers: newTiers }));
                  }}
                  min={5} max={50} step={1} factor={1} />
              </ConfigSection>

              {/* 市场状态 */}
              <ConfigSection title="市场状态滤网" icon={BrainCircuit}>
                <ConfigField label="正常交易情绪分" value={config.sentimentGoodMin}
                  onChange={(v) => setConfig((p) => ({ ...p, sentimentGoodMin: v }))}
                  min={0} max={100} step={5} factor={1} />
                <ConfigField label="禁止开仓情绪分" value={config.sentimentBadMax}
                  onChange={(v) => setConfig((p) => ({ ...p, sentimentBadMax: v }))}
                  min={0} max={50} step={5} factor={1} />
              </ConfigSection>

              {/* 权重配置 */}
              <ConfigSection title="综合评分权重" icon={Gauge} className="lg:col-span-2">
                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                  <ConfigField label="资金风控" value={config.riskWeightCapital} unit=""
                    onChange={(v) => setConfig((p) => ({ ...p, riskWeightCapital: v }))}
                    min={0} max={1} step={0.05} factor={100} />
                  <ConfigField label="仓位管理" value={config.riskWeightPosition} unit=""
                    onChange={(v) => setConfig((p) => ({ ...p, riskWeightPosition: v }))}
                    min={0} max={1} step={0.05} factor={100} />
                  <ConfigField label="止损系统" value={config.riskWeightStopLoss} unit=""
                    onChange={(v) => setConfig((p) => ({ ...p, riskWeightStopLoss: v }))}
                    min={0} max={1} step={0.05} factor={100} />
                  <ConfigField label="回撤控制" value={config.riskWeightDrawdown} unit=""
                    onChange={(v) => setConfig((p) => ({ ...p, riskWeightDrawdown: v }))}
                    min={0} max={1} step={0.05} factor={100} />
                  <ConfigField label="市场状态" value={config.riskWeightMarket} unit=""
                    onChange={(v) => setConfig((p) => ({ ...p, riskWeightMarket: v }))}
                    min={0} max={1} step={0.05} factor={100} />
                </div>
              </ConfigSection>

              {/* 保存按钮 */}
              <div className="lg:col-span-2 flex items-center gap-3">
                <button
                  onClick={saveConfig}
                  disabled={savingConfig}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium bg-brand-400/20 text-brand-400 hover:bg-brand-400/30 disabled:opacity-50 transition-all"
                >
                  {savingConfig ? (
                    <><Loader2 className="h-4 w-4 animate-spin" /> 保存中…</>
                  ) : (
                    <><Save className="h-4 w-4" /> 保存配置</>
                  )}
                </button>
                {saveMsg && (
                  <span className={cn(
                    "text-xs",
                    saveMsg.includes("失败") ? "text-negative" : "text-positive"
                  )}>
                    {saveMsg}
                  </span>
                )}
                <button
                  onClick={() => setConfig(DEFAULT_CONFIG)}
                  className="text-xs text-text-tertiary hover:text-text-primary transition-colors px-2 py-1"
                >
                  恢复默认
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════
//  子组件
// ═══════════════════════════════════════════════════════════════════

function RiskStat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-[11px] text-text-tertiary">{label}</span>
      <span className={cn("text-xs font-mono font-semibold tabular-nums", color)}>{value}</span>
    </div>
  );
}

function LayerCard({ name, score, icon: Icon }: { name: string; score: number; icon: any; }) {
  const getBarColor = (s: number) => {
    if (s <= 20) return "bg-positive";
    if (s <= 50) return "bg-warning";
    if (s <= 75) return "bg-orange-500";
    return "bg-negative";
  };

  return (
    <div className="rounded-lg bg-surface-2 p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <Icon className="h-3 w-3 text-text-tertiary" />
        <span className="text-[10px] text-text-tertiary font-medium">{name}</span>
      </div>
      <div className="text-lg font-bold font-mono tabular-nums text-text-primary">{score.toFixed(0)}</div>
      <div className="mt-1.5 h-1.5 rounded-full bg-surface-1 overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-300", getBarColor(score))}
          style={{ width: `${Math.min(100, score)}%` }}
        />
      </div>
    </div>
  );
}

function ConfigSection({ title, icon: Icon, children, className }: {
  title: string; icon: any; children: React.ReactNode; className?: string;
}) {
  return (
    <div className={cn("rounded-xl bg-card border border-border-subtle shadow-card p-4 space-y-3", className)}>
      <div className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
        <Icon className="h-3.5 w-3.5" /> {title}
      </div>
      {children}
    </div>
  );
}

function ConfigField({ label, value, unit, onChange, min, max, step, factor }: {
  label: string; value: number; unit?: string; onChange: (v: number) => void;
  min: number; max: number; step: number; factor: number;
}) {
  const displayVal = factor > 1 ? Math.round(value * factor) : value;
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] text-text-tertiary w-28 shrink-0">{label}</span>
      <input
        type="number"
        value={displayVal}
        min={factor > 1 ? Math.round(min * factor) : min}
        max={factor > 1 ? Math.round(max * factor) : max}
        step={factor > 1 ? Math.round(step * factor) || 1 : step}
        onChange={(e) => {
          const raw = parseFloat(e.target.value);
          if (!isNaN(raw)) {
            onChange(factor > 1 ? raw / factor : raw);
          }
        }}
        className="flex-1 text-xs bg-surface-1 border border-border-subtle rounded-lg px-2 py-1 outline-none focus:border-brand-400/50 text-text-primary max-w-[100px]"
      />
      {unit && <span className="text-[11px] text-text-tertiary w-6">{unit}</span>}
    </div>
  );
}
