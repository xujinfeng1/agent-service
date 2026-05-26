"""配置管理"""
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # LLM 配置（兼容 OpenAI API 格式）
    api_key: str = os.getenv("OPENAI_API_KEY", "sk-xxx")
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model: str = os.getenv("OPENAI_MODEL", "deepseek-v4-flash")

    # 服务配置
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8100"))
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Agent 配置
    max_tool_rounds: int = 10
    max_history_tokens: int = 4000  # 历史消息最大 token 数（中文约 1char≈1.5token）
    max_tools_per_request: int = 8  # 单次请求最多发送的工具数


config = Config()
