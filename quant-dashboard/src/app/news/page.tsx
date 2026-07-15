"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import { newsApi } from "@/lib/api";
import {
  RefreshCw, TrendingUp, TrendingDown, Minus, Search,
  X, ChevronDown, ChevronRight, Filter,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { NewsItem } from "@/lib/types";

const LOCAL_KEY = "yuanbao_watch_sectors";

// 默认关注板块（取前 8 个一级板块）
const DEFAULT_SECTORS = [
  "医药", "消费", "科技", "新能源",
  "金融", "制造", "TMT", "港股/海外",
];

export default function NewsPage() {
  const [data, setData] = useState<{
    matchedNews: NewsItem[]; matchedCount: number; totalCount: number;
    allKeywords: string[]; updateTime: string;
  } | null>(null);
  const [sectors, setSectors] = useState<Record<string, string[]> | null>(null);
  const [loading, setLoading] = useState(true);

  // 关注的板块（localStorage 持久化）
  const [watchList, setWatchList] = useState<string[]>([]);
  const [showSectorPicker, setShowSectorPicker] = useState(false);
  const [parentOpen, setParentOpen] = useState<Record<string, boolean>>({});
  const [search, setSearch] = useState("");
  const [customSector, setCustomSector] = useState("");

  // ── 加载 ──────────────────────────────────────────────────
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [newsRes, sectorRes] = await Promise.all([
        newsApi.portfolio(),
        newsApi.sectors().catch(() => null),
      ]);
      setData(newsRes);
      if (sectorRes) setSectors(sectorRes.sectors);
    } catch {
      // fallback mock
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    // 恢复 localStorage 关注的板块
    try {
      const saved = localStorage.getItem(LOCAL_KEY);
      if (saved) setWatchList(JSON.parse(saved));
    } catch { /* ignore */ }
    load();
  }, [load]);

  // ── 关注板块持久化 ────────────────────────────────────────
  const toggleWatch = useCallback((name: string) => {
    setWatchList(prev => {
      const next = prev.includes(name)
        ? prev.filter(s => s !== name)
        : [...prev, name];
      localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const addCustomSector = useCallback(() => {
    const s = customSector.trim();
    if (!s || watchList.includes(s)) return;
    setWatchList(prev => {
      const next = [...prev, s];
      localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
      return next;
    });
    setCustomSector("");
  }, [customSector, watchList]);

  const resetWatch = useCallback(() => {
    setWatchList(DEFAULT_SECTORS);
    localStorage.setItem(LOCAL_KEY, JSON.stringify(DEFAULT_SECTORS));
  }, []);

  // ── 板块树展开/折叠 ───────────────────────────────────────
  const toggleParent = (name: string) => {
    setParentOpen(prev => ({ ...prev, [name]: !prev[name] }));
  };

  // ── 过滤的新闻（按 watchList 匹配板块） ────────────────────
  const filteredNews = useMemo(() => {
    if (!data?.matchedNews) return [];
    if (watchList.length === 0) return data.matchedNews;
    return data.matchedNews.filter(item => {
      const tags = (item.tags || []).concat(item.matchedKeywords || []);
      return tags.some(t => watchList.some(w => t.includes(w)));
    });
  }, [data, watchList]);

  // ── 过滤板块列表（搜索） ──────────────────────────────────
  const filteredSectors = useMemo(() => {
    if (!sectors) return {};
    if (!search.trim()) return sectors;
    const q = search.trim().toLowerCase();
    const result: Record<string, string[]> = {};
    for (const [parent, children] of Object.entries(sectors)) {
      const matchedChildren = children.filter(c => c.includes(q) || parent.includes(q));
      if (parent.includes(q) || matchedChildren.length > 0) {
        result[parent] = matchedChildren;
      }
    }
    return result;
  }, [sectors, search]);

  const sentimentIcon = (s: string) =>
    s === "positive" ? <TrendingUp className="h-3.5 w-3.5" /> :
    s === "negative" ? <TrendingDown className="h-3.5 w-3.5" /> :
    <Minus className="h-3.5 w-3.5" />;
  const sentimentColor = (s: string) =>
    s === "positive" ? "text-positive" : s === "negative" ? "text-negative" : "text-text-tertiary";

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">持仓舆情</h1>
          <p className="text-sm text-text-tertiary mt-0.5">多板块关注 · 新闻匹配持仓关键词</p>
        </div>
        <Button variant="outline" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={cn("h-3.5 w-3.5 mr-1", loading && "animate-spin")} />
          刷新
        </Button>
      </div>

      {/* 统计 */}
      {data && (
        <div className="grid grid-cols-4 gap-3">
          <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3">
            <div className="text-xs text-text-tertiary">匹配条数</div>
            <div className="text-xl font-semibold tabular-nums text-positive mt-1">{data.matchedCount}</div>
          </div>
          <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3">
            <div className="text-xs text-text-tertiary">当前筛选</div>
            <div className="text-xl font-semibold tabular-nums text-text-primary mt-1">{filteredNews.length}</div>
          </div>
          <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3">
            <div className="text-xs text-text-tertiary">关注板块</div>
            <div className="text-xl font-semibold tabular-nums text-brand-400 mt-1">{watchList.length}</div>
          </div>
          <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3">
            <div className="text-xs text-text-tertiary">匹配率</div>
            <div className="text-xl font-semibold tabular-nums text-text-primary mt-1">
              {data.totalCount ? ((data.matchedCount / data.totalCount) * 100).toFixed(1) : "0"}%
            </div>
          </div>
        </div>
      )}

      {/* 关注板块标签行 */}
      <div className="rounded-xl bg-card border border-border-subtle shadow-card p-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-medium text-text-secondary flex items-center gap-1.5">
            <Filter className="h-3.5 w-3.5" /> 关注板块
          </div>
          <button
            onClick={() => setShowSectorPicker(!showSectorPicker)}
            className="text-[11px] text-brand-400 hover:text-brand-300 transition-colors"
          >
            {showSectorPicker ? "完成" : "编辑"}
          </button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {watchList.length === 0 ? (
            <span className="text-[11px] text-text-tertiary">未关注任何板块，显示全部</span>
          ) : (
            watchList.map((s) => (
              <Badge
                key={s}
                variant="outline"
                className={cn(
                  "text-[11px] font-normal cursor-pointer transition-all",
                  showSectorPicker && "hover:border-negative/50 hover:text-negative"
                )}
                onClick={() => showSectorPicker && toggleWatch(s)}
              >
                {s}
                {showSectorPicker && <X className="h-2.5 w-2.5 ml-1" />}
              </Badge>
            ))
          )}
        </div>
      </div>

      {/* 板块选择器 */}
      {showSectorPicker && sectors && (
        <div className="rounded-xl bg-card border border-border-subtle shadow-card p-4 space-y-3">
          {/* 搜索 */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-tertiary" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索板块..."
              className="w-full h-8 pl-8 pr-3 text-xs bg-surface-1 border border-border-subtle rounded-lg outline-none focus:border-brand-400/50 text-text-primary"
            />
          </div>

          {/* 快速操作 */}
          <div className="flex gap-2 flex-wrap">
            <button onClick={resetWatch} className="text-[11px] text-text-tertiary hover:text-text-primary px-2 py-0.5 rounded bg-surface-2">
              恢复默认
            </button>
            <button onClick={() => { setWatchList(Object.keys(sectors)); localStorage.setItem(LOCAL_KEY, JSON.stringify(Object.keys(sectors))); }}
              className="text-[11px] text-text-tertiary hover:text-text-primary px-2 py-0.5 rounded bg-surface-2">
              全选一级板块
            </button>
            <div className="text-[11px] text-text-tertiary self-center">({watchList.length} 个)</div>
          </div>

          {/* 板块树 */}
          <div className="max-h-64 overflow-y-auto space-y-0.5 scrollbar-thin">
            {Object.entries(filteredSectors).map(([parent, children]) => {
              const allWatched = children.every(c => watchList.includes(c)) && watchList.includes(parent);
              const someWatched = children.some(c => watchList.includes(c));
              return (
                <div key={parent}>
                  <div
                    className="flex items-center gap-1.5 py-1 px-1 rounded hover:bg-surface-2 cursor-pointer group"
                    onClick={() => toggleParent(parent)}
                  >
                    <button className="h-4 w-4 flex items-center justify-center text-text-tertiary">
                      {parentOpen[parent] ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                    </button>
                    <label className="flex items-center gap-2 flex-1 cursor-pointer" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={allWatched}
                        ref={(el) => { if (el) el.indeterminate = someWatched && !allWatched; }}
                        onChange={() => {
                          const all = [parent, ...children];
                          const allChecked = all.every(c => watchList.includes(c));
                          if (allChecked) {
                            setWatchList(prev => {
                              const next = prev.filter(s => !all.includes(s));
                              localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
                              return next;
                            });
                          } else {
                            setWatchList(prev => {
                              const next = [...new Set([...prev, ...all])];
                              localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
                              return next;
                            });
                          }
                        }}
                        className="h-3 w-3 accent-brand-400"
                      />
                      <span className="text-xs font-medium text-text-primary">{parent}</span>
                      <span className="text-[10px] text-text-tertiary">{children.length}</span>
                    </label>
                  </div>
                  {parentOpen[parent] && children.filter(c => !search || c.includes(search)).map(child => (
                    <div key={child} className="flex items-center gap-2 pl-8 py-0.5 hover:bg-surface-2 rounded">
                      <input
                        type="checkbox"
                        checked={watchList.includes(child)}
                        onChange={() => toggleWatch(child)}
                        className="h-3 w-3 accent-brand-400"
                      />
                      <span className="text-[11px] text-text-secondary">{child}</span>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>

          {/* 自定义输入 */}
          <div className="flex items-center gap-2 pt-1 border-t border-border-subtle">
            <input
              type="text"
              value={customSector}
              onChange={(e) => setCustomSector(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addCustomSector()}
              placeholder="输入自定义板块名..."
              className="flex-1 h-7 px-2 text-[11px] bg-surface-1 border border-border-subtle rounded outline-none focus:border-brand-400/50 text-text-primary"
            />
            <button onClick={addCustomSector} disabled={!customSector.trim()}
              className="text-[11px] px-2.5 py-1 rounded bg-brand-400/20 text-brand-400 hover:bg-brand-400/30 disabled:opacity-30 transition-all">
              添加
            </button>
          </div>
        </div>
      )}

      {/* 新闻列表 */}
      <div className="space-y-2">
        {filteredNews.map((item, i) => (
          <div key={i} className={cn(
            "rounded-xl border p-4 transition-colors",
            item.sentiment === "positive" ? "bg-card border-positive/20" :
            item.sentiment === "negative" ? "bg-card border-negative/20" :
            "bg-card border-border-subtle"
          )}>
            <div className="flex items-center gap-2 mb-1.5">
              <Badge variant="outline" className={cn("text-[11px] h-5", sentimentColor(item.sentiment))}>
                {sentimentIcon(item.sentiment)}
                <span className="ml-1">{item.sentiment === "positive" ? "利好" : item.sentiment === "negative" ? "利空" : "中性"}</span>
              </Badge>
              <span className="text-[11px] text-text-tertiary">{item.source}</span>
              <span className="text-[11px] text-text-tertiary">{item.time}</span>
              {item.urgent && <Badge className="h-5 text-[10px]">紧急</Badge>}
            </div>
            {item.title && <div className="text-sm font-medium text-text-primary mb-1">{item.title}</div>}
            <div className="text-xs text-text-secondary leading-relaxed">{item.content?.slice(0, 300)}</div>
            <div className="flex flex-wrap gap-2 mt-2">
              {(item.tags?.length || item.matchedKeywords?.length) ? (
                <span className="text-[11px] text-brand-400">
                  🏷️ {(item.tags || []).concat(item.matchedKeywords || []).slice(0, 5).join("、")}
                </span>
              ) : null}
              {(item as any).actionLabel && <span className="text-[11px] text-positive">⏰ {(item as any).actionLabel}</span>}
              {(item as any).riskNote && <span className="text-[11px] text-warning">⚠️ {(item as any).riskNote}</span>}
            </div>
          </div>
        ))}
        {(!filteredNews.length && !loading) && (
          <div className="py-16 text-center text-text-tertiary text-sm">
            {watchList.length > 0 ? `在关注的板块 ${watchList.join("、")} 中未匹配到新闻` : "暂无持仓相关新闻"}
          </div>
        )}
      </div>
    </div>
  );
}
