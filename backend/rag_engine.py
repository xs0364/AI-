"""
轻量级 RAG 引擎 — 关键词匹配 + 知识上下文注入
=============================================
设计原则：
  - 不依赖外部服务（无向量库/embedding）
  - 在 LLM 通用能力基础上补充系统特有知识
  - 匹配到的知识作为 system prompt 上下文注入，不覆盖原有能力
  - 未匹配时不注入，保持原行为
"""
import re
from typing import List, Dict, Optional

from loguru import logger
from trading_time_engine import get_knowledge_base


class SimpleRAGEngine:
    """轻量级 RAG — 无向量库，关键词匹配 + 上下文注入"""

    # ── 每章节的关键词映射 ──────────────────────────────────────
    SECTION_KEYWORDS: Dict[str, List[str]] = {
        "cutoff_1500": [
            "15:00", "三点", "收盘价", "净值", "确认", "份额",
            "计息", "T日", "T+1", "T+2", "买入", "卖出",
            "赎回", "申购", "周五", "周末", "节假", "假期",
        ],
        "redemption_fee": [
            "费率", "赎回费", "手续费", "持有天数", "持有期",
            "7天", "1年", "2年", "短线", "赎回",
        ],
        "etf_trading": [
            "ETF", "LOF", "场内", "交易时段", "集竞", "竞价",
            "T+0", "T+1", "资金到账", "卖出", "转出",
        ],
        "qdii": [
            "QDII", "海外", "美股", "港股", "纳指", "标普",
            "恒生", "时差", "到账", "确认", "T+2", "T+7",
            "T+10", "长假",
        ],
        "holidays": [
            "节假日", "长假", "春节", "国庆", "节前", "节后",
            "休市", "假期", "非交易日",
        ],
        "operation_windows": [
            "窗口", "止盈", "止损", "加仓", "减仓", "分批",
            "清仓", "仓位", "利好", "利空",
        ],
        "golden_rules": [
            "盈利", "原则", "纪律", "定投", "不要", "永远",
            "必须", "记住",
        ],
    }

    # ── 知识源加载 ──────────────────────────────────────────────
    _kb_cache: Optional[Dict] = None

    @classmethod
    def _load_knowledge_base(cls) -> Dict:
        """加载知识库（带缓存）"""
        if cls._kb_cache is None:
            cls._kb_cache = get_knowledge_base()
        return cls._kb_cache

    @classmethod
    def _get_section_title(cls, section_id: str) -> str:
        """通过 section id 查找标题"""
        kb = cls._load_knowledge_base()
        for s in kb.get("sections", []):
            if s["id"] == section_id:
                return s["title"]
        return section_id

    @classmethod
    def _flatten_section_text(cls, section: Dict) -> str:
        """将知识章节展平为可读的文本段落"""
        lines = []
        for rule in section.get("rules", []):
            title = rule.get("title", "")
            items = rule.get("items", [])
            warning = rule.get("warning", "")
            if title:
                lines.append(f"【{title}】")
            for item in items:
                lines.append(f"  • {item}")
            if warning:
                lines.append(f"  ⚠️ {warning}")
            lines.append("")
        return "\n".join(lines).strip()

    @classmethod
    def retrieve(cls, query: str, top_k: int = 3) -> List[Dict]:
        """
        根据用户问题检索最相关的知识章节

        返回:
            [{ section_id, title, text, score, matched_keywords }, ...]
        """
        if not query or not query.strip():
            return []

        query_lower = query.lower()

        # 1. 对每个章节计算关键词匹配分
        scores: List[tuple] = []
        for sec_id, keywords in cls.SECTION_KEYWORDS.items():
            matched = []
            for kw in keywords:
                if kw.lower() in query_lower:
                    matched.append(kw)
            if matched:
                # 分数 = 匹配关键词数 / 章节关键词总数（归一化）
                score = len(matched) / max(len(keywords), 1)
                scores.append((sec_id, score, matched))

        if not scores:
            return []

        # 2. 排序+取 Top-K
        scores.sort(key=lambda x: x[1], reverse=True)
        top = scores[:top_k]

        # 3. 获取章节内容
        kb = cls._load_knowledge_base()
        kb_sections = {s["id"]: s for s in kb.get("sections", [])}

        results = []
        for sec_id, score, matched in top:
            section = kb_sections.get(sec_id)
            if not section:
                continue
            text = cls._flatten_section_text(section)
            if not text:
                continue
            results.append({
                "section_id": sec_id,
                "title": section.get("title", sec_id),
                "icon": section.get("icon", ""),
                "text": text,
                "score": round(score, 4),
                "matched_keywords": matched,
            })

        return results

    @classmethod
    def format_context(cls, sections: List[Dict]) -> str:
        """将检索到的章节格式化为 context 字符串"""
        if not sections:
            return ""

        parts = [
            "📚 以下是从系统知识库中检索到的相关内容（供参考）：",
            "=" * 40,
        ]
        for i, sec in enumerate(sections, 1):
            icon = sec.get("icon", "")
            title = sec.get("title", "")
            text = sec.get("text", "")
            parts.append(f"\n{i}. {icon} {title}")
            parts.append("-" * 30)
            parts.append(text)
            # 标注匹配的关键词，便于 LLM 了解触发原因
            if sec.get("matched_keywords"):
                parts.append(f"  (匹配关键词: {'、'.join(sec['matched_keywords'])})")

        return "\n".join(parts)

    @classmethod
    def get_chat_context(cls, query: str) -> str:
        """
        对外主入口 — 根据用户问题获取注入到 system prompt 的上下文

        如果匹配到相关章节，返回格式化后的 context 字符串；
        否则返回空字符串（不注入）。
        """
        try:
            results = cls.retrieve(query, top_k=3)
            if not results:
                logger.debug(f"[RAG] 未匹配到相关知识, query='{query[:50]}'")
                return ""
            logger.info(
                f"[RAG] 匹配到 {len(results)} 个章节: "
                f"{[r['section_id'] for r in results]}"
            )
            return cls.format_context(results)
        except Exception as e:
            logger.warning(f"[RAG] 检索异常: {e}")
            return ""
