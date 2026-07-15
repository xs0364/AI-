"use client";

import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string;
  change?: number;       // 涨跌值（人民币）
  changePct?: number;    // 涨跌幅百分比
  format?: "currency" | "percent" | "number";
  size?: "sm" | "default";
  className?: string;
}

export function StatCard({
  label,
  value,
  change,
  changePct,
  size = "default",
  className,
}: StatCardProps) {
  const changeColor =
    change != null
      ? change > 0
        ? "text-positive"
        : change < 0
        ? "text-negative"
        : "text-text-tertiary"
      : "";

  const TrendIcon =
    change != null
      ? change > 0
        ? TrendingUp
        : change < 0
        ? TrendingDown
        : Minus
      : undefined;

  return (
    <div
      className={cn(
        "rounded-xl bg-card border border-border-subtle shadow-card p-4 transition-all hover:shadow-elevated",
        className
      )}
    >
      <div className="text-xs text-text-tertiary font-medium mb-1">{label}</div>

      <div
        className={cn(
          "font-mono tabular-nums font-semibold text-text-primary tracking-tight",
          size === "default" ? "text-2xl leading-none" : "text-lg leading-none"
        )}
      >
        {value}
      </div>

      {(change != null || changePct != null) && (
        <div className={cn("flex items-center gap-1.5 mt-1.5 text-xs font-medium", changeColor)}>
          {TrendIcon && <TrendIcon className="h-3.5 w-3.5" />}
          {change != null && (
            <span className="tabular-nums">
              {change > 0 ? "+" : ""}
              {change.toFixed(2)}
            </span>
          )}
          {changePct != null && (
            <span className="tabular-nums text-text-tertiary">
              ({changePct > 0 ? "+" : ""}
              {changePct.toFixed(2)}%)
            </span>
          )}
        </div>
      )}
    </div>
  );
}
