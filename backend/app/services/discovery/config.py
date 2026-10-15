"""Discovery settings. Independent from legacy mock switches and from Miaoshou settings."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DiscoverySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', case_sensitive=False)

    # 搜索结果中的标题只作临时预览，到期清除；商品资料以妙手采集为准。
    discovery_snippet_retention_hours: int = Field(default=24, ge=1, le=168)

    # Per-task hard limits. Budgets are reserved in PostgreSQL BEFORE any external call.
    discovery_max_results: int = Field(default=30, ge=1, le=30)
    discovery_max_keywords: int = Field(default=6, ge=1, le=10)
    discovery_pages_per_keyword: int = Field(default=1, ge=1, le=3)
    discovery_max_search_calls: int = Field(default=12, ge=1, le=30)
    discovery_max_model_calls: int = Field(default=20, ge=2, le=60)
    discovery_max_collect: int = Field(default=5, ge=1, le=5)
    # Automatic external collection stays off until a human-confirmed collection passed acceptance.
    discovery_auto_collect_enabled: bool = False
    discovery_poll_interval: int = Field(default=5, ge=1, le=120)
    # Waiting for Miaoshou/AI sub-tasks; afterwards the task finishes as partial_failed (only queries, never resubmits).
    discovery_wait_timeout_minutes: int = Field(default=30, ge=5, le=240)

    def limits(self) -> dict:
        return {'max_results': self.discovery_max_results, 'max_keywords': self.discovery_max_keywords,
                'pages_per_keyword': self.discovery_pages_per_keyword,
                'max_search_calls': self.discovery_max_search_calls, 'max_model_calls': self.discovery_max_model_calls,
                'max_collect': self.discovery_max_collect, 'auto_collect_enabled': False}
