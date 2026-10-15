"""Incomplete drafts may be saved; publishing requirements are checked separately."""
from typing import Literal
from uuid import UUID
import math
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from app.schemas.sourcing import public_url

LANGUAGES = {'en', 'zh', 'zh-tw', 'th', 'vi', 'ms', 'id', 'fil', 'ja', 'ko', 'de', 'es', 'fr', 'pt', 'it', 'ru', 'ar'}


class StrictInput(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class SKUContent(StrictInput):
    itemNum: str = Field(default='', max_length=200)
    price: float | None = Field(default=None, ge=0)
    originPrice: float | None = Field(default=None, ge=0)  # 货源价格 (source cost), shown beside the sale price
    stock: StrictInt | None = Field(default=None, ge=0)
    isDelete: Literal['0', '1'] = '0'
    weight: float | None = Field(default=None, ge=0)
    shopIdToWarehouseIdAndStockMap: dict[str, dict[str, StrictInt]] = Field(default_factory=dict)


class SaleValue(StrictInput):
    attrValueId: str = Field(max_length=100)
    attrValue: str = Field(max_length=255)
    imgUrl: str = Field(default='', max_length=2000)

    @field_validator('imgUrl')
    @classmethod
    def image(cls, value):
        return public_url(value) if value else ''


class SaleProperty(StrictInput):
    attrId: str = Field(default='', max_length=100)
    attrName: str = Field(max_length=255)
    attrValueList: list[SaleValue] = Field(max_length=200)


class AttributeValue(StrictInput):
    valueName: str = Field(max_length=255)
    valueId: str = Field(max_length=100)


class ProductAttribute(StrictInput):
    attributeId: str = Field(max_length=100)
    attributeName: str = Field(default='', max_length=255)
    attributeNameAlias: str = Field(default='', max_length=255)
    attributeValues: list[AttributeValue] = Field(max_length=200)


class SourceAttribute(StrictInput):
    name: str = Field(max_length=100)
    value: str = Field(default='', max_length=500)


class EditorialContent(StrictInput):
    title: str = Field(default='', max_length=500)
    bullet_points: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default='', max_length=20000)
    imgUrls: list[str] = Field(default_factory=list, max_length=30)
    # 详细描述 images (in order). Synced inside `notes` as generated HTML; never raw source HTML.
    descImgUrls: list[str] = Field(default_factory=list, max_length=50)
    # Free-form 货源属性 (Miaoshou "产品属性"): reference facts for operators and AI, not synced.
    sourceAttributes: list[SourceAttribute] = Field(default_factory=list, max_length=100)
    cid: str = Field(default='', max_length=20)
    brandId: str = Field(default='', max_length=20)
    weight: float | None = Field(default=None, ge=0)
    packageLength: float | None = Field(default=None, ge=0)
    packageWidth: float | None = Field(default=None, ge=0)
    packageHeight: float | None = Field(default=None, ge=0)
    isCodOpen: Literal['0', '1'] = '0'
    deliveryOptionSetType: Literal['default'] = 'default'
    skuMap: dict[str, dict] = Field(default_factory=dict)
    skuPropertyList: list[dict] = Field(default_factory=list, max_length=3)
    productAttributes: list[dict] = Field(default_factory=list, max_length=100)
    productCertifications: list[dict] = Field(default_factory=list, max_length=30)
    manufacturerIds: list[str] = Field(default_factory=list, max_length=30)
    responsiblePersonIds: list[str] = Field(default_factory=list, max_length=30)
    sizeChartType: Literal['', 'image'] = ''
    sizeChart: str = Field(default='', max_length=2000)
    confirmed_facts: str = Field(default='', max_length=5000)
    recognized_text: list[dict] = Field(default_factory=list, max_length=100)

    @field_validator('imgUrls', 'descImgUrls')
    @classmethod
    def urls(cls, values):
        return list(dict.fromkeys(public_url(x) for x in values))

    @field_validator('sizeChart')
    @classmethod
    def chart_url(cls, value):
        return public_url(value) if value else ''

    @model_validator(mode='after')
    def bounded_json(self):
        self.skuMap = {k: SKUContent.model_validate(v).model_dump(mode='json') for k, v in self.skuMap.items()}
        self.skuPropertyList = [SaleProperty.model_validate(x).model_dump(mode='json') for x in self.skuPropertyList]
        self.productAttributes = [ProductAttribute.model_validate(x).model_dump(mode='json') for x in self.productAttributes]
        for cert in self.productCertifications:
            if not isinstance(cert.get('id'), str) or not isinstance(cert.get('files'), list):
                raise ValueError('认证资料必须有 id 和文件列表')
            for file in cert['files']:
                if not isinstance(file, dict) or not isinstance(file.get('fileUrl'), str):
                    raise ValueError('认证资料缺少文件 URL')
                file['fileUrl'] = public_url(file['fileUrl'])
        def finite(value):
            if isinstance(value, dict):
                return all(finite(x) for x in value.values())
            if isinstance(value, list):
                return all(finite(x) for x in value)
            return not isinstance(value, float) or math.isfinite(value)
        if not finite(self.model_dump()):
            raise ValueError('商品数值须为有限数')
        if len(self.model_dump_json()) > 250000 or len(self.skuMap) > 200:
            raise ValueError('草稿超过 250 KB 或 200 个 SKU')
        return self


class CreateDrafts(StrictInput):
    ids: list[UUID] = Field(min_length=1, max_length=50)
    shop_id: int | None = Field(default=None, gt=0)


class SaveDraft(StrictInput):
    version: int = Field(gt=0)
    shop_id: int | None = Field(default=None, gt=0)
    language: str = 'en'
    content: EditorialContent

    @field_validator('language')
    @classmethod
    def language_supported(cls, value):
        if value not in LANGUAGES:
            raise ValueError('不支持的目标语言')
        return value


class VersionInput(StrictInput):
    version: int = Field(gt=0)


class AIInput(VersionInput):
    request_key: UUID
    kind: Literal['ocr', 'copy', 'generate', 'edit', 'translate', 'fill']
    image_urls: list[str] = Field(default_factory=list, max_length=3)
    prompt: str = Field(default='', max_length=5000)
    source_lang: str = 'auto'

    @field_validator('image_urls')
    @classmethod
    def urls(cls, values):
        return [public_url(x) for x in values]

    @field_validator('source_lang')
    @classmethod
    def source_language(cls, value):
        if value not in LANGUAGES | {'auto'}:
            raise ValueError('不支持的源语言')
        return value

    @model_validator(mode='after')
    def required_images(self):
        if self.kind in ('ocr', 'edit', 'translate') and not self.image_urls:
            raise ValueError('该操作需要选择图片')
        if self.kind == 'translate' and len(self.image_urls) != 1:
            raise ValueError('图片翻译每次处理一张图片')
        if self.kind in ('generate', 'edit') and not self.prompt.strip():
            raise ValueError('请填写图片生成或编辑指令')
        return self


class SyncInput(VersionInput):
    request_key: UUID
    # Explicit operator choice after a conflict: replace edits made directly in Miaoshou.
    overwrite_remote: bool = False


class AdoptInput(VersionInput):
    confirm_stale: bool = False
    image_action: Literal['append', 'replace'] = 'append'
    replace_url: str | None = None


class OCRBlock(StrictInput):
    image_index: int = Field(ge=0, le=2)
    text: str = Field(max_length=10000)


class OCROutput(StrictInput):
    blocks: list[OCRBlock] = Field(max_length=60)


class CopyOutput(StrictInput):
    title: str = Field(min_length=25, max_length=255)
    bullet_points: list[str] = Field(max_length=5)
    notes: str = Field(min_length=1, max_length=10000)


# AI fill suggestions. Shapes are validated here; ids/ranges are checked against real
# category data afterwards (workbench_service.clean_fill), and nothing is applied automatically.
class FillCategory(StrictInput):
    cid: str = Field(max_length=20)
    reason: str = Field(default='', max_length=300)


class FillNumber(StrictInput):
    value: float
    reason: str = Field(default='', max_length=300)


class FillPackage(StrictInput):
    length: float
    width: float
    height: float
    reason: str = Field(default='', max_length=300)


class FillSkuWeight(StrictInput):
    sku_key: str = Field(max_length=500)
    weight: float
    reason: str = Field(default='', max_length=300)


class FillAttribute(StrictInput):
    attr_id: str = Field(max_length=100)
    value_ids: list[str] = Field(default_factory=list, max_length=20)
    custom_values: list[str] = Field(default_factory=list, max_length=20)
    reason: str = Field(default='', max_length=300)


class FillSpecValue(StrictInput):
    source_value: str = Field(max_length=255)
    value_id: str = Field(default='', max_length=100)
    custom_value: str = Field(default='', max_length=255)


class FillSaleSpec(StrictInput):
    source_property: str = Field(max_length=255)
    attr_id: str = Field(max_length=100)
    values: list[FillSpecValue] = Field(max_length=200)


class FillOutput(StrictInput):
    category: FillCategory | None = None
    weight: FillNumber | None = None
    package: FillPackage | None = None
    sku_weights: list[FillSkuWeight] = Field(default_factory=list, max_length=200)
    attributes: list[FillAttribute] = Field(default_factory=list, max_length=100)
    sale_specs: list[FillSaleSpec] = Field(default_factory=list, max_length=3)
