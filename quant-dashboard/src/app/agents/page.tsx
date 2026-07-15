"use client";

import { useEffect, useState, useCallback } from "react";
import { agentApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Play, Loader2, BrainCircuit, TrendingUp, Grid3x3, Newspaper, AlertTriangle, Info, ChevronDown, ChevronUp } from "lucide-react";
import type { AgentDecision, MergedDecision, MarketNewsAnalysis } from "@/lib/api";

const SIGNAL_COLORS: Record<string, string> = {
  STRONG_BUY: "text-green-500 border-green-500/30 bg-green-500/10",
  BUY: "text-green-400 border-green-400/30 bg-green-400/10",
  LIGHTEN_BUY: "text-emerald-400 border-emerald-400/30 bg-emerald-400/10",
  HOLD: "text-yellow-400 border-yellow-400/30 bg-yellow-400/10",
  LIGHTEN_SELL: "text-orange-400 border-orange-400/30 bg-orange-400/10",
  SELL: "text-red-400 border-red-400/30 bg-red-400/10",
  STRONG_SELL: "text-red-500 border-red-500/30 bg-red-500/10",
  PAUSE_GRID: "text-purple-400 border-purple-400/30 bg-purple-400/10",
  ADJUST_GRID: "text-cyan-400 border-cyan-400/30 bg-cyan-400/10",
  ENABLE_GRID: "text-blue-400 border-blue-400/30 bg-blue-400/10",
  POSITIVE: "text-green-500",
  NEGATIVE: "text-red-500",
  NEUTRAL: "text-gray-400",
};

const SIGNAL_LABELS: Record<string, string> = {
  STRONG_BUY: "强烈买入",
  BUY: "买入",
  LIGHTEN_BUY: "轻仓试仓",
  HOLD: "持仓不动",
  LIGHTEN_SELL: "减仓",
  SELL: "卖出",
  STRONG_SELL: "清仓",
  PAUSE_GRID: "暂停网格",
  ADJUST_GRID: "调整网格",
  ENABLE_GRID: "运行网格",
  SWITCH_TREND: "切换趋势",
  POSITIVE: "利好",
  NEGATIVE: "利空",
  NEUTRAL: "中性",
};

const AGENT_ICONS: Record<string, React.ElementType> = {
  trend: TrendingUp,
  grid: Grid3x3,
  market: Newspaper,
};

const AGENT_LABELS: Record<string, string> = {
  trend: "趋势 Agent",
  grid: "网格 Agent",
  market: "市场情报",
};

function SignalBadge({ signal }: { signal: string }) {
  const color = SIGNAL_COLORS[signal] || "text-gray-400 border-gray-400/30";
  const label = SIGNAL_LABELS[signal] || signal;
  return <Badge variant="outline" className={cn("text-[11px] font-semibold", color)}>{label}</Badge>;
}

function ScoreMeter({ score }: { score: number }) {
  const color = score >= 65 ? "bg-green-500" : score >= 45 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded-full bg-surface-2 overflow-hidden">
        <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-mono tabular-nums text-text-secondary">{score}</span>
    </div>
  );
}

function DecisionCard({ fund }: { fund: AgentDecision }) {
  const [expanded, setExpanded] = useState(false);
  const { decision } = fund;

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-4 hover:bg-surface-1/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          <SignalBadge signal={decision.signal} />
          <div className="text-left">
            <span className="text-sm font-medium text-text-primary">{fund.fund_name}</span>
            <span className="text-xs text-text-tertiary ml-2">{fund.fund_code}</span>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-text-tertiary tabular-nums">¥{fund.current_price?.toFixed(4)}</span>
          {expanded ? <ChevronUp className="h-4 w-4 text-text-tertiary" /> : <ChevronDown className="h-4 w-4 text-text-tertiary" />}
        </div>
      </button>

      {/* Body */}
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-border-subtle pt-3">
          {/* 融合评分 */}
          <div className="grid grid-cols-3 gap-3">
            <div className="bg-surface-2 rounded-lg p-2.5 text-center">
              <div className="text-[10px] text-text-tertiary uppercase mb-0.5">综合评分</div>
              <div className={cn(
                "text-lg font-bold font-mono tabular-nums",
                decision.score >= 65 ? "text-green-400" : decision.score >= 45 ? "text-yellow-400" : "text-red-400"
              )}>{decision.score}</div>
            </div>
            <div className="bg-surface-2 rounded-lg p-2.5 text-center">
              <div className="text-[10px] text-text-tertiary uppercase mb-0.5">置信度</div>
              <div className="text-lg font-bold font-mono tabular-nums text-text-primary">{decision.confidence}</div>
            </div>
            <div className="bg-surface-2 rounded-lg p-2.5 text-center">
              <div className="text-[10px] text-text-tertiary uppercase mb-0.5">风险评分</div>
              <div className={cn(
                "text-lg font-bold font-mono tabular-nums",
                decision.risk >= 60 ? "text-red-400" : decision.risk >= 30 ? "text-yellow-400" : "text-green-400"
              )}>{decision.risk}</div>
            </div>
          </div>

          {/* Agent 贡献 */}
          <div>
            <div className="text-xs font-medium text-text-secondary mb-2">Agent 投票</div>
            <div className="space-y-2">
              {decision.agents_contributions?.map((ac, i) => {
                const Icon = AGENT_ICONS[ac.agent] || BrainCircuit;
                const label = AGENT_LABELS[ac.agent] || ac.agent;
                return (
                  <div key={i} className="flex items-center justify-between bg-surface-2 rounded-lg px-3 py-2">
                    <div className="flex items-center gap-2">
                      <Icon className="h-3.5 w-3.5 text-text-tertiary" />
                      <span className="text-xs text-text-primary">{label}</span>
                      <SignalBadge signal={ac.signal} />
                    </div>
                    <div className="flex items-center gap-3 text-xs tabular-nums text-text-tertiary">
                      <span>评{ac.score}</span>
                      <span>信{ac.confidence}</span>
                      <span>权{(ac.weight * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 推理链 */}
          <div>
            <div className="text-xs font-medium text-text-secondary mb-2">推理链</div>
            <div className="bg-surface-2 rounded-lg p-3 space-y-1">
              {decision.reasons?.map((r, i) => (
                <p key={i} className="text-xs text-text-secondary leading-relaxed">{r}</p>
              ))}
            </div>
          </div>

          {/* 执行状态 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-text-tertiary">
              <Info className="h-3 w-3" />
              过期时间: {decision.expire_at ? new Date(decision.expire_at).toLocaleTimeString() : "无"}
            </div>
            {decision.should_execute && (
              <Badge variant="outline" className="text-[11px] text-blue-400 border-blue-400/30">
                ⚡ 建议执行
              </Badge>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NewsCard({ news }: { news: MarketNewsAnalysis }) {
  return (
    <div className="rounded-lg bg-surface-2 border border-border-subtle p-3 space-y-1.5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <SignalBadge signal={news.signal} />
          <span className="text-[11px] text-text-tertiary">{news.source}</span>
          {news.method === "llm" && (
            <span className="text-[10px] text-purple-400 bg-purple-400/10 px-1.5 py-0.5 rounded">LLM</span>
          )}
        </div>
        <span className="text-[10px] text-text-tertiary">{news.time ? new Date(news.time).toLocaleTimeString() : ""}</span>
      </div>
      <p className="text-xs text-text-primary leading-relaxed">{news.summary || news.reason?.[0]}</p>
      {news.affected_funds && news.affected_funds.length > 0 && (
        <div className="flex gap-1 flex-wrap">
          {news.affected_funds.map((code) => (
            <Badge key={code} variant="outline" className="text-[10px] text-text-tertiary">{code}</Badge>
          ))}
        </div>
      )}
      <div className="flex gap-3 text-[10px] text-text-tertiary">
        <span>影响: {news.score}/100</span>
        <span>置信: {news.confidence}%</span>
        <span>风险: {news.risk}/100</span>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [marketNews, setMarketNews] = useState<MarketNewsAnalysis[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"decisions" | "news">("decisions");

  const runScan = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [scanRes, newsRes] = await Promise.all([
        agentApi.scan().catch(() => null),
        agentApi.marketNews().catch(() => null),
      ]);
      if (scanRes?.data) setDecisions(scanRes.data);
      if (newsRes?.data) setMarketNews(newsRes.data);
    } catch (e: any) {
      setError(e.message || "扫描失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { runScan(); }, []);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">AI 决策</h1>
          <p className="text-sm text-text-tertiary mt-0.5">多 Agent 协同决策系统 — 市场情报 → 趋势/网格 → 融合决策</p>
        </div>
        <Button size="sm" onClick={runScan} disabled={loading}>
          {loading ? <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" /> : <Play className="h-3.5 w-3.5 mr-1" />}
          {loading ? "扫描中..." : "立即扫描"}
        </Button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-surface-2 rounded-lg p-1 w-fit">
        <button
          onClick={() => setTab("decisions")}
          className={cn(
            "px-3 py-1.5 text-xs font-medium rounded-md transition-colors",
            tab === "decisions" ? "bg-card text-text-primary shadow-sm" : "text-text-tertiary hover:text-text-primary"
          )}
        >
          <BrainCircuit className="h-3.5 w-3.5 inline mr-1" />
          决策结果
        </button>
        <button
          onClick={() => setTab("news")}
          className={cn(
            "px-3 py-1.5 text-xs font-medium rounded-md transition-colors",
            tab === "news" ? "bg-card text-text-primary shadow-sm" : "text-text-tertiary hover:text-text-primary"
          )}
        >
          <Newspaper className="h-3.5 w-3.5 inline mr-1" />
          市场情报
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 text-xs text-negative bg-negative/10 rounded-lg px-3 py-2">
          <AlertTriangle className="h-3.5 w-3.5" />
          {error}
        </div>
      )}

      {/* Tab Content */}
      {tab === "decisions" && (
        <div className="space-y-3">
          {decisions.length === 0 && !loading && (
            <div className="py-16 text-center text-text-tertiary text-sm">
              <BrainCircuit className="h-12 w-12 mx-auto mb-3 opacity-30" />
              点击「立即扫描」运行 Agent 决策
            </div>
          )}
          {decisions.map((d) => (
            <DecisionCard key={d.fund_id} fund={d} />
          ))}
        </div>
      )}

      {tab === "news" && (
        <div className="space-y-2">
          {marketNews.length === 0 && !loading && (
            <div className="py-16 text-center text-text-tertiary text-sm">
              <Newspaper className="h-12 w-12 mx-auto mb-3 opacity-30" />
              暂无市场情报数据
            </div>
          )}
          {marketNews.map((n, i) => (
            <NewsCard key={i} news={n} />
          ))}
        </div>
      )}

      {/* 架构图 */}
      <details className="rounded-xl bg-card border border-border-subtle shadow-card">
        <summary className="flex items-center gap-2 p-3 text-xs font-medium text-text-secondary cursor-pointer hover:text-text-primary">
          <Info className="h-3.5 w-3.5" />
          Agent 架构说明
        </summary>
        <div className="px-3 pb-3 text-xs text-text-tertiary leading-relaxed space-y-1 font-mono">
          <p>Market Intelligence (Qwen3.5 397B)  ←  新闻/宏观/情绪</p>
          <p>  ↓ sentiment_score</p>
          <p>Trend Agent (Python)  ←  MACD/RSI/BOLL/ATR/EMA</p>
          <p>Grid Agent (Python)  ←  ATR动态网格/波动率/突破检测</p>
          <p>  ↓</p>
          <p>Signal Merge Engine (规则融合)</p>
          <p>  ↓</p>
          <p>Trade Executor</p>
          <p className="pt-1 text-text-quaternary">NVIDIA API: qwen3.5-397b-a17b + deepseek-v4-flash (key轮询)</p>
        </div>
      </details>
    </div>
  );
}
