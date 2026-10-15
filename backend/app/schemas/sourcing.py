"""Validated source input and strict, bounded AI output schemas."""
import re
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer, model_validator

Market = Literal['TH', 'VN', 'MY', 'SG', 'PH', 'ID']
NonEmpty = Annotated[str, Field(min_length=1, max_length=2000)]
StringList = Annotated[list[NonEmpty], Field(max_length=30)]


def public_url(value: str) -> str:
    p = urlsplit(value)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.port not in (None, 80, 443):
        raise ValueError('必须是无认证信息的 HTTP/HTTPS 链接')
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ''))


class SKUInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sku_id: str = Field(max_length=100)
    name: str = Field(default='', max_length=500)
    specs: dict[str, str] = Field(default_factory=dict)
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)

    @field_serializer('purchase_price', when_used='json')
    def serialize_price(self, value):
        return format(value, '.2f') if value is not None else None


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    source_platform: Literal['1688', 'manual'] = '1688'
    source_product_id: str | None = Field(default=None, max_length=100)
    product_url: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, min_length=1, max_length=500)
    description: str = Field(default='', max_length=10000)
    main_image: str | None = Field(default=None, max_length=2000)
    images: list[str] = Field(default_factory=list, max_length=10)
    purchase_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default='CNY', pattern=r'^[A-Z]{3}$')
    skus: list[SKUInput] = Field(default_factory=list, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    supplier: str | None = Field(default=None, max_length=500)
    target_market: Market = 'MY'
    source_note: str = Field(default='', max_length=2000)

    @field_serializer('purchase_price', when_used='json')
    def serialize_price(self, value):
        return format(value, '.2f') if value is not None else None

    @field_validator('product_url', 'main_image')
    @classmethod
    def check_url(cls, value):
        return public_url(value) if value else value

    @field_validator('images')
    @classmethod
    def check_images(cls, value):
        return list(dict.fromkeys(public_url(x) for x in value))

    @model_validator(mode='after')
    def check_source(self):
        if self.source_platform == '1688':
            p = urlsplit(self.product_url)
            if not (p.hostname == '1688.com' or p.hostname.endswith('.1688.com')):
                raise ValueError('1688 商品必须使用 1688.com 链接')
            m = re.fullmatch(r'/offer/(\d+)\.html/?', p.path)
            if m:
                if self.source_product_id and self.source_product_id != m[1]:
                    raise ValueError('商品 ID 与链接不一致')
                self.source_product_id = m[1]
                self.product_url = f'https://detail.1688.com/offer/{m[1]}.html'
        return self


class ImportInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    format: Literal['json', 'csv'] = 'json'
    content: str = Field(max_length=2_000_000)
    target_market: Market = 'MY'

    @field_validator('content')
    @classmethod
    def check_byte_size(cls, value):
        if len(value.encode('utf-8')) > 2_000_000:
            raise ValueError('导入资料不能超过 2 MB（UTF-8）')
        return value


class BatchInput(BaseModel):
    candidate_ids: list[UUID] = Field(min_length=1, max_length=100)


class ReviewInput(BaseModel):
    evaluation_id: UUID | None = None
    input_version: int = Field(ge=1)
    action: Literal['approve', 'reject', 'favorite', 'unfavorite']
    note: str = Field(default='', max_length=2000)


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Risk(StrictOutput):
    kind: Literal['observed', 'inferred', 'needs_verification']
    detail: NonEmpty


class VisionOutput(StrictOutput):
    visual_score: Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
    product_type: NonEmpty
    visual_selling_points: StringList
    presentation_quality: NonEmpty
    potential_risks: Annotated[list[Risk], Field(max_length=30)]
    score_basis: Annotated[list[NonEmpty], Field(min_length=1, max_length=30)]
    limitations: Annotated[list[NonEmpty], Field(min_length=1, max_length=30)]


class MarketFit(StrictOutput):
    target_market: Market
    suggestion: NonEmpty
    basis: NonEmpty
    limitation: NonEmpty


class TextOutput(StrictOutput):
    advantages: StringList
    disadvantages: StringList
    market_fit_suggestions: Annotated[list[MarketFit], Field(min_length=1, max_length=6)]
    differentiation: StringList
    cost_risks: StringList
    english_title_suggestion: NonEmpty
    worth_review: bool
    recommendation_reasons: Annotated[list[NonEmpty], Field(min_length=1, max_length=30)]
    limitations: Annotated[list[NonEmpty], Field(min_length=1, max_length=30)]
