"""UI input schemas use names specific to the common box, never TK box IDs."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.schemas.sourcing import CandidateInput, Market


def normalized_link(url):
    data = CandidateInput(product_url=url)
    if not data.source_product_id:
        raise ValueError('采集链接必须为标准 1688 offer 商品链接')
    return data


class CollectInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: UUID
    links: list[str] = Field(min_length=1, max_length=50)
    target_market: Market
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    analyze_after_sync: bool = False
    # 采集进公共采集箱后再认领到平台采集箱（#8）；None 表示只留在公共采集箱
    claim_platform: Literal['tiktok'] | None = None

    @field_validator('links')
    @classmethod
    def validate_links(cls, values):
        for url in values:
            normalized_link(url)
        return values


class SyncInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_key: UUID
    common_detail_ids: list[str] = Field(min_length=1, max_length=50)
    target_market: Market
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    analyze_after_sync: bool = False

    @field_validator('common_detail_ids')
    @classmethod
    def validate_ids(cls, values):
        if any(not x.isdecimal() or int(x) <= 0 for x in values):
            raise ValueError('公共采集箱详情 ID 必须为正整数；不能传入 TK 采集箱 ID')
        return list(dict.fromkeys(values))
