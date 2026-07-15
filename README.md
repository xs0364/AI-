# 量化交易系统 — Quant Trading System

一个由 **真实市场数据驱动** 的基金量化交易平台，集成多 Agent 决策 → 信号融合 → 风控 → 模拟盘执行 → AI 复盘完整闭环。

---

## 系统架构

```
东财实时数据 (fundgz / K线 / 新闻)
        │
        ▼
┌───────────────┐     ┌─────────────────┐
│  Market Data   │     │ Benchmark Index │
│  Fetcher       │     │ Engine          │
│  (fund实时估值)  │     │ (沪深300/中证500)│
└───────┬───────┘     └────────┬────────┘
        │                      │
        ▼                      ▼
    ┌──────────────────────────────┐
    │     Decision Orchestrator    │
    │  ┌──────┐ ┌──────┐ ┌─────┐  │
    │  │Trend │ │Grid  │ │Market│  │
    │  │Agent │ │Agent │ │Agent │  │
    │  └──┬───┘ └──┬───┘ └──┬──┘  │
    │     └────┬───┘────────┘     │
    │          ▼                  │
    │  Signal Merge Engine       │
    │  (加权融合 + 否决规则)      │
    └──────────┬──────────────────┘
               │
               ▼
       ┌──────────────┐
       │  Risk Engine │  6层检查：仓位/止盈止损/回撤/情绪/市场制度/综合评分
       └──────┬───────┘
               │
        ┌──────┴──────┐
        ▼              ▼
   ┌─────────┐   ┌──────────┐
   │ 实盘交易  │   │ 模拟盘执行 │
   │ trades  │   │ sim_engine│
   └─────────┘   └────┬─────┘
                       │
                       ▼
              ┌──────────────────┐
              │ Portfolio Snapshot│
              │ 每日净值 → 归因   │
              │ 绩效指标 → 对比   │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │  AI 复盘报告      │
              │  15:10 自动生成   │
              └──────────────────┘
```

---

## 功能清单

### 🔄 数据层

| 功能 | 说明 |
|------|------|
| **东财实时估值** | `fetch_fund_realtime()` — 基金实时估算净值（fundgz 接口）|
| **批量价格刷新** | 14:30 调度器自动遍历所有基金，批量更新 `funds.current_price` |
| **基金历史净值** | `fetch_fund_history()` — 东财 F10DataApi 历史净值 |
| **ETF 实时分时** | `fetch_etf_trend()` — 场内 ETF 分钟线 |
| **十大持仓** | `fetch_fund_holdings()` — 基金重仓股 |
| **基金代码列表** | `fetch_fund_code_list()` — 全市场基金清单 |
| **基准指数** | 沪深300(000300) / 中证500(000905) / 中证红利(000922) / 上证50(000016) |
| **新闻舆情** | 东财快讯 + 选股宝 Flash + TerminalFeed |

### 🤖 Agent 决策系统

| Agent | 类型 | 输入 | 输出 |
|-------|------|------|------|
| **Trend Agent** | 纯计算 | MACD / RSI / BOLL / ATR / EMA | `{signal, score, confidence}` |
| **Grid Agent** | 纯计算 | ATR 自适应网格 / 波动率 / 区间突破 | `{signal, score, confidence}` |
| **Market Agent** | LLM 驱动 | 新闻语义分析 / 情感评分 | `{signal, score, confidence, affected_funds}` |
| **Signal Merge** | 规则引擎 | 三路信号加权融合 (40/25/35) + 否决规则 | `MergedDecision` |

### 🛡️ 风控引擎

六层检查体系：

1. **资金风控** — 单笔/单基金仓位上限、现金储备
2. **仓位调整** — 分级仓位管理 (5档)
3. **止损管理** — 固定止损 / ATR 动态 / 浮动跟踪 / 时间止损
4. **回撤控制** — 分级回撤降仓
5. **市场制度** — 情绪过滤、涨跌停/停牌检测
6. **综合评分** — 加权汇总 + 风险等级判定

### 📈 模拟盘（三账户）

| 账户 | 策略组合 | 初始资金 | 最大仓位 |
|------|---------|---------|---------|
| **保守·均线趋势** | Trend only | ¥1,000 | 30% |
| **进取·网格增强** | Grid + Market | ¥10,000 | 50% |
| **混合·AI 全开** | Trend + Grid + Market | ¥100,000 | 80% |

每个账户独立 `strategy_config`，同一份 Agent 信号按策略配置过滤执行。

### 📊 回测引擎

- **策略支持**：MA 均线趋势 / Grid 网格交易
- **T+1 模拟**：15:00 前/后下单 → 不同成交日期
- **绩效指标**：总收益、年化收益、夏普比率、索提诺比率、卡尔玛比率、最大回撤、胜率、盈亏比、换手率、平均持仓天数
- **基准对比**：净值曲线叠加沪深300/中证500等指数
- **一键部署**：回测结果 → 创建模拟账户

### 📝 AI 每日复盘

- **调度**：交易日 15:10 自动触发
- **数据源**：模拟盘净值 + 归因分析 + 基准指数 + 交易记录
- **输出**：结构化 Markdown 报告（总览/归因/风险/建议）
- **前端**：复盘页面，左侧列表 + 右侧 Markdown 渲染（表格/标题/列表/加粗）

### 📋 前端 Dashboard（12 页面）

| 页面 | 路由 | 功能 |
|------|------|------|
| **仪表盘** | `/` | 资产总览 / 净值曲线 / 资产配置 / 系统状态 |
| **持仓** | `/holdings` | 基金持仓管理 / 实时价格 / 盈亏计算 |
| **策略** | `/strategies` | 策略列表 / 创建 / 编辑 / 启停 |
| **交易** | `/trades` | 交易记录 / 手动交易 / 批量扫描执行 |
| **回测** | `/backtest` | 策略参数配置 / 运行回测 / 净值曲线 / 指标卡片 / 部署到模拟盘 |
| **模拟盘** | `/simulation` | 三账户总览卡（今日涨跌/现金占比） / 三线净值图 / 持仓明细 / 交易记录 / 收益归因 / 基准切换 |
| **舆情** | `/news` | 多源新闻 / 行业板块 / 持仓关键词匹配 |
| **复盘** | `/reports` | AI 复盘报告列表 / Markdown 渲染 / 手动生成 |
| **智能决策** | `/agents` | Agent 扫描结果 / 各维度信号 / 融合决策链 |
| **AI 聊天** | `/ai-chat` | 多会话圆宝 AI 聊天 / RAG 上下文注入 |
| **风控配置** | `/risk` | 风控参数编辑器 / 逐基金检查工具 |
| **时间知识库** | `/time-rules` | 15:00 截止时间 / QDII 时差 / 费率表 / 节假规则 |
| **设置** | `/settings` | 主题切换 |

### ⏰ 交易日调度流水线

```
14:30  市场数据更新（基准指数 + 基金实时价格刷新）
14:40  Agent 全量扫描 + 自动执行实盘交易
14:50  模拟盘执行（三账户独立运行）
14:55  Agent 二次扫描补充
15:05  收盘净值快照
15:10  AI 复盘报告生成
```

### 💬 圆宝 AI 聊天

- 基于 NVIDIA NIM (qwen3.5-397b-a17b) 的 LLM 对话
- 多会话管理 + 持久化
- RAG 上下文注入（交易规则 + 风控知识 + 市场常识）
- 支持联网搜索 + 持仓查询

---

## 技术栈

### 后端
- **框架**：FastAPI + uvicorn
- **数据库**：SQLite (WAL模式, `fund_manager.db`)
- **调度器**：APScheduler (CronTrigger)
- **LLM**：NVIDIA NIM API (qwen3.5-397b-a17b)
- **数据源**：东方财富 HTTP API (逆向) + 选股宝 + TerminalFeed

### 前端
- **quant-dashboard**：Next.js 16 + React 19 + TypeScript + Tailwind CSS v4 + shadcn/ui
- **图表**：Lightweight Charts v5 (净值曲线)
- **图标**：Lucide React
- **fund-manager**（旧版）：Vue 3 + Vite + ECharts + Pinia

---

## 快速启动

```bash
# 1. 启动后端
cd backend
pip install -r requirements.txt
python app.py
# → http://localhost:3000

# 2. 启动前端 Dashboard
cd quant-dashboard
npm install
npm run dev
# → http://localhost:3001

# 3. (可选) 旧版 Vue 前端
cd fund-manager
npm install
npm run dev
# → http://localhost:5173
```

### 首次启动

系统自动：
1. 创建 SQLite 数据库和全部表
2. 填充 5 只示例基金 + 3 个模拟账户
3. 启动 APScheduler 交易日流水线
4. 12 小时内首次访问时自动拉取基准指数数据

---

## 项目结构

```
H:\lhjy\
├── backend/                    # FastAPI 后端
│   ├── app.py                  # 入口：所有 API 端点 + 调度器
│   ├── database.py             # SQLite 连接 + 建表
│   ├── models.py               # Pydantic 模型
│   ├── seed.py                 # 初始数据填充
│   ├── market_data_fetcher.py  # 东财数据接口
│   ├── strategy_engine.py      # 策略信号生成
│   ├── trading_time_engine.py  # 交易时间规则引擎
│   ├── decision_orchestrator.py # Agent 编排
│   ├── agent_schema.py         # Agent 统一数据契约
│   ├── agent_trend.py          # 趋势 Agent
│   ├── agent_grid.py           # 网格 Agent
│   ├── agent_market.py         # 市场舆情 Agent (LLM)
│   ├── signal_merge_engine.py  # 信号融合引擎
│   ├── risk_engine.py          # 六层风控引擎
│   ├── backtest_engine.py      # 回测引擎
│   ├── sim_engine.py           # 模拟盘执行引擎
│   ├── sim_analytics.py        # 模拟盘分析 (归因/绩效)
│   ├── benchmark_engine.py     # 基准指数引擎
│   ├── daily_review_agent.py   # AI 复盘 Agent
│   ├── llm_service.py          # LLM 统一服务
│   ├── chat_history.py         # 聊天历史持久化
│   ├── rag_engine.py           # 轻量 RAG 引擎
│   ├── news_engine.py          # 新闻引擎
│   └── requirements.txt
│
├── quant-dashboard/            # Next.js 前端 (主力)
│   └── src/
│       ├── app/                # 12 个页面路由
│       ├── components/         # UI 组件
│       └── lib/                # API 调用 + 类型 + 工具
│
└── fund-manager/               # Vue 3 前端 (旧版)
    └── src/
        ├── views/              # 6 个功能页面
        ├── components/         # 通用组件
        └── stores/             # Pinia 状态管理
```

---

## 配置文件

| 文件 | 说明 |
|------|------|
| `backend/risk_config.json` | 风控参数（仓位/止损/回撤阈值） |
| `backend/llm_service.py` | LLM API 密钥配置（NVIDIA NIM） |
| `quant-dashboard/.env.local` | 前端环境变量 |

---

## 数据库表

| 表 | 说明 |
|----|------|
| `funds` | 基金主表 |
| `strategies` | 策略定义 |
| `trades` | 实盘交易记录 |
| `daily_values` | 每日组合市值 |
| `sim_accounts` | 模拟账户 |
| `sim_positions` | 模拟持仓 |
| `sim_trades` | 模拟交易 |
| `sim_daily_values` | 模拟每日净值 |
| `simulation_runs` | 执行快照 |
| `sim_agent_attribution` | Agent 收益归因 |
| `daily_benchmark` | 基准指数每日收盘 |
| `backtest_results` | 回测历史结果 |
| `daily_reports` | AI 复盘报告 |
| `fund_prices` | 基金每日净值历史 |
| `chat_messages` | AI 聊天记录 |
| `trade_signals` | 交易信号 |
