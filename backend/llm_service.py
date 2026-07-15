"""
Unified LLM Service — 封装 NVIDIA NIM API，支持多 Key 轮询
==========================================================
所有需要大模型的地方统一走这里，不各自调 API。

设计原则：
  - Key 自动轮询（一个限流自动切下一个）
  - 超时控制（策略调用限 45s，Chat 可放宽）
  - 支持系统提示词 + 结构化 JSON 输出
  - 所有调用可追溯（loguru 打印 model + 耗时）
"""
import json
import re
import time
from typing import Optional, List, Dict, Any

from openai import OpenAI
from loguru import logger

# ── NVIDIA NIM 配置 ──────────────────────────────────────────────

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

API_KEYS = [
    "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",
    "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",
]

# ── 模型配置 ─────────────────────────────────────────────────────

MODELS = {
    # Market Intelligence Agent 用 — 中文最强，速度快
    "market_intelligence": "qwen/qwen3.5-397b-a17b",

    # AI Chat 用 — 快速对话（Qwen3.5 中文强且确认可用）
    "chat": "qwen/qwen3.5-397b-a17b",

    # Portfolio Advisor 用 — 深度分析
    "advisor": "qwen/qwen3.5-397b-a17b",
}

DEFAULT_MODEL = "qwen/qwen3.5-397b-a17b"
DEFAULT_TIMEOUT = 30  # 秒

# 策略调用超时（15:00前那10分钟不能卡）
# Market Intelligence Agent 超时（大模型冷启动慢，给足时间）
AGENT_TIMEOUT = 45


# ── Key 轮询器 ───────────────────────────────────────────────────

class KeyRotator:
    """多 API Key 自动轮询，避免单 Key 限流"""

    def __init__(self, keys: List[str]):
        self._keys = keys
        self._idx = 0

    def next(self) -> str:
        key = self._keys[self._idx]
        self._idx = (self._idx + 1) % len(self._keys)
        return key


_key_rotator = KeyRotator(API_KEYS)


# ══════════════════════════════════════════════════════════════════
# 核心调用函数
# ══════════════════════════════════════════════════════════════════

def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    timeout: int = DEFAULT_TIMEOUT,
    json_mode: bool = False,
) -> Optional[str]:
    """
    统一 LLM 调用入口

    Args:
        messages: 对话历史 [{role, content}, ...]
        model: 模型 ID，默认 DEFAULT_MODEL
        system_prompt: 系统提示词（前置）
        temperature: 0-1，量化分析用 0.1，创意用 0.7
        max_tokens: 最大输出 token
        timeout: 超时秒数
        json_mode: 是否要求 JSON 格式输出

    Returns:
        模型回复文本，失败返回 None
    """
    if model is None:
        model = DEFAULT_MODEL

    api_key = _key_rotator.next()

    # 构建完整 messages
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    # 如果要求 JSON 输出，在最后加一条指令
    request_messages = list(full_messages)
    if json_mode:
        last = request_messages[-1]
        last["content"] += (
            "\n\n你必须只输出一个合法的 JSON 对象，不要包含其他任何文字。"
        )

    # 构造请求参数
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": request_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # NVIDIA NIM 部分模型不支持 response_format，用提示词方式代替

    # 计时 + 调用
    t0 = time.time()
    try:
        client = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=api_key,
            timeout=timeout,
        )
        resp = client.chat.completions.create(**kwargs)
        elapsed = time.time() - t0

        content = resp.choices[0].message.content
        logger.info("LLM [model={} key={}... tokens={} elapsed={:.1f}s]",
                     model, api_key[:8],
                     resp.usage.total_tokens if resp.usage else "?",
                     elapsed)
        return content

    except Exception as e:
        elapsed = time.time() - t0
        logger.warning("LLM error [model={} key={}... elapsed={:.1f}s error={}]",
                        model, api_key[:8], elapsed, e)
        return None


def chat_json(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    system_prompt: Optional[str] = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[dict]:
    """
    调用 LLM 并解析 JSON 返回

    用法：
        result = chat_json(
            system_prompt="你是一个金融分析师",
            messages=[{"role": "user", "content": "分析这篇新闻"}],
        )
        if result:
            sentiment = result.get("sentiment")
    """
    content = chat(
        messages=messages,
        model=model,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        json_mode=True,
    )
    if not content:
        return None

    # 尝试解析 JSON（防止模型没按 JSON 输出）
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # 尝试从 markdown 代码块中提取
        import re
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        logger.warning("LLM 输出不是合法 JSON: {}", content[:200])
        return None


def analyze_news(news_title: str, news_content: str,
                 holdings_context: str) -> Optional[dict]:
    """
    快捷方法：分析一篇新闻对持仓的影响

    供 Market Intelligence Agent 调用

    Args:
        news_title: 新闻标题
        news_content: 新闻正文/摘要
        holdings_context: 持仓基金简要（如 "110011 易方达中小盘重仓贵州茅台9.85%..."）

    Returns:
        { sentiment, impact_score, confidence, affected_funds, reasoning, summary }
    """
    system_prompt = """你是一个专业的量化基金新闻分析助手。

你的任务：
1. 分析新闻对持仓基金的影响
2. 判断情绪倾向（正面/负面/中性）
3. 评估影响程度（0-100）
4. 给出置信度（0-100）
5. 列出受影响的基金代码
6. 给出自然语言推理过程

输出 JSON 格式，字段如下：
{
    "sentiment": "positive|negative|neutral",
    "impact_score": 0-100,
    "confidence": 0-100,
    "affected_funds": ["基金代码1", "基金代码2"],
    "summary": "一句话总结",
    "reasoning": "推理过程，分点说明"
}"""

    user_msg = f"""【新闻标题】
{news_title}

【新闻内容】
{news_content}

【当前持仓】
{holdings_context}

请分析这条新闻对持仓基金的影响。"""

    return chat_json(
        messages=[{"role": "user", "content": user_msg}],
        model=MODELS["market_intelligence"],
        system_prompt=system_prompt,
        temperature=0.1,
        timeout=AGENT_TIMEOUT,
    )


# ── 快捷测试 ─────────────────────────────────────────────────────

if __name__ == "__main__":
    from loguru import logger
    result = analyze_news(
        "第七批药品集采启动",
        "第七批国家药品集采平均降价60%，创新药企业豁免。",
        "005827 中欧医疗健康混合C 重仓恒瑞医药9.85% 药明康德7.23%",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
