"""应用配置 — 通过环境变量和 .env 文件加载 Ryu、LLM 及系统运行参数"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """应用全局配置，字段自动从环境变量或 .env 文件加载"""
    RYU_REST_URL: str = "http://127.0.0.1:8080"
    LLM_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "Qwen/Qwen2.5-72B-Instruct"
    POLL_INTERVAL: int = 5
    MAX_LLM_RETRY: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
