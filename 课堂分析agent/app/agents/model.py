"""OpenAI Agents SDK 的模型配置。"""

from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from app.core.config import settings


deepseek_client = AsyncOpenAI(
    api_key=settings.llm.api_key,
    base_url=settings.llm.base_url,
    timeout=settings.llm.timeout_seconds,
    max_retries=settings.llm.max_retries,
)

deepseek_model = OpenAIChatCompletionsModel(
    model=settings.llm.model,
    openai_client=deepseek_client,
)
