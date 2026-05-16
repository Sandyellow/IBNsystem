from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # VM Agent
    VM_AGENT_URL: str = "http://192.168.114.130:5000"
    RYU_REST_URL: str = "http://192.168.114.130:8080"

    # LLM 配置 (OpenAI 兼容格式)
    LLM_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "Qwen/Qwen2.5-72B-Instruct"

    # 系统配置
    POLL_INTERVAL: int = 5       # 轮询网络状态间隔(秒)
    MAX_LLM_RETRY: int = 3       # LLM 输出校验最大重试次数

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
