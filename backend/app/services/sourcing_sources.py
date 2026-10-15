"""Authorized source boundaries. No HTML scraping or fabricated products."""
import json
import csv
import io
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from app.clients.miaoshou_client import MiaoshouClient, MiaoshouError
from urllib.parse import urlsplit

from app.schemas.sourcing import CandidateInput
from app.services.sourcing_config import SourcingSettings
from app.services.sourcing_providers import AnalysisError


class SourceAdapter(ABC):
    @abstractmethod
    def status(self) -> dict: ...

    @abstractmethod
    async def search(self, page: int, page_size: int) -> dict: ...

    @abstractmethod
    async def detail(self, product_id: str) -> dict: ...

    @abstractmethod
    def normalize(self, record: dict, **context) -> CandidateInput: ...


class UnavailableSourceAdapter(SourceAdapter):
    def status(self):
        return {'name': 'alibaba1688', 'available': False, 'reason': '1688 开放平台直连接口未授权；关键词/以图搜图请使用“1688 货源中心”（本机 1688 CLI，只读）', 'keyword_search': False}

    async def search(self, page, page_size):
        raise AnalysisError('source_unavailable', self.status()['reason'])

    async def detail(self, product_id):
        raise AnalysisError('source_unavailable', self.status()['reason'])

    def normalize(self, record, **context):
        raise AnalysisError('source_unavailable', self.status()['reason'])


class ManualSourceAdapter(SourceAdapter):
    def status(self):
        return {'name': 'manual', 'available': True, 'reason': '备用：用户提供资料，不自动抓取', 'keyword_search': False}

    async def search(self, page, page_size):
        raise AnalysisError('source_unavailable', '人工资料不支持实时平台查询')

    async def detail(self, product_id):
        raise AnalysisError('source_unavailable', '人工链接不自动获取详情，请补充资料')

    def normalize(self, record, **context):
        return CandidateInput.model_validate(record)


class FileSourceAdapter(ManualSourceAdapter):
    def status(self):
        return {'name': 'file_import', 'available': True, 'reason': '备用：CSV/JSON 资料导入，保留未知字段', 'keyword_search': False}

    def records(self, data):
        if data.format == 'json':
            records = json.loads(data.content)
            if not isinstance(records, list):
                raise ValueError('JSON 顶层必须为商品数组')
        else:
            records = list(csv.DictReader(io.StringIO(data.content.lstrip('\ufeff'))))
        if not 1 <= len(records) <= 500:
            raise ValueError('一次导入限 1–500 条商品')
        return records


class MiaoshouSourceAdapter(SourceAdapter):
    """Keeps the SourceAdapter boundary; request protocol is owned by MiaoshouClient."""
    def __init__(self, settings=None, client=None):
        self.settings = settings or SourcingSettings()
        self.client = client or MiaoshouClient(self.settings)

    def status(self):
        return {'name': 'miaoshou', 'available': self.client.configured, 'keyword_search': False,
                'capabilities': ['shops', 'fetch_items', 'common_list', 'common_detail'],
                'reason': '授权 API 货源采集与公共采集箱同步；非 1688 全站搜索，连接状态须真实验证' if self.client.configured else '妙手服务端凭证未配置'}

    async def search(self, page, page_size, source_id=None, tab='all'):
        try:
            response = await self.client.get_common_list(page, page_size, source_id, tab)
        except MiaoshouError as error:
            raise AnalysisError(error.code, error.message) from None
        result = response.data
        items = [{'id': str(x['commonCollectBoxDetailId']), 'commonCollectBoxDetailId': x['commonCollectBoxDetailId'],
                  'title': x.get('title'), 'thumbnail': x.get('thumbnail'), 'sources': x.get('sourceList') or [],
                  'price': x.get('price'), 'minSkuPrice': x.get('minSkuPrice'), 'maxSkuPrice': x.get('maxSkuPrice'),
                  'stock': x.get('stock'), 'weight': x.get('weight'), 'status': x.get('status'), 'reason': x.get('reason')}
                 for x in result['detailList']]
        return {'items': items, 'total': result['total'], 'page': page, 'page_size': page_size}

    async def detail(self, product_id):
        try:
            response = await self.client.get_common_detail(product_id)
        except MiaoshouError as error:
            raise AnalysisError(error.code, error.message) from None
        return {**response.data, '_response_envelope': response.envelope, '_raw_response_text': response.raw_text}

    def normalize(self, record: dict, source: dict, market: str, currency: str):
        detail = record['editCommonCollectBoxDetail']
        url = source.get('sourceItemUrl', '')
        host = urlsplit(url).hostname or ''
        if host != '1688.com' and not host.endswith('.1688.com'):
            raise AnalysisError('source_platform', '本阶段只接受有明确 1688 货源链接的记录')
        images = detail.get('imgUrls') or []
        price = detail.get('price')
        note = '妙手授权资料；SPU price 为货源价，币种由操作人确认；SKU price/oriPrice 按原字段保留，不作为已确认的 SKU 采购价或 TikTok 售价。'
        if price is not None:
            try:
                decimal_price = Decimal(str(price))
                if not decimal_price.is_finite() or decimal_price < 0 or decimal_price.as_tuple().exponent < -2 or decimal_price >= 10**10:
                    price = None
                    note += 'SPU 价格需确认，原值完整保留，未擅自取整。'
            except InvalidOperation:
                price = None
                note += 'SPU 价格格式需确认，原值完整保留。'
        return CandidateInput(source_platform='1688', source_product_id=source.get('sourceItemId') or None,
                              product_url=url, name=detail.get('title') or None,
                              description=detail.get('notesText') or '',
                              main_image=images[0] if images else None, images=images[1:11],
                              purchase_price=price, currency=currency,
                              skus=[{'sku_id': str(k), 'name': x.get('itemNum') or '', 'specs': {'原始规格键': str(k)},
                                     'purchase_price': None} for k, x in list((detail.get('skuMap') or {}).items())[:200]],
                              category=' / '.join(detail.get('cateList') or []) or None,
                              target_market=market, source_note=note)
