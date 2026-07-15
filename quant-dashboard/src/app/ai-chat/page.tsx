"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { agentApi } from "@/lib/api";
import type { ChatMessage, ChatSession } from "@/lib/api";
import {
  Send, Loader2, User, AlertTriangle, Trash2, Plus, MessageSquare,
  ChevronLeft, ChevronRight, X, Edit3, Check, MoreHorizontal,
} from "lucide-react";
import Image from "next/image";
import ReactMarkdown from "react-markdown";

const DEFAULT_SESSION_ID = "default";
const LOCAL_SESSION_KEY = "yuanbao_active_session";

export default function AIChatPage() {
  // ── 状态 ────────────────────────────────────────────────────
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [error, setError] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeSession, setActiveSession] = useState(DEFAULT_SESSION_ID);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [contextMenu, setContextMenu] = useState<{ id: string; y: number } | null>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const renameRef = useRef<HTMLInputElement>(null);

  // ── 加载 session 列表 ──────────────────────────────────────
  const loadSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const res = await agentApi.sessions();
      setSessions(res.sessions || []);
    } catch {
      // 安静失败，不影响主界面
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  // ── 切换/加载 session ──────────────────────────────────────
  const switchSession = useCallback(async (sessionId: string) => {
    if (sessionId === activeSession && messages.length > 0) return;
    setActiveSession(sessionId);
    localStorage.setItem(LOCAL_SESSION_KEY, sessionId);
    setContextMenu(null);
    setError("");

    setHistoryLoading(true);
    try {
      const res = await agentApi.chatHistory(sessionId, 50);
      if (res.messages?.length) {
        setMessages(res.messages.map(m => ({ role: m.role, content: m.content, id: m.id })));
      } else {
        setMessages([{
          role: "assistant" as const,
          content: sessionId === DEFAULT_SESSION_ID
            ? "🐾 你好呀，我是圆宝！你的量化交易 AI 小助手。有什么可以帮你的？"
            : "🐾 新的对话，开始吧！",
        }]);
      }
    } catch {
      setMessages([{ role: "assistant" as const, content: "🐾 你好呀，我是圆宝！" }]);
    } finally {
      setHistoryLoading(false);
    }
  }, [activeSession, messages.length]);

  // ── 初始化：恢复上次 session / 加载列表 ────────────────────
  useEffect(() => {
    const saved = localStorage.getItem(LOCAL_SESSION_KEY);
    const initial = saved && saved !== DEFAULT_SESSION_ID ? saved : DEFAULT_SESSION_ID;
    setActiveSession(initial);
    switchSession(initial);
    loadSessions();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── 新消息时滚到底部 ──────────────────────────────────────
  useEffect(() => {
    if (!historyLoading) {
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }, [messages, historyLoading]);

  // ── 自动刷新 session 列表（切换后或对话后） ────────────────
  const refreshSessions = useCallback(() => {
    // 延迟一点等后端写入完成
    setTimeout(() => loadSessions(), 300);
  }, [loadSessions]);

  // ── 新建 session ──────────────────────────────────────────
  const newSession = useCallback(async () => {
    const newId = "session_" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    await switchSession(newId);
    // 立即在 session 列表中注册（往 greet 写一条，后端才有记录）
    setMessages([{ role: "assistant", content: "🐾 新的对话，开始吧！" }]);
    refreshSessions();
  }, [switchSession, refreshSessions]);

  // ── 发送消息 ──────────────────────────────────────────────
  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setError("");

    setMessages(prev => [...prev, { role: "user", content: text }]);
    setLoading(true);

    try {
      const res = await agentApi.chat(text, activeSession);
      if (res.status === "ok") {
        setMessages(prev => [...prev, { role: "assistant", content: res.reply }]);
        refreshSessions();
      } else {
        setError(res.reply || "圆宝暂时开小差了");
      }
    } catch (e: any) {
      setError(e.message || "请求失败");
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  }, [input, loading, activeSession, refreshSessions]);

  // ── 清空当前对话 ──────────────────────────────────────────
  const clearHistory = async () => {
    if (!confirm("确定清空当前对话记录？")) return;
    try {
      await agentApi.chatClear(activeSession);
      setMessages([{ role: "assistant", content: "🐾 记忆已清空，重新开始吧！" }]);
      refreshSessions();
    } catch {
      setError("清空失败");
    }
  };

  // ── 删除 session ──────────────────────────────────────────
  const deleteSession = async (sessionId: string) => {
    if (sessionId === DEFAULT_SESSION_ID) {
      // 默认 session：清空而非删除
      if (!confirm("确定清空默认对话？")) return;
      try {
        await agentApi.chatClear(DEFAULT_SESSION_ID);
        setMessages([{ role: "assistant", content: "🐾 默认对话已清空，重新开始吧！" }]);
        refreshSessions();
      } catch { setError("清空失败"); }
      return;
    }
    if (!confirm("确定删除此对话？删除后无法恢复。")) return;
    try {
      await agentApi.sessionDelete(sessionId);
      // 如果删的是当前 session，切回 default
      if (activeSession === sessionId) {
        await switchSession(DEFAULT_SESSION_ID);
      }
      refreshSessions();
    } catch {
      setError("删除失败");
    }
  };

  // ── 重命名 session ────────────────────────────────────────
  const startRename = (sessionId: string, currentTitle: string) => {
    setRenamingId(sessionId);
    setRenameValue(currentTitle || "新对话");
    setTimeout(() => renameRef.current?.select(), 50);
  };

  const confirmRename = () => {
    const title = renameValue.trim() || "新对话";
    // 将标题存到 localStorage（简单的客户端方案）
    localStorage.setItem(`session_title_${renamingId}`, title);
    setRenamingId(null);
    // 更新本地 session 列表显示
    setSessions(prev => prev.map(s =>
      s.sessionId === renamingId ? { ...s, title } : s
    ));
  };

  const getSessionTitle = useCallback((s: ChatSession) => {
    // localStorage 标题优先（仅在客户端）
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem(`session_title_${s.sessionId}`);
      if (saved) return saved;
    }
    return s.title || "新对话";
  }, []);

  const getSessionPreview = useCallback((s: ChatSession) => {
    if (s.preview) return s.preview;
    return s.msgCount > 0 ? `${s.msgCount} 条消息` : "空对话";
  }, []);

  // ── 计算未读/活跃提示 ─────────────────────────────────────
  const formatTime = (iso: string) => {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    if (diffMs < 60000) return "刚刚";
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}分钟前`;
    if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}小时前`;
    return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric" });
  };

  // ── 渲染 ──────────────────────────────────────────────────
  return (
    <div className="flex h-[calc(100vh-6rem)] gap-0 relative">
      {/* ── 侧边栏 ────────────────────────────────────────────── */}
      <div className={`
        flex flex-col shrink-0 border-r border-border-subtle bg-card/50 transition-all duration-200 overflow-hidden
        ${sidebarOpen ? "w-60" : "w-0 border-0"}
      `}>
        <div className="shrink-0 flex items-center justify-between px-3 h-11 min-w-0">
          {sidebarOpen && (
            <>
              <span className="text-xs font-medium text-text-secondary tracking-wide">对话列表</span>
              <button
                onClick={newSession}
                className="h-6 w-6 rounded flex items-center justify-center hover:bg-surface-2 text-text-tertiary hover:text-text-primary transition-colors"
                title="新建对话"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>

        {sidebarOpen && (
          <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5 scrollbar-thin">
            {sessions.length === 0 && !sessionsLoading && (
              <div className="text-xs text-text-tertiary text-center py-6">暂无对话</div>
            )}
            {sessions.map((s) => {
              const isActive = s.sessionId === activeSession;
              const title = getSessionTitle(s);
              const isRenaming = renamingId === s.sessionId;
              return (
                <div
                  key={s.sessionId}
                  className={`group relative flex items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer text-sm transition-colors ${
                    isActive
                      ? "bg-brand-400/15 text-text-primary"
                      : "text-text-secondary hover:bg-surface-2"
                  }`}
                  onClick={() => !isRenaming && switchSession(s.sessionId)}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setContextMenu({ id: s.sessionId, y: e.clientY });
                  }}
                >
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 opacity-60" />
                  <div className="flex-1 min-w-0">
                    {isRenaming ? (
                      <input
                        ref={renameRef}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") confirmRename();
                          if (e.key === "Escape") setRenamingId(null);
                        }}
                        onBlur={confirmRename}
                        className="w-full text-xs bg-surface-1 border border-border-subtle rounded px-1 py-0.5 outline-none focus:border-brand-400/50"
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                      />
                    ) : (
                      <>
                        <div className="text-xs truncate leading-tight">{title}</div>
                        <div className="text-[10px] text-text-tertiary truncate leading-tight mt-0.5">
                          {getSessionPreview(s)}
                        </div>
                      </>
                    )}
                  </div>
                  {!isRenaming && (
                    <button
                      onClick={(e) => { e.stopPropagation(); startRename(s.sessionId, title); }}
                      className="h-5 w-5 rounded flex items-center justify-center opacity-0 group-hover:opacity-100 hover:bg-surface-1 text-text-tertiary hover:text-text-primary transition-all"
                      title="重命名"
                    >
                      <Edit3 className="h-3 w-3" />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── 切换侧边栏按钮 ──────────────────────────────────── */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="absolute left-0 top-1 z-10 h-7 w-5 rounded-r-md bg-card border border-border-subtle border-l-0 flex items-center justify-center text-text-tertiary hover:text-text-primary transition-colors cursor-pointer"
        style={{ left: sidebarOpen ? "15rem" : "0" }}
        title={sidebarOpen ? "收起" : "展开对话列表"}
      >
        {sidebarOpen
          ? <ChevronLeft className="h-3 w-3" />
          : <ChevronRight className="h-3 w-3" />}
      </button>

      {/* ── 右键菜单 ────────────────────────────────────────── */}
      {contextMenu && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setContextMenu(null)} />
          <div
            className="fixed z-50 bg-card border border-border-subtle rounded-lg shadow-lg py-1 min-w-[120px]"
            style={{ top: contextMenu.y, left: 16 }}
          >
            <button
              className="w-full px-3 py-1.5 text-xs text-text-secondary hover:bg-surface-2 text-left flex items-center gap-2"
              onClick={() => {
                const found = sessions.find(s => s.sessionId === contextMenu.id);
                const curTitle = found ? getSessionTitle(found) : "新对话";
                startRename(contextMenu.id, curTitle);
                setContextMenu(null);
              }}
            >
              <Edit3 className="h-3 w-3" /> 重命名
            </button>
            <button
              className="w-full px-3 py-1.5 text-xs text-negative hover:bg-negative/10 text-left flex items-center gap-2"
              onClick={() => { deleteSession(contextMenu.id); setContextMenu(null); }}
            >
              <Trash2 className="h-3 w-3" /> 删除
            </button>
          </div>
        </>
      )}

      {/* ── 主聊天区 ────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 px-4">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-full overflow-hidden border-2 border-brand-400/30 shrink-0">
              <Image src="/yuanbao.png" alt="圆宝" width={36} height={36}
                className="object-cover w-full h-full" />
            </div>
            <div className="min-w-0">
              <h1 className="text-lg font-semibold text-text-primary truncate">
                {getSessionTitle(sessions.find(s => s.sessionId === activeSession) ?? { sessionId: activeSession, msgCount: 0, lastActive: "", title: "圆宝", preview: "" }) || "圆宝"}
              </h1>
              <p className="text-xs text-text-tertiary">
                🐾 {messages.length} 条对话 · {activeSession === DEFAULT_SESSION_ID ? "默认对话" : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={newSession}
              className="h-7 px-2 rounded-md text-xs text-text-tertiary hover:text-text-primary hover:bg-surface-2 transition-colors flex items-center gap-1"
              title="新建对话"
            >
              <Plus className="h-3 w-3" />
              新建
            </button>
            <button
              onClick={clearHistory}
              className="h-7 px-2 rounded-md text-xs text-text-tertiary hover:text-negative hover:bg-negative/10 transition-colors flex items-center gap-1"
              title="清空当前对话"
            >
              <Trash2 className="h-3 w-3" />
              清空
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto space-y-3 pr-1 scrollbar-thin">
          {historyLoading ? (
            <div className="flex items-center justify-center h-32 text-text-tertiary">
              <Loader2 className="h-5 w-5 animate-spin mr-2" />
              加载记忆中...
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={msg.id || i} className={`flex gap-2.5 ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                {msg.role === "assistant" && (
                  <div className="w-8 h-8 rounded-full overflow-hidden shrink-0 border-2 border-brand-400/30 flex items-center justify-center bg-card">
                    <Image src="/yuanbao.png" alt="圆宝" width={32} height={32}
                      className="object-cover w-full h-full" />
                  </div>
                )}
                <div className={`max-w-[75%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-brand-400/20 text-text-primary"
                    : "bg-surface-2 text-text-primary"
                }`}>
                  <ReactMarkdown
                    components={{
                      strong: ({ children }) => <span className="font-semibold text-text-primary">{children}</span>,
                      p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                </div>
                {msg.role === "user" && (
                  <div className="w-7 h-7 rounded-lg bg-surface-2 flex items-center justify-center shrink-0">
                    <User className="h-4 w-4 text-text-secondary" />
                  </div>
                )}
              </div>
            ))
          )}

          {loading && (
            <div className="flex gap-2.5">
              <div className="w-8 h-8 rounded-full overflow-hidden shrink-0 border-2 border-brand-400/30 flex items-center justify-center bg-card">
                <Image src="/yuanbao.png" alt="圆宝" width={32} height={32}
                  className="object-cover w-full h-full opacity-70" />
              </div>
              <div className="bg-surface-2 rounded-xl px-3.5 py-2.5">
                <Loader2 className="h-4 w-4 animate-spin text-text-tertiary" />
              </div>
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 text-xs text-negative bg-negative/10 rounded-lg px-3 py-2">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              {error}
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="flex items-center gap-2 pt-3 border-t border-border-subtle mt-3 shrink-0">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            placeholder="问关于持仓、策略、市场的问题..."
            className="flex-1 h-9 px-3 rounded-lg bg-surface-2 border border-border-subtle text-sm text-text-primary placeholder:text-text-tertiary outline-none focus:border-brand-400/50 transition-colors"
            disabled={loading || historyLoading}
          />
          <button
            onClick={send}
            disabled={loading || historyLoading || !input.trim()}
            className="h-9 w-9 rounded-lg bg-brand-400/20 flex items-center justify-center hover:bg-brand-400/30 disabled:opacity-30 transition-colors"
          >
            {loading
              ? <Loader2 className="h-4 w-4 animate-spin text-brand-400" />
              : <Send className="h-4 w-4 text-brand-400" />}
          </button>
        </div>

        {/* Quick prompts */}
        {!historyLoading && (
          <div className="flex gap-2 mt-2 overflow-x-auto pb-1 shrink-0">
            {["今天应该买吗", "分析我的持仓", "帮我解释趋势Agent的决策", "今天交易时间状态"].map((q) => (
              <button
                key={q}
                onClick={() => setInput(q)}
                className="shrink-0 text-[11px] px-2.5 py-1 rounded-full bg-surface-2 text-text-tertiary hover:text-text-primary hover:bg-surface-1 transition-colors border border-border-subtle"
              >
                {q}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
