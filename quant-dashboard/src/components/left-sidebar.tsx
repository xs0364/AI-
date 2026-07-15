"use client";

import {
  LayoutDashboard, TrendingUp, Wallet, ArrowLeftRight,
  Backpack, ShieldAlert, ScrollText, Settings,
  Newspaper, Clock, ChevronLeft, ChevronRight,
  BrainCircuit, FlaskConical, FileText,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useState } from "react";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/holdings", label: "持仓", icon: Wallet },
  { href: "/strategies", label: "策略", icon: TrendingUp },
  { href: "/trades", label: "交易", icon: ArrowLeftRight },
  { href: "/backtest", label: "回测", icon: Backpack },
  { href: "/simulation", label: "模拟盘", icon: FlaskConical },
  { href: "/news", label: "舆情", icon: Newspaper },
  { href: "/reports", label: "复盘", icon: FileText },
  { href: "/time-rules", label: "时间知识库", icon: Clock },
  { href: "/risk", label: "风控", icon: ShieldAlert },
  { href: "/agents", label: "AI 决策", icon: BrainCircuit },
  { href: "/ai-chat", label: "圆宝", icon: LayoutDashboard },
  { href: "/logs", label: "日志", icon: ScrollText },
  { href: "/settings", label: "设置", icon: Settings },
];

export function LeftSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-border-subtle bg-sidebar-bg transition-all duration-200",
        collapsed ? "w-12" : "w-48"
      )}
    >
      {/* 导航项 */}
      <nav className="flex-1 py-2 space-y-0.5 px-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-2.5 h-8 px-2 rounded-md text-sm transition-colors",
                active
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-text-secondary hover:text-text-primary hover:bg-surface-2"
              )}
              title={item.label}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* 折叠按钮 */}
      <div className="p-1 border-t border-border-subtle">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="flex items-center justify-center w-full h-8 rounded-md text-text-tertiary hover:text-text-primary hover:bg-surface-2 transition-colors"
          title={collapsed ? "展开" : "折叠"}
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  );
}
