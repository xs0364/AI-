"use client";

import { useEffect, useState } from "react";
import { timeApi } from "@/lib/api";
import {
  Clock, CalendarDays, Sun, Moon, AlertTriangle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { TimeStatus } from "@/lib/types";

export function SystemStatus() {
  const [status, setStatus] = useState<TimeStatus | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  useEffect(() => {
    timeApi.status()
      .then((s) => { setStatus(s); setBackendOnline(true); })
      .catch(() => setBackendOnline(false));

    const t = setInterval(() => {
      timeApi.status()
        .then((s) => { setStatus(s); setBackendOnline(true); })
        .catch(() => setBackendOnline(false));
    }, 30000);
    return () => clearInterval(t);
  }, []);

  const now = new Date();
  const timeStr = now.toLocaleTimeString("zh-CN", { hour12: false });

  return (
    <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4">
      <div className="text-xs text-text-tertiary font-medium mb-3">系统状态</div>

      <div className="space-y-2.5">
        {/* 后端连接 */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-secondary">后端连接</span>
          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "w-1.5 h-1.5 rounded-full",
                backendOnline === true && "bg-positive",
                backendOnline === false && "bg-negative",
                backendOnline === null && "bg-text-tertiary"
              )}
            />
            <span className="text-xs tabular-nums text-text-primary font-medium">
              {backendOnline === true ? "在线" : backendOnline === false ? "离线" : "检测中"}
            </span>
          </div>
        </div>

        {/* 当前时间 */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-text-secondary">当前时间</span>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3 text-text-tertiary" />
            <span className="text-xs tabular-nums text-text-primary font-medium">{timeStr}</span>
          </div>
        </div>

        {status && (
          <>
            {/* 交易日 */}
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">交易日</span>
              <Badge
                variant="outline"
                className={cn(
                  "h-5 text-[10px] font-normal",
                  status.isTradingDay
                    ? "text-positive border-positive/30"
                    : "text-text-tertiary"
                )}
              >
                <CalendarDays className="h-3 w-3 mr-1" />
                {status.isTradingDay ? "是" : "否"}
              </Badge>
            </div>

            {/* 交易时段 */}
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">交易时段</span>
              <Badge
                variant="outline"
                className={cn(
                  "h-5 text-[10px] font-normal",
                  status.isBefore1500
                    ? "border-brand-300 text-brand-400"
                    : "text-text-tertiary"
                )}
              >
                {status.isBefore1500 ? "15:00前" : "15:00后"}
              </Badge>
            </div>

            {/* 当前状态 */}
            <div className="flex items-center justify-between">
              <span className="text-xs text-text-secondary">交易状态</span>
              <span className="text-xs text-text-primary font-medium">
                {status.statusLabel || status.status}
              </span>
            </div>
          </>
        )}

        {/* 告警摘要 */}
        {status?.holidayStrategy?.warnings?.length ? (
          <div className="flex items-start gap-1.5 p-2 rounded-lg bg-warning/5 text-warning text-xs mt-1">
            <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
            <span>{status.holidayStrategy.warnings[0]}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
