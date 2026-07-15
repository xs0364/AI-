"use client";

import { useEffect, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  ArrowDownRight,
  AlertTriangle,
  X,
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface LogEntry {
  id: number;
  time: string;
  message: string;
  type: "info" | "trade" | "warn" | "error";
}

interface Alert {
  id: number;
  message: string;
  severity: "low" | "medium" | "high";
}

// 模拟数据 — 后端接入后替换
const DEMO_LOGS: LogEntry[] = [
  { id: 7, time: "13:45:02", message: "网格策略 中欧医疗A 减仓成功", type: "trade" },
  { id: 6, time: "13:30:00", message: "定期检查：净值更新完成", type: "info" },
  { id: 5, time: "10:15:22", message: "均线策略 易方达中小盘 发出买入信号", type: "trade" },
  { id: 4, time: "09:45:00", message: "新闻舆情匹配：医药板块利好 (置信度 78%)", type: "info" },
  { id: 3, time: "09:32:10", message: "实时估值刷新：5/5 基金全部成功", type: "info" },
  { id: 2, time: "09:30:05", message: "开盘检测：今日为交易日，15:00前可操作", type: "info" },
  { id: 1, time: "09:25:00", message: "系统启动完成，服务正常", type: "info" },
];

const DEMO_ALERTS: Alert[] = [
  { id: 3, message: "中欧医疗C 浮亏 -22.5%，触发风控预警线", severity: "high" },
  { id: 2, message: "景顺长城新兴成长 接近目标止盈位 +18.3%", severity: "medium" },
  { id: 1, message: "明日为节假日休市，请提前安排操作", severity: "low" },
];

export function RightPanel() {
  const [logs, setLogs] = useState<LogEntry[]>(DEMO_LOGS);
  const [alerts, setAlerts] = useState<Alert[]>(DEMO_ALERTS);
  const [collapsed, setCollapsed] = useState(false);

  // 模拟日志追加
  useEffect(() => {
    if (collapsed) return;
    const t = setInterval(() => {
      const types: LogEntry["type"][] = ["info", "trade", "info"];
      const msgs = [
        "心跳检测：后端连接正常",
        "实时估值已刷新",
        "策略引擎空闲中",
      ];
      const entry: LogEntry = {
        id: Date.now(),
        time: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
        message: msgs[Math.floor(Math.random() * msgs.length)],
        type: types[Math.floor(Math.random() * types.length)],
      };
      setLogs((prev) => [entry, ...prev].slice(0, 50));
    }, 15000);
    return () => clearInterval(t);
  }, [collapsed]);

  if (collapsed) {
    return (
      <aside className="flex flex-col border-l border-border-subtle bg-rightpanel-bg w-10 items-center pt-2">
        <button
          onClick={() => setCollapsed(false)}
          className="h-8 w-8 flex items-center justify-center rounded-md text-text-tertiary hover:text-text-primary hover:bg-surface-2"
        >
          <Activity className="h-4 w-4" />
        </button>
        {alerts.length > 0 && (
          <span className="mt-1 w-2 h-2 rounded-full bg-negative" />
        )}
      </aside>
    );
  }

  return (
    <aside className="flex flex-col border-l border-border-subtle bg-rightpanel-bg w-72">
      {/* 标题栏 */}
      <div className="flex items-center justify-between h-10 px-3 border-b border-border-subtle">
        <span className="text-xs font-medium text-text-primary">活动面板</span>
        <button
          onClick={() => setCollapsed(true)}
          className="h-6 w-6 flex items-center justify-center rounded text-text-tertiary hover:text-text-primary hover:bg-surface-2"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <ScrollArea className="flex-1">
        {/* 告警 */}
        {alerts.length > 0 && (
          <div className="px-3 pt-2 pb-1">
            <div className="text-[11px] font-medium text-text-tertiary mb-1 uppercase tracking-wider">
              告警 ({alerts.length})
            </div>
            <div className="space-y-1">
              {alerts.map((a) => (
                <div
                  key={a.id}
                  className={cn(
                    "flex items-start gap-2 p-2 rounded-md text-xs",
                    a.severity === "high" && "bg-negative/10 text-negative",
                    a.severity === "medium" && "bg-warning/10 text-warning",
                    a.severity === "low" && "bg-muted text-text-secondary"
                  )}
                >
                  <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
                  <span>{a.message}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 实时日志 */}
        <div className="px-3 pt-2 pb-1">
          <div className="text-[11px] font-medium text-text-tertiary mb-1 uppercase tracking-wider">
            日志流
          </div>
          <div className="space-y-0.5">
            {logs.map((log) => (
              <div key={log.id} className="flex items-start gap-2 text-xs py-0.5">
                <span className="text-text-tertiary shrink-0 tabular-nums w-14">
                  {log.time}
                </span>
                {log.type === "trade" && (
                  log.message.includes("买入") || log.message.includes("买") ? (
                    <ArrowUpRight className="h-3 w-3 mt-0.5 shrink-0 text-positive" />
                  ) : (
                    <ArrowDownRight className="h-3 w-3 mt-0.5 shrink-0 text-negative" />
                  )
                )}
                {log.type === "error" && (
                  <span className="w-3 h-3 mt-0.5 rounded-full bg-negative shrink-0" />
                )}
                {log.type === "warn" && (
                  <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0 text-warning" />
                )}
                <span
                  className={cn(
                    "leading-relaxed",
                    log.type === "error" && "text-negative",
                    log.type === "trade" && "text-text-primary",
                    log.type === "info" && "text-text-tertiary"
                  )}
                >
                  {log.message}
                </span>
              </div>
            ))}
          </div>
        </div>
      </ScrollArea>

      {/* 底部 — 策略运行状态 */}
      <div className="border-t border-border-subtle px-3 py-2">
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-text-tertiary">策略引擎</span>
          <Badge variant="outline" className="h-5 text-[10px] text-positive border-positive/30">
            <span className="w-1.5 h-1.5 rounded-full bg-positive mr-1" />
            运行中
          </Badge>
        </div>
        <div className="mt-1 flex items-center gap-2 text-[11px] text-text-secondary">
          <span>2/3 策略活跃</span>
          <span className="text-border-default">·</span>
          <span>最近: 13:45</span>
        </div>
      </div>
    </aside>
  );
}
