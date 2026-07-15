"use client";

import { ScrollText } from "lucide-react";

export default function LogsPage() {
  return (
    <div className="flex flex-col items-center justify-center h-96 text-text-tertiary space-y-3">
      <ScrollText className="h-12 w-12" />
      <h2 className="text-lg font-medium text-text-primary">系统日志</h2>
      <p className="text-sm">功能开发中，预计展示策略运行日志、错误追踪、操作审计</p>
    </div>
  );
}
