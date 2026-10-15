"""Agent configuration."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    """Agent service configuration."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    backend_api_url: str = "http://localhost:8000/api/v1"
    # 调用后端受保护接口（1688 货源工具）所需的 JWT；放在 agent/.env，不写入代码库
    backend_api_token: str = ""
    sourcing_tool_timeout: float = 150.0
    redis_url: str = "redis://localhost:6379/1"
    debug: bool = True

    # LLM Configuration
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_temperature: float = 0.7

    # TikTok Shop API
    tiktok_app_key: str = ""
    tiktok_app_secret: str = ""
    tiktok_sandbox: bool = True
    tiktok_shop_mock_mode: bool = True

    # 1688：货源工具经后端调用 1688 CLI（只读），不再使用 mock 数据
    alibaba_app_key: str = ""
    alibaba_app_secret: str = ""
    alibaba_1688_mock_mode: bool = True  # 保留旧字段兼容配置；1688 货源工具已不读取


agent_settings = AgentSettings()
