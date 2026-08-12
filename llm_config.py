# llm_config.py
import os
from langchain_openai import ChatOpenAI

_MODEL_TIERS = {
    "cheap": "deepseek/deepseek-v4-flash-0731",
    "mid": "anthropic/claude-haiku-4.5",
    "premium": "anthropic/claude-sonnet-5",
}

def get_llm(tier: str = "premium") -> ChatOpenAI:
    return ChatOpenAI(
        model=_MODEL_TIERS[tier],
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        streaming=False,  # avoid OpenRouter partial-JSON accumulator bug on structured output
    )