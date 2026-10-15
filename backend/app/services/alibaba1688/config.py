"""1688 CLI 只读货源配置。不包含任何账号凭证：登录态只存在于 CLI 自己的浏览器 Profile 中。"""
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Alibaba1688Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', case_sensitive=False, env_prefix='ALIBABA1688_')

    # local：后端进程直接调用本机 CLI；remote：后端在容器内，通过宿主机 CLI Adapter 调用
    transport: str = Field(default='local', pattern='^(local|remote)$')
    # 可指向 1688 / 1688.cmd 或 node_modules/1688-cli/dist/cli.js；留空时自动查找
    cli_path: str = ''
    node_path: str = ''
    # 透传给 CLI 的 BB1688_HOME；留空使用 CLI 默认的 %USERPROFILE%\.1688
    cli_home: str = ''
    profile: str = Field(default='default', pattern=r'^[A-Za-z0-9_-]{1,40}$')

    search_timeout: int = Field(default=90, ge=10, le=300)
    detail_timeout: int = Field(default=90, ge=10, le=300)
    status_timeout: int = Field(default=30, ge=5, le=120)
    # CLI 同一 Profile 同一时刻只允许一个命令；后端串行化并限制排队等待
    max_concurrency: int = Field(default=1, ge=1, le=3)
    queue_wait: int = Field(default=20, ge=1, le=120)
    min_interval: float = Field(default=1.5, ge=0, le=60)
    max_results: int = Field(default=20, ge=1, le=40)
    search_cache_ttl: int = Field(default=600, ge=0, le=86400)
    detail_cache_ttl: int = Field(default=1800, ge=0, le=86400)
    status_cache_ttl: int = Field(default=15, ge=0, le=600)
    image_max_bytes: int = Field(default=5 * 1024 * 1024, ge=10 * 1024, le=20 * 1024 * 1024)

    # remote 模式：仅允许本机/内网受信地址上的 Adapter，使用共享令牌鉴权
    adapter_url: str = 'http://host.docker.internal:8765'
    adapter_token: SecretStr = SecretStr('')
    adapter_bind: str = '127.0.0.1'
    adapter_port: int = Field(default=8765, ge=1024, le=65535)
