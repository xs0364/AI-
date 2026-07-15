"""
Chat History — 圆宝对话上下文持久化
====================================
支持多 session，每条消息存 SQLite，查询时按 session 和时间排序返回。
"""
from datetime import datetime
from typing import List, Dict, Optional

from database import get_connection

# 每次加载的最大历史消息数
MAX_HISTORY = 50
# 传给 LLM 的上限（token 控制）
MAX_LLM_HISTORY = 20


# ── 写 ───────────────────────────────────────────────────────────

def save_message(session_id: str, role: str, content: str):
    """保存一条消息到数据库"""
    conn = get_connection()
    conn.execute(
        "INSERT INTO chat_messages (session_id, role, content, created_at) VALUES (?,?,?,?)",
        (session_id, role, content, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def save_user_message(session_id: str, content: str):
    save_message(session_id, "user", content)


def save_assistant_message(session_id: str, content: str):
    save_message(session_id, "assistant", content)


# ── 读 ───────────────────────────────────────────────────────────

def get_history(
    session_id: str = "default",
    limit: int = MAX_HISTORY,
    offset: int = 0,
) -> List[Dict]:
    """获取历史消息（旧→新排序）"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, role, content, created_at FROM chat_messages "
        "WHERE session_id = ? ORDER BY id ASC LIMIT ? OFFSET ?",
        (session_id, limit, offset),
    ).fetchall()
    conn.close()
    return [
        {"id": r["id"], "role": r["role"], "content": r["content"], "createdAt": r["created_at"]}
        for r in rows
    ]


def get_llm_context(session_id: str = "default") -> List[Dict]:
    """
    获取给 LLM 的上下文（取最近 N 条，剔除过长的）
    返回 [{role, content}, ...] 格式，直接可传入 chat()
    """
    messages = get_history(session_id, limit=MAX_LLM_HISTORY)
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def get_recent_summary(session_id: str = "default", count: int = 3) -> str:
    """
    获取最近几条对话摘要（给前端展示用）
    """
    messages = get_history(session_id, limit=count)
    if not messages:
        return "暂无对话"
    lines = []
    for m in messages:
        icon = "🧑" if m["role"] == "user" else "🐾"
        content = m["content"][:60].replace("\n", " ")
        lines.append(f"{icon} {content}")
    return "\n".join(lines)


# ── 管理 ────────────────────────────────────────────────────────

def clear_history(session_id: str = "default"):
    """清空某个 session 的对话"""
    conn = get_connection()
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def delete_session(session_id: str):
    """删除一个 session 及其全部消息"""
    conn = get_connection()
    conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


def count_messages(session_id: str = "default") -> int:
    conn = get_connection()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()[0]
    conn.close()
    return cnt


def list_sessions() -> List[Dict]:
    """列出所有有历史记录的 session，包含预览文本"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            cm.session_id,
            COUNT(*) AS msg_count,
            MAX(cm.created_at) AS last_active,
            (SELECT content FROM chat_messages
             WHERE session_id = cm.session_id AND role = 'user'
             ORDER BY id ASC LIMIT 1) AS first_user_msg,
            (SELECT content FROM chat_messages
             WHERE session_id = cm.session_id
             ORDER BY id DESC LIMIT 1) AS last_content
        FROM chat_messages cm
        GROUP BY cm.session_id
        ORDER BY last_active DESC
    """).fetchall()
    conn.close()
    return [
        {
            "sessionId": r["session_id"],
            "msgCount": r["msg_count"],
            "lastActive": r["last_active"],
            "preview": _preview_text(r["last_content"] or r["first_user_msg"] or ""),
            "title": _preview_session_title(r["first_user_msg"] or "新对话"),
        }
        for r in rows
    ]


def _preview_text(text: str, max_len: int = 80) -> str:
    """截断过长文本作为预览"""
    return text[:max_len].replace("\n", " ").strip()


def _preview_session_title(text: str, max_len: int = 24) -> str:
    """截断作为会话标题（第一句）"""
    text = text.replace("\n", " ").strip()
    # 只取第一句
    for sep in ("？", "！", "。", "?", "!", ".", "，", ","):
        idx = text.find(sep)
        if idx > 0 and idx < max_len:
            text = text[:idx]
            break
    return text[:max_len].strip()
