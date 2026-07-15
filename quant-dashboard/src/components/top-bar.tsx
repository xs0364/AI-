"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { ThemeToggle } from "@/components/theme-toggle";
import { Badge } from "@/components/ui/badge";
import { useState, useEffect } from "react";
import type { TimeStatus } from "@/lib/types";
import { timeApi } from "@/lib/api";

export function TopBar() {
  const [status, setStatus] = useState<TimeStatus | null>(null);

  useEffect(() => {
    timeApi.status().then(setStatus).catch(() => {});
    const t = setInterval(() => timeApi.status().then(setStatus).catch(() => {}), 60000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="sticky top-0 z-50 flex h-12 items-center gap-3 border-b border-border-subtle bg-topbar-bg px-4">
      {/* 品牌 */}
      <Link href="/" className="flex items-center gap-2 font-semibold text-text-primary mr-2">
        <span className="text-lg">📊</span>
        <span className="hidden sm:inline text-sm font-heading">Quant</span>
      </Link>

      {/* 全局搜索 */}
      <div className="relative flex-1 max-w-sm">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-tertiary" />
        <Input
          placeholder="搜索基金代码或名称…"
          className="h-7 pl-8 text-xs bg-surface-1 border-border-subtle"
        />
      </div>

      <div className="flex-1" />

      {/* 交易状态 */}
      {status && (
        <Badge
          variant="outline"
          className={`h-6 text-[11px] gap-1 font-normal ${
            status.inOptimalBuyWindow || status.inOptimalSellWindow
              ? "border-warning text-warning"
              : status.isTradingDay && status.isBefore1500
              ? "border-positive text-positive"
              : "border-border-default text-text-tertiary"
          }`}
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              status.isTradingDay && status.isBefore1500 ? "bg-positive" : "bg-text-tertiary"
            }`}
          />
          {status.status}
        </Badge>
      )}

      {/* 主题切换 */}
      <ThemeToggle />
    </header>
  );
}
