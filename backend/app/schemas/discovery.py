"""Discovery task input and strict model-output schemas."""
import re
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.sourcing import Market, NonEmpty, StrictOutput

Word = Annotated[str, Field(min_length=1, max_length=30)]
MAX_COLLECT = 5


class DiscoveryTaskInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_key: UUID
    target_market: Market = 'MY'
    report_id: UUID | None = None
    report_rows: list[int] = Field(default_factory=list, max_length=20)
    category: str = Field(min_length=1, max_length=100)
    price_min: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    price_max: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: Literal['CNY'] = 'CNY'
    keywords: list[Word] = Field(default_factory=list, max_length=10)
    exclude_words: list[Word] = Field(default_factory=list, max_length=20)
    preferences: str = Field(default='', max_length=500)
    max_candidates: int = Field(default=30, ge=1, le=30)
    auto_collect: bool = False

    @field_validator('keywords', 'exclude_words')
    @classmethod
    def dedupe_words(cls, values):
        return list(dict.fromkeys(' '.join(v.split()) for v in values if v.strip()))

    @model_validator(mode='after')
    def check_price(self):
        if self.price_min is not None and self.price_max is not None and self.price_min > self.price_max:
            raise ValueError('采购价下限不能高于上限')
        return self

    def goal(self) -> dict:
        data = self.model_dump(mode='json', exclude={'request_key', 'auto_collect'})
        return data


class ConfirmCollectInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_item_ids: list[Annotated[str, Field(pattern=r'^\d{6,20}$')]] = Field(min_length=1, max_length=MAX_COLLECT)

    @field_validator('source_item_ids')
    @classmethod
    def unique(cls, values):
        return list(dict.fromkeys(values))


# ---------- model outputs (strict) ----------

class PlannedKeyword(StrictOutput):
    keyword: Annotated[str, Field(min_length=2, max_length=30)]
    angle: Annotated[str, Field(min_length=1, max_length=60)]
    rationale: Annotated[str, Field(min_length=1, max_length=300)]


class PlanOutput(StrictOutput):
    keywords: Annotated[list[PlannedKeyword], Field(min_length=1, max_length=10)]
    notes: Annotated[list[NonEmpty], Field(max_length=5)]


FORBIDDEN_KEYWORD = [
    (re.compile(r'https?://|www\.|\.com|\.cn', re.I), '包含链接或域名'),
    (re.compile(r'\d{6,}'), '包含疑似商品 ID 的长数字'),
    (re.compile(r'[¥￥$]|\d+(\.\d+)?\s*(元|块|CNY|RMB)', re.I), '包含价格'),
    (re.compile(r'site:|offer', re.I), '包含搜索运算符或页面路径'),
]


def keyword_problem(keyword: str) -> str | None:
    for pattern, reason in FORBIDDEN_KEYWORD:
        if pattern.search(keyword):
            return reason
    return None


class Dimension(StrictOutput):
    score: Annotated[int, Field(ge=0, le=100)]
    level: Literal['low', 'medium', 'high']
    explanation: NonEmpty
    evidence: Annotated[list[NonEmpty], Field(min_length=1, max_length=6)]


class AssessmentOutput(StrictOutput):
    selling_points: Annotated[list[NonEmpty], Field(min_length=1, max_length=8)]
    short_video_potential: Dimension
    market_fit: Dimension
    homogeneity_risk: Dimension
    ip_compliance_risk: Dimension
    compliance_flags: Annotated[list[NonEmpty], Field(max_length=10)]
    summary: NonEmpty
    limitations: Annotated[list[NonEmpty], Field(min_length=1, max_length=10)]
