"""Sourcing settings never inherit legacy mock switches."""
from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SourcingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', case_sensitive=False)
    bailian_api_key: SecretStr = Field(default=SecretStr(''), validation_alias=AliasChoices('BAILIAN_API_KEY', 'DASHSCOPE_API_KEY'))
    bailian_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    bailian_vision_model: str = 'qwen3-vl-flash'
    deepseek_api_key: SecretStr = SecretStr('')
    deepseek_base_url: str = 'https://api.deepseek.com/v1'
    deepseek_model: str = 'deepseek-chat'
    sourcing_model_timeout: int = Field(default=90, ge=5, le=180)
    sourcing_worker_concurrency: int = Field(default=2, ge=1, le=10)
    sourcing_max_attempts: int = Field(default=3, ge=1, le=5)
    miaoshou_app_key: SecretStr = SecretStr('')
    miaoshou_app_secret: SecretStr = SecretStr('')
    miaoshou_timeout: int = Field(default=30, ge=5, le=120)
    miaoshou_request_interval: float = Field(default=1.0, ge=0.1, le=60)
    miaoshou_poll_interval: int = Field(default=5, ge=1, le=300)
    miaoshou_max_polls: int = Field(default=8, ge=1, le=30)

    @model_validator(mode='before')
    @classmethod
    def fallback_dashscope_key(cls, values):
        if isinstance(values, dict) and not values.get('BAILIAN_API_KEY') and values.get('DASHSCOPE_API_KEY'):
            values['BAILIAN_API_KEY'] = values['DASHSCOPE_API_KEY']
        return values

    def analysis_config(self):
        return {'text_provider': 'deepseek', 'text_model': self.deepseek_model,
                'text_base_url': self.deepseek_base_url,
                'text_enabled': bool(self.deepseek_api_key.get_secret_value()),
                'prompt_version': 'market-evidence-v2', 'schema_version': '2'}
