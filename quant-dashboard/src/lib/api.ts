/**
 * API 层 — 桥接 Python FastAPI 后端 (localhost:3000)
 * 所有接口返回原始数据，错误由调用组件处理
 */
import type {
  Fund, RealtimeQuote, Strategy, Trade, TradeSignal,
  PortfolioValue, AnalyticsSummary, TimeStatus, NewsItem, RiskMetrics,
} from "./types";

const BASE = "http://localhost:3000/api";

async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText);
    throw new Error(msg);
  }
  return res.json();
}

// ── Funds ───────────────────────────────────────────────────────────
export const fundApi = {
  list: (): Promise<{ data: Fund[]; total: number }> =>
    fetchApi("/funds"),
  create: (data: Partial<Fund>) =>
    fetchApi<Fund>("/funds", { method: "POST", body: JSON.stringify(data) }),
  update: (id: number, data: Partial<Fund>) =>
    fetchApi<Fund>(`/funds/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  remove: (id: number): Promise<{ message: string }> =>
    fetchApi(`/funds/${id}`, { method: "DELETE" }),
};

// ── Market Data ─────────────────────────────────────────────────────
export const marketApi = {
  realtime: (code: string): Promise<RealtimeQuote> =>
    fetchApi(`/market/fund/${code}/realtime`),
  batchRealtime: (codes: string): Promise<{ data: RealtimeQuote[]; total: number }> =>
    fetchApi(`/market/batch-realtime?codes=${encodeURIComponent(codes)}`),
  holdings: (code: string): Promise<{ code: string; holdings: { stockName: string; ratio: number }[]; error: string | null }> =>
    fetchApi(`/market/fund/${code}/holdings`),
};

// ── Analytics ───────────────────────────────────────────────────────
export const analyticsApi = {
  summary: (): Promise<AnalyticsSummary> =>
    fetchApi("/analytics/summary"),
  portfolio: (days = 30): Promise<{ data: PortfolioValue[]; total: number }> =>
    fetchApi(`/analytics/portfolio?days=${days}`),
  trades: (days = 30): Promise<{ data: any[]; total: number }> =>
    fetchApi(`/analytics/trades?days=${days}`),
};

// ── Trades ──────────────────────────────────────────────────────────
export const tradeApi = {
  list: (params?: { direction?: string; limit?: number }): Promise<{ data: Trade[]; total: number }> => {
    const q = new URLSearchParams();
    if (params?.direction) q.set("direction", params.direction);
    if (params?.limit) q.set("limit", String(params.limit));
    const qs = q.toString();
    return fetchApi(`/trades${qs ? `?${qs}` : ""}`);
  },
  scan: (): Promise<{ signals: TradeSignal[]; total: number }> =>
    fetchApi("/trades/scan", { method: "POST" }),
};

// ── Strategies ──────────────────────────────────────────────────────
export const strategyApi = {
  list: (): Promise<{ data: Strategy[]; total: number }> =>
    fetchApi("/strategies"),
  toggle: (id: number, enabled: boolean) =>
    fetchApi(`/strategies/${id}/toggle`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
  remove: (id: number): Promise<{ message: string }> =>
    fetchApi(`/strategies/${id}`, { method: "DELETE" }),
};

// ── Time Engine ─────────────────────────────────────────────────────
export const timeApi = {
  status: (): Promise<TimeStatus> =>
    fetchApi("/time/status"),
  knowledge: (): Promise<any> =>
    fetchApi("/time/knowledge"),
};

// ── News ────────────────────────────────────────────────────────────
export const newsApi = {
  portfolio: (): Promise<{
    matchedNews: NewsItem[];
    matchedCount: number;
    totalCount: number;
    allKeywords: string[];
    updateTime: string;
  }> => fetchApi("/news/portfolio"),

  sectors: (): Promise<{ sectors: Record<string, string[]>; parents: string[] }> =>
    fetchApi("/news/sectors"),
};

// ── Risk Engine ──────────────────────────────────────────────────

export interface RiskVerdict {
  allow: boolean;
  riskScore: number;
  riskLevel: string;
  maxPosition: number;
  stopLossPrice: number | null;
  takeProfit: number | null;
  layerScores: Record<string, number>;
  reasons: string[];
}

export interface RiskConfigData {
  singleTradeCapPct: number;
  singleFundCapPct: number;
  cashReservePct: number;
  positionTiers: [number, number][];
  stopLossFixedPct: number;
  stopLossAtrMultiple: number;
  stopLossTrailingActivatePct: number;
  stopLossTrailingDistancePct: number;
  stopLossTimeDays: number;
  drawdownTiers: [number, number][];
  sentimentGoodMin: number;
  sentimentBadMax: number;
  riskWeightCapital: number;
  riskWeightPosition: number;
  riskWeightStopLoss: number;
  riskWeightDrawdown: number;
  riskWeightMarket: number;
}

export const riskApi = {
  metrics: (): Promise<RiskMetrics> =>
    fetchApi("/analytics/risk"),

  /** 获取风控配置 */
  config: (): Promise<RiskConfigData> =>
    fetchApi("/risk/config"),

  /** 更新风控配置 */
  updateConfig: (data: Partial<RiskConfigData>): Promise<{ status: string; message: string }> =>
    fetchApi("/risk/config", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  /** 运行风控检查 */
  check: (params: { fundCode: string; decisionScore: number; decisionSignal: string }): Promise<RiskVerdict> =>
    fetchApi("/risk/check", {
      method: "POST",
      body: JSON.stringify(params),
    }),
};

// ── Agent 多 Agent 决策系统 ────────────────────────────────────
export const agentApi = {
  /** 全量 Agent 扫描（所有基金） */
  scan: (): Promise<{
    data: AgentDecision[];
    total: number;
    timestamp: string;
    status: string;
  }> => fetchApi("/agents/scan"),

  /** 单基金 Agent 分析详情 */
  fund: (fundId: number): Promise<{
    fund: { id: number; code: string; name: string; currentPrice: number };
    decision: MergedDecision;
    timestamp: string;
  }> => fetchApi(`/agents/fund/${fundId}`),

  /** Market Intelligence 新闻分析结果 */
  marketNews: (): Promise<{
    data: MarketNewsAnalysis[];
    total: number;
    timestamp: string;
  }> => fetchApi("/agents/market-news"),

  /** AI 聊天（带持久化） */
  chat: (message: string, sessionId?: string): Promise<{
    reply: string;
    status: string;
    session_id: string;
  }> => fetchApi("/chat", {
    method: "POST",
    body: JSON.stringify({ message, session_id: sessionId || "default" }),
  }),

  /** 获取历史对话 */
  chatHistory: (sessionId?: string, limit?: number): Promise<{
    messages: ChatMessage[];
    total: number;
    session_id: string;
  }> => {
    const sid = sessionId || "default";
    return fetchApi(`/chat/history?session_id=${sid}&limit=${limit || 50}`);
  },

  /** 清空历史 */
  chatClear: (sessionId?: string): Promise<{ message: string; session_id: string }> =>
    fetchApi(`/chat/history?session_id=${sessionId || "default"}`, { method: "DELETE" }),

  /** 列出所有 session */
  sessions: (): Promise<{
    sessions: ChatSession[];
    total: number;
  }> => fetchApi("/chat/sessions"),

  /** 删除 session */
  sessionDelete: (sessionId: string): Promise<{ message: string; session_id: string }> =>
    fetchApi("/chat/session/delete", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId }),
    }),
};

// ── Backtest API ──────────────────────────────────────────────────

export interface BacktestFund {
  id: number;
  code: string;
  name: string;
  currentPrice: number;
  dataStart: string | null;
  dataEnd: string | null;
  dataPoints: number;
}

export interface BacktestConfig {
  fundCode: string;
  fundName: string;
  strategyType: "ma" | "grid";
  strategyParams: Record<string, number>;
  initialCash: number;
  buyFeeRate: number;
  maxPositionPct: number;
  maxDrawdownPct: number;
}

export interface EquityPoint {
  date: string;
  totalValue: number;
  cash: number;
  shares: number;
  price: number;
  action: string;
}

export interface BacktestTrade {
  date: string;
  action: "buy" | "sell";
  price: number;
  shares: number;
  amount: number;
  fee: number;
  reason: string;
}

export interface BacktestMetrics {
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  calmar_ratio: number;
  win_rate: number;
  profit_loss_ratio: number;
  total_trades: number;
  total_buys: number;
  total_sells: number;
  max_consecutive_loss: number;
  max_consecutive_profit: number;
  avg_hold_days: number;
  turnover_rate: number;
  start_date: string;
  end_date: string;
  total_days: number;
  trading_days: number;
  final_value: number;
  total_profit: number;
  benchmark_code?: string;
  benchmark_return?: number;
}

export interface BacktestRunResponse {
  status: "ok" | "error";
  message?: string;
  config?: BacktestConfig;
  equityCurve?: EquityPoint[];
  trades?: BacktestTrade[];
  metrics?: BacktestMetrics;
}

export const backtestApi = {
  funds: (): Promise<{ funds: BacktestFund[]; total: number }> =>
    fetchApi("/backtest/funds"),

  run: (params: Record<string, any>): Promise<BacktestRunResponse> =>
    fetchApi("/backtest/run", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  /** 将回测结果部署到模拟盘 */
  deploy: (params: Record<string, any>): Promise<{
    status: string;
    accountId?: number;
    accountName?: string;
    strategyConfig?: Record<string, any>;
    message?: string;
  }> => fetchApi("/backtest/deploy", {
    method: "POST",
    body: JSON.stringify(params),
  }),
};

// ── Type exports for Agent system ───────────────────────────────
export interface AgentDecision {
  fund_id: number;
  fund_code: string;
  fund_name: string;
  current_price: number;
  decision: MergedDecision;
}

export interface MergedDecision {
  signal: string;
  score: number;
  confidence: number;
  reasons: string[];
  risk: number;
  expire_at: string | null;
  should_execute: boolean;
  trade_quantity: number;
  trade_price: number;
  agents_contributions: {
    agent: string;
    signal: string;
    score: number;
    confidence: number;
    weight: number;
  }[];
}

export interface ChatMessage {
  id?: number;
  role: "user" | "assistant";
  content: string;
  createdAt?: string;
}

export interface ChatSession {
  sessionId: string;
  msgCount: number;
  lastActive: string;
  preview?: string;
  title?: string;
}

// ── Sim Account API ───────────────────────────────────────────────

export interface SimAccount {
  id: number;
  name: string;
  initialCash: number;
  cash: number;
  positionValue: number;
  totalValue: number;
  holdingCount: number;
  strategyConfig: Record<string, any>;
  createdAt: string;
  updatedAt: string;
}

export interface SimPosition {
  id: number;
  accountId: number;
  fundCode: string;
  shares: number;
  costPrice: number;
  fundName: string;
  currentPrice: number;
}

export interface SimTrade {
  id: number;
  accountId: number;
  fundCode: string;
  direction: "buy" | "sell";
  price: number;
  shares: number;
  amount: number;
  fee: number;
  reason: string;
  fundName: string;
  createdAt: string;
}

export const simApi = {
  accounts: (): Promise<{ accounts: SimAccount[]; total: number }> =>
    fetchApi("/sim/accounts"),

  detail: (id: number): Promise<{
    account: SimAccount;
    positions: SimPosition[];
    trades: SimTrade[];
    dailyValues: { date: string; totalValue: number; cash: number; positionValue: number }[];
  }> => fetchApi(`/sim/accounts/${id}`),

  execute: (): Promise<{ status: string; results: any[]; total: number; timestamp: string }> =>
    fetchApi("/sim/execute", { method: "POST" }),

  trades: (id: number, limit = 50): Promise<{ trades: SimTrade[]; total: number }> =>
    fetchApi(`/sim/trades/${id}?limit=${limit}`),

  equity: (): Promise<{
    accounts: { accountId: number; accountName: string; initialCash: number; equity: { date: string; nav: number; totalValue: number }[] }[];
    total: number;
  }> => fetchApi("/sim/equity"),

  updateConfig: (id: number, config: Record<string, any>): Promise<{ status: string; message: string }> =>
    fetchApi(`/sim/accounts/${id}/config`, { method: "POST", body: JSON.stringify({ config }) }),

  snapshot: (): Promise<{ status: string; message: string }> =>
    fetchApi("/sim/snapshot", { method: "POST" }),

  /** 获取执行记录（输入快照） */
  runs: (accountId = 0, limit = 50): Promise<{ runs: any[]; total: number }> =>
    fetchApi(`/sim/runs?account_id=${accountId}&limit=${limit}`),

  /** 获取收益归因汇总 */
  attribution: (accountId: number, days = 30): Promise<{ data: {
    agent_name: string;
    total_trades: number;
    avg_confidence: number;
    total_pnl: number;
    pnl_share_pct: number;
  }[]; total: number }> =>
    fetchApi(`/sim/attribution?account_id=${accountId}&days=${days}`),

  /** 获取归因详情 */
  attributionDetail: (accountId = 0, days = 30): Promise<{ data: any[]; total: number }> =>
    fetchApi(`/sim/attribution/detail?account_id=${accountId}&days=${days}`),

  /** 获取账户绩效指标 */
  metrics: (accountId: number): Promise<{
    account_id: number;
    metrics: Record<string, any>;
  }> => fetchApi(`/sim/metrics?account_id=${accountId}`),
};

export interface MarketNewsAnalysis {
  signal: string;
  score: number;
  confidence: number;
  reason: string[];
  risk: number;
  affected_funds: string[];
  summary: string;
  source: string;
  time: string;
  method: string;
}

// ── Daily Reports API ──────────────────────────────────────────────

export interface DailyReport {
  id: number;
  date: string;
  report_type: string;
  content: string;
  accounts_summary: string;
  created_at: string;
}

export const reportApi = {
  /** 获取最近复盘报告列表 */
  list: (limit = 10): Promise<{ reports: DailyReport[]; total: number }> =>
    fetchApi(`/reports?limit=${limit}`),

  /** 获取完整报告内容 */
  detail: (id: number): Promise<DailyReport> =>
    fetchApi(`/reports/${id}`),

  /** 手动触发当日报告生成 */
  generate: (): Promise<{ status: string; reportId?: number; date?: string; message?: string }> =>
    fetchApi("/reports/generate", { method: "POST" }),
};

// ── Benchmark API ──────────────────────────────────────────────────

export interface BenchmarkData {
  code: string;
  name: string;
  data: { date: string; close: number; nav: number }[];
  total: number;
}

export const benchmarkApi = {
  /** 获取基准指数历史净值（归一化 nav） */
  history: (code = "000300", days = 365): Promise<BenchmarkData> =>
    fetchApi(`/benchmark/history?code=${code}&days=${days}`),

  /** 获取支持的指数列表 */
  list: (): Promise<{ indices: { code: string; name: string }[]; total: number }> =>
    fetchApi("/benchmark/list"),
};

// ── Fund Prices API ──────────────────────────────────────────────────

export interface FundPriceRecord {
  date: string;
  nav: number;
  estimate_nav: number | null;
  change_pct: number | null;
  source: string;
}

export const fundPriceApi = {
  /** 获取基金历史净值 */
  history: (code: string, days = 30): Promise<{ code: string; data: FundPriceRecord[]; total: number }> =>
    fetchApi(`/fund-prices/history?code=${code}&days=${days}`),

  /** 获取今日所有基金最新价格 */
  latest: (): Promise<{ data: { fund_code: string; name: string; date: string; nav: number; estimate_nav: number; change_pct: number }[]; total: number; date: string }> =>
    fetchApi("/fund-prices/latest"),
};
