import re
from pydantic import Field, field_validator
from app.services.sourcing_config import SourcingSettings

HOSTNAME = re.compile(r'(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}')


class WorkbenchSettings(SourcingSettings):
    workbench_text_model: str = 'qwen3.5-plus'
    workbench_image_model: str = 'qwen-image-3.0'
    workbench_image_base_url: str = ''
    workbench_translation_model: str = 'qwen-mt-image-2.0'
    workbench_resolution: str = '1024x1024'
    workbench_language: str = 'en'
    workbench_dashscope_base_url: str = 'https://dashscope.aliyuncs.com/api/v1'
    workbench_asset_directory: str = '../.runtime/workbench-assets'
    workbench_timeout: int = Field(default=180, ge=30, le=600)
    # Extra exact hostnames that may be downloaded through HTTPS_PROXY when local DNS returns Fake-IP.
    workbench_trusted_image_hosts: str = ''

    @field_validator('workbench_trusted_image_hosts')
    @classmethod
    def exact_hosts(cls, value):
        hosts = [x.strip().lower() for x in value.split(',') if x.strip()]
        for host in hosts:
            if not HOSTNAME.fullmatch(host):
                raise ValueError(f'可信图片域名必须是精确主机名（不支持通配符或 IP）：{host}')
        return ','.join(dict.fromkeys(hosts))

    @property
    def trusted_image_hosts(self):
        return frozenset(filter(None, self.workbench_trusted_image_hosts.split(',')))

    def public_config(self):
        return {'configured': bool(self.bailian_api_key.get_secret_value()),
                'text_model': self.workbench_text_model, 'image_model': self.workbench_image_model,
                'translation_model': self.workbench_translation_model,
                'resolution': self.workbench_resolution, 'language': self.workbench_language}
