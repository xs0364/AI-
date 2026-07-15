"use client";

import { Settings } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  return (
    <div className="space-y-4 max-w-2xl">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">设置</h1>
        <p className="text-sm text-text-tertiary mt-0.5">系统配置和偏好</p>
      </div>

      <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4 space-y-4">
        <div>
          <h2 className="text-sm font-medium text-text-primary mb-3">主题</h2>
          <div className="flex gap-2">
            {["light", "dark", "system"].map((t) => (
              <button key={t} onClick={() => setTheme(t)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  mounted && theme === t ? "bg-primary text-primary-foreground" : "bg-surface-2 text-text-secondary hover:text-text-primary"
                }`}
              >
                {t === "light" ? "🌞 浅色" : t === "dark" ? "🌙 深色" : "💻 跟随系统"}
              </button>
            ))}
          </div>
        </div>

        <Separator />

        <div>
          <h2 className="text-sm font-medium text-text-primary mb-3">后端连接</h2>
          <div className="flex items-center gap-2 text-sm">
            <Badge variant="outline" className="text-positive border-positive/30">
              <span className="w-1.5 h-1.5 rounded-full bg-positive mr-1" />
              localhost:3000
            </Badge>
            <span className="text-text-tertiary text-xs">FastAPI 后端</span>
          </div>
        </div>

        <Separator />

        <div>
          <h2 className="text-sm font-medium text-text-primary mb-3">关于</h2>
          <p className="text-xs text-text-tertiary leading-relaxed">
            Quant Dashboard v2.0 — 模拟基金量化交易系统<br />
            Next.js + Tailwind CSS + Lightweight Charts + shadcn/ui<br />
            Python FastAPI 后端 + SQLite + 东方财富 API
          </p>
        </div>
      </div>
    </div>
  );
}

function Separator() {
  return <div className="border-t border-border-subtle" />;
}
