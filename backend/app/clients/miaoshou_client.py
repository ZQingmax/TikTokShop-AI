"""Signed sourcing and editorial collect-box operations; never log credentials or headers."""
import asyncio
import hashlib
import hmac
import json
import logging
import re
import time
import weakref
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError
from app.services.sourcing_config import SourcingSettings

logger = logging.getLogger(__name__)
SHOPS = '/open/v1/product/shop/shop/get_shop_list'
FETCH = '/open/v1/product/common_collect_box/common_collect_box/fetch_item'
LIST = '/open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_list'
DETAIL = '/open/v1/product/common_collect_box/common_collect_box/get_common_collect_box_detail'
CLAIM = '/open/v1/product/common_collect_box/common_collect_box/claimed'
TK_LIST = '/open/v1/product/collect_box/tiktok/collect_box/search_collect_box_detail_list'
TK_ROOT = '/open/v1/product/collect_box/tiktok/collect_box/'
CATEGORY = TK_ROOT + 'get_category_tree_by_site'
METADATA = TK_ROOT + 'get_category_metadata'
WAREHOUSES = TK_ROOT + 'get_shop_warehouse_list'
CLAIM_SHOP = TK_ROOT + 'claim_to_shop'
SHOP_DETAIL = TK_ROOT + 'get_shop_collect_item_info'
SAVE_SHOP = TK_ROOT + 'save_shop_collect_item_info'
PICTURE_UPLOAD = '/open/v1/product/picture/picture_space/upload_picture_link'
PUBLISH = TK_ROOT + 'save_move_collect_task'
PUBLISH_RECORDS = '/open/v1/product/collect_box/tiktok/move_collect/search_move_collect_list'
PACKAGES = '/open/v1/order/package/fetch/search_package_list'
PURCHASE_ORDERS = '/open/v1/ewm/goods_purchase_order/goods_purchase_order/fetch/search_goods_purchase_order_page'
READ_PATHS = {SHOPS, LIST, DETAIL, TK_LIST, CATEGORY, METADATA, WAREHOUSES, SHOP_DETAIL, PUBLISH_RECORDS, PACKAGES, PURCHASE_ORDERS}
# Miaoshou reports an empty search as result=fail with this message instead of an empty list.
NO_DATA = '没有符合条件的数据'
WRITE_PATHS = {FETCH, CLAIM, CLAIM_SHOP, SAVE_SHOP, PICTURE_UPLOAD, PUBLISH}


class WorkbenchData(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)


class AnyData(RootModel[object]):
    """Order APIs return `data` as an array or an object; callers normalise it."""


class ShopDetailData(WorkbenchData):
    ossMd5: str
    shopCollectItemInfo: dict


class SavedShopData(WorkbenchData):
    ossMd5: str


class PictureData(WorkbenchData):
    picturePath: str
    width: int
    height: int


class CategoryData(WorkbenchData):
    cateTree: dict


class MetadataData(WorkbenchData):
    categoryMetadata: dict


class WarehouseData(WorkbenchData):
    shopWarehouseList: list[dict]


class MiaoshouError(Exception):
    def __init__(self, code, category, message, uncertain=False, retry_after=None):
        super().__init__(message)
        self.code, self.category, self.message = code, category, message
        self.uncertain, self.retry_after = uncertain, retry_after


class Envelope(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    result: str
    code: str
    data: dict | list | None = None


class ShopList(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    shopList: list[dict]


class CommonList(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    detailList: list[dict]
    total: int = Field(ge=0)


class CommonDetail(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    editCommonCollectBoxDetail: dict


class CollectedMap(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    sourceItemIdAndDetailIdMap: dict[str, int]


class ClaimResult(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    platformCollectBoxDetailIdMap: dict = Field(default_factory=dict)


class TiktokList(BaseModel):
    model_config = ConfigDict(extra='allow', strict=True)
    detailList: list[dict]


@dataclass
class MiaoshouResponse:
    data: dict
    envelope: dict
    raw_text: str
    path: str
    body_sha256: str


class RequestLimiter:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.next_at = 0.0

    async def wait(self, interval):
        async with self.lock:
            delay = self.next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.next_at = time.monotonic() + interval

    def cool_down(self, seconds):
        self.next_at = max(self.next_at, time.monotonic() + seconds)


_limiters = weakref.WeakKeyDictionary()


def shared_limiter(key):
    per_loop = _limiters.setdefault(asyncio.get_running_loop(), {})
    return per_loop.setdefault(hashlib.sha256(key.encode()).hexdigest(), RequestLimiter())


def serialize_body(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sign_body(secret, app_key, path, timestamp, body: bytes):
    """Sign precisely the bytes supplied to httpx content, including UTF-8 data."""
    parts = [secret.encode(), path.encode(), str(timestamp).encode(), app_key.encode(), body, secret.encode()]
    return hmac.new(secret.encode(), b''.join(parts), hashlib.sha256).hexdigest()


# Explicit error codes that may still mean "processed but unconfirmed"; any other explicit
# rejection of a write is definite (the platform refused it), so it can be resubmitted after fixing.
AMBIGUOUS_CODES = {'unknown', 'systemError', 'systemBusy', 'serviceError', 'internalError', 'timeout'}


def platform_error(raw_code, writing, limiter, reason='', secrets=()):
    code = raw_code if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,60}', raw_code) else 'unknown'
    auth_codes = {'appNotFound', 'signMissing', 'signExpired', 'signInvalid'}
    permission_codes = {'appNoPermission', 'ipNotInWhitelist'}
    category = 'auth' if code in auth_codes else 'permission' if code in permission_codes else 'rate_limit' if code.endswith('RateLimit') else 'upstream' if code.startswith('upstream') else 'platform'
    labels = {'appNotFound': '应用不存在或已禁用', 'signMissing': '签名参数缺失', 'signExpired': '请求时间戳过期',
              'signInvalid': '签名校验失败', 'appNoPermission': '应用没有此接口权限', 'ipNotInWhitelist': '服务器 IP 不在白名单',
              'routeNotFound': '接口路径不存在'}
    if category == 'rate_limit':
        limiter.cool_down(60)
    # Business rejections carry the platform's explanation, which the operator needs to fix the draft.
    # It is shown (credentials scrubbed, length-capped) but never logged; auth-type reasons stay hidden.
    detail = ''
    if category == 'platform' and isinstance(reason, str):
        for secret in secrets:
            if secret:
                reason = reason.replace(secret, '[redacted]')
        detail = re.sub(r'[\x00-\x1f\x7f]+', ' ', reason).strip()[:300]
    message = labels.get(code) or (f'妙手拒绝了请求（{code}）：{detail}' if detail else f'妙手返回错误（{code}），未自动重复请求')
    uncertain = writing and (category == 'upstream' or code in AMBIGUOUS_CODES)
    return MiaoshouError(code, category, message, uncertain, 60 if category == 'rate_limit' else None)


class MiaoshouClient:
    BASE_URL = 'https://openapi-erp.91miaoshou.com'

    def __init__(self, settings=None, transport=None, limiter=None):
        self.settings = settings or SourcingSettings()
        self.transport, self.limiter = transport, limiter

    @property
    def configured(self):
        return bool(self.settings.miaoshou_app_key.get_secret_value() and self.settings.miaoshou_app_secret.get_secret_value())

    async def post_json(self, path, payload, response_type):
        if path not in READ_PATHS | WRITE_PATHS:
            raise MiaoshouError('unsupported_operation', 'configuration', '此阶段仅开放已确认的货源与采集箱接口')
        writing = path in WRITE_PATHS
        if not self.configured:
            raise MiaoshouError('not_configured', 'configuration', '妙手服务端凭证未配置')
        key = self.settings.miaoshou_app_key.get_secret_value()
        secret = self.settings.miaoshou_app_secret.get_secret_value()
        limiter = self.limiter or shared_limiter(key)
        await limiter.wait(self.settings.miaoshou_request_interval)
        body = serialize_body(payload)
        timestamp = str(int(time.time()))
        headers = {'Content-Type': 'application/json', 'x-app-key': key, 'x-timestamp': timestamp,
                   'x-sign': sign_body(secret, key, path, timestamp, body)}
        try:
            async with httpx.AsyncClient(timeout=self.settings.miaoshou_timeout, follow_redirects=False, transport=self.transport) as client:
                # No retry transport, SDK retries, redirect following or re-serialization.
                response = await client.post(self.BASE_URL + path, content=body, headers=headers)
            if len(response.content) > 8 * 1024 * 1024:
                raise MiaoshouError('response_too_large', 'response', '妙手响应超过 8 MiB', writing)
            if response.status_code != 200:
                # The OpenAPI document also returns SimpleErrorResponse with HTTP 500.
                # Its code is more useful than the status, while its reason is never logged.
                try:
                    error_envelope = Envelope.model_validate(response.json())
                except (ValidationError, ValueError, TypeError):
                    error_envelope = None
                if error_envelope and (error_envelope.result != 'success' or error_envelope.code != 'success'):
                    extra = error_envelope.model_extra or {}
                    raise platform_error(error_envelope.code, writing, limiter, extra.get('reason') or extra.get('message'), (key, secret))
                status = response.status_code
                category = 'rate_limit' if status == 429 else 'auth' if status == 401 else 'permission' if status == 403 else 'http'
                retry_after = response.headers.get('retry-after', '60')
                seconds = min(3600, max(1, int(retry_after))) if retry_after.isdecimal() else 60
                if status == 429:
                    limiter.cool_down(seconds)
                raise MiaoshouError(f'http_{status}', category, f'妙手 HTTP {status}', writing and status not in (401, 403, 429), seconds if status == 429 else None)
            raw = response.json()
            parsed = Envelope.model_validate(raw)
            if parsed.result != 'success' or parsed.code != 'success':
                extra = parsed.model_extra or {}
                raise platform_error(parsed.code, writing, limiter, extra.get('message') or extra.get('reason'), (key, secret))
            validated = response_type.model_validate(parsed.data or {} if response_type is WorkbenchData else parsed.data)
            if response_type is CommonList:
                for item in validated.detailList:
                    id = item.get('commonCollectBoxDetailId')
                    if type(id) is not int or id <= 0:
                        raise ValueError('Invalid common ID')
            if response_type is CollectedMap and any(v <= 0 for v in validated.sourceItemIdAndDetailIdMap.values()):
                raise ValueError('Invalid collected ID')
            return MiaoshouResponse(parsed.data, raw, response.text, path, hashlib.sha256(body).hexdigest())
        except MiaoshouError as error:
            logger.warning('Miaoshou operation=%s code=%s category=%s uncertain=%s', path, error.code, error.category, error.uncertain)
            raise
        except httpx.TimeoutException:
            raise MiaoshouError('timeout', 'timeout', '妙手请求超时；采集结果可能已产生，须先查询平台状态' if writing else '妙手只读查询超时', writing) from None
        except httpx.RequestError:
            raise MiaoshouError('connection', 'network', '妙手连接失败；没有自动重试', writing) from None
        except (ValidationError, ValueError, TypeError, KeyError):
            raise MiaoshouError('invalid_response', 'response', '妙手响应未通过结构校验；没有自动重试', writing) from None

    async def get_shops(self, platform, site, page=1, page_size=20):
        if platform not in {'tiktok', 'tiktokGlobal', 'pddkj', 'pddkjChoice', 'shopee', 'shopeeGlobal', 'mercadolibre', 'ozon'} or not site or not 1 <= page_size <= 100 or page < 1:
            raise MiaoshouError('invalid_parameters', 'input', '店铺平台、站点或分页参数无效')
        return await self.post_json(SHOPS, {'platform': platform, 'site': site, 'pageNo': page, 'pageSize': page_size}, ShopList)

    async def get_common_list(self, page=1, page_size=20, source_id=None, tab='all'):
        if page < 1 or not 1 <= page_size <= 500 or tab not in {'all', 'noClaimed', 'claimed', 'collectFail', 'collectSuccess'}:
            raise MiaoshouError('invalid_parameters', 'input', '公共采集箱分页或状态参数无效')
        payload = {'pageNo': page, 'pageSize': page_size}
        if source_id is not None:
            if len(source_id) > 255:
                raise MiaoshouError('invalid_parameters', 'input', '来源商品 ID 超长')
            payload['filter'] = {'tabPaneName': tab, 'sourceItemIdKeyword': source_id}
        elif tab != 'all':
            payload['filter'] = {'tabPaneName': tab}
        return await self.post_json(LIST, payload, CommonList)

    async def get_common_detail(self, detail_id):
        if not str(detail_id).isdecimal() or int(detail_id) <= 0:
            raise MiaoshouError('invalid_parameters', 'input', '公共采集箱详情 ID 必须为正整数')
        return await self.post_json(DETAIL, {'commonCollectBoxDetailId': int(detail_id)}, CommonDetail)

    async def fetch_items(self, links):
        if not 1 <= len(links) <= 50:
            raise MiaoshouError('invalid_parameters', 'input', '一次采集限 1–50 个货源链接')
        return await self.post_json(FETCH, {'collectLinks': links}, CollectedMap)

    async def claim_to_platform(self, detail_ids, platform='tiktok'):
        """认领公共采集箱商品到平台采集箱（#8），只写入妙手采集箱，不发布到店铺。"""
        if not 1 <= len(detail_ids) <= 100 or platform != 'tiktok':
            raise MiaoshouError('invalid_parameters', 'input', '一次认领限 1–100 个公共采集箱商品，本阶段仅支持 TikTok')
        if any(not str(x).isdecimal() or int(x) <= 0 for x in detail_ids):
            raise MiaoshouError('invalid_parameters', 'input', '公共采集箱详情 ID 必须为正整数')
        items = [{'detailId': int(x), 'platform': platform, 'serialNumber': 1} for x in detail_ids]
        return await self.post_json(CLAIM, {'detailSerialNumberPlatformList': items}, ClaimResult)

    async def get_tiktok_list(self, page=1, page_size=20, source_id=None, status=None):
        if page < 1 or not 1 <= page_size <= 500 or status not in (None, 'notPublished', 'timingPublish', 'published'):
            raise MiaoshouError('invalid_parameters', 'input', 'TikTok 采集箱分页或状态参数无效')
        payload, filters = {'pageNo': page, 'pageSize': page_size}, {}
        if source_id:
            if len(source_id) > 255:
                raise MiaoshouError('invalid_parameters', 'input', '来源商品 ID 超长')
            filters['sourceItemIdKeyword'] = source_id
        if status:
            filters['status'] = status
        if filters:
            payload['filter'] = filters
        return await self.post_json(TK_LIST, payload, TiktokList)

    async def get_categories(self, site):
        return await self.post_json(CATEGORY, {'site': site}, CategoryData)

    async def get_category_metadata(self, site, cid, shop_id):
        return await self.post_json(METADATA, {'site': site, 'cid': int(cid), 'shopIds': [int(shop_id)]}, MetadataData)

    async def get_warehouses(self, shop_id):
        return await self.post_json(WAREHOUSES, {'shopIds': [int(shop_id)]}, WarehouseData)

    async def claim_to_shop(self, detail_id, shop_id):
        return await self.post_json(CLAIM_SHOP, {'detailIds': [int(detail_id)], 'shopIds': [int(shop_id)]}, WorkbenchData)

    async def get_shop_detail(self, detail_id, shop_id):
        return await self.post_json(SHOP_DETAIL, {'detailId': int(detail_id), 'shopId': int(shop_id)}, ShopDetailData)

    async def save_shop_detail(self, detail_id, shop_id, md5, content):
        return await self.post_json(SAVE_SHOP, {'detailId': int(detail_id), 'shopId': int(shop_id),
                                             'ossMd5': md5, 'shopCollectItemInfo': content}, SavedShopData)

    async def publish(self, detail_ids, shop_ids):
        """发布产品（#25）：把 TK 采集箱商品发布到店铺。写操作，超时结果不确定时只能查询，不能重发。"""
        if not 1 <= len(detail_ids) <= 200 or not 1 <= len(shop_ids) <= 200:
            raise MiaoshouError('invalid_parameters', 'input', '一次发布限 1–200 个采集箱商品和 1–200 个店铺')
        if any(not str(x).isdecimal() or int(x) <= 0 for x in [*detail_ids, *shop_ids]):
            raise MiaoshouError('invalid_parameters', 'input', '采集箱详情 ID 与店铺 ID 必须为正整数')
        return await self.post_json(PUBLISH, {'shopIds': [int(x) for x in shop_ids], 'detailIds': [int(x) for x in detail_ids]}, WorkbenchData)

    async def get_publish_records(self, page=1, page_size=100):
        """发布记录列表（#26）只读。"""
        if page < 1 or not 1 <= page_size <= 100:
            raise MiaoshouError('invalid_parameters', 'input', '发布记录分页参数无效')
        return await self.post_json(PUBLISH_RECORDS, {'pageNo': page, 'pageSize': page_size}, WorkbenchData)

    async def get_packages(self, page=1, page_size=50, platform='tiktok', modified_from=None):
        """批量获取包裹列表（#150）只读；包裹即平台订单在妙手中的履约单元。"""
        if page < 1 or not 1 <= page_size <= 100:
            raise MiaoshouError('invalid_parameters', 'input', '包裹分页参数无效')
        payload = {'page': page, 'pageSize': page_size, 'platform': platform}
        if modified_from:
            payload['gmtModifiedFrom'] = modified_from
        try:
            response = await self.post_json(PACKAGES, payload, AnyData)
        except MiaoshouError as error:
            if error.code == 'fail' and NO_DATA in error.message:
                return []
            raise
        data = response.data
        groups = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
        return [p for g in groups if isinstance(g, dict) for p in (g.get('orderPackageList') or []) if isinstance(p, dict)]

    async def get_purchase_orders(self, page=1, page_size=50):
        """获取采购单列表（#161）只读。"""
        if page < 1 or not 10 <= page_size <= 100:
            raise MiaoshouError('invalid_parameters', 'input', '采购单分页参数无效（每页 10–100）')
        try:
            response = await self.post_json(PURCHASE_ORDERS, {'page': page, 'pageSize': page_size}, AnyData)
        except MiaoshouError as error:
            if error.code == 'fail' and NO_DATA in error.message:
                return []
            raise
        data = response.data if isinstance(response.data, dict) else {}
        return [x for x in data.get('goodsPurchaseOrderList') or [] if isinstance(x, dict)]

    async def upload_picture(self, url):
        return await self.post_json(PICTURE_UPLOAD, {'imgUrl': url, 'scene': 'product'}, PictureData)
