"use client";

import { useState, useEffect, useCallback } from "react";
import { reportApi } from "@/lib/api";
import type { DailyReport } from "@/lib/api";
import {
  FileText, Loader2, ChevronRight, RefreshCw,
  Sparkles, Calendar, Clock, AlertCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReactElement } from "react";

export default function ReportsPage() {
  const [reports, setReports] = useState<DailyReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<DailyReport | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genResult, setGenResult] = useState("");

  // ── 加载报告列表 ──────────────────────────────────────────
  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const res = await reportApi.list(20);
      setReports(res.reports || []);
      // 自动选中最新报告
      if (res.reports?.length && !selected) {
        setSelected(res.reports[0]);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadList(); }, [loadList]);

  // ── 选中报告 ──────────────────────────────────────────────
  const selectReport = useCallback(async (r: DailyReport) => {
    setSelected(r);
    // 如果只有摘要没有完整内容，加载完整内容
    if (!r.content || r.content.length < 50) {
      setContentLoading(true);
      try {
        const detail = await reportApi.detail(r.id);
        setSelected(detail);
      } catch { /* ignore */ }
      finally { setContentLoading(false); }
    }
  }, []);

  // ── 手动生成 ──────────────────────────────────────────────
  const generateNow = useCallback(async () => {
    setGenerating(true);
    setGenResult("");
    try {
      const res = await reportApi.generate();
      if (res.status === "ok") {
        setGenResult("✅ 报告已生成");
        loadList();
      } else {
        setGenResult(res.message || "⏭ 跳过");
      }
    } catch (e: any) {
      setGenResult("❌ 生成失败: " + (e.message || ""));
    } finally { setGenerating(false); }
  }, [loadList]);

  // ── 解析 Markdown 渲染（简单行级渲染） ────────────────────
  function renderMarkdown(text: string) {
    if (!text) return <p className="text-text-tertiary py-8 text-center">暂无内容</p>;

    const lines = text.split("\n");
    const elements: (ReactElement | null)[] = [];
    let inTable = false;
    let tableRows: string[] = [];
    let key = 0;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      // 表格行检测
      if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
        inTable = true;
        tableRows.push(trimmed);
        continue;
      } else if (inTable) {
        // 结束表格
        elements.push(renderTable(tableRows, key++));
        tableRows = [];
        inTable = false;
      }

      // 空行
      if (!trimmed) {
        elements.push(<div key={key++} className="h-2" />);
        continue;
      }

      // 分隔线
      if (trimmed.startsWith("---") || trimmed.startsWith("***")) {
        elements.push(<hr key={key++} className="border-border-subtle my-2" />);
        continue;
      }

      // 标题
      if (trimmed.startsWith("## ")) {
        elements.push(<h3 key={key++} className="text-sm font-semibold text-text-primary mt-4 mb-1.5">{renderInline(trimmed.slice(3))}</h3>);
        continue;
      }
      if (trimmed.startsWith("# ")) {
        elements.push(<h2 key={key++} className="text-base font-bold text-text-primary mt-4 mb-2">{renderInline(trimmed.slice(2))}</h2>);
        continue;
      }

      // 列表项
      if (trimmed.startsWith("- ") || trimmed.startsWith("* ")) {
        elements.push(
          <div key={key++} className="flex items-start gap-1.5 text-xs text-text-secondary py-0.5">
            <span className="text-text-tertiary mt-0.5 shrink-0">•</span>
            <span>{renderInline(trimmed.slice(2))}</span>
          </div>
        );
        continue;
      }

      // 数字列表
      const numMatch = trimmed.match(/^\d+\.\s(.+)/);
      if (numMatch) {
        elements.push(
          <div key={key++} className="flex items-start gap-1.5 text-xs text-text-secondary py-0.5">
            <span className="text-text-tertiary shrink-0 font-mono">{key - elements.filter(e => e?.type === 'div').length}.</span>
            <span>{renderInline(numMatch[1])}</span>
          </div>
        );
        continue;
      }

      // 普通段落
      elements.push(<p key={key++} className="text-xs text-text-secondary leading-relaxed py-0.5">{renderInline(trimmed)}</p>);
    }

    // 处理最后未关闭的表格
    if (inTable && tableRows.length) {
      elements.push(renderTable(tableRows, key++));
    }

    return <div>{elements}</div>;
  }

  function renderInline(text: string) {
    // 加粗 **text**
    const parts = text.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, i) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={i} className="font-semibold text-text-primary">{part.slice(2, -2)}</strong>;
      }
      return part;
    });
  }

  function renderTable(rows: string[], idx: number): ReactElement | null {
    // 分离表头和分隔行
    const dataRows = rows.filter(r => !r.match(/^[\s|:-]+$/));
    if (dataRows.length < 2) return null;

    const headers = dataRows[0].split("|").filter(Boolean).map(h => h.trim());
    const bodyRows = dataRows.slice(1);

    return (
      <div key={idx} className="overflow-x-auto my-2">
        <table className="w-full text-[11px] border-collapse">
          <thead>
            <tr>
              {headers.map((h, i) => (
                <th key={i} className="text-left text-text-tertiary font-medium px-2 py-1 border-b border-border-subtle bg-surface-1 first:rounded-l-md last:rounded-r-md">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {bodyRows.map((row, ri) => {
              const cells = row.split("|").filter(Boolean).map(c => c.trim());
              return (
                <tr key={ri}>
                  {cells.map((c, ci) => (
                    <td key={ci} className="px-2 py-1 border-b border-border-subtle/50 text-text-secondary tabular-nums">
                      {c}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="flex gap-4 h-[calc(100vh-6rem)]">
      {/* ═══ 报告列表（左） ═══ */}
      <div className="w-64 shrink-0 space-y-4 overflow-y-auto pr-2 scrollbar-thin">
        <div className="flex items-center justify-between">
          <h1 className="text-lg font-semibold text-text-primary tracking-tight">量化日报</h1>
          <button onClick={generateNow} disabled={generating}
            className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg bg-brand-400/20 text-brand-400 hover:bg-brand-400/30 disabled:opacity-50 transition-all">
            {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
            生成
          </button>
        </div>

        {genResult && (
          <div className="text-[10px] text-text-tertiary bg-surface-2 rounded px-2 py-1">{genResult}</div>
        )}

        {loading ? (
          <div className="flex items-center justify-center h-24 text-text-tertiary">
            <Loader2 className="h-4 w-4 animate-spin mr-2" />加载中…
          </div>
        ) : reports.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-text-tertiary space-y-2">
            <FileText className="h-8 w-8" />
            <p className="text-xs">暂无报告</p>
            <p className="text-[10px] text-center">点击"生成"创建今日复盘报告</p>
          </div>
        ) : (
          <div className="space-y-1">
            {reports.map((r) => (
              <button key={r.id} onClick={() => selectReport(r)}
                className={cn(
                  "w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-left transition-all text-xs",
                  selected?.id === r.id
                    ? "bg-brand-400/15 text-text-primary border border-brand-400/20"
                    : "text-text-secondary hover:bg-surface-2 border border-transparent"
                )}>
                <Calendar className="h-3.5 w-3.5 shrink-0 text-text-tertiary" />
                <span className="flex-1 font-mono">{r.date}</span>
                <ChevronRight className={cn("h-3 w-3 shrink-0 transition-all",
                  selected?.id === r.id ? "text-brand-400 rotate-90" : "text-text-tertiary opacity-0 group-hover:opacity-100")} />
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ═══ 报告内容（右） ═══ */}
      <div className="flex-1 min-w-0 overflow-y-auto scrollbar-thin">
        {contentLoading ? (
          <div className="flex items-center justify-center h-64 text-text-tertiary">
            <Loader2 className="h-5 w-5 animate-spin mr-2" />加载报告…
          </div>
        ) : selected ? (
          <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4 sm:p-6 max-w-3xl">
            {/* 报告元信息 */}
            <div className="flex items-center gap-3 mb-4 pb-3 border-b border-border-subtle">
              <div className="flex items-center gap-1.5 text-xs text-text-tertiary">
                <Calendar className="h-3.5 w-3.5" />
                <span className="font-mono">{selected.date}</span>
              </div>
              <div className="flex items-center gap-1.5 text-xs text-text-tertiary">
                <Clock className="h-3.5 w-3.5" />
                <span className="font-mono">{selected.created_at?.slice(11, 16) || "-"}</span>
              </div>
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-brand-400/10 text-brand-400 ml-auto">
                {selected.report_type}
              </span>
            </div>
            {/* Markdown 正文 */}
            {renderMarkdown(selected.content)}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-96 text-text-tertiary space-y-3">
            <FileText className="h-12 w-12" />
            <h2 className="text-base font-medium text-text-primary">选择一份报告</h2>
            <p className="text-xs">从左侧列表选择，或生成新的复盘日报</p>
          </div>
        )}
      </div>
    </div>
  );
}
