"""DeepSeek LLM client wrapper using OpenAI-compatible API."""

import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

# Load .env from project root
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        if not api_key:
            raise ValueError("未找到 API Key，请在 .env 文件中设置 DEEPSEEK_API_KEY")
        _client = OpenAI(api_key=api_key, base_url=api_base, timeout=120.0)
    return _client


def chat_completion(
    messages: list[dict],
    model: str = "deepseek-chat",
    max_tokens: int = 4096,
    temperature: float = 0.1,
    json_mode: bool = False,
    retries: int = 3,
) -> str:
    """Send a chat completion request and return the text response."""
    client = get_client()
    kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(**kwargs)
            text = resp.choices[0].message.content or ""
            return text.replace("\r\n", "\n").replace("\r", "\n")
        except Exception as e:
            logger.warning(f"LLM 请求失败 (尝试 {attempt + 1}/{retries}): {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise


def parse_json_response(text: str) -> dict | list:
    """Extract JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    # Remove markdown code block if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return json.loads(text)
