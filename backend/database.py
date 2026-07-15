"""
SQLite database setup and connection management.
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "fund_manager.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS funds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            shares REAL NOT NULL DEFAULT 0,
            cost_price REAL NOT NULL DEFAULT 0,
            current_price REAL NOT NULL DEFAULT 0,
            update_time TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS strategies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            strategy_type TEXT NOT NULL,
            params TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS trade_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER NOT NULL,
            strategy_id INTEGER NOT NULL,
            signal_type TEXT NOT NULL,
            price REAL NOT NULL,
            quantity REAL NOT NULL DEFAULT 0,
            generated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            executed INTEGER NOT NULL DEFAULT 0,
            executed_at TEXT,
            FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE CASCADE,
            FOREIGN KEY (strategy_id) REFERENCES strategies(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER NOT NULL,
            direction TEXT NOT NULL,
            price REAL NOT NULL,
            shares REAL NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            strategy TEXT,
            strategy_id INTEGER,
            time TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            status TEXT NOT NULL DEFAULT 'executed',
            FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS daily_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL DEFAULT 'default',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_chat_session ON chat_messages(session_id, id);

        -- 模拟盘
        CREATE TABLE IF NOT EXISTS sim_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            initial_cash REAL NOT NULL DEFAULT 0,
            cash REAL NOT NULL DEFAULT 0,
            strategy_config TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS sim_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            shares REAL NOT NULL DEFAULT 0,
            cost_price REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (account_id) REFERENCES sim_accounts(id) ON DELETE CASCADE,
            UNIQUE(account_id, fund_code)
        );

        CREATE TABLE IF NOT EXISTS sim_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            fund_code TEXT NOT NULL,
            direction TEXT NOT NULL,
            price REAL NOT NULL,
            shares REAL NOT NULL,
            amount REAL NOT NULL DEFAULT 0,
            fee REAL NOT NULL DEFAULT 0,
            reason TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (account_id) REFERENCES sim_accounts(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_sim_trades_account ON sim_trades(account_id);
        CREATE INDEX IF NOT EXISTS idx_sim_positions_account ON sim_positions(account_id);

        -- 模拟盘每日净值
        CREATE TABLE IF NOT EXISTS sim_daily_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            cash REAL NOT NULL DEFAULT 0,
            position_value REAL NOT NULL DEFAULT 0,
            UNIQUE(account_id, date),
            FOREIGN KEY (account_id) REFERENCES sim_accounts(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sim_dv_account ON sim_daily_values(account_id);

        -- 模拟盘运行记录（输入快照 + 决策 + 结果）
        CREATE TABLE IF NOT EXISTS simulation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            run_version TEXT NOT NULL DEFAULT '1.0',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            -- 输入快照
            ma20 REAL,
            rsi REAL,
            atr REAL,
            news_score REAL,
            -- 决策
            signal TEXT,
            score REAL,
            confidence REAL,
            -- 结果
            trades_count INTEGER DEFAULT 0,
            pnl REAL DEFAULT 0,
            total_value_before REAL,
            total_value_after REAL,
            FOREIGN KEY (account_id) REFERENCES sim_accounts(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_sim_runs_account ON simulation_runs(account_id);

        -- Agent 收益归因（每日汇总）
        CREATE TABLE IF NOT EXISTS sim_agent_attribution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            agent_name TEXT NOT NULL,
            trade_count INTEGER DEFAULT 0,
            total_score REAL DEFAULT 0,
            avg_confidence REAL DEFAULT 0,
            weighted_share REAL DEFAULT 0,
            pnl_contribution REAL DEFAULT 0,
            FOREIGN KEY (account_id) REFERENCES sim_accounts(id) ON DELETE CASCADE,
            UNIQUE(account_id, date, agent_name)
        );
        CREATE INDEX IF NOT EXISTS idx_sim_attr_account ON sim_agent_attribution(account_id);

        -- 基准指数每日收盘价（沪深300/中证500等）
        CREATE TABLE IF NOT EXISTS daily_benchmark (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            index_code TEXT NOT NULL,
            date TEXT NOT NULL,
            close REAL NOT NULL,
            UNIQUE(index_code, date)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_benchmark ON daily_benchmark(index_code, date);

        -- 回测历史结果
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT NOT NULL,
            fund_name TEXT NOT NULL,
            strategy_type TEXT NOT NULL,
            strategy_params TEXT NOT NULL DEFAULT '{}',
            initial_cash REAL NOT NULL DEFAULT 100000,
            start_date TEXT,
            end_date TEXT,
            -- 绩效指标
            total_return REAL,
            annual_return REAL,
            max_drawdown_pct REAL,
            sharpe_ratio REAL,
            sortino_ratio REAL,
            calmar_ratio REAL,
            win_rate REAL,
            total_trades INTEGER,
            final_value REAL,
            total_profit REAL,
            -- 元数据
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            benchmark_code TEXT DEFAULT '',
            benchmark_return REAL
        );
        CREATE INDEX IF NOT EXISTS idx_backtest_results ON backtest_results(created_at DESC);

        -- AI 每日复盘报告
        CREATE TABLE IF NOT EXISTS daily_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            report_type TEXT NOT NULL DEFAULT 'daily',
            content TEXT NOT NULL,
            accounts_summary TEXT DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE INDEX IF NOT EXISTS idx_daily_reports ON daily_reports(date DESC);

        -- 基金每日净值历史（东财真实数据）
        CREATE TABLE IF NOT EXISTS fund_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT NOT NULL,
            date TEXT NOT NULL,
            nav REAL NOT NULL DEFAULT 0,
            estimate_nav REAL,
            change_pct REAL,
            source TEXT NOT NULL DEFAULT 'realtime',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(fund_code, date)
        );
        CREATE INDEX IF NOT EXISTS idx_fund_prices ON fund_prices(fund_code, date DESC);
    """)

    conn.commit()
    conn.close()
