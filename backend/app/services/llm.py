"""LLM 接入层（OpenAI 兼容协议）。

开发期接 DeepSeek 公网 API；私有化部署时仅需修改 .env 的
LLM_BASE_URL / LLM_API_KEY / LLM_MODEL，代码零改动。
"""
import json
import re

import httpx

from app.core.config import settings


class LLMError(Exception):
    """LLM 调用失败（网络异常 / 非 200 / 返回结构异常 / JSON 解析失败）。"""


def chat(messages: list[dict], temperature: float = 0.2, max_tokens: int = 4096,
         json_mode: bool = False) -> str:
    """调用 Chat Completions，返回文本内容。失败抛 LLMError。"""
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        resp = httpx.post(
            f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            json=payload,
            timeout=120,
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"LLM 请求失败：{exc}") from exc

    if resp.status_code != 200:
        raise LLMError(f"LLM 返回 {resp.status_code}：{resp.text[:200]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"LLM 返回结构异常：{str(data)[:200]}") from exc


def chat_json(messages: list[dict], temperature: float = 0.1, max_tokens: int = 4096):
    """调用并要求返回 JSON（json_object 模式 + 容错解析）。"""
    content = chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
    return parse_json(content)


def parse_json(content: str):
    """从 LLM 输出中容错提取 JSON（兼容 ```json 包裹与前后杂文本）。"""
    text = content.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        raise LLMError(f"LLM 输出不含 JSON：{content[:200]}")
    for end in range(len(text), start, -1):
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            continue
    raise LLMError(f"LLM 输出 JSON 解析失败：{content[:200]}")
