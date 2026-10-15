from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]
UPSTREAM_REVISION = 'dcd45e7f2b088867551fb10772e32b21f4219193'
UPSTREAM_SHA256 = '87db03925fb83d914f7a92ad9b45569a3bc022902b6d297bd0a6cb3ee9025ffd'
MARKETS = {'MY': '马来西亚', 'TH': '泰国', 'VN': '越南', 'SG': '新加坡', 'PH': '菲律宾', 'ID': '印度尼西亚'}
BROWSER_LOCK = 714202610


class FastmossSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore', env_prefix='FASTMOSS_')
    bsk_bin: str = ''
    upstream_dir: str = str(ROOT / '.runtime' / 'fastmoss-upstream')
    category_timeout: int = 600
