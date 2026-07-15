// ── Portfolio / Fund Types ──────────────────────────────────────────
export interface Fund {
  id: number;
  code: string;
  name: string;
  shares: number;
  costPrice: number;
  currentPrice: number;
  updateTime: string;
}

export interface RealtimeQuote {
  code: string;
  name: string;
  dwjz: number | null;
  gsz: number | null;
  gszzl: number | null;
  gztime: string;
  error: string | null;
}

// ── Strategy ────────────────────────────────────────────────────────
export interface Strategy {
  id: number;
  fundId: number;
  name: string;
  type: "ma" | "grid";
  params: Record<string, unknown>;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

// ── Trade ───────────────────────────────────────────────────────────
export interface Trade {
  id: number;
  fundId: number;
  direction: "buy" | "sell";
  price: number;
  shares: number;
  amount: number;
  strategy: string | null;
  strategyId: number | null;
  time: string;
  status: string;
}

export interface TradeSignal {
  fundId: number;
  strategyId: number;
  signalType: "buy" | "sell";
  price: number;
  quantity: number;
  generatedAt: string;
  fundCode?: string;
  fundName?: string;
  strategyName?: string;
}

// ── Analytics ───────────────────────────────────────────────────────
export interface PortfolioValue {
  date: string;
  totalValue: number;
}

export interface AnalyticsSummary {
  totalValue: number;
  totalCost: number;
  profit: number;
  profitRate: number;
  fundCount: number;
  tradeCount: number;
  winningFunds: number;
  losingFunds: number;
}

// ── Time Engine ─────────────────────────────────────────────────────
export interface TimeStatus {
  currentTime: string;
  date: string;
  isTradingDay: boolean;
  isBefore1500: boolean;
  isETFTradingTime: boolean;
  isCallAuction: boolean;
  inOptimalBuyWindow: boolean;
  inOptimalSellWindow: boolean;
  inMorningNewsWindow: boolean;
  status: string;
  statusLabel: string;
  nextTradingDay: string | null;
  holidayStrategy: {
    warnings: string[];
    actions: string[];
    countdownDays: number | null;
  };
}

// ── News ────────────────────────────────────────────────────────────
export interface NewsItem {
  title: string;
  content: string;
  source: string;
  time: string;
  tags: string[];
  urgent: boolean;
  sentiment: "positive" | "negative" | "neutral";
  sentimentScore: number;
  matchedKeywords: string[];
  actionLabel: string;
  riskNote: string;
  matched: boolean;
}

// ── Risk Metrics ────────────────────────────────────────────────────
export interface RiskMetrics {
  maxDrawdown: number;
  maxDrawdownPct: number;
  sharpeRatio: number;
  volatility: number;
  winRate: number;
  totalTrades: number;
}
